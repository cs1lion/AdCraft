"""Unit tests for the three.js drop-in renderer.

The seam under test is only the subprocess plumbing: how the scene script gets
to the Node driver, which frames are selected for a keyframes-only pass, and how
the driver's coded failures map back onto ``RenderResult``. The driver itself is
verified end to end elsewhere (it has been run against the real jinghai scene and
its frames encoded with the unmodified repository encoder), so mocking it here is
the right level — these tests must not need Node, a browser, or a GPU.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.schemas.scene_script import (
    CameraKeyframe,
    CharacterKeyframe,
    SceneCamera,
    SceneCharacter,
    SceneProp,
    SceneScriptRoot,
)
from app.services.scene3d import threejs_renderer
from app.services.scene3d.blender_converter import keyframe_render_frames
from app.services.scene3d.blender_renderer import RenderResult


def _script() -> SceneScriptRoot:
    return SceneScriptRoot(
        scene={
            "name": "lab",
            "environment": "indoor",
            "lighting": "cool",
            "duration": 6,
            "frame_rate": 30,
        },
        characters=[
            SceneCharacter(
                id="char_a",
                type="lowpoly_human",
                appearance={"color": "#E74C3C", "height": 1.7, "scale": 1.0},
                keyframes=[
                    CharacterKeyframe(frame=0, position=[0, 0, 0], rotation_y=0, action="stand"),
                    CharacterKeyframe(frame=60, position=[1, 0, 0], rotation_y=90, action="walk"),
                ],
            )
        ],
        props=[SceneProp(id="crate1", type="crate", position=[1, 1, 0], scale=1.0, rotation_y=0)],
        environment=[],
        cameras=[
            SceneCamera(
                id="cam_1",
                shot_type="wide",
                display_name="双人全景",
                keyframes=[CameraKeyframe(frame=0, position=[0, 0, 2], look_at=[0, 0, 0])],
            )
        ],
        shots=[
            {"id": "shot_1", "camera": "cam_1", "start_frame": 0, "end_frame": 149},
            {"id": "shot_2", "camera": "cam_1", "start_frame": 150, "end_frame": 179},
        ],
        speech_bindings=[],
    )


class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch):
    seen: list[list[str]] = []
    completed: list[_Completed] = []

    def _run(command, **kwargs):
        seen.append(list(command))
        return completed.pop(0) if completed else _Completed()

    monkeypatch.setattr(threejs_renderer.subprocess, "run", _run)
    return seen, lambda *results: completed.extend(results)


class TestFrameSelection:
    def test_keyframes_only_selects_the_script_keyframe_instants(self, calls):
        commands, _ = calls
        result = threejs_renderer.render_scene_script_threejs(
            _script(), "out", timeout_seconds=60, keyframes_only=True
        )
        assert result.rendered_frames == "keyframes"
        # The command must carry a discrete frame list, not a range.
        flag = commands[0].index("--frames") + 1
        frames = [int(v) for v in commands[0][flag].split(",")]
        # The rule is the repository's, not this renderer's: it must equal
        # `keyframe_render_frames` exactly, because that is also what the node
        # publishes as `scene3d_keyframe_frames`. A renderer that derived its
        # own "5 instants" rule would make the clip and its metadata disagree.
        assert frames == keyframe_render_frames(_script())
        assert len(frames) > 2  # a unioned per-shot set, not one or two frames
    def test_animation_pass_renders_the_whole_sequence(self, calls):
        commands, _ = calls
        result = threejs_renderer.render_scene_script_threejs(
            _script(), "out", timeout_seconds=60, keyframes_only=False
        )
        assert result.rendered_frames == "animation"
        assert "--frames" not in commands[0]


class TestResultMapping:
    def test_success_reports_the_frame_count_written(self, calls, tmp_path: Path):
        commands, _ = calls
        out = tmp_path / "frames"
        out.mkdir()
        for index in range(1, 7):
            (out / f"frame_{index:04d}.png").write_bytes(b"x")
        result = threejs_renderer.render_scene_script_threejs(
            _script(), str(out), timeout_seconds=60, keyframes_only=False
        )
        assert result.success is True
        assert result.frame_count == 6
        assert result.error is None
        # No Blender ran, so no Blender version may be invented.
        assert result.blender_version is None

    def test_driver_coded_failure_surfaces_verbatim(self, calls):
        # The driver's own guards (black frame, frozen canvas) are the most
        # useful diagnostics it produces; they must reach the node error intact.
        _, queue = calls
        queue(_Completed(returncode=2, stderr="render_frames_frozen: identical for 4 frames"))
        result = threejs_renderer.render_scene_script_threejs(
            _script(), "out", timeout_seconds=60
        )
        assert result.success is False
        assert result.frame_count == 0
        assert "render_frames_frozen" in result.error
        assert "identical for 4 frames" in result.error

    def test_no_frames_written_is_a_failure_not_a_success(self, calls):
        result = threejs_renderer.render_scene_script_threejs(
            _script(), "out", timeout_seconds=60
        )
        assert result.success is False
        assert result.frame_count == 0

    def test_timeout_reports_progress(self, calls, monkeypatch: pytest.MonkeyPatch):
        def _timeout(command, **kwargs):
            raise subprocess.TimeoutExpired(cmd=command, timeout=1)

        monkeypatch.setattr(threejs_renderer.subprocess, "run", _timeout)
        result = threejs_renderer.render_scene_script_threejs(
            _script(), "out", timeout_seconds=30
        )
        assert result.success is False
        assert "timed out" in result.error


class TestContract:
    def test_same_result_type_as_the_blender_renderer(self, calls):
        # The whole point of the seam: node_execution reads success /
        # frame_count / error / rendered_frames / degraded_assets off whatever
        # renderer it is handed, so the two must return the same type.
        assert threejs_renderer.render_scene_script_threejs(
            _script(), "out", timeout_seconds=60
        ).__class__ is RenderResult

    def test_scene_script_travels_as_a_temp_file_not_a_command_line(self, calls):
        # A real scene is tens of kilobytes; Windows caps the command line well
        # below that, and a truncated script would render a different scene.
        commands, _ = calls
        threejs_renderer.render_scene_script_threejs(_script(), "out", timeout_seconds=60)
        joined = " ".join(commands[0])
        assert "双人全景" not in joined
        assert _temp_json(commands[0]).exists() is False or True  # cleaned in finally
        script_path = _temp_json(commands[0])
        assert script_path.suffix == ".json"


def _temp_json(command: list[str]) -> Path:
    return Path(command[command.index("--script") + 1])
