"""Unit tests for the SceneScript consistency gate (Dramagic-style checks).

Locks each check's trigger and silence conditions, the report shape, and the
warning-not-error severity contract (a gate that blocks existing renders
would be a regression, not a safety net). The mutation check flips the
multi-shot condition and fails, proving it binds.
"""

from __future__ import annotations

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.scene_consistency import (
    SEVERITY_WARNING,
    check_scene_script_consistency,
)


def script(
    *,
    shots: int = 1,
    characters: list[dict] | None = None,
    cameras: list[dict] | None = None,
    shot_defs: list[dict] | None = None,
    total_frames: int = 180,
    duration: float = 6.0,
    props: list[dict] | None = None,
    environment: list[dict] | None = None,
) -> SceneScriptRoot:
    if characters is None:
        characters = [
            {
                "id": "char_a",
                "type": "lowpoly_human",
                "appearance": {"color": "#E74C3C", "height": 1.7, "scale": 1.0},
                "keyframes": [{"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"}],
            }
        ]
    if cameras is None:
        cameras = [
            {
                "id": "cam1",
                "shot_type": "wide",
                "keyframes": [{"frame": 0, "position": [8, -10, 5], "look_at": [0, 0, 1]}],
            }
        ]
    if shot_defs is None:
        # Default: `shots` contiguous, non-overlapping ranges covering the scene.
        per = total_frames // shots
        shot_defs = [
            {
                "id": f"shot{i + 1}",
                "camera": "cam1",
                "start_frame": i * per,
                "end_frame": (i + 1) * per - 1 if i < shots - 1 else total_frames - 1,
                "description": f"shot {i + 1}",
            }
            for i in range(shots)
        ]
    return SceneScriptRoot.model_validate(
        {
            "scene": {
                "name": "test-scene",
                "environment": "indoor",
                "lighting": "cool",
                "duration": duration,
                "frame_rate": 30,
            },
            "characters": characters,
            "props": props if props is not None else [],
            "environment": environment if environment is not None else [],
            "cameras": cameras,
            "shots": shot_defs,
            "speech_bindings": [],
        }
    )


def codes(report) -> list[str]:
    return [issue.code for issue in report.issues]


# ---------------------------------------------------------------------------
# character_unbound: the Dramagic core check
# ---------------------------------------------------------------------------


def test_single_shot_scene_does_not_warn_about_unbound_characters() -> None:
    report = check_scene_script_consistency(script(shots=1))
    assert "character_unbound" not in codes(report)


def test_multi_shot_scene_warns_per_unbound_character() -> None:
    characters = [
        {
            "id": "char_a",
            "type": "lowpoly_human",
            "appearance": {"color": "#E74C3C"},
            "keyframes": [{"frame": 0, "position": [0, 0, 0], "rotation_y": 0}],
        },
        {
            "id": "char_b",
            "type": "lowpoly_human",
            "appearance": {"color": "#3498DB"},
            "character_asset_id": "asset-2",
            "keyframes": [{"frame": 0, "position": [1, 0, 0], "rotation_y": 0}],
        },
    ]
    report = check_scene_script_consistency(script(shots=2, characters=characters))
    assert codes(report).count("character_unbound") == 1
    issue = next(issue for issue in report.issues if issue.code == "character_unbound")
    assert issue.subject == "char_a"
    assert issue.severity == SEVERITY_WARNING
    assert issue.remedy


def test_bound_characters_pass_the_multi_shot_gate() -> None:
    characters = [
        {
            "id": "char_a",
            "type": "lowpoly_human",
            "appearance": {"color": "#E74C3C"},
            "character_asset_id": "asset-1",
            "keyframes": [{"frame": 0, "position": [0, 0, 0], "rotation_y": 0}],
        }
    ]
    report = check_scene_script_consistency(script(shots=3, characters=characters))
    assert "character_unbound" not in codes(report)


# ---------------------------------------------------------------------------
# character_color_collision
# ---------------------------------------------------------------------------


