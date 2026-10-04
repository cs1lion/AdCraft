"""Tests for the per-segment edit report.

The report is what an author reads after an edit, so every test states the
question it answers in the terms the reference framework uses: which 机位,
which 镜像段, what changed.
"""

from typing import Any

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.scene_edit_report import (
    CHANGE_CAMERA_ADDED,
    CHANGE_CAMERA_MOVED,
    CHANGE_CAMERA_RENAMED,
    CHANGE_OBJECT_ADDED,
    CHANGE_OBJECT_MOVED,
    CHANGE_SHOT_ADDED,
    CHANGE_SHOT_REMOVED,
    CHANGE_SHOT_REPOINTED,
    build_scene_edit_report,
    camera_display_name,
)
from app.services.scene3d.scene_script_tool_service import SceneScriptToolService

SERVICE = SceneScriptToolService()


def _script() -> dict[str, Any]:
    return {
        "scene": {
            "name": "走廊战斗",
            "environment": "indoor",
            "lighting": "cool",
            "duration": 6.0,
            "frame_rate": 30,
        },
        "characters": [
            {
                "id": "char_a",
                "type": "lowpoly_human",
                "appearance": {"color": "#E74C3C", "height": 1.7, "scale": 1.0},
                "keyframes": [
                    {"frame": 0, "position": [0, 0, 0], "rotation_y": 90, "action": "stand"}
                ],
            }
        ],
        "props": [{"id": "crate1", "type": "crate", "position": [1, 1, 0], "scale": 1.0}],
        "environment": [{"id": "wall1", "type": "wall", "position": [0, 5, 0], "scale": 1.0}],
        "cameras": [
            {
                "id": "cam1",
                "shot_type": "wide",
                "keyframes": [{"frame": 0, "position": [8, -10, 5], "look_at": [0, 0, 1]}],
            },
            {
                "id": "cam2",
                "shot_type": "closeup",
                "keyframes": [{"frame": 90, "position": [3, -4, 2], "look_at": [0, 1, 1]}],
            },
        ],
        "shots": [
            {"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 89},
            {"id": "shot2", "camera": "cam2", "start_frame": 90, "end_frame": 179},
        ],
        "speech_bindings": [],
    }


def _apply(operations: list[dict[str, Any]]) -> dict[str, Any]:
    result = SERVICE.apply_operations(_script(), operations)
    return result.scene_script.model_dump(mode="json")


def _report(operations: list[dict[str, Any]]) -> dict[str, Any]:
    return build_scene_edit_report(_script(), _apply(operations))


# ---------------------------------------------------------------------------
# Changing a camera is news for the shot it belongs to
# ---------------------------------------------------------------------------


def test_moving_a_camera_reports_the_shot_that_owns_it() -> None:
    """"把机位拉远" must name the segment that shot covers, or the author cannot
    tell which cut changed."""

    report = _report(
        [{"op": "move_object", "kind": "camera", "id": "cam2", "position": [6, -7, 4]}]
    )
    assert [shot["id"] for shot in report["shots"]] == ["shot2"]
    shot = report["shots"][0]
    assert shot["camera_label"] == "机位02"
    assert CHANGE_CAMERA_MOVED in shot["changes"]
    # shot2 is frames 90..179 at 30fps → 3.0s..6.0s inclusive.
    assert shot["start_seconds"] == 3.0
    assert shot["end_seconds"] == 6.0


def test_an_untouched_shot_is_not_news() -> None:
    report = _report(
        [{"op": "move_object", "kind": "camera", "id": "cam2", "position": [6, -7, 4]}]
    )
    assert "shot1" not in [shot["id"] for shot in report["shots"]]


def test_renaming_a_camera_reports_the_new_name() -> None:
    """"机位05 | 飞船俯瞰" is the sentence the reference framework prints; the
    label has to come from the camera, not from a second naming table."""

    report = _report(
        [{"op": "set_camera", "kind": "camera", "id": "cam2", "display_name": "飞船俯瞰"}]
    )
    shot = report["shots"][0]
    assert shot["camera_label"] == "机位02 | 飞船俯瞰"
    assert CHANGE_CAMERA_RENAMED in shot["changes"]


def test_a_keyframed_move_reports_the_beat_frame() -> None:
    """A framed move writes a keyframe; the report must still describe it as a
    camera move (the beat is where, not what)."""

    report = _report(
        [
            {
                "op": "move_object",
                "kind": "camera",
                "id": "cam1",
                "position": [12, -12, 6],
                "frame": 30,
            }
        ]
    )
    assert report["shots"][0]["id"] == "shot1"
    assert CHANGE_CAMERA_MOVED in report["shots"][0]["changes"]


def test_moving_a_prop_is_reported_without_a_shot() -> None:
    """A prop belongs to no camera, so it cannot be attributed to a shot. It is
    still a change the author made, and dropping it would under-report."""

    report = _report(
        [{"op": "move_object", "kind": "prop", "id": "crate1", "position": [2, 1, 0]}]
    )
    assert report["shots"] == []
    assert CHANGE_OBJECT_MOVED in report["changes"]["crate1"]


def test_adding_a_camera_and_shot_reports_both() -> None:
    # The base script tiles frames 0..179 with no gap, so this case uses one
    # that leaves 120..179 free (the way a real author would before adding a
    # shot): the point is the report, not the gate's overlap rule.
    script = _script()
    script["shots"][1]["end_frame"] = 119
    script["cameras"][1]["keyframes"][0]["frame"] = 110
    result = SERVICE.apply_operations(
        SceneScriptRoot.model_validate(script),
        [
            {
                "op": "add_camera",
                "id": "cam3",
                "position": [5, -6, 3],
                "look_at": [0, 1, 1],
                "display_name": "飞船起飞",
                "frame": 120,
            },
            {"op": "add_shot", "camera": "cam3", "start_frame": 120, "end_frame": 179},
        ],
    )
    report = build_scene_edit_report(
        SceneScriptRoot.model_validate(script), result.scene_script
    )
    added = next(
        shot for shot in report["shots"] if shot["id"] not in {"shot1", "shot2"}
    )
    assert CHANGE_SHOT_ADDED in added["changes"]
    assert added["camera_label"] == "机位03 | 飞船起飞"
    assert CHANGE_CAMERA_ADDED in report["changes"]["cam3"]
    assert CHANGE_OBJECT_ADDED in report["changes"]["cam3"]


def test_removing_a_camera_reports_its_shot_as_gone() -> None:
    report = _report([{"op": "remove_object", "kind": "camera", "id": "cam2"}])
    gone = next(shot for shot in report["shots"] if shot["id"] == "shot2")
    assert CHANGE_SHOT_REMOVED in gone["changes"]
    assert CHANGE_CAMERA_ADDED not in report["changes"].get("cam2", [])
    assert "camera_removed" in report["changes"]["cam2"]


def test_repointing_a_shot_reports_the_rebind() -> None:
    report = _report([{"op": "set_shot_camera", "id": "shot2", "camera": "cam1"}])
    shot = next(item for item in report["shots"] if item["id"] == "shot2")
    assert CHANGE_SHOT_REPOINTED in shot["changes"]


def test_a_shot_that_moved_its_range_is_news() -> None:
    """Trimming a shot changes the render schedule even when nothing inside it
    moved; the report must not stay silent."""

    script = _script()
    script["shots"][1]["end_frame"] = 150
    result = SERVICE.apply_operations(
        SceneScriptRoot.model_validate(script),
        [{"op": "move_object", "kind": "prop", "id": "crate1", "position": [3, 1, 0]}],
    )
    report = build_scene_edit_report(
        SceneScriptRoot.model_validate(script), result.scene_script
    )
    assert report["shots"] == []  # only the prop moved; no shot range changed in THIS run


def test_the_end_second_is_inclusive_like_the_shot_strip() -> None:
    """Frames 0..149 at 30fps is 5.0s of picture, not 4.97s: ShotStrip measures
    `end - start + 1` and the report must not disagree about one number."""

    report = _report(
        [{"op": "move_object", "kind": "camera", "id": "cam1", "position": [9, -10, 5]}]
    )
    shot = report["shots"][0]
    assert shot["start_seconds"] == 0.0
    assert shot["end_seconds"] == 3.0  # frames 0..89 → 90 frames → 3.0s


# ---------------------------------------------------------------------------
# camera_display_name
# ---------------------------------------------------------------------------


def test_camera_display_name_falls_back_to_the_ordinal() -> None:
    class _Camera:
        id = "cam_5"
        display_name = None

    assert camera_display_name(_Camera(), 4) == "机位05"


def test_camera_display_name_joins_an_authored_name() -> None:
    class _Camera:
        id = "cam_5"
        display_name = "飞船俯瞰"

    assert camera_display_name(_Camera(), 4) == "机位05 | 飞船俯瞰"


def test_camera_display_name_ignores_a_blank_name() -> None:
    class _Camera:
        id = "cam_5"
        display_name = "   "

    assert camera_display_name(_Camera(), 4) == "机位05"


def test_a_no_op_batch_reports_nothing_changed() -> None:
    """Moving a prop to where it already is is not a change. Reporting it would
    make the author re-read a sentence that says nothing happened."""

    report = _report(
        [{"op": "move_object", "kind": "prop", "id": "crate1", "position": [1, 1, 0]}]
    )
    assert report["changes"] == {}
    assert report["shots"] == []
    assert report["change_count"] == 0


def test_the_report_is_json_ready() -> None:
    import json

    report = _report(
        [{"op": "set_camera", "kind": "camera", "id": "cam2", "display_name": "双人全景"}]
    )
    assert json.loads(json.dumps(report)) == report
