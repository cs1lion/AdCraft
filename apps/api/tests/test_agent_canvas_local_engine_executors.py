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
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.persistence.errors import V2PersistenceError
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


def test_voicecast_synthesizes_prepared_prompt() -> None:
    node = _make_node(
        node_type="voice-cast",
        creative_role="voice_cast",
        generation_prompt="你好，世界",
    )
    executor = VoiceCastNodeExecutor(
        Settings(agent_runtime_mode="fake"),
        engine=_FakeLiveEngine(),
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
    )

    outcome = executor(_context(node))

    assert outcome.media is not None
    assert outcome.media.content == _fake_tts_audio("authored line")


def test_voicecast_fails_without_text() -> None:
    node = _make_node(node_type="voice-cast", creative_role="voice_cast")
    executor = VoiceCastNodeExecutor(
        Settings(agent_runtime_mode="fake"),
        engine=_FakeLiveEngine(),
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
    rendered_frames: str = "keyframes"
    degraded_assets: tuple[str, ...] = ()


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
    params: dict[str, Any] = {
        "capability_probe": lambda: _FakeCapability(),
        "renderer": lambda script, frames_dir, timeout_seconds=1800, keyframes_only=True: (
            _FakeRenderResult()
        ),
        "encoder": lambda input_dir, output_path, fps=30: (
            Path(output_path).write_bytes(b"\x00\x00\x00\x18ftypmp42fake"),
            _FakeEncodeResult(),
        )[1],
    }
    params.update(overrides)
    return Scene3DNodeExecutor(Settings(agent_runtime_mode="fake"), **params)


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
    assert metadata["scene3d_rendered_frames"] == "keyframes"
    assert metadata["scene3d_keyframe_frames"] == [0, 22, 44, 67, 89]


def test_scene3d_asks_the_renderer_for_the_draft_pass() -> None:
    seen: dict[str, object] = {}

    def _renderer(script, frames_dir, **kwargs):
        seen.update(kwargs)
        return _FakeRenderResult()

    _scene3d_executor(renderer=_renderer)(_context(_scene3d_node()))

    assert seen["keyframes_only"] is True
    # 5 keyframes at the default 90s + 6s/frame, not the 1800s ceiling: the
    # draft must not be given a full animation's patience.
    assert seen["timeout_seconds"] == 120


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
    assert _timeout(short) == 90 + 6 * 5  # draft: 5 keyframes, 90s ceiling is 1800
    assert (
        _timeout(short, scene3d_render_keyframes_only=False)
        == 90 + 6 * short.total_frames
    )

    long = _minimal_scene_script()
    long.shots = [
        SceneShot(id=f"shot{i}", camera="cam1", start_frame=i * 60, end_frame=(i + 1) * 60)
        for i in range(4)
    ]
    long.scene.duration = 8.0
    draft = _timeout(long)
    animation = _timeout(long, scene3d_render_keyframes_only=False)
    assert draft == 90 + 6 * 20  # 4 shots x 5 keyframes
    assert animation == 90 + 6 * 240
    # The draft of a 240-frame scene must not be handed the animation's budget.
    assert animation > draft * 6


def test_scene3d_timeout_never_exceeds_the_configured_ceiling() -> None:
    """The ceiling is a cap, not a value: the derived budget wins when smaller.

    A 90-frame animation derives 630s, but an operator who set 300s must not be
    overruled by the formula.
    """

    import dataclasses

    settings = dataclasses.replace(
        Settings(agent_runtime_mode="fake"),
        scene3d_render_timeout_seconds=300,
        scene3d_render_keyframes_only=False,
    )
    executor = Scene3DNodeExecutor(settings, **_render_less_params())
    assert executor._render_timeout_for(_minimal_scene_script()) == 300

    # And the same executor's draft is still way under it.
    draft = dataclasses.replace(settings, scene3d_render_keyframes_only=True)
    assert (
        Scene3DNodeExecutor(draft, **_render_less_params())._render_timeout_for(
            _minimal_scene_script()
        )
        == 120
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


def test_scene3d_can_opt_back_into_a_full_animation() -> None:
    import dataclasses

    executor = _scene3d_executor()
    assert executor._keyframes_only is True

    settings = dataclasses.replace(
        Settings(agent_runtime_mode="fake"),
        scene3d_render_keyframes_only=False,
    )
    executor = Scene3DNodeExecutor(
        settings,
        capability_probe=lambda: _FakeCapability(),
        renderer=lambda script, frames_dir, **kwargs: _FakeRenderResult(
            rendered_frames="animation"
        ),
        encoder=lambda input_dir, output_path, fps=30: _FakeEncodeResult(),
    )
    assert executor._keyframes_only is False


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
    assert set(outcome.structured_content) == {"scene_script", "previs_trajectory"}
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
    assert trajectory["rendered_frames"] == "keyframes"
    assert trajectory["keyframe_frames"] == [0, 22, 44, 67, 89]

    (shot,) = trajectory["shots"]
    assert shot["id"] == "shot1"
    assert shot["camera"] == "cam1"
    assert shot["shot_type"] == "medium"
    assert shot["start_frame"] == 0
    assert shot["end_frame"] == 90
    assert shot["start_seconds"] == 0.0
    assert shot["end_seconds"] == 3.0
    # The draft renders 5 of this shot's 90 frames, and says which five.
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
    assert "scene3d_keyframe_frames" not in outcome.media.metadata


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
    assert outcome.media.metadata["scene3d_rendered_frames"] == "keyframes"
    # The data half survives either way.
    assert outcome.structured_content["previs_trajectory"]["keyframe_frames"] == [
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
    # authored and the executor adds only the trajectory it derived.
    assert outcome.structured_content == {
        "previs_trajectory": outcome.structured_content["previs_trajectory"]
    }
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