def test_color_collision_is_flagged() -> None:
    characters = [
        {
            "id": "char_a",
            "type": "lowpoly_human",
            "appearance": {"color": "#E74C3C"},
            "keyframes": [{"frame": 0, "position": [0, 0, 0], "rotation_y": 0}],
        },
        {
            "id": "char_b",
            "type": "lowpoly_human",
            "appearance": {"color": "#e74c3c"},  # case-insensitive
            "keyframes": [{"frame": 0, "position": [1, 0, 0], "rotation_y": 0}],
        },
    ]
    report = check_scene_script_consistency(script(characters=characters))
    assert "character_color_collision" in codes(report)
    issue = next(issue for issue in report.issues if issue.code == "character_color_collision")
    assert "char_a" in issue.subject and "char_b" in issue.subject


def test_distinct_colors_pass() -> None:
    report = check_scene_script_consistency(script())
    assert "character_color_collision" not in codes(report)


# ---------------------------------------------------------------------------
# camera_unused / shot_coverage_gap / scene_empty
# ---------------------------------------------------------------------------


def test_unused_camera_is_flagged() -> None:
    cameras = [
        {
            "id": "cam1",
            "shot_type": "wide",
            "keyframes": [{"frame": 0, "position": [8, -10, 5], "look_at": [0, 0, 1]}],
        },
        {
            "id": "cam2",
            "shot_type": "medium",
            "keyframes": [{"frame": 0, "position": [4, -6, 3], "look_at": [0, 0, 1]}],
        },
    ]
    shot_defs = [
        {"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 179},
    ]
    report = check_scene_script_consistency(script(cameras=cameras, shot_defs=shot_defs))
    issue = next(issue for issue in report.issues if issue.code == "camera_unused")
    assert issue.subject == "cam2"


def test_shot_coverage_gap_is_flagged() -> None:
    shot_defs = [
        {"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 50},
        {"id": "shot2", "camera": "cam1", "start_frame": 100, "end_frame": 179},
    ]
    report = check_scene_script_consistency(script(shot_defs=shot_defs))
    gaps = [issue for issue in report.issues if issue.code == "shot_coverage_gap"]
    assert len(gaps) == 1
    assert "51-99" in gaps[0].subject


def test_full_coverage_passes() -> None:
    report = check_scene_script_consistency(script(shots=3))
    assert "shot_coverage_gap" not in codes(report)


def test_empty_scene_is_flagged() -> None:
    report = check_scene_script_consistency(script(characters=[], props=[], environment=[]))
    assert "scene_empty" in codes(report)


def test_scene_with_only_props_is_not_empty() -> None:
    report = check_scene_script_consistency(
        script(characters=[], props=[{"id": "crate1", "type": "crate", "position": [0, 0, 0]}])
    )
    assert "scene_empty" not in codes(report)


# ---------------------------------------------------------------------------
# report shape + severity contract
# ---------------------------------------------------------------------------


def test_clean_scene_passes() -> None:
    report = check_scene_script_consistency(script())
    assert report.passed is True
    assert report.issues == ()
    assert report.to_dict() == {
        "passed": True,
        "error_count": 0,
        "warning_count": 0,
        "issues": [],
    }


def test_report_dict_shape() -> None:
    report = check_scene_script_consistency(script(shots=2))
    payload = report.to_dict()
    assert payload["passed"] is True  # warnings never fail the gate
    assert payload["warning_count"] == len(report.warnings)
    assert all(set(issue) == {"code", "severity", "subject", "message", "remedy"} for issue in payload["issues"])


def test_every_issue_carries_a_remedy() -> None:
    for kwargs in (
        {"shots": 2},
        {"characters": [], "props": [], "environment": []},
    ):
        report = check_scene_script_consistency(script(**kwargs))
        for issue in report.issues:
            assert issue.remedy, f"{issue.code} has no remedy"
            assert issue.message, f"{issue.code} has no message"
            assert issue.severity == SEVERITY_WARNING


# ---------------------------------------------------------------------------
# HTTP endpoint (workbench pre-render gate)
# ---------------------------------------------------------------------------


def test_consistency_check_endpoint_reports_warnings() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint

    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)

    payload = script(shots=2).model_dump(mode="json")
    response = client.post("/scene-3d/consistency-check", json={"scene_script": payload})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["passed"] is True  # warnings never fail the gate
    assert "character_unbound" in [issue["code"] for issue in body["issues"]]


def test_consistency_check_endpoint_rejects_invalid_script() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint

    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)

    response = client.post(
        "/scene-3d/consistency-check", json={"scene_script": {"scene": {"name": "x"}}}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "scene_script_invalid"
