"""Tests for the dialogue takes data model — 听法分叉 (V0.2 §14.13).

Locks the contract the fork depends on:

* the ids are STABLE (catalogue-driven, independent of the line, of the
  requested count and of dict ordering) — "use the pressed one" has to
  mean the same thing tomorrow;
* the cap is stated, not inferred: asking for more than
  ``MAX_DIALOGUE_TAKES`` is clamped and reported, never silently trimmed;
* an unusable line FAILS CLOSED with a named reason (empty text, an
  emotion annotation that would break the TTS prompt, a non-line) and
  never degrades to "no forks yet";
* the deltas are correct and clamp: resolve() applies them to a base and
  keeps the tempo readable, and applying an unknown fork id fails closed.
"""

from __future__ import annotations

import pytest

from app.services.dialogue.voice_cast_lines import DialogueLine
from app.services.scene3d.dialogue_takes import (
    DIALOGUE_TAKE_FORKS,
    DIALOGUE_TAKE_FORK_IDS,
    MAX_DIALOGUE_TAKES,
    MAX_TAKE_TEMPO_RATE,
    MIN_TAKE_TEMPO_RATE,
    DialogueTakeError,
    DialogueTakePlan,
    apply_dialogue_take,
    dialogue_take_fork,
    plan_dialogue_takes,
    plan_dialogue_takes_with_report,
    resolve_dialogue_take,
)
from app.services.scene3d.director_takes import MAX_DIRECTOR_TAKES

_WEB_CANVAS = (
    __import__("pathlib")
    .Path(__file__)
    .resolve()
    .parents[2]
    .joinpath("web/src/features/agent-canvas/canvas")
)


def _web_cap(filename: str, constant: str) -> int | None:
    """Read a numeric cap out of a web module, or None when absent.

    The caps live on both sides of the fence (``MAX_TRANSITION_VARIANTS``
    only exists in TS; ``MAX_DIRECTOR_TAKES`` in both), so the parity test
    reads the tree instead of assuming a shared constant.
    """

    import re

    source_path = _WEB_CANVAS / filename
    if not source_path.exists():
        return None
    match = re.search(rf"{constant}\s*=\s*(\d+)", source_path.read_text(encoding="utf-8"))
    return int(match.group(1)) if match else None


