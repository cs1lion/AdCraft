"""Tests for the director takes data model.

Locks the contract: a take is a labelled whole-script snapshot + the ops
diff that produced it. The tolerant parse must skip a take without a
scene_script (restoring a blank scene over the director's work is worse
than losing one take), and the serialize cap is the product's answer to
the "branches explode" warning.

The cap must also be *queryable*: a take that falls off the end is named
in the report rather than vanishing from the panel (engineering standard
§4 — silent drops are forbidden).
"""

from __future__ import annotations

from app.services.scene3d.director_takes import (
    MAX_DIRECTOR_TAKES,
    DirectorTake,
    DirectorTakeSerialization,
    next_take_label,
    parse_director_takes,
    serialize_director_takes,
    serialize_director_takes_with_report,
)


def _scene_script() -> dict:
    return {
        "scene": {"name": "lab", "environment": "indoor", "duration": 4, "frame_rate": 30},
        "characters": [
            {
                "id": "char_a",
                "type": "lowpoly_human",
                "appearance": {"color": "#E74C3C"},
                "keyframes": [{"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"}],
            }
        ],
        "cameras": [
            {
                "id": "cam1",
                "shot_type": "wide",
                "keyframes": [{"frame": 0, "position": [5, -6, 2.6], "look_at": [0, 0, 1.2]}],
            }
        ],
        "shots": [{"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 119}],
    }


def test_round_trip_preserves_fields() -> None:
    take = DirectorTake(
        id="take_1",
        label="Take 1",
        scene_script=_scene_script(),
        operations=[{"op": "add_keyframe", "kind": "camera", "id": "cam1", "frame": 30}],
        frame=30,
    )
    parsed = parse_director_takes([take.to_dict()])
    assert len(parsed) == 1
    restored = parsed[0]
    assert restored.id == "take_1"
    assert restored.label == "Take 1"
    assert restored.frame == 30
    assert restored.operations[0]["op"] == "add_keyframe"
    assert restored.scene_script["scene"]["name"] == "lab"


def test_parse_skips_entry_without_scene_script() -> None:
    """A take without a script is skipped — restoring a blank scene over
    the director's work is worse than losing one take."""
    good = DirectorTake(id="t1", label="Take 1", scene_script=_scene_script())
    bad = {"id": "t2", "label": "Take 2", "operations": []}  # no scene_script
    parsed = parse_director_takes([good.to_dict(), bad])
    assert len(parsed) == 1
    assert parsed[0].id == "t1"


def test_parse_returns_empty_for_absent_key() -> None:
    assert parse_director_takes(None) == []
    assert parse_director_takes({}) == []
    assert parse_director_takes("garbage") == []


def test_parse_fills_missing_id_and_label() -> None:
    entry = {"scene_script": _scene_script()}
    parsed = parse_director_takes([entry])
    assert parsed[0].id == "take_1"
    assert parsed[0].label == "Take 1"


def test_serialize_caps_at_max() -> None:
    takes = [DirectorTake(id=f"t{i}", label=f"Take {i}", scene_script=_scene_script()) for i in range(1, 10)]
    serialized = serialize_director_takes(takes)
    assert len(serialized) == MAX_DIRECTOR_TAKES
    # Newest last: the last serialized take is t9.
    assert serialized[-1]["id"] == "t9"


def test_next_take_label_skips_used() -> None:
    takes = [
        DirectorTake(id="t1", label="Take 1", scene_script=_scene_script()),
        DirectorTake(id="t2", label="Take 2", scene_script=_scene_script()),
    ]
    assert next_take_label(takes) == "Take 3"
    assert next_take_label([]) == "Take 1"


def test_frame_bool_is_treated_as_missing() -> None:
    """A boolean frame must not pass the isinstance check as an int."""
    entry = {"id": "t1", "label": "Take 1", "scene_script": _scene_script(), "frame": True}
    parsed = parse_director_takes([entry])
    assert parsed[0].frame is None


def test_operations_non_dict_entries_are_dropped() -> None:
    entry = {
        "id": "t1",
        "label": "Take 1",
        "scene_script": _scene_script(),
        "operations": ["garbage", {"op": "add_keyframe"}, 42],
    }
    parsed = parse_director_takes([entry])
    assert parsed[0].operations == [{"op": "add_keyframe"}]


# ---------------------------------------------------------------------------
# Serialization report (the cap is queryable, never silent)
# ---------------------------------------------------------------------------


def _many_takes(count: int) -> list[DirectorTake]:
    return [
        DirectorTake(id=f"t{i}", label=f"Take {i}", scene_script=_scene_script())
        for i in range(1, count + 1)
    ]


def test_report_names_every_dropped_take() -> None:
    """The panel can say "Take 1 was replaced" instead of watching it vanish."""
    report = serialize_director_takes_with_report(_many_takes(6))
    assert isinstance(report, DirectorTakeSerialization)
    assert len(report.takes) == MAX_DIRECTOR_TAKES
    assert report.dropped_take_ids == ("t1", "t2")
    assert report.capped is True


def test_report_keeps_newest_last() -> None:
    report = serialize_director_takes_with_report(_many_takes(6))
    assert [entry["id"] for entry in report.takes] == ["t3", "t4", "t5", "t6"]


def test_report_is_uncapped_at_or_below_the_cap() -> None:
    for count in range(0, MAX_DIRECTOR_TAKES + 1):
        report = serialize_director_takes_with_report(_many_takes(count))
        assert len(report.takes) == count
        assert report.dropped_take_ids == ()
        assert report.capped is False


def test_report_round_trips_through_parse() -> None:
    """The serialized payload is the same payload the parse accepts."""
    report = serialize_director_takes_with_report(_many_takes(5))
    parsed = parse_director_takes(report.takes)
    assert [take.id for take in parsed] == ["t2", "t3", "t4", "t5"]


def test_plain_serialize_matches_the_report() -> None:
    """``serialize_director_takes`` stays a thin wrapper, not a second rule."""
    takes = _many_takes(6)
    assert serialize_director_takes(takes) == serialize_director_takes_with_report(takes).takes


def test_dropped_take_ids_stay_stable_when_nothing_is_dropped() -> None:
    report = serialize_director_takes_with_report([])
    assert report.takes == []
    assert report.dropped_take_ids == ()
    assert report.capped is False


def test_cap_is_stated_not_inferred() -> None:
    """The cap is a named constant the panel reads, not a magic slice."""
    assert MAX_DIRECTOR_TAKES == 4
