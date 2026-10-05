"""Unit tests for the local-engine node executors.

Covers the voice-cast TTS executor and the scene-3d Blender executor plus
their registration in ``NodeExecutionDispatcher``. External engines and
Blender/FFmpeg are replaced by fakes so these tests stay hermetic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.persistence.errors import V2PersistenceError
from app.tools.media_provider_protocol import MediaConfigurationError
from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.scene_script import (
    CameraKeyframe,
    CharacterAppearance,
    CharacterKeyframe,
    SceneCamera,
    SceneCharacter,
    SceneInfo,
    SceneScriptRoot,
    SceneShot,
)
from app.services.agent_canvas_node_execution import (
    NodeExecutionContext,
    NodeExecutionDispatcher,
    NodeExecutionOutcome,
    Scene3DNodeExecutor,
    VoiceCastNodeExecutor,
)
from app.services.scene3d.blender_converter import keyframe_render_frames
from app.services.scene3d.scene_script_generator import (
    LLMSceneScriptGenerator,
    SceneScriptGenerationError,
    TemplateSceneScriptGenerator,
)
from app.services.scene3d.speech_orchestration import SimpleTTSEngine


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_node(
    *,
    node_type: str,
    creative_role: str,
    generation_prompt: str | None = None,
    structured_content: dict[str, Any] | None = None,
) -> CanvasNodeV2:
    return CanvasNodeV2(
        node_id=f"node-{node_type}",
        workflow_id="wf-test",
        node_type=node_type,  # type: ignore[arg-type]
        creative_role=creative_role,  # type: ignore[arg-type]
        title=f"Node {node_type}",
        status="draft",
        generation_prompt=generation_prompt,
        structured_content=structured_content or {},
        position={"x": 0.0, "y": 0.0},
        revision=1,
        created_at=_now(),
        updated_at=_now(),
    )


def _context(node: CanvasNodeV2) -> NodeExecutionContext:
    return NodeExecutionContext(
        execution_id="exec-1",
        node=node,
        inputs=(),
    )


def _minimal_scene_script() -> SceneScriptRoot:
    character = SceneCharacter(
        id="char1",
        type="lowpoly_human",
        appearance=CharacterAppearance(color="#FF0000"),
        keyframes=[
            CharacterKeyframe(frame=0, position=[0, 0, 0], rotation_y=0, action="stand"),
            CharacterKeyframe(frame=90, position=[1, 0, 0], rotation_y=0, action="stand"),
        ],
    )
    camera = SceneCamera(
        id="cam1",
        shot_type="medium",
        keyframes=[CameraKeyframe(frame=0, position=[5, -5, 3], look_at=[0, 0, 1])],
    )
    return SceneScriptRoot(
        scene=SceneInfo(name="test", duration=3.0, frame_rate=30),
        characters=[character],
        cameras=[camera],
        shots=[SceneShot(id="shot1", camera="cam1", start_frame=0, end_frame=90)],
    )


@dataclass
class _FakeLiveEngine:
    """An engine that leaves something decodable on disk.

    The media output gate refuses a payload below the audio size floor, and a
    TTS engine that reports success into a stub file is exactly the failure it
    exists to catch -- so the fake has to write an ID3 tag and an MPEG frame
    rather than the text it was handed.
    """

    provider: str = "fake-tts"
    model: str = "fake-tts-1"

    def is_configured(self) -> bool:
        return True

    def synthesize(
        self,
        text: str,
        character_id: str,
        output_path: str,
        emotion: str | None = None,
        voice_id: str | None = None,
    ) -> str:
        Path(output_path).write_bytes(_fake_tts_audio(text))
        return output_path


@dataclass
class _FakeBatchEngine:
    """A per-line engine that remembers which lines it was asked for.

    The §14.7 property under test is "changing one line re-synthesizes THAT
    line only" — which is only observable if the fake keeps a record of the
    requests it received.
    """

    provider: str = "fake-tts"
    model: str = "fake-tts-1"
    calls: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.calls = []

    def is_configured(self) -> bool:
        return True

    def synthesize(
        self,
        text: str,
        character_id: str,
        output_path: str,
        emotion: str | None = None,
        voice_id: str | None = None,
    ) -> str:
        self.calls.append({"text": text, "emotion": emotion})
        Path(output_path).write_bytes(_fake_tts_audio(text))
        return output_path

    def synthesize_batch(self, items, output_dir) -> list[str]:
        paths = []
        for item in items:
            path = os.path.join(output_dir, f"{item.get('segment_id', 'segment')}.mp3")
            self.synthesize(
                item["text"], item.get("character_id", ""), path, item.get("emotion")
            )
            paths.append(path)
        return paths


def _fake_tts_audio(text: str) -> bytes:
    return (
        b"ID3\x04\x00\x00"
        + b"\x00" * 10
        + text.encode("utf-8")
        + b"\xff\xfb\x90\x00"
        + b"\x00" * 512
    )


@dataclass
class _FakeVendorShapedEngine:
    """A real engine's shape: ``.model`` but no ``.provider``.

    ``StepFunTTSEngine`` and ``FishAudioTTSEngine`` both look like this, so
    the provider label has to be derived rather than read.
    """

    model: str = "stepaudio-2.5-tts"

    def is_configured(self) -> bool:
        return True

    def synthesize(
        self,
        text: str,
        character_id: str,
        output_path: str,
        emotion: str | None = None,
        voice_id: str | None = None,
    ) -> str:
        Path(output_path).write_bytes(_fake_tts_audio(text))
        return output_path


class _StepFunShapedEngine(_FakeVendorShapedEngine):
    """Named like the real engine so label derivation is exercised."""


_StepFunShapedEngine.__name__ = "StepFunTTSEngine"


# ---------------------------------------------------------------------------
# VoiceCastNodeExecutor
# ---------------------------------------------------------------------------


class _StubQaRegistry:
    """Registry double: ``statuses`` decides what the gate sees."""

    def __init__(self, statuses: list[str] | None = None) -> None:
        self._statuses = statuses or ["pass"]

    def report(self, subject) -> dict:
        outcomes = [
            {
                "check": f"stub_{index}",
                "status": status,
                "reason": "stub" if status == "pass" else f"stub {status}",
                "details": {},
            }
            for index, status in enumerate(self._statuses)
        ]
        return {
            "checks": [outcome["check"] for outcome in outcomes],
            "outcomes": outcomes,
            "failed": [o["check"] for o in outcomes if o["status"] == "fail"],
            "warned": [o["check"] for o in outcomes if o["status"] == "warn"],
            "passed": not any(o["status"] == "fail" for o in outcomes),
        }


def _all_pass_qa_factory():
    return lambda: _StubQaRegistry(["pass"])


def _fixed_qa_factory(statuses: list[str]):
    return lambda: _StubQaRegistry(statuses)


def test_voicecast_synthesizes_prepared_prompt() -> None:
    node = _make_node(
        node_type="voice-cast",
        creative_role="voice_cast",
        generation_prompt="你好，世界",
    )
    executor = VoiceCastNodeExecutor(
        Settings(agent_runtime_mode="fake"),
        engine=_FakeLiveEngine(),
        qa_registry_factory=_all_pass_qa_factory(),
    )

    outcome = executor(_context(node))

    assert outcome.media is not None
    assert outcome.media.content == _fake_tts_audio("你好，世界")
    assert outcome.media.mime_type == "audio/mpeg"
    assert outcome.media.filename == "voice-cast.mp3"
    # provider/model_id are the first-class asset columns; they must not be
    # null just because a voice-cast node resolves no catalog model.
    assert outcome.media.metadata == {
        "provider": "fake-tts",
        "model_id": "fake-tts-1",
        "tts_provider": "fake-tts",
        "tts_model": "fake-tts-1",
        "media_output_gate": {
            "status": "passed",
            "media_type": "audio",
            "size_bytes": len(_fake_tts_audio("你好，世界")),
            "checks": [
                {"code": "media_output_format_matches", "status": "passed",
                 "detected_media_format": "mp3"},
                {"code": "media_output_minimum_size", "status": "passed",
                 "size_bytes": len(_fake_tts_audio("你好，世界")),
                 "minimum_bytes": 512},
            ],
            "detected_media_format": "mp3",
            "mime_type": "audio/mpeg",
        },
    }
    assert outcome.structured_content == {
        "tts_provider": "fake-tts",
        "tts_model": "fake-tts-1",
    }


def test_voicecast_stamps_a_vendor_shaped_engine_onto_the_asset() -> None:
    """A real engine exposes ``.model`` but no ``.provider``.

    The label has to be derived (``StepFunTTSEngine`` -> ``stepfun``) or the
    asset row carries a class name that matches nothing else in the system.
    """

    node = _make_node(
        node_type="voice-cast",
        creative_role="voice_cast",
        generation_prompt="你好，世界",
    )
    executor = VoiceCastNodeExecutor(
        Settings(agent_runtime_mode="fake"),
        engine=_StepFunShapedEngine(),
        qa_registry_factory=_all_pass_qa_factory(),
    )

    outcome = executor(_context(node))

    assert outcome.media is not None
    assert outcome.media.metadata["provider"] == "stepfun"
    assert outcome.media.metadata["model_id"] == "stepaudio-2.5-tts"
    assert outcome.media.metadata["tts_provider"] == "stepfun"
    assert outcome.structured_content == {
        "tts_provider": "stepfun",
        "tts_model": "stepaudio-2.5-tts",
    }


def test_voicecast_model_label_is_none_when_the_engine_exposes_no_model() -> None:
    node = _make_node(
        node_type="voice-cast",
        creative_role="voice_cast",
        generation_prompt="hello",
    )

    class _NoModelEngine:
        def is_configured(self) -> bool:
            return True

        def synthesize(
            self,
            text: str,
            character_id: str,
            output_path: str,
            emotion: str | None = None,
            voice_id: str | None = None,
        ) -> str:
            Path(output_path).write_bytes(_fake_tts_audio(text))
            return output_path

    executor = VoiceCastNodeExecutor(
        Settings(agent_runtime_mode="fake"),
        engine=_NoModelEngine(),
        qa_registry_factory=_all_pass_qa_factory(),
    )

    outcome = executor(_context(node))

    assert outcome.media is not None
    assert outcome.media.metadata["provider"] == "_NoModelEngine"
    assert outcome.media.metadata["model_id"] is None


def test_voicecast_prefers_structured_content_over_prompt() -> None:
    node = _make_node(
        node_type="voice-cast",
        creative_role="voice_cast",
        generation_prompt="ignored prompt",
        structured_content={"content": "authored line"},
    )
    executor = VoiceCastNodeExecutor(
        Settings(agent_runtime_mode="fake"),
        engine=_FakeLiveEngine(),
        qa_registry_factory=_all_pass_qa_factory(),
    )

    outcome = executor(_context(node))

    assert outcome.media is not None
    assert outcome.media.content == _fake_tts_audio("authored line")


def test_voicecast_fails_without_text() -> None:
    node = _make_node(node_type="voice-cast", creative_role="voice_cast")
    executor = VoiceCastNodeExecutor(
        Settings(agent_runtime_mode="fake"),
        engine=_FakeLiveEngine(),
        qa_registry_factory=_all_pass_qa_factory(),
    )

    with pytest.raises(V2PersistenceError) as exc_info:
        executor(_context(node))

    assert exc_info.value.code == "node_prompt_empty"


def test_voicecast_fails_closed_when_tts_not_configured() -> None:
    node = _make_node(
        node_type="voice-cast",
        creative_role="voice_cast",
        generation_prompt="hello",
    )
    executor = VoiceCastNodeExecutor(
        Settings(agent_runtime_mode="fake"),
        engine=SimpleTTSEngine(),
    )

    with pytest.raises(V2PersistenceError) as exc_info:
        executor(_context(node))

    assert exc_info.value.code == "voicecast_tts_unconfigured"


@dataclass
class _RejectingStepFunEngine(_StepFunShapedEngine):
    """Stands in for a StepFun engine whose credential the gateway refuses."""

    def synthesize(
        self,
        text: str,
        character_id: str,
        output_path: str,
        emotion: str | None = None,
        voice_id: str | None = None,
    ) -> str:
        raise RuntimeError(
            "StepFun TTS API error 401: "
            '{"error":{"message":"Incorrect API key provided",'
            '"type":"invalid_api_key"}}'
        )


def test_voicecast_names_the_provider_when_the_tts_request_fails() -> None:
    """A rejected credential must say which vendor to re-credential.

    The live failure was a 401 from StepFun surfacing as a bare ``RuntimeError``
    whose free text was the only clue.  The attempt error now carries the
    provider, the model and a remedy in structured ``details``, so a caller can
    act on it without parsing prose.
    """
    node = _make_node(
        node_type="voice-cast",
        creative_role="voice_cast",
        generation_prompt="hello",
    )
    executor = VoiceCastNodeExecutor(
        Settings(agent_runtime_mode="fake"),
        engine=_RejectingStepFunEngine(),
    )

    with pytest.raises(V2PersistenceError) as exc_info:
        executor(_context(node))

    error = exc_info.value
    assert error.code == "voicecast_tts_failed"
    assert "stepfun" in str(error)
    assert error.details["tts_provider"] == "stepfun"
    assert error.details["tts_model"] == "stepaudio-2.5-tts"
    assert error.details["failure_type"] == "RuntimeError"
    assert "401" in error.details["failure"]
    assert error.details["remedy"]
    # The disposition is the part that actually reaches the client.
    disposition = error.details["actionable_failure"]
    assert disposition.user_action == "revise"
    assert disposition.retry_scope == "none"
    assert disposition.retryable is False


# ---------------------------------------------------------------------------
# Scene3DNodeExecutor
# ---------------------------------------------------------------------------


@dataclass
class _FakeCapability:
    state: str = "ready"
    error: str | None = None


@dataclass
class _FakeRenderResult:
    success: bool = True
    frame_count: int = 2
    error: str | None = None
    blender_version: str = "Blender 5.2"
    # The real RenderResult reports which pass ran; the fake must too, or the
    # executor's metadata would be tested against a value it can never see.
    # Default is set per-call by `_renderer_that_mirrors_the_flag`: the real
    # renderer derives `rendered_frames` from the `keyframes_only` argument it
    # was handed, so a fake with a frozen value would test the fixture instead
    # of the wiring.
    rendered_frames: str = "animation"
    degraded_assets: tuple[str, ...] = ()


def _renderer_that_mirrors_the_flag(script, frames_dir, **kwargs):
    """A fake renderer that reports the pass it was asked for.

    Mirrors ``blender_renderer.render_scene_script``, which derives
    ``rendered_frames`` from its own ``keyframes_only`` argument. Without this,
    ``scene3d_rendered_frames`` in the executor's metadata would be a value the
    executor can never influence — the test would pass no matter what it asked
    the renderer for.
    """

    return _FakeRenderResult(
        rendered_frames="keyframes" if kwargs.get("keyframes_only") else "animation"
    )


@dataclass
class _FakeEncodeResult:
    success: bool = True
    output_path: str | None = None
    frame_count: int = 2
    error: str | None = None


def _render_less_params() -> dict[str, Any]:
    """Fakes for an executor that is never asked to render.

    ``_render_timeout_for`` only needs the settings, but the constructor demands
    the whole collaborator set; these keep it hermetic.
    """

    return {
        "capability_probe": lambda: _FakeCapability(),
        "renderer": lambda script, frames_dir, **kwargs: _FakeRenderResult(),
        "encoder": lambda input_dir, output_path, fps=30: _FakeEncodeResult(),
    }


def _scene3d_executor(**overrides: Any) -> Scene3DNodeExecutor:
    params: dict[str, Any] = _scene3d_params()
    params.update(overrides)
    return Scene3DNodeExecutor(Settings(agent_runtime_mode="fake"), **params)


def _scene3d_params() -> dict[str, Any]:
    """Fakes for an executor that renders, encodes and muxes for real.

    The encoder writes the bytes the executor then reads, because the mux step
    opens its own output path.
    """
    from pathlib import Path as _Path

    return {
        "capability_probe": lambda: _FakeCapability(),
        "renderer": _renderer_that_mirrors_the_flag,
        "encoder": lambda input_dir, output_path, fps=30: (
            _Path(output_path).write_bytes(b"\x00\x00\x00\x18ftypmp42fake"),
            _FakeEncodeResult(),
        )[1],
    }


def _scene3d_node() -> CanvasNodeV2:
    script = _minimal_scene_script().model_dump(mode="json")
    return _make_node(
        node_type="scene-3d",
        creative_role="scene_3d_previs",
        structured_content={"scene_script": script},
    )


def test_scene3d_renders_to_mp4() -> None:
    outcome = _scene3d_executor()(_context(_scene3d_node()))

    assert outcome.media is not None
    assert outcome.media.content == b"\x00\x00\x00\x18ftypmp42fake"
    assert outcome.media.mime_type == "video/mp4"
    assert outcome.media.filename == "previs.mp4"
    assert outcome.media.metadata["scene3d_renderer"] == "blender"
    assert outcome.media.metadata["blender_version"] == "Blender 5.2"


def test_scene3d_reports_which_frames_it_rendered() -> None:
    """A slideshow of keyframes must not read as an animation downstream.

    ``scene3d_rendered_frames`` is the only signal a consumer has that the clip
    is a draft; the frame list pins which instants those are.
    """

    outcome = _scene3d_executor()(_context(_scene3d_node()))

    metadata = outcome.media.metadata
    assert metadata["scene3d_rendered_frames"] == "animation"
    # The keyframe schedule is still published for the video model — a full
    # render costs time, not the reference frames it extracts.
    assert metadata["scene3d_keyframe_frames"] == [0, 22, 44, 67, 89]


def test_scene3d_asks_the_renderer_for_the_full_animation() -> None:
    """The previs must move, so the default render is the full animation.

    Five keyframes cannot show a dolly, a pan or a cut — a "previs" made of
    stills is a slideshow, and that is exactly what authors reported. The video
    model downstream still gets its reference frames (extracted from the
    rendered frames), so a full pass costs wall clock and nothing else.
    """

    seen: dict[str, object] = {}

    def _renderer(script, frames_dir, **kwargs):
        seen.update(kwargs)
        return _FakeRenderResult()

    _scene3d_executor(renderer=_renderer)(_context(_scene3d_node()))

    assert seen["keyframes_only"] is False
    # The budget follows the whole animation's frame count (capped by the
    # 1800s ceiling): the default render is asked to finish what it started.
    # Slope is measured, not guessed: a real 180-frame render took 168.7s.
    assert seen["timeout_seconds"] == min(
        1800, 90 + 2 * _minimal_scene_script().total_frames
    )


def test_scene3d_can_still_ask_for_the_draft_pass() -> None:
    """The escape hatch stays: a node run purely as a data source.

    Nobody watches that result, so keyframes-only remain available — but it is
    an explicit opt-in now, not the default that silently shipped a slideshow.
    """

    import dataclasses

    from app.core.config import Settings

    seen: dict[str, object] = {}

    def _renderer(script, frames_dir, **kwargs):
        seen.update(kwargs)
        return _FakeRenderResult()

    settings = dataclasses.replace(
        Settings(agent_runtime_mode="fake"),
        scene3d_render_keyframes_only=True,
    )
    params = _scene3d_params()
    params["renderer"] = _renderer
    Scene3DNodeExecutor(settings, **params)(_context(_scene3d_node()))

    assert seen["keyframes_only"] is True
    # 5 keyframes at the measured 90s startup + 2s/frame, not the 1800s
    # ceiling: the draft must not be given a full animation's patience.
    assert seen["timeout_seconds"] == 100


def test_scene3d_timeout_follows_the_frame_count() -> None:
    """The budget follows the work, not a flat guess.

    A flat timeout has to serve both a 5-frame draft (which measured 7.7s end
    to end) and a 240-frame animation, so it either kills the full pass early or
    lets the draft hang for half an hour after the failure it should report.
    """

    import dataclasses

    from app.schemas.scene_script import SceneShot

    def _timeout(script: SceneScriptRoot, **overrides: object) -> int:
        settings = dataclasses.replace(
            Settings(agent_runtime_mode="fake"), **overrides  # type: ignore[arg-type]
        )
        executor = Scene3DNodeExecutor(settings, **_render_less_params())
        return executor._render_timeout_for(script)

    short = _minimal_scene_script()
    # The default IS the full animation now: keyframes-only is the opt-in, so
    # the default budget must be the animation's.
    assert _timeout(short) == 90 + 2 * short.total_frames
    assert (
        _timeout(short, scene3d_render_keyframes_only=True)
        == 90 + 2 * 5  # 5 keyframes
    )

    long = _minimal_scene_script()
    long.shots = [
        SceneShot(id=f"shot{i}", camera="cam1", start_frame=i * 60, end_frame=(i + 1) * 60)
        for i in range(4)
    ]
    long.scene.duration = 8.0
    animation = _timeout(long)
    draft = _timeout(long, scene3d_render_keyframes_only=True)
    assert animation == 90 + 2 * 240
    assert draft == 90 + 2 * 20  # 4 shots x 5 keyframes
    # The draft of a 240-frame scene must not be handed the animation's budget.
    # 12x the frames, so well over 4x the budget even after the fixed startup
    # flattens the ratio.
    assert animation > draft * 4
    assert animation - draft == 2 * (240 - 20)


def test_scene3d_timeout_never_exceeds_the_configured_ceiling() -> None:
    """The ceiling is a cap, not a value: the derived budget wins when smaller.

    A 90-frame animation derives 270s at the measured slope, but an operator
    who set 300s must not be overruled by the formula.
    """

    import dataclasses

    settings = dataclasses.replace(
        Settings(agent_runtime_mode="fake"),
        scene3d_render_timeout_seconds=300,
        scene3d_render_keyframes_only=False,
    )
    executor = Scene3DNodeExecutor(settings, **_render_less_params())
    assert executor._render_timeout_for(_minimal_scene_script()) == 270

    # And the same executor's draft is still way under it.
    draft = dataclasses.replace(settings, scene3d_render_keyframes_only=True)
    assert (
        Scene3DNodeExecutor(draft, **_render_less_params())._render_timeout_for(
            _minimal_scene_script()
        )
        == 100
    )


def test_scene3d_timeout_has_a_floor_for_a_one_frame_scene() -> None:
    import dataclasses

    settings = dataclasses.replace(
        Settings(agent_runtime_mode="fake"),
        scene3d_render_startup_seconds=0,
        scene3d_render_seconds_per_frame=0.0,
    )
    executor = Scene3DNodeExecutor(settings, **_render_less_params())
    assert executor._render_timeout_for(_minimal_scene_script()) == 30


def test_scene3d_renders_the_full_animation_by_default() -> None:
    """The default must make the previs move.

    This is the whole point: a node run with no tuning should produce an
    animatic an author can watch for pacing, not five stills.
    """

    import dataclasses

    executor = _scene3d_executor()
    assert executor._keyframes_only is False

    # Explicit opt-in into the draft pass still works.
    settings = dataclasses.replace(
        Settings(agent_runtime_mode="fake"),
        scene3d_render_keyframes_only=True,
    )
    params = _render_less_params()
    params["renderer"] = lambda script, frames_dir, **kwargs: _FakeRenderResult()
    executor = Scene3DNodeExecutor(settings, **params)
    assert executor._keyframes_only is True


def test_scene3d_surfaces_degraded_assets_in_metadata() -> None:
    executor = _scene3d_executor(
        renderer=lambda script, frames_dir, **kwargs: _FakeRenderResult(
            degraded_assets=("prop_halberd",)
        )
    )
    outcome = executor(_context(_scene3d_node()))

    assert outcome.media.metadata["degraded_assets"] == ["prop_halberd"]


def test_scene3d_accepts_json_string_script() -> None:
    node = _make_node(
        node_type="scene-3d",
        creative_role="scene_3d_previs",
        structured_content={"scene_script": _minimal_scene_script().model_dump_json()},
    )

    outcome = _scene3d_executor()(_context(node))

    assert outcome.media is not None


def test_scene3d_fails_without_scene_script() -> None:
    node = _make_node(node_type="scene-3d", creative_role="scene_3d_previs")

    with pytest.raises(V2PersistenceError) as exc_info:
        _scene3d_executor()(_context(node))

    assert exc_info.value.code == "scene3d_scene_script_missing"


def test_scene3d_fails_closed_when_blender_missing() -> None:
    executor = _scene3d_executor(
        capability_probe=lambda: _FakeCapability(
            state="unsupported",
            error="Blender executable not found",
        )
    )

    with pytest.raises(V2PersistenceError) as exc_info:
        executor(_context(_scene3d_node()))

    assert exc_info.value.code == "scene3d_blender_unavailable"
    assert "Blender executable not found" in str(exc_info.value)


def test_scene3d_fails_when_render_produces_no_frames() -> None:
    executor = _scene3d_executor(
        renderer=lambda script, frames_dir, **kwargs: _FakeRenderResult(
            success=False,
            frame_count=0,
            error="Blender exited with code 1",
        )
    )

    with pytest.raises(V2PersistenceError) as exc_info:
        executor(_context(_scene3d_node()))

    assert exc_info.value.code == "scene3d_render_failed"
    assert "Blender exited with code 1" in str(exc_info.value)


def test_scene3d_fails_when_encoding_fails() -> None:
    executor = _scene3d_executor(
        encoder=lambda input_dir, output_path, fps=30: _FakeEncodeResult(
            success=False,
            error="ffmpeg not found",
        )
    )

    with pytest.raises(V2PersistenceError) as exc_info:
        executor(_context(_scene3d_node()))

    assert exc_info.value.code == "scene3d_encode_failed"


# ---------------------------------------------------------------------------
# Dispatcher registration
# ---------------------------------------------------------------------------


def test_dispatcher_routes_local_engine_nodes() -> None:
    called: list[str] = []

    def voice_executor(_: NodeExecutionContext) -> NodeExecutionOutcome:
        called.append("voice-cast")
        return NodeExecutionOutcome()

    def scene_executor(_: NodeExecutionContext) -> NodeExecutionOutcome:
        called.append("scene-3d")
        return NodeExecutionOutcome()

    dispatcher = NodeExecutionDispatcher(
        voice_cast_executor=voice_executor,
        scene_3d_executor=scene_executor,
    )

    voice_node = _make_node(node_type="voice-cast", creative_role="voice_cast")
    scene_node = _scene3d_node()
    dispatcher.execute(_context(voice_node))
    dispatcher.execute(_context(scene_node))

    assert called == ["voice-cast", "scene-3d"]


# ---------------------------------------------------------------------------
# SceneScript generation path inside Scene3DNodeExecutor
# ---------------------------------------------------------------------------


@dataclass
class _FakeScriptGenerator:
    script: SceneScriptRoot
    seen_descriptions: list[str]

    def generate(self, *, description: str) -> SceneScriptRoot:
        self.seen_descriptions.append(description)
        return self.script


def _draft_scene3d_node(prompt: str = "A quiet indoor cafe at dusk") -> CanvasNodeV2:
    return _make_node(
        node_type="scene-3d",
        creative_role="scene_3d_previs",
        generation_prompt=prompt,
    )


def test_scene3d_generates_script_from_prompt_then_renders() -> None:
    generator = _FakeScriptGenerator(_minimal_scene_script(), [])
    executor = _scene3d_executor(script_generator=generator)

    outcome = executor(_context(_draft_scene3d_node()))

    assert generator.seen_descriptions == ["A quiet indoor cafe at dusk"]
    assert outcome.media is not None
    assert outcome.media.content == b"\x00\x00\x00\x18ftypmp42fake"
    assert outcome.structured_content is not None
    persisted = outcome.structured_content["scene_script"]
    assert persisted["scene"]["name"] == "test"
    assert persisted["shots"][0]["camera"] == "cam1"


def test_scene3d_generation_publishes_scene_script_structured_content() -> None:
    node = _make_node(
        node_type="scene-3d",
        creative_role="scene_3d_previs",
        generation_prompt="A quiet indoor cafe at dusk",
        structured_content={"previs_control_level": "full"},
    )
    executor = _scene3d_executor(
        script_generator=_FakeScriptGenerator(_minimal_scene_script(), [])
    )

    outcome = executor(_context(node))

    # The executor publishes only its own keys; publish_node_output merges
    # them onto the persisted column, preserving panel-authored fields such
    # as previs_control_level (locked in test_agent_canvas_review_fixes).
    assert outcome.structured_content is not None
    assert set(outcome.structured_content) == {
            "scene_script",
            "previs_trajectory",
            "scene3d_consistency",
            # Animatic provenance (V0.2 §14.9): published for every scene —
            # here the scene has no speech binding, so nothing to mux.
            "animatic_audio",
            # Cross-node drift (V0.2 §5 服装维度): published for every scene.
            "scene3d_wardrobe_drift",
            # Continuity State's motion dimension (V0.2 §5): published for
            # every scene — the gate had no caller until now.
            "scene3d_blocking_continuity",
            # §13 第 4 问: the declared reading reconciled with the
            # continuity findings on the same boundary.
            "scene3d_transition_intent",
        }
    assert outcome.structured_content["animatic_audio"]["reason"] == "no_speech_binding"
    assert outcome.structured_content["scene_script"]["scene"]["name"] == "test"


def test_scene3d_generator_failure_maps_to_error_code() -> None:
    class _BrokenGenerator:
        def generate(self, *, description: str) -> SceneScriptRoot:
            raise SceneScriptGenerationError("scene3d_llm_unconfigured", "missing key")

    executor = _scene3d_executor(script_generator=_BrokenGenerator())

    with pytest.raises(V2PersistenceError) as exc_info:
        executor(_context(_draft_scene3d_node()))

    assert exc_info.value.code == "scene3d_llm_unconfigured"


def test_scene3d_publishes_the_camera_trajectory() -> None:
    """The trajectory, not the clip, is the deliverable a video node binds.

    An MP4 tells a consumer nothing it can act on: it cannot tell which frames
    exist, where the camera was at each one, or how long a shot runs.  All of
    that is derivable from the SceneScript, so it is published rather than left
    for every consumer to re-derive (and re-derive differently).
    """

    outcome = _scene3d_executor()(_context(_scene3d_node()))

    assert outcome.structured_content is not None
    trajectory = outcome.structured_content["previs_trajectory"]
    assert trajectory["coordinate_system"] == "blender_z_up"
    assert trajectory["frame_rate"] == 30
    assert trajectory["total_frames"] == 90
    assert trajectory["duration_seconds"] == 3.0
    # The default pass is the full animation, and the trajectory must say so —
    # a consumer reading "keyframes" would measure a 3s scene as 5 instants.
    assert trajectory["rendered_frames"] == "animation"
    # In a full pass every frame exists, so the schedule is the frame list — the
    # draft's five instants are the exception, not the rule.
    assert trajectory["keyframe_frames"] == list(range(90))

    (shot,) = trajectory["shots"]
    assert shot["id"] == "shot1"
    assert shot["camera"] == "cam1"
    assert shot["shot_type"] == "medium"
    assert shot["start_frame"] == 0
    assert shot["end_frame"] == 90
    assert shot["start_seconds"] == 0.0
    assert shot["end_seconds"] == 3.0
    # The keyframe plan is per-shot (five instants of THIS shot) and is
    # published in both passes; `rendered_frames` is what this pass actually
    # produced, which in a full pass is every one of those five.
    assert shot["keyframe_frames"] == [0, 22, 44, 67, 89]
    assert shot["rendered_frames"] == [0, 22, 44, 67, 89]
    assert shot["camera_keyframes"] == [
        {"frame": 0, "position": [5, -5, 3], "look_at": [0, 0, 1]}
    ]


def test_scene3d_trajectory_marks_a_full_pass_as_continuous() -> None:
    """``rendered_frames`` is the one field that distinguishes draft from full.

    A consumer that measures a clip's duration against ``total_frames`` gets a
    wrong answer for a draft unless it reads this.
    """

    outcome = _scene3d_executor(
        renderer=lambda script, frames_dir, **kwargs: _FakeRenderResult(
            rendered_frames="animation"
        ),
    )(_context(_scene3d_node()))

    trajectory = outcome.structured_content["previs_trajectory"]
    assert trajectory["rendered_frames"] == "animation"
    assert trajectory["keyframe_frames"] == list(range(90))
    assert outcome.media.metadata["scene3d_rendered_frames"] == "animation"
    # The keyframe schedule is published in BOTH passes: it is what a video
    # model binds, and the full animation extracts exactly these instants.
    assert outcome.media.metadata["scene3d_keyframe_frames"] == [0, 22, 44, 67, 89]


def test_scene3d_can_skip_the_video_and_publish_a_still() -> None:
    """The MP4 is optional; the trajectory is not.

    An operator running the node purely as a data source for a video model does
    not want an encoder in the path at all, but the node still has to carry a
    real image -- and the metadata has to say which frame it is, so one still is
    never mistaken for the whole previs.
    """

    import dataclasses

    rendered: list[int] = []

    def _renderer(scene_script, frames_dir, **kwargs):
        # Write the frames the draft pass would write, as Blender does:
        # 1-indexed, unpadded.
        for frame in keyframe_render_frames(scene_script):
            (Path(frames_dir) / f"frame_{frame + 1}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            rendered.append(frame)
        return _FakeRenderResult()

    def _encoder(input_dir, output_path, fps=30):  # pragma: no cover - must not run
        raise AssertionError("the encoder must not run when video is disabled")

    settings = dataclasses.replace(
        Settings(agent_runtime_mode="fake"), scene3d_emit_video=False
    )
    executor = Scene3DNodeExecutor(
        settings,
        capability_probe=lambda: _FakeCapability(),
        renderer=_renderer,
        encoder=_encoder,
    )

    outcome = executor(_context(_scene3d_node()))

    assert rendered == [0, 22, 44, 67, 89]
    assert outcome.media.mime_type == "image/png"
    assert outcome.media.filename == "previs_still.png"
    assert outcome.media.content == b"\x89PNG\r\n\x1a\n"
    # The establishing frame, not "some frame".
    assert outcome.media.metadata["scene3d_still_frame"] == 0
    assert outcome.media.metadata["scene3d_rendered_frames"] == "animation"
    # The data half survives either way.
    assert outcome.structured_content["previs_trajectory"]["rendered_frames"] == "animation"
    assert outcome.structured_content["previs_trajectory"]["keyframe_frames"] == list(
        range(90)
    )
    assert outcome.structured_content["previs_trajectory"]["shots"][0]["keyframe_frames"] == [
        0,
        22,
        44,
        67,
        89,
    ]


def test_scene3d_fails_when_no_rendered_frame_can_be_read_back() -> None:
    """A render that claims frames it never wrote must not publish a still."""

    import dataclasses

    settings = dataclasses.replace(
        Settings(agent_runtime_mode="fake"), scene3d_emit_video=False
    )
    executor = Scene3DNodeExecutor(
        settings,
        capability_probe=lambda: _FakeCapability(),
        # Reports success and a frame count, but writes nothing -- the exact
        # shape of a Blender that "succeeded" into a directory we cannot read.
        renderer=lambda script, frames_dir, **kwargs: _FakeRenderResult(frame_count=5),
        encoder=lambda input_dir, output_path, fps=30: _FakeEncodeResult(),
    )

    with pytest.raises(V2PersistenceError) as exc_info:
        executor(_context(_scene3d_node()))

    assert exc_info.value.code == "scene3d_render_failed"


def test_scene3d_prefers_existing_script_without_calling_generator() -> None:
    class _MustNotRunGenerator:
        def generate(self, *, description: str) -> SceneScriptRoot:
            raise AssertionError("generator must not be called for a stored script")

    executor = _scene3d_executor(script_generator=_MustNotRunGenerator())

    outcome = executor(_context(_scene3d_node()))

    assert outcome.media is not None
    # No script was generated, so the node's column keeps whatever the panel
    # authored; the executor adds the trajectory it derived plus the
    # consistency report (published for every scene, generated or not).
    assert outcome.structured_content == {
        "previs_trajectory": outcome.structured_content["previs_trajectory"],
        "scene3d_consistency": outcome.structured_content["scene3d_consistency"],
        "animatic_audio": outcome.structured_content["animatic_audio"],
        "scene3d_wardrobe_drift": outcome.structured_content["scene3d_wardrobe_drift"],
        # The motion gate and the reconciliation run for every scene, so this
        # single-shot scene publishes both (empty: nothing to reconcile).
        "scene3d_blocking_continuity": [],
        "scene3d_transition_intent": [],
    }
    assert outcome.structured_content["animatic_audio"]["reason"] == "no_speech_binding"
    assert "scene_script" not in outcome.structured_content


def test_scene3d_fails_when_prompt_empty_and_no_generator() -> None:
    node = _make_node(node_type="scene-3d", creative_role="scene_3d_previs")
    executor = _scene3d_executor(script_generator=_FakeScriptGenerator(_minimal_scene_script(), []))

    with pytest.raises(V2PersistenceError) as exc_info:
        executor(_context(node))

    assert exc_info.value.code == "scene3d_scene_script_missing"


# ---------------------------------------------------------------------------
# TemplateSceneScriptGenerator
# ---------------------------------------------------------------------------


def test_template_generator_builds_valid_script() -> None:
    generator = TemplateSceneScriptGenerator()

    script = generator.generate(description="A wide view of an ancient hall")

    assert isinstance(script, SceneScriptRoot)
    assert script.cameras
    assert script.shots
    assert script.shots[0].camera == script.cameras[0].id


def test_template_generator_fails_on_empty_description() -> None:
    with pytest.raises(SceneScriptGenerationError) as exc_info:
        TemplateSceneScriptGenerator().generate(description="   ")

    assert exc_info.value.code == "scene3d_scene_script_missing"


# ---------------------------------------------------------------------------
# LLMSceneScriptGenerator
# ---------------------------------------------------------------------------


def _llm_settings() -> Settings:
    return Settings(
        agent_runtime_mode="real",
        llm_api_key="test-key",
        llm_base_url="https://llm.example/v1",
    )


def _client_factory(transport: httpx.BaseTransport) -> Callable[..., httpx.Client]:
    def factory(**_kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=transport)

    return factory


def _valid_script_response() -> dict[str, Any]:
    script = _minimal_scene_script().model_dump(mode="json")
    content = "```json\n" + json.dumps(script) + "\n```"
    return {"choices": [{"message": {"content": content}}]}


def test_llm_generator_generates_valid_script() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=_valid_script_response())
    )
    generator = LLMSceneScriptGenerator(_llm_settings(), client_factory=_client_factory(transport))

    script = generator.generate(description="A character walks into the room")

    assert isinstance(script, SceneScriptRoot)
    assert script.scene.name == "test"


def test_llm_generator_fails_without_configuration() -> None:
    generator = LLMSceneScriptGenerator(
        Settings(agent_runtime_mode="real"),
        client_factory=_client_factory(httpx.MockTransport(lambda r: httpx.Response(500))),
    )

    with pytest.raises(SceneScriptGenerationError) as exc_info:
        generator.generate(description="anything")

    assert exc_info.value.code == "scene3d_llm_unconfigured"


def test_llm_generator_fails_on_invalid_output() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"choices": [{"message": {"content": "no json here"}}]}
        )
    )
    generator = LLMSceneScriptGenerator(_llm_settings(), client_factory=_client_factory(transport))

    with pytest.raises(SceneScriptGenerationError) as exc_info:
        generator.generate(description="anything")

    assert exc_info.value.code == "scene3d_scene_script_generation_failed"


def test_llm_generator_fails_on_http_error() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503, text="service unavailable"))
    generator = LLMSceneScriptGenerator(_llm_settings(), client_factory=_client_factory(transport))

    with pytest.raises(SceneScriptGenerationError) as exc_info:
        generator.generate(description="anything")

    assert exc_info.value.code == "scene3d_scene_script_generation_failed"


# ---------------------------------------------------------------------------
# VoiceCastNodeExecutor — unified audio bed (StepAudio 3 Gen)
# ---------------------------------------------------------------------------


def _audio_bed_node(config: dict | None = None, **overrides) -> CanvasNodeV2:
    structured: dict = {}
    if config is not None:
        structured["audio_bed"] = config
    return _make_node(
        node_type="voice-cast",
        creative_role="voice_cast",
        structured_content=structured,
        **overrides,
    )


_BED_CONFIG = {
    "scripts": [
        {"text": "[地下研究所 B2 层，低频电机嗡鸣]"},
        {"speaker": "林澈", "text": "（压低声音，警惕）就是这里，信号源在墙后面。"},
    ],
    "roles": [{"name": "林澈", "description": "二十多岁的男性，嗓音低沉冷静"}],
    "instruction": "废弃地下研究所，悬疑氛围",
}


class _FakeAudioBedAdapter:
    """Adapter double: records the call, writes a WAV under the data dir.

    Mirrors the real adapter's contract: ``status``/``local_path`` on success,
    ``status: failed`` + ``error_code`` on failure, and the storage path is
    relative to the media data dir the executor owns.
    """

    def __init__(
        self,
        data_dir,
        *,
        status: str = "ready",
        error_code: str | None = None,
    ) -> None:
        self.calls: list[dict] = []
        self._data_dir = data_dir
        self._status = status
        self._error_code = error_code

    def generate_unified_audio(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        if self._status != "ready":
            return {
                "status": "failed",
                "error": "provider said no",
                "error_code": self._error_code or "step_audio_gen_provider_error",
                "metadata": {"retryable": True},
            }
        from app.services.agent_canvas_node_execution import _mock_audio_bed_bytes

        relative = "assets/provider-output/wf-bed/step_audio_gen_test.wav"
        target = self._data_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_mock_audio_bed_bytes({"scripts": kwargs.get("scripts") or []}))
        return {
            "status": "ready",
            "local_path": relative,
            "duration_seconds": 4.5,
            "audio_codec": "pcm_s16le",
        }


def test_voicecast_audio_bed_mock_mode_writes_deterministic_wav(tmp_path) -> None:
    node = _audio_bed_node(_BED_CONFIG)
    executor = VoiceCastNodeExecutor(
        Settings(agent_runtime_mode="fake", media_data_dir=tmp_path / "data"),
        # This test's subject is the bed's asset shape, not the QA gate (the
        # gate has its own tests below, incl. one against real ffmpeg).
        qa_registry_factory=_all_pass_qa_factory(),
    )

    outcome = executor(_context(node))

    assert outcome.media is not None
    assert outcome.media.metadata["audio_bed"] is True
    assert outcome.media.metadata["duration_source"] == "mock"
    # The model returns no per-element timestamps: that fact travels with the
    # asset so alignment cannot silently assume otherwise.
    assert outcome.media.metadata["per_element_timing_available"] is False
    assert outcome.media.metadata["script_count"] == 2
    assert outcome.media.metadata["role_count"] == 1
    assert outcome.media.filename == "audio-bed.mp3"


def test_voicecast_audio_bed_real_mode_reads_adapter_output(tmp_path) -> None:
    node = _audio_bed_node(_BED_CONFIG)
    data_dir = tmp_path / "data"
    adapter = _FakeAudioBedAdapter(data_dir)
    executor = VoiceCastNodeExecutor(
        Settings(
            agent_runtime_mode="real",
            media_mode="real",
            media_data_dir=data_dir,
            stepfun_api_key="test-key",
        ),
        audio_bed_adapter=adapter,
    )

    outcome = executor(_context(node))

    assert outcome.media is not None
    assert outcome.media.metadata["audio_bed"] is True
    assert outcome.media.metadata["duration_source"] == "measured"
    assert outcome.media.metadata["model_id"] == "stepaudio-3-gen-preview"
    # The executor forwards the bundle to the adapter with workflow ownership.
    call = adapter.calls[0]
    assert call["workflow_id"] == node.workflow_id
    assert [script["text"] for script in call["scripts"]] == [
        _BED_CONFIG["scripts"][0]["text"],
        _BED_CONFIG["scripts"][1]["text"],
    ]
    assert call["roles"] == _BED_CONFIG["roles"]
    assert call["instruction"] == _BED_CONFIG["instruction"]


def test_voicecast_audio_bed_adapter_failure_is_coded(tmp_path) -> None:
    node = _audio_bed_node(_BED_CONFIG)
    executor = VoiceCastNodeExecutor(
        Settings(
            agent_runtime_mode="real",
            media_mode="real",
            media_data_dir=tmp_path / "data",
            stepfun_api_key="test-key",
        ),
        audio_bed_adapter=_FakeAudioBedAdapter(tmp_path / "data", status="failed"),
    )

    with pytest.raises(V2PersistenceError) as exc:
        executor(_context(node))

    assert exc.value.code == "voicecast_audio_bed_failed"
    assert "provider said no" in str(exc.value)


def test_voicecast_audio_bed_unconfigured_key_is_actionable(tmp_path) -> None:
    node = _audio_bed_node(_BED_CONFIG)

    class _RaisingAdapter:
        def __init__(self, *args, **kwargs):
            raise MediaConfigurationError("STEPFUN_API_KEY is required")

    executor = VoiceCastNodeExecutor(
        Settings(
            agent_runtime_mode="real",
            media_mode="real",
            media_data_dir=tmp_path / "data",
        ),
        audio_bed_adapter=_RaisingAdapter,
    )

    with pytest.raises(V2PersistenceError) as exc:
        executor(_context(node))

    assert exc.value.code == "voicecast_audio_bed_unconfigured"
    details = exc.value.details or {}
    failure = details.get("actionable_failure")
    assert failure is not None
    assert failure.user_action == "revise"
    assert failure.retry_scope == "none"


def test_voicecast_audio_bed_requires_scripts() -> None:
    node = _audio_bed_node({"scripts": [], "roles": []})
    executor = VoiceCastNodeExecutor(Settings(agent_runtime_mode="fake"))

    with pytest.raises(V2PersistenceError) as exc:
        executor(_context(node))

    assert exc.value.code == "audio_bed_scripts_required"


def test_voicecast_audio_bed_rejects_non_object_scripts() -> None:
    node = _audio_bed_node({"scripts": ["just a string"]})
    executor = VoiceCastNodeExecutor(Settings(agent_runtime_mode="fake"))

    with pytest.raises(V2PersistenceError) as exc:
        executor(_context(node))

    assert exc.value.code == "audio_bed_scripts_invalid"


def test_voicecast_audio_bed_rejects_non_list_roles() -> None:
    node = _audio_bed_node({"scripts": [{"text": "hi"}], "roles": "nope"})
    executor = VoiceCastNodeExecutor(Settings(agent_runtime_mode="fake"))

    with pytest.raises(V2PersistenceError) as exc:
        executor(_context(node))

    assert exc.value.code == "audio_bed_roles_invalid"


# ---------------------------------------------------------------------------
# Scene3DNodeExecutor — Dramagic-style consistency publication
# ---------------------------------------------------------------------------


def test_scene3d_publishes_consistency_report_on_the_node() -> None:
    """A multi-shot scene with an unbound character must SURFACE the warning,
    not silently render (engineering standard §4: queryable, never silent —
    and never a new blocker on an old path, so the render still succeeds)."""

    script = _minimal_scene_script()
    # Multi-shot so the unbound-character check applies.
    script.shots = [
        SceneShot(id="shot1", camera="cam1", start_frame=0, end_frame=45),
        SceneShot(id="shot2", camera="cam1", start_frame=46, end_frame=90),
    ]
    node = _make_node(
        node_type="scene-3d",
        creative_role="scene_3d_previs",
        structured_content={"scene_script": script.model_dump(mode="json")},
    )
    executor = _scene3d_executor()

    outcome = executor(_context(node))

    assert outcome.structured_content is not None
    report = outcome.structured_content["scene3d_consistency"]
    assert report["passed"] is True  # warnings never block the render
    codes = [issue["code"] for issue in report["issues"]]
    assert "character_unbound" in codes
    assert report["warning_count"] >= 1


def test_scene3d_consistency_clean_for_single_shot_bound_scene() -> None:
    executor = _scene3d_executor()
    outcome = executor(_context(_scene3d_node()))
    report = outcome.structured_content["scene3d_consistency"]
    assert report["warning_count"] == 0
    assert report["issues"] == []


# ---------------------------------------------------------------------------
# Cross-node character drift: the identity binding checked across nodes
# (V0.2 §5 服装维度 / plan §5.3)
# ---------------------------------------------------------------------------


def test_scene3d_publishes_cross_node_character_drift() -> None:
    """The node executes with a blue-jacketed twin of its own character in
    another node: the published report names the disagreement."""

    from app.schemas.scene_script import SceneScriptRoot

    mine = _scene3d_node()
    mine.structured_content["scene_script"]["characters"][0]["character_asset_id"] = "asset-girl"
    mine.structured_content["scene_script"]["characters"][0]["appearance"]["color"] = "#E74C3C"

    twin_script = _minimal_scene_script().model_dump(mode="json")
    twin_script["characters"][0]["character_asset_id"] = "asset-girl"
    twin_script["characters"][0]["appearance"]["color"] = "#3498DB"
    twin = SceneScriptRoot.model_validate(twin_script)

    executor = _scene3d_executor(
        sibling_scripts=lambda workflow_id: {"node-self": twin},
    )
    outcome = executor(_context(mine))

    report = outcome.structured_content["scene3d_wardrobe_drift"]
    assert report["checked"] is True
    assert [finding["code"] for finding in report["findings"]] == [
        "character_appearance_drift"
    ]
    assert report["findings"][0]["subject"] == "asset-girl"


# ---------------------------------------------------------------------------
# Animatic: the emitted previs carries the dialogue bed (V0.2 §14.9)
# ---------------------------------------------------------------------------


@dataclass
class _FakeMuxResult:
    success: bool = True
    output_path: str | None = None
    error: str | None = None


def _speaking_scene3d_node() -> CanvasNodeV2:
    script = _minimal_scene_script().model_dump(mode="json")
    script["speech_bindings"] = [
        {"character": "char1", "speech_asset": "speech_audio:bed-1", "mode": "bound"},
    ]
    return _make_node(
        node_type="scene-3d",
        creative_role="scene_3d_previs",
        structured_content={"scene_script": script},
    )


def _animatic_executor(
    *,
    rendered_frames: str = "animation",
    resolve_audio: bool = True,
    mux_success: bool = True,
    mux_error: str | None = None,
    mux_calls: list[tuple[str, str, str]] | None = None,
) -> Scene3DNodeExecutor:
    def _encoder(input_dir: str, output_path: str, fps: int = 30):
        Path(output_path).write_bytes(b"\x00\x00\x00\x18ftypmp42fake")
        return _FakeEncodeResult()

    def _muxer(video_path: str, audio_path: str, output_path: str):
        if mux_calls is not None:
            mux_calls.append((video_path, audio_path, output_path))
        if mux_success:
            Path(output_path).write_bytes(b"ANIMATIC-WITH-SOUND")
            return _FakeMuxResult(success=True, output_path=output_path)
        return _FakeMuxResult(success=False, error=mux_error or "ffmpeg mux failed")

    return _scene3d_executor(
        renderer=lambda script, frames_dir, timeout_seconds=1800, keyframes_only=True: (
            _FakeRenderResult(rendered_frames=rendered_frames)
        ),
        encoder=_encoder,
        audio_muxer=_muxer,
    )


def test_scene3d_animatic_muxes_the_dialogue_bed_into_the_emitted_previs(monkeypatch) -> None:
    calls: list[tuple[str, str, str]] = []
    executor = _animatic_executor(mux_calls=calls)
    # The bed asset resolves to a local file (the same path the lip-sync pass
    # uses); patched here so the test needs no database or storage.
    monkeypatch.setattr(
        executor,
        "_resolve_speech_asset_path",
        lambda asset_ref: Path("/tmp/bed-1.mp3"),
    )

    outcome = executor(_context(_speaking_scene3d_node()))

    # The emitted media is the MUXED file: the render side now has sound.
    assert outcome.media is not None
    assert outcome.media.content == b"ANIMATIC-WITH-SOUND"
    assert outcome.media.filename == "previs.mp4"
    # The mux was asked for exactly this asset (native path spelling).
    assert len(calls) == 1
    assert calls[0][1] == str(Path("/tmp/bed-1.mp3"))
    # And the provenance says so on the node.
    report = outcome.structured_content["animatic_audio"]
    assert report["muxed"] is True
    assert report["asset_ref"] == "speech_audio:bed-1"
    assert report["reason"] is None


def test_scene3d_animatic_reports_a_mux_failure_without_failing_the_render() -> None:
    executor = _animatic_executor(mux_success=False, mux_error="aac encoder missing")
    executor._resolve_speech_asset_path = lambda asset_ref: Path("/tmp/bed-1.mp3")

    outcome = executor(_context(_speaking_scene3d_node()))

    # The silent render still ships: a missing audio track must not cost the
    # author the previs (engineering standard §4).
    assert outcome.media is not None
    assert outcome.media.content == b"\x00\x00\x00\x18ftypmp42fake"
    report = outcome.structured_content["animatic_audio"]
    assert report["muxed"] is False
    assert "aac encoder missing" in report["reason"]


def test_scene3d_animatic_skips_a_keyframes_only_render_and_says_why() -> None:
    calls: list[tuple[str, str, str]] = []
    executor = _animatic_executor(rendered_frames="keyframes", mux_calls=calls)
    executor._resolve_speech_asset_path = lambda asset_ref: Path("/tmp/bed-1.mp3")

    outcome = executor(_context(_speaking_scene3d_node()))

    # Five instants cannot host a continuous bed honestly: no mux attempted.
    assert calls == []
    assert outcome.media is not None
    report = outcome.structured_content["animatic_audio"]
    assert report["muxed"] is False
    assert report["reason"] == "keyframes_only_render"


def test_scene3d_animatic_reports_an_unresolved_bed_asset(monkeypatch) -> None:
    executor = _animatic_executor()
    monkeypatch.setattr(executor, "_resolve_speech_asset_path", lambda asset_ref: None)

    outcome = executor(_context(_speaking_scene3d_node()))

    assert outcome.media is not None
    report = outcome.structured_content["animatic_audio"]
    assert report["muxed"] is False
    assert report["reason"] == "speech_asset_unresolved"
    # The asset the author bound is still named, so the failure is actionable.
    assert report["asset_ref"] is None


def test_scene3d_animatic_reports_a_scene_without_any_binding() -> None:
    executor = _animatic_executor()

    outcome = executor(_context(_scene3d_node()))

    assert outcome.media is not None
    report = outcome.structured_content["animatic_audio"]
    assert report["muxed"] is False
    assert report["reason"] == "no_speech_binding"


# ---------------------------------------------------------------------------
# The pre-commit QA gate (ADR 0003 §5's second half)
# ---------------------------------------------------------------------------


def test_voicecast_qa_failure_blocks_the_commit_with_the_report() -> None:
    """A take that measures as silence must not commit: the downstream
    alignment, lip-sync and final mix would all inherit a silent voice."""

    node = _make_node(
        node_type="voice-cast",
        creative_role="voice_cast",
        generation_prompt="你好，世界",
    )
    executor = VoiceCastNodeExecutor(
        Settings(agent_runtime_mode="fake"),
        engine=_FakeLiveEngine(),
        qa_registry_factory=_fixed_qa_factory(["fail"]),
    )

    with pytest.raises(V2PersistenceError) as excinfo:
        executor(_context(node))

    assert excinfo.value.code == "voicecast_qa_failed"
    # The whole report rides along: the author sees WHICH check failed and why.
    report = (excinfo.value.details or {}).get("qa_report")
    assert report is not None
    assert report["failed"] == ["stub_0"]


def test_voicecast_qa_warn_publishes_the_report_as_a_marker() -> None:
    node = _make_node(
        node_type="voice-cast",
        creative_role="voice_cast",
        generation_prompt="你好，世界",
    )
    executor = VoiceCastNodeExecutor(
        Settings(agent_runtime_mode="fake"),
        engine=_FakeLiveEngine(),
        qa_registry_factory=_fixed_qa_factory(["warn"]),
    )

    outcome = executor(_context(node))

    # The audio still commits — a warn is not a failure...
    assert outcome.media is not None
    # ...and the warn is a queryable event on the node, not a log line.
    report = (outcome.structured_content or {}).get("voicecast_qa_report")
    assert report is not None
    assert report["warned"] == ["stub_0"]


def test_voicecast_qa_all_pass_stays_silent() -> None:
    node = _make_node(
        node_type="voice-cast",
        creative_role="voice_cast",
        generation_prompt="你好，世界",
    )
    executor = VoiceCastNodeExecutor(
        Settings(agent_runtime_mode="fake"),
        engine=_FakeLiveEngine(),
        qa_registry_factory=_all_pass_qa_factory(),
    )

    outcome = executor(_context(node))

    assert outcome.media is not None
    # Silence is the compliment: no key when nothing needs saying.
    assert "voicecast_qa_report" not in (outcome.structured_content or {})


@pytest.mark.media
def test_the_real_gate_blocks_a_silent_take(tmp_path) -> None:
    """The real registry against a real file: a silent WAV fails the gate.

    The one media-marked proof that the fail floor is reachable through real
    ffmpeg, not only through a stub."""

    import wave

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")

    # A stub engine that writes TRUE SILence (a take with no voice in it).
    class _SilentEngine:
        provider = "fake-tts"
        model = "fake-tts-1"

        def is_configured(self) -> bool:
            return True

        def synthesize(self, text: str, character_id: str, output_path: str, **_: object) -> str:
            rate = 8000
            with wave.open(output_path, "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(rate)
                handle.writeframes(b"\x00\x00" * rate)  # one second of silence
            return output_path

    node = _make_node(
        node_type="voice-cast",
        creative_role="voice_cast",
        generation_prompt="你好，世界",
    )
    executor = VoiceCastNodeExecutor(
        Settings(agent_runtime_mode="fake"),
        engine=_SilentEngine(),
    )

    with pytest.raises(V2PersistenceError) as excinfo:
        executor(_context(node))

    assert excinfo.value.code == "voicecast_qa_failed"
    report = (excinfo.value.details or {}).get("qa_report") or {}
    loudness = next(
        (o for o in report.get("outcomes", []) if o["check"] == "speech_loudness_target"),
        None,
    )
    assert loudness is not None
    assert loudness["status"] == "fail"
    assert "静音" in loudness["reason"]


class TestScene3DTransitionIntentReconciliation:
    """§13 第 4 问 through the executor: the two halves must meet.

    The blocking gate had no caller at all, so a facing flip was invisible to
    everyone; the declared reading was equally invisible to the gate. These
    tests publish both and check they are JOINED, not merely adjacent.
    """

    def _node(self, script: SceneScriptRoot) -> CanvasNodeV2:
        return _make_node(
            node_type="scene-3d",
            creative_role="scene_3d_previs",
            structured_content={"scene_script": script.model_dump(mode="json")},
        )

    def _script(self, *, intent: str | None) -> SceneScriptRoot:
        payload = _minimal_scene_script().model_dump(mode="json")
        # Six seconds so a second shot fits (the minimal scene is three).
        payload["scene"]["duration"] = 6.0
        # A second shot so there is a boundary to reconcile, and the same
        # character posing the OTHER way across it (the facing flip the gate
        # notices).
        # The flip must sit ON the boundary: the exit pose of shot1 (frame 89)
        # versus the entry pose of shot2 (frame 90). A single keyframe at 90
        # would be interpolated from frame 0, smearing the turn across the
        # whole shot — so the pose holds to 89 and changes at 90.
        payload["characters"][0]["keyframes"] = [
            {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"},
            {"frame": 89, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"},
            {"frame": 90, "position": [0, 0, 0], "rotation_y": 170, "action": "stand"},
            {"frame": 150, "position": [0, 0, 0], "rotation_y": 170, "action": "stand"},
        ]
        payload["shots"] = [
            {"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 89},
            {
                "id": "shot2",
                "camera": "cam1",
                "start_frame": 90,
                "end_frame": 150,
                "transition_intent": intent,
            },
        ]
        return SceneScriptRoot.model_validate(payload)

    def test_a_declared_continuous_motion_over_a_flip_is_contradicted(self) -> None:
        outcome = _scene3d_executor()(_context(self._node(self._script(intent="continuous_motion"))))
        blocking = outcome.structured_content["scene3d_blocking_continuity"]
        assert any(issue["code"] == "facing_flip" for issue in blocking)
        notes = outcome.structured_content["scene3d_transition_intent"]
        assert [note["code"] for note in notes] == [
            "transition_intent_contradicts_continuity"
        ]
        assert notes[0]["shot_id"] == "shot2"

    def test_a_declared_time_jump_explains_the_same_flip(self) -> None:
        """The same keyframes, a different declaration, a different answer —
        which is the whole point of joining the two gates."""

        outcome = _scene3d_executor()(_context(self._node(self._script(intent="time_jump"))))
        assert any(
            issue["code"] == "facing_flip"
            for issue in outcome.structured_content["scene3d_blocking_continuity"]
        )
        notes = outcome.structured_content["scene3d_transition_intent"]
        assert [note["code"] for note in notes] == [
            "transition_intent_explains_continuity"
        ]
        assert notes[0]["severity"] == "info"

    def test_no_declaration_leaves_the_finding_a_plain_question(self) -> None:
        outcome = _scene3d_executor()(_context(self._node(self._script(intent=None))))
        assert any(
            issue["code"] == "facing_flip"
            for issue in outcome.structured_content["scene3d_blocking_continuity"]
        )
        assert outcome.structured_content["scene3d_transition_intent"] == []


class TestVoiceCastPerLineDialogue:
    """V0.2 §14.7 内容层/表演层: each line is an Audio Event of its own.

    The property the whole increment exists for: **changing one line does not
    re-synthesize the take**. The executor's answer is a content-addressed
    cache plus a join, and these tests check that the engine is asked for the
    changed line ONLY — not that the output "looks joined".
    """

    def _executor(self, engine: _FakeBatchEngine, tmp_path) -> VoiceCastNodeExecutor:
        settings = Settings(agent_runtime_mode="fake")
        object.__setattr__(settings, "media_data_dir", Path(tmp_path))
        return VoiceCastNodeExecutor(
            settings,
            engine=engine,
            qa_registry_factory=_all_pass_qa_factory(),
            # A fake join keeps the bytes decodable (the media gate reads the
            # take) without pretending ffmpeg ran.
            audio_concat=lambda paths, output: _ConcatOk(output, paths),
            audio_duration_probe=lambda path: 1.0,
        )

    def _node(self, lines: list[dict], **extra) -> CanvasNodeV2:
        return _make_node(
            node_type="voice-cast",
            creative_role="voice_cast",
            structured_content={"dialogue_lines": lines, **extra},
        )

    def test_only_the_changed_line_is_synthesized(self, tmp_path) -> None:
        engine = _FakeBatchEngine()
        executor = self._executor(engine, tmp_path)
        lines = [
            {"id": "l1", "text": "就是这里", "emotion": "压低声音"},
            {"id": "l2", "text": "别出声"},
        ]
        executor(_context(self._node(lines)))
        first = [call["text"] for call in engine.calls]
        assert first == ["就是这里", "别出声"]
        assert engine.calls[0]["emotion"] == "压低声音"

        # Re-run with ONE line re-worded: the other line's take is reused, so
        # the engine is asked for exactly one line.
        engine.calls.clear()
        executor(
            _context(
                self._node([lines[0], {"id": "l2", "text": "千万别出声"}])
            )
        )
        assert [call["text"] for call in engine.calls] == ["千万别出声"]

    def test_nothing_is_synthesized_when_nothing_changed(self, tmp_path) -> None:
        engine = _FakeBatchEngine()
        executor = self._executor(engine, tmp_path)
        node = self._node([{"id": "l1", "text": "就是这里"}])
        executor(_context(node))
        engine.calls.clear()
        # Same node again: a pure cache replay must not call the provider.
        executor(_context(node))
        assert engine.calls == []

    def test_an_emotion_change_alone_forces_a_new_take_of_the_same_words(self, tmp_path) -> None:
        """表演层: same words, new direction — that IS a new performance."""

        engine = _FakeBatchEngine()
        executor = self._executor(engine, tmp_path)
        executor(_context(self._node([{"id": "l1", "text": "我做到了"}])))
        engine.calls.clear()
        executor(_context(self._node([{"id": "l1", "text": "我做到了", "emotion": "冷淡"}])))
        assert [call["text"] for call in engine.calls] == ["我做到了"]
        assert engine.calls[0]["emotion"] == "冷淡"

    def test_regenerate_line_ids_forces_a_line_even_when_cached(self, tmp_path) -> None:
        engine = _FakeBatchEngine()
        executor = self._executor(engine, tmp_path)
        lines = [{"id": "l1", "text": "一句"}, {"id": "l2", "text": "二句"}]
        executor(_context(self._node(lines)))
        engine.calls.clear()
        executor(_context(self._node(lines, regenerate_line_ids=["l2"])))
        assert [call["text"] for call in engine.calls] == ["二句"]

    def test_the_manifest_carries_the_editable_structure(self, tmp_path) -> None:
        engine = _FakeBatchEngine()
        executor = self._executor(engine, tmp_path)
        outcome = executor(
            _context(
                self._node(
                    [
                        {"id": "l1", "text": "一句", "emotion": "急"},
                        {"id": "l2", "text": "二句"},
                    ]
                )
            )
        )
        manifest = outcome.structured_content["dialogue_line_manifest"]
        assert [entry["line_id"] for entry in manifest] == ["l1", "l2"]
        assert [entry["text"] for entry in manifest] == ["一句", "二句"]
        assert manifest[0]["emotion"] == "急"
        assert [entry["regenerated"] for entry in manifest] == [True, True]
        assert [entry["duration_seconds"] for entry in manifest] == [1.0, 1.0]
        # Offsets are the running sum: the timeline that follows can recompute.
        assert [entry["offset_seconds"] for entry in manifest] == [0, 1.0]
        assert outcome.structured_content["reused_line_ids"] == []
        assert outcome.structured_content["regenerated_line_ids"] == ["l1", "l2"]

    def test_a_replay_reports_which_lines_were_reused(self, tmp_path) -> None:
        engine = _FakeBatchEngine()
        executor = self._executor(engine, tmp_path)
        node = self._node(
            [{"id": "l1", "text": "一句"}, {"id": "l2", "text": "二句"}]
        )
        executor(_context(node))
        engine.calls.clear()
        outcome = executor(_context(node))
        assert engine.calls == []
        assert outcome.structured_content["reused_line_ids"] == ["l1", "l2"]
        assert outcome.structured_content["regenerated_line_ids"] == []
        assert [entry["regenerated"] for entry in outcome.structured_content["dialogue_line_manifest"]] == [
            False,
            False,
        ]

    def test_a_line_with_no_usable_row_fails_with_every_reason(self, tmp_path) -> None:
        engine = _FakeBatchEngine()
        executor = self._executor(engine, tmp_path)
        with pytest.raises(Exception) as raised:
            executor(
                _context(
                    self._node(
                        [
                            {"text": "no id"},
                            {"id": "bad id!", "text": "x"},
                        ]
                    )
                )
            )
        details = getattr(raised.value, "details", None) or {}
        # Each dropped row, individually: the author needs to know which to fix.
        assert len(details.get("dropped", [])) == 2
        assert engine.calls == []

    def test_the_take_is_published_as_one_audio_event_stream(self, tmp_path) -> None:
        engine = _FakeBatchEngine()
        executor = self._executor(engine, tmp_path)
        outcome = executor(_context(self._node([{"id": "l1", "text": "一句"}])))
        assert outcome.media is not None
        assert outcome.media.mime_type == "audio/mpeg"
        assert outcome.media.metadata["per_line"] is True
        assert outcome.media.metadata["line_count"] == 1


@dataclass
class _ConcatOk:
    """A fake join that leaves the concatenated bytes decodable.

    The media gate reads the take it is handed, so a fake that reports success
    without writing anything would blow up downstream for a reason that has
    nothing to do with the property under test.
    """

    output_path: str
    paths: list

    success: bool = True
    error: str | None = None

    def __post_init__(self) -> None:
        payload = b""
        for path in self.paths or []:
            try:
                payload += Path(path).read_bytes()
            except OSError:
                payload += b""
        Path(self.output_path).write_bytes(payload or b"ID3\x04\x00\x00joined-take")
