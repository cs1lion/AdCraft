"""Unit tests: geometric control pass collection (ADR 0005 §4).

Mutation check (engineering standard §3): collection must align pass files
to each shot's keyframe frames (0/25/50/75/100%), surface missing passes as
queryable degradation markers, and derive the job-level completeness marker
(full/partial/none).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.control_passes import (
    ControlPassResult,
    ShotControlPasses,
    collect_control_passes,
    control_passes_for_shot,
)


SCENE = {
    "scene": {
        "name": "teahouse",
        "environment": "indoor",
        "lighting": "warm",
        "duration": 8.0,
        "frame_rate": 30,
    },
    "characters": [
        {
            "id": "scholar",
            "keyframes": [
                {"frame": 0, "position": [0.9, -0.9, 0], "rotation_y": 150, "action": "stand"}
            ],
        }
    ],
    "cameras": [
        {
            "id": "cam1",
            "shot_type": "wide",
            "keyframes": [
                {"frame": 0, "position": [12, -14, 8], "look_at": [0, -1.5, 1.3]},
                {"frame": 60, "position": [8, -10, 6], "look_at": [0, -1.5, 1.3]},
            ],
        }
    ],
    "shots": [
        {
            "id": "shot1",
            "camera": "cam1",
            "start_frame": 0,
            "end_frame": 60,
            "description": "wide establishing",
        }
    ],
}


@pytest.fixture
def script() -> SceneScriptRoot:
    return SceneScriptRoot.model_validate(SCENE)


def _make_pass_dirs(
    base: Path,
    passes: dict[str, tuple[str, ...] | None] = {},
    frame_nums: tuple[int, ...] = (0, 15, 30, 44, 59),
    extension: str = ".png",
) -> None:
    """Create sibling control-pass subdirectories with 0-indexed pass files.

    Matches what ``blender_converter._control_pass_lines`` actually writes:
    ``depth_<N>.png`` where ``N`` is the 0-based SceneScript frame, and the
    sampled frames are the shot's 5 keyframes (0/25/50/75/100% of frames
    0-59, since ``end_frame`` is exclusive). Unlike the color pass, these are
    not offset to Blender's 1-indexed frame numbering.

    ``extension`` mirrors the writer's output format: ``".png"``, or ``""``
    for an extensionless name.
    """
    for pass_name, files in passes.items():
        pass_dir = base / f"control_{pass_name}"
        if files is None:
            continue
        if files != ():
            pass_dir.mkdir(parents=True, exist_ok=True)
            for frame_num in frame_nums:
                (pass_dir / f"{pass_name}_{frame_num}{extension}").write_bytes(b"px")


class TestCollectControlPasses:
    def test_full_passes_collect_all_files(self, script, tmp_path: Path) -> None:
        _make_pass_dirs(
            tmp_path,
            passes={"depth": ("all",), "normal": ("all",), "flow": ("all",)},
        )
        result = collect_control_passes(script, str(tmp_path))
        assert isinstance(result, ControlPassResult)
        shot = result.shots[0]
        assert shot.shot_id == "shot1"
        # 5 keyframe frames → 5 files per available pass.
        assert len(shot.depth_files) == 5
        assert len(shot.normal_files) == 5
        assert len(shot.flow_files) == 5
        assert shot.available_passes == ("depth", "normal", "flow")
        assert result.completeness == "full"
        assert result.degradation_markers == {}

    def test_missing_flow_degrades_with_marker(self, script, tmp_path: Path) -> None:
        # Eevee has no motion-vector output → flow dir empty (mutation: drop
        # the flow pass, watch completeness fall and the marker appear).
        _make_pass_dirs(tmp_path, passes={"depth": ("all",), "normal": ("all",)})
        result = collect_control_passes(script, str(tmp_path))
        shot = result.shots[0]
        assert shot.available_passes == ("depth", "normal")
        assert result.completeness == "partial"
        assert result.degradation_markers == {"shot1": ["flow"]}

    def test_no_pass_dirs_is_none(self, script, tmp_path: Path) -> None:
        result = collect_control_passes(script, str(tmp_path))
        assert result.completeness == "none"
        assert result.degradation_markers == {"shot1": ["depth", "normal", "flow"]}

    def test_missing_individual_frames_partial(self, script, tmp_path: Path) -> None:
        # Blender writes non-zero-padded names; missing frame files shrink
        # the per-pass file list but the pass still counts as available.
        _make_pass_dirs(
            tmp_path,
            passes={"depth": ("all",), "normal": ("all",), "flow": ("all",)},
            frame_nums=(0, 15, 59),  # drop the 50%/75% samples
        )
        result = collect_control_passes(script, str(tmp_path))
        shot = result.shots[0]
        assert len(shot.depth_files) == 3
        assert len(shot.normal_files) == 3
        assert len(shot.flow_files) == 3
        assert shot.available_passes == ("depth", "normal", "flow")
        # All three passes still have files → job stays full; per-shot
        # sparsity is visible through the file counts, not the marker.
        assert result.completeness == "full"

    def test_shot_lookup(self, script, tmp_path: Path) -> None:
        _make_pass_dirs(tmp_path, passes={"depth": ("all",)})
        result = collect_control_passes(script, str(tmp_path))
        assert control_passes_for_shot(result, "shot1") is not None
        assert control_passes_for_shot(result, "nope") is None


class TestShotControlPassesAvailability:
    def test_empty_shot_reports_no_passes(self) -> None:
        shot = ShotControlPasses(shot_id="s")
        assert shot.available_passes == ()