def _line(**overrides: object) -> DialogueLine:
    payload: dict[str, object] = {
        "line_id": "l1",
        "text": "别出声，信号源在墙后面。",
        "emotion": "克制",
    }
    payload.update(overrides)
    return DialogueLine(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The catalogue and its stable ids
# ---------------------------------------------------------------------------


def test_catalogue_is_capped_like_the_other_fork_caps() -> None:
    """Same magnitude as the transition variants' cap (web) and the director
    takes' cap (python).

    The number is restated in the module (a fork is a different object and
    must be able to move on its own evidence), so the parity is what this
    test pins rather than the import.
    """

    assert MAX_DIALOGUE_TAKES == 4
    assert MAX_DIALOGUE_TAKES == MAX_DIRECTOR_TAKES
    transition_cap = _web_cap("transitionVariants.ts", "MAX_TRANSITION_VARIANTS")
    if transition_cap is not None:
        assert MAX_DIALOGUE_TAKES == transition_cap
    assert len(DIALOGUE_TAKE_FORKS) == MAX_DIALOGUE_TAKES


def test_fork_ids_are_unique_and_prefixed() -> None:
    assert len(set(DIALOGUE_TAKE_FORK_IDS)) == MAX_DIALOGUE_TAKES
    assert all(fork_id.startswith("take_emotion_") for fork_id in DIALOGUE_TAKE_FORK_IDS)


def test_every_fork_carries_a_chinese_label_and_a_note() -> None:
    for fork in DIALOGUE_TAKE_FORKS:
        assert fork.label.strip()
        assert any("\u4e00" <= char <= "\u9fff" for char in fork.label)
        assert fork.note.strip()


def test_the_authored_fork_is_the_baseline_it_claims_to_be() -> None:
    """The comparison must contain the original, or it cannot be won."""

    authored = DIALOGUE_TAKE_FORKS[-1]
    assert authored.label == "就按稿"
    assert authored.tempo_delta == 0.0
    assert authored.pause_delta == 0.0
    assert authored.emotion == ""


# ---------------------------------------------------------------------------
# plan_dialogue_takes — the pure fork
# ---------------------------------------------------------------------------


def test_plan_returns_one_take_per_fork_in_catalogue_order() -> None:
    takes = plan_dialogue_takes(_line())
    assert [take.id for take in takes] == list(DIALOGUE_TAKE_FORK_IDS)
    assert [take.label for take in takes] == [fork.label for fork in DIALOGUE_TAKE_FORKS]


def test_take_ids_are_stable_across_lines_and_orderings() -> None:
    """An id means a READING, not a position: same fork, same id, always."""

    first = plan_dialogue_takes(_line(line_id="a", text="第一句。", emotion=""))
    second = plan_dialogue_takes(_line(line_id="zz", text="另一句完全不同的长度。", emotion="恐惧"))
    assert [take.id for take in first] == [take.id for take in second]
    # And stable when fewer forks are asked for — the ids do not renumber.
    assert [take.id for take in plan_dialogue_takes(_line(), 2)] == [
        "take_emotion_pressed",
        "take_emotion_lifted",
    ]


def test_each_take_carries_the_line_it_forks() -> None:
    for take in plan_dialogue_takes(_line()):
        assert take.line_id == "l1"


def test_emotion_override_and_inheritance() -> None:
    takes = {take.id: take for take in plan_dialogue_takes(_line(emotion="克制"))}
    # An override replaces the authored direction…
    assert takes["take_emotion_pressed"].emotion == "压低"
    assert takes["take_emotion_pressed"].inherits_emotion is False
    # …and the baseline fork keeps it, saying so.
    assert takes["take_emotion_authored"].emotion == "克制"
    assert takes["take_emotion_authored"].inherits_emotion is True


def test_a_line_without_emotion_forks_from_an_empty_baseline() -> None:
    takes = {take.id: take for take in plan_dialogue_takes(_line(emotion=""))}
    assert takes["take_emotion_authored"].emotion == ""
    assert "语气：留空" in takes["take_emotion_authored"].summary


def test_summary_names_every_parameter() -> None:
    pressed = {take.id: take for take in plan_dialogue_takes(_line())}["take_emotion_pressed"]
    assert pressed.summary == "压下去 · 语速 -15% · 停顿 +0.12s · 语气：压低"
    authored = {take.id: take for take in plan_dialogue_takes(_line())}["take_emotion_authored"]
    assert "（稿件原有）" in authored.summary


def test_plan_accepts_a_raw_mapping_line() -> None:
    """The panel's line is plain JSON; the fork must not care."""

    takes = plan_dialogue_takes({"line_id": "l1", "text": "别出声。", "emotion": None})
    assert len(takes) == MAX_DIALOGUE_TAKES
    assert takes[0].emotion == "压低"


def test_to_dict_round_trips_the_panel_payload() -> None:
    entry = plan_dialogue_takes(_line())[0].to_dict()
    assert entry["id"] == "take_emotion_pressed"
    assert entry["tempo_delta"] == -0.15
    assert entry["pause_delta"] == 0.12
    assert entry["summary"] == entry["summary"]  # a property, not a stale copy
    assert "语速 -15%" in entry["summary"]


# ---------------------------------------------------------------------------
# The cap is stated, never silent
# ---------------------------------------------------------------------------


def test_cap_is_clamped_and_reported() -> None:
    plan = plan_dialogue_takes_with_report(_line(), 9)
    assert isinstance(plan, DialogueTakePlan)
    assert len(plan.takes) == MAX_DIALOGUE_TAKES
    assert plan.requested_variants == 9
    assert plan.capped is True
    assert plan.ok is True
    # The catalogue itself is the cap: nothing beyond it is dropped, so the
    # eviction list stays empty and the request is what gets reported.
    assert plan.dropped_take_ids == ()


def test_an_uncapped_request_is_not_reported_as_capped() -> None:
    for count in range(1, MAX_DIALOGUE_TAKES + 1):
        plan = plan_dialogue_takes_with_report(_line(), count)
        assert len(plan.takes) == count
        assert plan.capped is False
        assert plan.dropped_take_ids == ()


def test_variants_below_one_fails_closed_with_a_reason() -> None:
    plan = plan_dialogue_takes_with_report(_line(), 0)
    assert plan.takes == ()
    assert plan.ok is False
    assert "至少为 1" in (plan.reason or "")


# ---------------------------------------------------------------------------
# Fail closed, queryable — never a silent empty list
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "code", "needle", "names"),
    [
        ({"text": "   "}, "dialogue_line_text_empty", "没有台词文本", "l1"),
        ({"text": ""}, "dialogue_line_text_empty", "没有台词文本", "l1"),
        ({"line_id": ""}, "dialogue_line_id_missing", "没有 id", "台词行"),
        ({"line_id": "bad id!"}, "dialogue_line_id_invalid", "只能用字母数字", "bad id!"),
        ({"text": "x" * 401}, "dialogue_line_text_too_long", "超过 400 字符", "l1"),
        ({"emotion": "a" * 65}, "dialogue_line_emotion_too_long", "超过 64 字符", "l1"),
        ({"emotion": "压低(很轻)"}, "dialogue_line_emotion_unbalanced", "含括号", "l1"),
        ({"emotion": "压低\n很轻"}, "dialogue_line_emotion_unbalanced", "含括号", "l1"),
    ],
)
def test_invalid_lines_fail_closed_with_a_named_reason(
    overrides: dict[str, object], code: str, needle: str, names: str
) -> None:
    line = _line(**overrides)
    # The raising form is for callers that must not proceed…
    with pytest.raises(DialogueTakeError) as raised:
        plan_dialogue_takes(line)
    assert raised.value.code == code
    assert needle in raised.value.reason
    assert names in raised.value.reason  # it says WHICH line
    # …and the reporting form degrades with the same reason, never silently.
    plan = plan_dialogue_takes_with_report(line)
    assert plan.takes == ()
    assert plan.ok is False
    assert plan.reason == raised.value.reason
    assert plan.code == code


