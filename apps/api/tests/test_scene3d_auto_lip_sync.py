"""Unit tests for automatic speech-bound lip-sync and its executor wiring.

The service's contract: bound speech audio with a MEASURED duration moves the
mouths; unresolvable audio leaves that character un-animated and is NAMED (no
invented timing); an already-talking script is left untouched (rerun
idempotence); the duration source is honest.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.auto_lip_sync import (
    apply_speech_bound_lip_sync,
    speech_asset_ref,
)
from app.services.scene3d import auto_lip_sync as auto_lip_sync_module


def _scene() -> SceneScriptRoot:
    return SceneScriptRoot.model_validate(
        {
            "scene": {"name": "lab", "environment": "indoor", "lighting": "cool", "duration": 9.0, "frame_rate": 30},
            "characters": [
                {
                    "id": "lin",
                    "type": "lowpoly_human",
                    "appearance": {"color": "#E74C3C"},
                    "character_asset_id": "asset-lin",
                    "keyframes": [
                        {"frame": 0, "position": [0.8, 0.0, 0.0], "rotation_y": 160, "action": "stand"}
                    ],
                },
                {
                    "id": "su",
                    "type": "lowpoly_human",
                    "appearance": {"color": "#3498DB"},
                    "keyframes": [
                        {"frame": 0, "position": [-0.9, 0.1, 0.0], "rotation_y": 20, "action": "stand"}
                    ],
                },
            ],
            "props": [],
            "environment": [],
            "cameras": [
                {"id": "cam1", "shot_type": "wide", "keyframes": [{"frame": 0, "position": [5, -6, 2.6], "look_at": [0, 0, 1.2]}]}
            ],
            "shots": [{"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 269}],
            "speech_bindings": [
                {"character": "lin", "speech_asset": "speech_audio:asset_lin_audio", "mode": "bound"},
                {"character": "su", "speech_asset": "asset_su_audio", "mode": "bound"},
            ],
        }
    )


def _resolver(available: dict[str, Path]):
    def resolve(ref: str) -> Path | None:
        return available.get(ref)

    return resolve


def test_speech_asset_ref_strips_prefix() -> None:
    assert speech_asset_ref("speech_audio:abc") == "abc"
    assert speech_asset_ref("abc") == "abc"


def test_no_bindings_is_a_no_op() -> None:
    script = _scene()
    script.speech_bindings = []
    result = apply_speech_bound_lip_sync(script, asset_resolver=lambda ref: None)
    assert result.applied is False
    assert result.duration_source == "none"
    assert result.scene_script is script  # identity


def test_measured_speech_drives_talk_keyframes(tmp_path, monkeypatch) -> None:
    lin_audio = tmp_path / "lin.mp3"
    lin_audio.write_bytes(b"fake")
    su_audio = tmp_path / "su.mp3"
    su_audio.write_bytes(b"fake")
    durations = {str(lin_audio): 1.5, str(su_audio): 2.0}
    monkeypatch.setattr(
        auto_lip_sync_module,
        "probe_audio_duration_seconds",
        lambda path: durations.get(str(path)),
    )

    result = apply_speech_bound_lip_sync(
        _scene(),
        asset_resolver=_resolver(
            {"asset_lin_audio": lin_audio, "asset_su_audio": su_audio}
        ),
    )

    assert result.applied is True
    assert result.duration_source == "measured"
    assert result.segment_count == 2
    assert result.warnings == []

    lin_talk = [
        kf.frame for kf in result.scene_script.characters[0].keyframes if kf.action == "talk"
    ]
    su_talk = [
        kf.frame for kf in result.scene_script.characters[1].keyframes if kf.action == "talk"
    ]
    assert lin_talk, "the measured line drives lip-sync"
    assert su_talk
    assert lin_talk[0] == 0
    # 1.5s at 30fps closes the mouth at frame ~45.
    assert max(lin_talk) <= 50
    # The authored blocking survived (the merged character did not teleport).
    assert any(kf.position == [0.8, 0.0, 0.0] for kf in result.scene_script.characters[0].keyframes)


def test_unresolvable_speech_leaves_characters_unanimated(tmp_path) -> None:
    result = apply_speech_bound_lip_sync(
        _scene(), asset_resolver=lambda ref: None
    )
    assert result.applied is False
    assert result.duration_source == "none"
    assert result.scene_script is _scene() or result.scene_script.speech_bindings
    # No fake timing was invented: no talk keyframes at all.
    assert not any(
        kf.action == "talk"
        for character in result.scene_script.characters
        for kf in character.keyframes
    )
    assert len(result.warnings) == 2
    assert all("speech_asset_unresolved" in warning for warning in result.warnings)


def test_unreadable_audio_is_reported(tmp_path, monkeypatch) -> None:
    audio = tmp_path / "broken.mp3"
    audio.write_bytes(b"not audio")
    monkeypatch.setattr(auto_lip_sync_module, "probe_audio_duration_seconds", lambda path: None)

    result = apply_speech_bound_lip_sync(
        _scene(), asset_resolver=_resolver({"asset_lin_audio": audio, "asset_su_audio": audio})
    )
    assert result.applied is False
    assert all("speech_audio_unreadable" in warning for warning in result.warnings)


def test_partial_resolution_reports_mixed_source(tmp_path, monkeypatch) -> None:
    lin_audio = tmp_path / "lin.mp3"
    lin_audio.write_bytes(b"fake")
    monkeypatch.setattr(
        auto_lip_sync_module, "probe_audio_duration_seconds", lambda path: 1.2
    )

    result = apply_speech_bound_lip_sync(
        _scene(), asset_resolver=_resolver({"asset_lin_audio": lin_audio})
    )
    assert result.applied is True
    assert result.duration_source == "mixed"
    assert result.segment_count == 1
    assert any("asset_su_audio" in warning for warning in result.warnings)
    # Su stays still (her audio was not resolved).
    assert not any(kf.action == "talk" for kf in result.scene_script.characters[1].keyframes)


def test_rerun_with_existing_talk_keyframes_is_idempotent() -> None:
    payload = _scene().model_dump(mode="json")
    payload["characters"][0]["keyframes"] = [
        {"frame": 0, "position": [0.8, 0.0, 0.0], "rotation_y": 160, "action": "talk"},
        {"frame": 45, "position": [0.8, 0.0, 0.0], "rotation_y": 160, "action": "stand"},
    ]
    script = SceneScriptRoot.model_validate(payload)
    result = apply_speech_bound_lip_sync(
        script, asset_resolver=lambda ref: None
    )
    assert result.applied is False
    assert result.scene_script is script
    assert any("lip_sync_already_present" in warning for warning in result.warnings)


# ---------------------------------------------------------------------------
# Executor wiring
# ---------------------------------------------------------------------------


def _speech_bound_node() -> object:
    """A scene-3d node whose stored SceneScript carries speech bindings."""
    from app.schemas.agent_canvas import CanvasNodeV2

    payload = _scene().model_dump(mode="json")
    return CanvasNodeV2.model_validate(
        {
            "node_id": "node-speech",
            "workflow_id": "wf-1",
            "node_type": "scene-3d",
            "creative_role": "scene_3d_previs",
            "role_contract_version": "ad-media-role-v1",
            "title": "speech bound node",
            "status": "draft",
            "summary_prompt": None,
            "generation_prompt": None,
            "structured_content": {"scene_script": payload},
            "parameters": {},
            "prompt_context_snapshot_id": None,
            "output_asset_id": None,
            "position": {"x": 0, "y": 0},
            "revision": 1,
            "error": None,
            "created_at": "2026-09-26T00:00:00Z",
            "updated_at": "2026-09-26T00:00:00Z",
        }
    )


def _executor(**overrides):
    from pathlib import Path

    from app.services.agent_canvas_node_execution import Scene3DNodeExecutor

    params = {
        "capability_probe": lambda: type(
            "Cap", (), {"state": "ready", "version": "5.0", "executable": "blender", "error": None}
        )(),
        "renderer": lambda script, frames_dir, timeout_seconds=1800, keyframes_only=True: type(
            "R",
            (),
            {
                "success": True,
                "frame_count": 5,
                "error": None,
                "blender_version": "5.0",
                "degraded_assets": (),
                "rendered_frames": "keyframes",
            },
        )(),
        "encoder": lambda input_dir, output_path, fps=30: (
            Path(output_path).write_bytes(b"\x00\x00\x00\x18ftypmp42fake"),
            type("E", (), {"success": True, "error": None})(),
        )[1],
    }
    params.update(overrides)
    return Scene3DNodeExecutor(
        Settings(agent_runtime_mode="fake"), **params
    )


def test_executor_reports_unresolved_speech_assets_without_blocking_render() -> None:
    """The empty asset store cannot resolve the speech assets: the render
    still succeeds and the report SAYS the mouths did not move."""

    from app.services.agent_canvas_node_execution import NodeExecutionContext

    outcome = _executor()(NodeExecutionContext(execution_id="exec-1", node=_speech_bound_node(), inputs=()))

    assert outcome.media is not None  # the render was not blocked
    report = outcome.structured_content["auto_lip_sync"]
    assert report["applied"] is False
    assert len(report["warnings"]) == 2
    assert all("speech_asset_unresolved" in warning for warning in report["warnings"])
    # The script itself was not republished (nothing changed).
    assert "scene_script" not in outcome.structured_content


def test_executor_publishes_lip_synced_script_when_speech_resolves() -> None:
    """With resolvable speech audio, the merged script (talk keyframes) is
    published so downstream nodes and reviewers see the animated mouths."""

    from app.services.agent_canvas_node_execution import NodeExecutionContext

    executor = _executor()
    executor._resolve_speech_asset_path = lambda ref: Path("fake.mp3")

    import app.services.scene3d.auto_lip_sync as als

    original_probe = als.probe_audio_duration_seconds
    als.probe_audio_duration_seconds = lambda path: 1.5
    try:
        outcome = executor(
            NodeExecutionContext(execution_id="exec-1", node=_speech_bound_node(), inputs=())
        )
    finally:
        als.probe_audio_duration_seconds = original_probe

    assert outcome.structured_content["auto_lip_sync"]["applied"] is True
    assert outcome.structured_content["auto_lip_sync"]["duration_source"] == "measured"
    published = outcome.structured_content["scene_script"]
    talk_actions = [
        kf["action"]
        for character in published["characters"]
        for kf in character["keyframes"]
        if kf["action"] == "talk"
    ]
    assert talk_actions, "the published script carries the lip-sync keyframes"


def test_executor_without_bindings_publishes_no_report() -> None:
    from app.schemas.agent_canvas import CanvasNodeV2
    from app.services.agent_canvas_node_execution import NodeExecutionContext

    payload = _scene().model_dump(mode="json")
    payload["speech_bindings"] = []
    node = CanvasNodeV2.model_validate(
        {
            "node_id": "node-plain",
            "workflow_id": "wf-1",
            "node_type": "scene-3d",
            "creative_role": "scene_3d_previs",
            "role_contract_version": "ad-media-role-v1",
            "title": "plain node",
            "status": "draft",
            "summary_prompt": None,
            "generation_prompt": None,
            "structured_content": {"scene_script": payload},
            "parameters": {},
            "prompt_context_snapshot_id": None,
            "output_asset_id": None,
            "position": {"x": 0, "y": 0},
            "revision": 1,
            "error": None,
            "created_at": "2026-09-26T00:00:00Z",
            "updated_at": "2026-09-26T00:00:00Z",
        }
    )
    outcome = _executor()(NodeExecutionContext(execution_id="exec-1", node=node, inputs=()))
    assert "auto_lip_sync" not in outcome.structured_content
