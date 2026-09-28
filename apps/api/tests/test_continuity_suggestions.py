"""Tests for the continuity suggestions translator.

Locks the contract: the existing advisory checks (blocking / emotion /
held-items) are translated into conversational suggestions, and any
finding whose code the translator does not know yet is reported in
``untranslated`` — never dropped silently.

The degradation paths are locked as hard as the happy path (engineering
standard §4): an unknown code, a rule that declares an unrenderable kind,
and a check that raises each have to show up somewhere a creator can read.
"""

from __future__ import annotations

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.continuity_suggestions import (
    CONTINUITY_CHECK_FAILED,
    CONTINUITY_RULE_INVALID,
    SUGGESTION_KINDS,
    build_continuity_suggestions,
    build_continuity_suggestions_dict,
)


def _script() -> SceneScriptRoot:
    """A two-shot scene with a facing flip on char_a across the cut."""
    return SceneScriptRoot.model_validate(
        {
            "scene": {"name": "lab", "environment": "indoor", "duration": 4.0, "frame_rate": 30},
            "characters": [
                {
                    "id": "char_a",
                    "type": "lowpoly_human",
                    "appearance": {"color": "#E74C3C"},
                    "keyframes": [
                        # Facing 0° at the end of s1 (frame 59).
                        {"frame": 59, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"},
                        # Use 270° so the interpolated delta exceeds the 90° threshold.
                        {"frame": 61, "position": [0, 0, 0], "rotation_y": 270, "action": "stand"},
                        {"frame": 119, "position": [0, 0, 0], "rotation_y": 180, "action": "stand"},
                    ],
                }
            ],
            "cameras": [
                {
                    "id": "cam1",
                    "shot_type": "wide",
                    "keyframes": [{"frame": 0, "position": [5, -6, 2.6], "look_at": [0, 0, 1.2]}],
                },
            ],
            "shots": [
                {"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 60},
                {"id": "s2", "camera": "cam1", "start_frame": 61, "end_frame": 120},
            ],
        }
    )


def test_facing_flip_yields_a_question_suggestion() -> None:
    suggestions, untranslated = build_continuity_suggestions(_script())
    codes = [s.source_code for s in suggestions]
    assert "facing_flip" in codes, f"expected facing_flip in {codes}"
    flip = next(s for s in suggestions if s.source_code == "facing_flip")
    assert flip.kind == "question"
    assert "char_a" in flip.subjects
    assert flip.remedy is not None


def test_no_finding_yields_empty_lists() -> None:
    """A single-shot scene has no cut, so blocking continuity is empty."""
    script = _script()
    script.shots = script.shots[:1]
    suggestions, untranslated = build_continuity_suggestions(script)
    # No facing flip (no boundary), no held items, no segments → all empty.
    assert suggestions == []
    assert untranslated == []


def test_untranslated_catches_unknown_codes() -> None:
    """Monkey-patch the blocking check to emit an unknown code and verify
    it lands in ``untranslated``, not silently dropped."""
    from app.services.scene3d import continuity_suggestions as cs
    from app.services.scene3d.blocking_continuity import BlockingContinuityIssue

    original = cs.check_blocking_continuity

    def _fake(script):
        return [
            BlockingContinuityIssue(
                code="teleport_gap",
                severity="warning",
                subject="char_a",
                boundary="s1→s2",
                message="teleport",
                remedy="add a walk",
            )
        ]

    cs.check_blocking_continuity = _fake
    try:
        suggestions, untranslated = build_continuity_suggestions(_script())
    finally:
        cs.check_blocking_continuity = original

    assert suggestions == []
    assert len(untranslated) == 1
    assert untranslated[0]["code"] == "teleport_gap"
    assert untranslated[0]["detail"] == "teleport"


def test_segments_enable_emotion_check() -> None:
    """With segments, the emotion check runs; without, it is skipped."""
    from app.services.scene3d.speech_orchestration import SpeechSegment

    segments = [
        SpeechSegment(
            segment_id="seg_0",
            character_id="char_a",
            text="hello",
            start_time=0.0,
            end_time=1.0,
        ),
    ]
    # With segments the function accepts them without raising.
    _, _ = build_continuity_suggestions(_script(), segments)
    # Without segments it is also safe (emotion half skipped).
    _, _ = build_continuity_suggestions(_script(), None)


def test_dict_shape_is_json_safe() -> None:
    import json

    payload = build_continuity_suggestions_dict(_script())
    decoded = json.loads(json.dumps(payload))
    assert "suggestions" in decoded
    assert "untranslated" in decoded
    for entry in decoded["suggestions"]:
        assert "kind" in entry
        assert "source_code" in entry
        assert "message" in entry


# ---------------------------------------------------------------------------
# Degradation paths (named reasons, never silent)
# ---------------------------------------------------------------------------


def _hand_conflict_script() -> SceneScriptRoot:
    """Two props declared on the same character's same hand."""
    return SceneScriptRoot.model_validate(
        {
            "scene": {"name": "lab", "environment": "indoor", "duration": 4.0, "frame_rate": 30},
            "characters": [
                {
                    "id": "char_a",
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
                    "keyframes": [{"frame": 0, "position": [5, -6, 2.6], "look_at": [0, 0, 1.2]}],
                },
            ],
            "props": [
                {
                    "id": "umbrella",
                    "type": "weapon",
                    "position": [0.2, 0, 1.0],
                    "held_by": "char_a",
                    "held_side": "right",
                },
                {
                    "id": "torch",
                    "type": "weapon",
                    "position": [0.2, 0, 1.0],
                    "held_by": "char_a",
                    "held_side": "right",
                },
            ],
            "shots": [
                {"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 119},
            ],
        }
    )


def test_hand_conflict_becomes_a_note_suggestion() -> None:
    """The held-items half is wired to its own rules, not just blocking."""
    suggestions, untranslated = build_continuity_suggestions(_hand_conflict_script())
    codes = [s.source_code for s in suggestions]
    assert "held_item_hand_conflict" in codes, f"expected the held-item code in {codes}"
    assert untranslated == []
    assert all(s.kind in SUGGESTION_KINDS for s in suggestions)


def test_untranslated_entries_name_their_check() -> None:
    """A surface must be able to point at the check that fell behind."""
    from app.services.scene3d import continuity_suggestions as cs
    from app.services.scene3d.held_items import HeldItemFinding

    original = cs.check_held_items

    def _fake(script):
        return [
            HeldItemFinding(
                code="held_item_vanished",
                subject="umbrella",
                message="item vanished",
                remedy="re-declare it",
            )
        ]

    cs.check_held_items = _fake
    try:
        _, untranslated = build_continuity_suggestions(_hand_conflict_script())
    finally:
        cs.check_held_items = original

    assert len(untranslated) == 1
    assert untranslated[0]["code"] == "held_item_vanished"
    assert untranslated[0]["check"] == "held_items"
    assert untranslated[0]["detail"] == "item vanished"


def test_rule_with_unrenderable_kind_is_reported_not_shipped() -> None:
    """A rule nobody can render must not reach the surface as a suggestion."""
    from app.services.scene3d import continuity_suggestions as cs

    # Mutate the rule table in place: _RULES_BY_CHECK holds the same dict.
    cs._HELD_ITEM_RULES["held_item_hand_conflict"] = {
        "kind": "banner",  # not in SUGGESTION_KINDS
        "message": "…",
    }
    try:
        suggestions, untranslated = build_continuity_suggestions(_hand_conflict_script())
    finally:
        cs._HELD_ITEM_RULES["held_item_hand_conflict"] = {
            "kind": "note",
            "message": "一只手放不下两件道具，调一下持有手。",
        }

    assert all(s.source_code != "held_item_hand_conflict" for s in suggestions)
    entry = next(item for item in untranslated if item.get("code") == CONTINUITY_RULE_INVALID)
    assert entry["check"] == "held_items"
    assert "banner" in entry["reason"]


def test_rule_without_message_is_reported_not_shipped() -> None:
    """An empty hook is as unrenderable as an illegal kind."""
    from app.services.scene3d import continuity_suggestions as cs

    cs._HELD_ITEM_RULES["held_item_hand_conflict"] = {"kind": "note", "message": "   "}
    try:
        suggestions, untranslated = build_continuity_suggestions(_hand_conflict_script())
    finally:
        cs._HELD_ITEM_RULES["held_item_hand_conflict"] = {
            "kind": "note",
            "message": "一只手放不下两件道具，调一下持有手。",
        }

    assert all(s.source_code != "held_item_hand_conflict" for s in suggestions)
    entry = next(item for item in untranslated if item.get("code") == CONTINUITY_RULE_INVALID)
    assert "没有 message" in entry["reason"]


def test_a_raising_check_degrades_without_killing_the_others() -> None:
    """Advisory never blocks: one broken check costs its own advice only."""
    from app.services.scene3d import continuity_suggestions as cs

    original = cs.check_held_items

    def _boom(script):
        raise RuntimeError("held-items index is corrupt")

    cs.check_held_items = _boom
    try:
        suggestions, untranslated = build_continuity_suggestions(_script())
    finally:
        cs.check_held_items = original

    # The blocking half still translated the facing flip.
    assert "facing_flip" in [s.source_code for s in suggestions]
    failure = next(item for item in untranslated if item["code"] == CONTINUITY_CHECK_FAILED)
    assert failure["check"] == "held_items"
    assert "held-items index is corrupt" in failure["detail"]


def test_empty_script_yields_two_empty_lists() -> None:
    """A scene with no shots, characters or props has nothing to translate."""
    empty = SceneScriptRoot.model_validate(
        {
            "scene": {"name": "void", "environment": "indoor", "duration": 2.0, "frame_rate": 30},
            "shots": [],
        }
    )
    suggestions, untranslated = build_continuity_suggestions(empty)
    assert suggestions == []
    assert untranslated == []


def test_every_shipped_suggestion_carries_its_detail_and_message() -> None:
    """The detail view is the finding verbatim — the hook never replaces it."""
    suggestions, _ = build_continuity_suggestions(_script())
    assert suggestions, "the fixture must produce at least one suggestion"
    for suggestion in suggestions:
        assert suggestion.detail
        assert suggestion.message
        assert suggestion.source_code
        assert suggestion.subjects
        assert suggestion.kind in SUGGESTION_KINDS
        assert suggestion.remedy is not None


def test_dict_report_round_trips_through_json() -> None:
    import json

    payload = build_continuity_suggestions_dict(_hand_conflict_script())
    decoded = json.loads(json.dumps(payload))
    assert decoded["suggestions"]
    assert decoded["untranslated"] == []