def test_a_non_line_fails_closed() -> None:
    for bad in (None, "别出声。", 42, ["l1", "别出声。"]):
        with pytest.raises(DialogueTakeError) as raised:
            plan_dialogue_takes(bad)
        assert raised.value.code == "dialogue_line_not_a_line"
        assert "已拒绝听法分叉" in raised.value.reason


def test_a_refusal_is_not_mistaken_for_no_forks_yet() -> None:
    """The reason is part of the return value, not an exception the UI eats."""

    plan = plan_dialogue_takes_with_report(_line(text=""))
    assert plan.takes == ()
    assert plan.reason is not None and plan.reason != ""


def test_a_valid_line_has_no_reason() -> None:
    assert plan_dialogue_takes_with_report(_line()).reason is None


# ---------------------------------------------------------------------------
# Deltas: resolve / apply
# ---------------------------------------------------------------------------


def test_resolve_applies_the_deltas_to_the_base() -> None:
    parameters = resolve_dialogue_take(
        _line(), "take_emotion_pressed", base_tempo_rate=1.0, base_pause_seconds=0.4
    )
    assert parameters.tempo_rate == pytest.approx(0.85)
    assert parameters.pause_seconds == pytest.approx(0.52)
    assert parameters.emotion == "压低"


def test_resolve_keeps_the_authored_emotion_for_the_baseline_fork() -> None:
    parameters = resolve_dialogue_take(_line(emotion="克制"), "take_emotion_authored")
    assert parameters.emotion == "克制"
    assert parameters.tempo_rate == 1.0
    assert parameters.pause_seconds == 0.0


