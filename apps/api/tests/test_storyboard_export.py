"""Tests for the storyboard export module.

Locks the contract: a validated SceneScript expands into a deterministic
storyboard strip (shot list + flat keyframe frame strip) with no new asset
pipeline. Same script in → same strip out.

The span findings are locked too: a strip that asks for frames the scene
does not contain is reported with a named reason next to the strip, not
rejected and not silently rendered short.
"""

from __future__ import annotations

import pytest

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.storyboard_export import (
    StoryboardFinding,
    build_storyboard,
    check_storyboard_span,
)


def _script() -> SceneScriptRoot:
    return SceneScriptRoot.model_validate(
        {
            "scene": {
                "name": "lab",
                "environment": "indoor",
                "duration": 4.0,
                "frame_rate": 30,
            },
            "characters": [
                {
                    "id": "lin",
                    "type": "lowpoly_human",
                    "appearance": {"color": "#E74C3C"},
                    "keyframes": [
                        {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"}
                    ],
                }
            ],
            "cameras": [
                {
                    "id": "cam1",
                    "shot_type": "wide",
                    "keyframes": [
                        {"frame": 0, "position": [5, -6, 2.6], "look_at": [0, 0, 1.2]}
                    ],
                },
                {
                    "id": "cam2",
                    "shot_type": "closeup",
                    "keyframes": [
                        {"frame": 60, "position": [1, -2, 2], "look_at": [0, 0, 1]}
                    ],
                },
            ],
            "shots": [
                {"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 60},
                {"id": "s2", "camera": "cam2", "start_frame": 60, "end_frame": 120},
            ],
        }
    )


def test_storyboard_has_one_entry_per_shot() -> None:
    strip = build_storyboard(_script())
    assert strip.total_shots == 2
    assert [entry.shot_id for entry in strip.shots] == ["s1", "s2"]


def test_storyboard_shot_entry_carries_camera_and_shot_type() -> None:
    strip = build_storyboard(_script())
    s1, s2 = strip.shots
    assert s1.camera_id == "cam1"
    assert s1.shot_type == "wide"
    assert s2.camera_id == "cam2"
    assert s2.shot_type == "closeup"


def test_storyboard_keyframe_frames_are_sorted_and_deduplicated() -> None:
    strip = build_storyboard(_script())
    frames = list(strip.all_keyframe_frames)
    assert frames == sorted(frames)
    assert len(frames) == len(set(frames))
    # s1 spans 0..59 → 5 frames; s2 spans 60..119 → 5 frames;
    # the union may share frame 60 (s2's 0% = 60, s1's 100% = 59 — no overlap here)
    assert 0 in frames
    assert 60 in frames


def test_storyboard_shot_entry_keyframe_frame_count() -> None:
    strip = build_storyboard(_script())
    for entry in strip.shots:
        # A shot with duration > 0 always yields 5 keyframe frames.
        assert len(entry.keyframe_frames) == 5, entry


def test_storyboard_missing_camera_raises() -> None:
    script = _script()
    script.shots[0] = type(script.shots[0])(**{**script.shots[0].model_dump(), "camera": "ghost"})
    with pytest.raises(ValueError, match="storyboard_shot_camera_missing"):
        build_storyboard(script)


def test_storyboard_to_dict_is_json_safe() -> None:
    import json

    strip = build_storyboard(_script())
    payload = json.loads(json.dumps(strip.to_dict()))
    assert payload["total_shots"] == 2
    assert payload["shots"][0]["shot_id"] == "s1"
    assert isinstance(payload["all_keyframe_frames"], list)


def test_storyboard_transition_intent_is_preserved() -> None:
    script = _script()
    script.shots[0].transition_intent = "cut_after_line"
    strip = build_storyboard(script)
    assert strip.shots[0].transition_intent == "cut_after_line"
    # s2 never declared one; it stays None.
    assert strip.shots[1].transition_intent is None


def test_storyboard_deterministic() -> None:
    strip_a = build_storyboard(_script())
    strip_b = build_storyboard(_script())
    assert strip_a.to_dict() == strip_b.to_dict()


# ---------------------------------------------------------------------------
# Span findings (named reasons, advisory not blocking)
# ---------------------------------------------------------------------------


def _script_with_shots(shots: list[dict]) -> SceneScriptRoot:
    # The camera's keyframe must sit inside one of the shots (a soft
    # structural check), so anchor it to the first shot's start.
    anchor_frame = min((shot["start_frame"] for shot in shots), default=0)
    return SceneScriptRoot.model_validate(
        {
            "scene": {
                "name": "lab",
                "environment": "indoor",
                "duration": 4.0,
                "frame_rate": 30,
            },
            "characters": [
                {
                    "id": "lin",
                    "type": "lowpoly_human",
                    "appearance": {"color": "#E74C3C"},
                    "keyframes": [
                        {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"}
                    ],
                }
            ],
            "cameras": [
                {
                    "id": "cam1",
                    "shot_type": "wide",
                    "keyframes": [
                        {
                            "frame": anchor_frame,
                            "position": [5, -6, 2.6],
                            "look_at": [0, 0, 1.2],
                        }
                    ],
                },
            ],
            "shots": shots,
        }
    )


def test_no_shots_yields_a_named_finding_and_an_empty_strip() -> None:
    """An empty storyboard is a real answer — but it must not look like a fault."""
    strip = build_storyboard(_script_with_shots([]))
    assert strip.total_shots == 0
    assert strip.shots == ()
    findings = check_storyboard_span(strip)
    assert [finding.code for finding in findings] == ["storyboard_no_shots"]


def test_clean_strip_has_no_findings() -> None:
    strip = build_storyboard(_script())
    assert check_storyboard_span(strip) == []


def test_gap_between_shots_is_reported_with_the_frame_range() -> None:
    """Frames that belong to no shot render nothing — the strip skips them."""
    # total_frames is 120; these shots leave 80..89 uncovered.
    strip = build_storyboard(_script_with_shots(
        [
            {"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 80},
            {"id": "s2", "camera": "cam1", "start_frame": 90, "end_frame": 120},
        ]
    ))
    findings = check_storyboard_span(strip)
    assert [finding.code for finding in findings] == ["storyboard_shots_leave_gap"]
    assert findings[0].subject == "s1\u2192s2"
    assert "80" in findings[0].message and "89" in findings[0].message


def test_leading_and_trailing_uncovered_frames_are_reported() -> None:
    """A strip that starts late or stops early is still a hole in the film."""
    strip = build_storyboard(_script_with_shots(
        [{"id": "s1", "camera": "cam1", "start_frame": 30, "end_frame": 90}]
    ))
    findings = check_storyboard_span(strip)
    assert [finding.code for finding in findings] == [
        "storyboard_shots_leave_gap",
        "storyboard_shots_leave_gap",
    ]
    # Neither end names a shot: the hole is against the scene, not a pair.
    assert [finding.subject for finding in findings] == ["", ""]


def test_findings_are_advisory_the_strip_still_builds() -> None:
    """A finding never costs the storyboard itself (it is a read-only view)."""
    strip = build_storyboard(_script_with_shots(
        [{"id": "s1", "camera": "cam1", "start_frame": 30, "end_frame": 90}]
    ))
    assert strip.total_shots == 1
    assert check_storyboard_span(strip)


def test_short_shot_reports_fewer_than_five_keyframes() -> None:
    """The strip advertises 5 representative frames; a 2-frame shot cannot."""
    strip = build_storyboard(_script_with_shots(
        [{"id": "tiny", "camera": "cam1", "start_frame": 0, "end_frame": 2}]
    ))
    assert len(strip.shots[0].keyframe_frames) < 5
    findings = check_storyboard_span(strip)
    short = [f for f in findings if f.code == "storyboard_shot_keyframes_short"]
    assert len(short) == 1
    assert short[0].subject == "tiny"


def test_finding_to_dict_is_json_safe() -> None:
    import json

    strip = build_storyboard(_script_with_shots(
        [{"id": "s1", "camera": "cam1", "start_frame": 30, "end_frame": 90}]
    ))
    payload = json.loads(json.dumps([f.to_dict() for f in check_storyboard_span(strip)]))
    assert payload[0]["code"] == "storyboard_shots_leave_gap"
    assert set(payload[0]) == {"code", "subject", "message"}


def test_findings_are_ordered_by_shot_start() -> None:
    """The report reads in script order even when the shots arrive shuffled."""
    strip = build_storyboard(_script_with_shots(
        [
            {"id": "late", "camera": "cam1", "start_frame": 90, "end_frame": 120},
            {"id": "early", "camera": "cam1", "start_frame": 0, "end_frame": 60},
        ]
    ))
    findings = check_storyboard_span(strip)
    assert findings[0].subject == "early\u2192late"
    assert isinstance(findings[0], StoryboardFinding)


# ---------------------------------------------------------------------------
# E3: 端点层——findings 必须随分镜响应透传（算了不回传 = 用户永远看不到）
# ---------------------------------------------------------------------------


def test_storyboard_endpoint_surfaces_findings() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d

    app = FastAPI()
    app.include_router(scene_3d.router)
    client = TestClient(app)

    # 留下 80..89 空隙的镜头表：findings 必须出现在响应里
    script = _script_with_shots(
        [
            {"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 80},
            {"id": "s2", "camera": "cam1", "start_frame": 90, "end_frame": 120},
        ]
    )
    response = client.post(
        "/scene-3d/storyboard",
        json={"scene_script": script.model_dump(mode="json")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    codes = [finding["code"] for finding in body["findings"]]
    assert codes == ["storyboard_shots_leave_gap"]
    assert body["findings"][0]["subject"] == "s1\u2192s2"
    assert set(body["findings"][0]) == {"code", "subject", "message"}
    # advisory：分镜本身照常返回
    assert body["total_shots"] == 2


def test_storyboard_endpoint_clean_script_has_no_findings() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d

    app = FastAPI()
    app.include_router(scene_3d.router)
    client = TestClient(app)

    script = _script()
    response = client.post(
        "/scene-3d/storyboard",
        json={"scene_script": script.model_dump(mode="json")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["findings"] == []