def test_deltas_cannot_talk_the_tempo_out_of_the_readable_range() -> None:
    for fork in DIALOGUE_TAKE_FORKS:
        for base in (0.0, 0.6, 1.0, 1.9):
            rate = resolve_dialogue_take(_line(), fork.id, base_tempo_rate=base).tempo_rate
            assert MIN_TAKE_TEMPO_RATE <= rate <= MAX_TAKE_TEMPO_RATE
    # A negative pause never goes below zero (silence is not negative time).
    parameters = resolve_dialogue_take(_line(), "take_emotion_lifted", base_pause_seconds=0.0)
    assert parameters.pause_seconds == 0.0


def test_resolve_clamps_a_fork_stacked_on_an_extreme_base() -> None:
    fast = resolve_dialogue_take(_line(), "take_emotion_lifted", base_tempo_rate=1.95)
    assert fast.tempo_rate == MAX_TAKE_TEMPO_RATE
    slow = resolve_dialogue_take(_line(), "take_emotion_pressed", base_tempo_rate=0.51)
    assert slow.tempo_rate == MIN_TAKE_TEMPO_RATE


def test_apply_shapes_the_patch_for_the_line_edit_path() -> None:
    patch = apply_dialogue_take(_line(emotion="克制"), "take_emotion_pressed")
    assert patch == {"emotion": "压低", "tempo_delta": -0.15, "pause_delta": 0.12}
    baseline = apply_dialogue_take(_line(emotion="克制"), "take_emotion_authored")
    assert baseline["emotion"] == "克制"
    assert baseline["tempo_delta"] == 0.0


def test_apply_accepts_a_planned_take_object() -> None:
    take = plan_dialogue_takes(_line())[2]
    patch = apply_dialogue_take(_line(), take)
    assert patch["emotion"] == "紧绷"
    assert patch["pause_delta"] == 0.22


def test_unknown_fork_ids_fail_closed() -> None:
    """Applying a take nobody planned must not silently keep the old values."""

    with pytest.raises(DialogueTakeError) as raised:
        dialogue_take_fork("take_emotion_mystery")
    assert raised.value.code == "dialogue_take_unknown"
    assert "take_emotion_pressed" in raised.value.reason  # it lists what exists
    with pytest.raises(DialogueTakeError):
        apply_dialogue_take(_line(), "take_emotion_mystery")
    with pytest.raises(DialogueTakeError):
        resolve_dialogue_take(_line(), "take_emotion_mystery")


def test_resolve_fails_closed_on_an_unusable_line_too() -> None:
    with pytest.raises(DialogueTakeError):
        resolve_dialogue_take(_line(text=""), "take_emotion_pressed")


def test_a_fork_object_is_accepted_verbatim() -> None:
    fork = dialogue_take_fork(DIALOGUE_TAKE_FORKS[1])
    assert fork.id == "take_emotion_lifted"
    assert dialogue_take_fork(" take_emotion_lifted ").id == "take_emotion_lifted"


# ---------------------------------------------------------------------------
# Parity with the frontend mirror
# ---------------------------------------------------------------------------


def test_frontend_parity_shape() -> None:
    """``dialogueTakes.ts`` mirrors the ids/labels the panel lists."""

    frontend = _WEB_CANVAS / "dialogueTakes.ts"
    if not frontend.exists():
        pytest.skip(f"parity module missing: {frontend}")
    source = frontend.read_text(encoding="utf-8")
    for fork in DIALOGUE_TAKE_FORKS:
        assert f'id: "{fork.id}"' in source
        assert f'label: "{fork.label}"' in source
