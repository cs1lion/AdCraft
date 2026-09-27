"""Tests for per-line voice-cast synthesis (V0.2 §14.7 内容层/表演层).

The property these tests defend: **changing one line must not re-synthesize the
take**. The plan is content-addressed, so "has this line changed?" is "does its
cache file exist?" — no manifest can be out of sync, and no stale artifact can
be mistaken for a fresh one. The regeneration request forces a line regardless
(the author wants a different take of the SAME words).

Also locked: the offsets in the published manifest stop being trustworthy the
moment a duration is unreadable — a joined take whose gaps were measured cannot
claim to know where the following lines sit.
"""

from __future__ import annotations

import os

import pytest

from app.services.dialogue.voice_cast_lines import (
    MAX_DIALOGUE_LINES,
    DialogueLine,
    parse_dialogue_lines,
    plan_line_synthesis,
)


class TestParseDialogueLines:
    def test_parses_id_text_and_emotion_in_authoring_order(self) -> None:
        lines, dropped = parse_dialogue_lines(
            [
                {"id": "l1", "text": "就是这里。", "emotion": "压低声音"},
                {"id": "l2", "text": "别出声。"},
            ]
        )
        assert dropped == []
        assert [(line.line_id, line.text, line.emotion) for line in lines] == [
            ("l1", "就是这里。", "压低声音"),
            ("l2", "别出声。", ""),
        ]

    def test_a_line_id_may_also_arrive_as_line_id(self) -> None:
        lines, _ = parse_dialogue_lines([{"line_id": "l1", "text": "hi"}])
        assert lines[0].line_id == "l1"

    @pytest.mark.parametrize(
        "entry",
        [
            {"text": "no id"},
            {"id": "l1", "text": ""},
            {"id": "bad id!", "text": "x"},
            {"id": "x" * 49, "text": "x"},
            {"id": "l1", "text": "x" * 401},
            {"id": "l1", "text": "x", "emotion": "e" * 65},
        ],
    )
    def test_a_bad_row_is_dropped_with_a_reason_not_a_crash(self, entry: dict) -> None:
        lines, dropped = parse_dialogue_lines([entry])
        assert lines == []
        assert len(dropped) == 1

    def test_duplicate_ids_are_dropped_not_merged(self) -> None:
        lines, dropped = parse_dialogue_lines(
            [{"id": "l1", "text": "one"}, {"id": "l1", "text": "two"}]
        )
        assert [line.text for line in lines] == ["one"]
        assert "重复" in dropped[0]

    def test_a_non_list_block_is_reported(self) -> None:
        lines, dropped = parse_dialogue_lines({"id": "l1", "text": "x"})
        assert lines == []
        assert dropped

    def test_the_line_cap_says_so_instead_of_silently_dropping(self) -> None:
        lines, dropped = parse_dialogue_lines(
            [{"id": f"l{index}", "text": "x"} for index in range(MAX_DIALOGUE_LINES + 5)]
        )
        assert len(lines) == MAX_DIALOGUE_LINES
        assert any(str(MAX_DIALOGUE_LINES) in reason for reason in dropped)


class TestContentAddressedCache:
    def test_the_same_words_and_emotion_share_one_take(self) -> None:
        assert DialogueLine("l1", "hi", "soft").filename == DialogueLine("l1", "hi", "soft").filename

    def test_a_changed_word_or_emotion_is_a_different_take(self) -> None:
        base = DialogueLine("l1", "hi").filename
        assert DialogueLine("l1", "hello").filename != base
        assert DialogueLine("l1", "hi", "soft").filename != base

    def test_two_lines_never_collide(self) -> None:
        names = {DialogueLine(f"l{index}", "same words").filename for index in range(20)}
        assert len(names) == 20


class TestPlanLineSynthesis:
    def _existing(self, present: set[str]):
        return lambda path: os.path.basename(path) in present

    def test_a_cached_line_is_reused(self) -> None:
        lines = [DialogueLine("l1", "hi")]
        plan = plan_line_synthesis(
            lines, cache_dir="/cache", file_exists=self._existing({lines[0].filename})
        )
        assert plan.to_synthesize == []
        assert plan.all_cached is True

    def test_an_uncached_line_is_synthesized(self) -> None:
        lines = [DialogueLine("l1", "hi")]
        plan = plan_line_synthesis(lines, cache_dir="/cache", file_exists=self._existing(set()))
        assert [line.line_id for line in plan.to_synthesize] == ["l1"]
        assert plan.all_cached is False

    def test_only_the_changed_line_is_paid_for(self) -> None:
        """THE property of §14.7's 内容层: one edit, one synthesis."""

        lines = [DialogueLine("l1", "keep me"), DialogueLine("l2", "new words")]
        plan = plan_line_synthesis(
            lines,
            cache_dir="/cache",
            file_exists=self._existing({DialogueLine("l1", "keep me").filename}),
        )
        assert [line.line_id for line in plan.to_synthesize] == ["l2"]

    def test_an_emotion_change_alone_forces_a_new_take(self) -> None:
        """表演层: same words, new direction — that IS a new performance."""

        lines = [DialogueLine("l1", "hi", "冷淡")]
        plan = plan_line_synthesis(
            lines,
            cache_dir="/cache",
            file_exists=self._existing({DialogueLine("l1", "hi", "温柔").filename}),
        )
        assert [line.line_id for line in plan.to_synthesize] == ["l1"]

    def test_regenerate_forces_a_line_even_when_cached(self) -> None:
        """Same words on purpose: the author did not like the last take."""

        lines = [DialogueLine("l1", "hi"), DialogueLine("l2", "and me")]
        plan = plan_line_synthesis(
            lines,
            cache_dir="/cache",
            regenerate_ids=["l2"],
            file_exists=self._existing({line.filename for line in lines}),
        )
        assert [line.line_id for line in plan.to_synthesize] == ["l2"]

    def test_regenerating_an_unknown_id_is_not_an_error(self) -> None:
        lines = [DialogueLine("l1", "hi")]
        plan = plan_line_synthesis(
            lines, cache_dir="/cache", regenerate_ids=["ghost"], file_exists=self._existing(set())
        )
        assert [line.line_id for line in plan.to_synthesize] == ["l1"]


class TestPublishedManifest:
    def test_offsets_are_the_running_sum_of_measured_durations(self) -> None:
        lines = [DialogueLine("l1", "one"), DialogueLine("l2", "two")]
        plan = plan_line_synthesis(lines, cache_dir="/cache", file_exists=lambda _: True)
        manifest = plan.manifest({"l1": 1.5, "l2": 2.25})
        assert [entry["offset_seconds"] for entry in manifest] == [0, 1.5]
        assert [entry["duration_seconds"] for entry in manifest] == [1.5, 2.25]

    def test_an_unmeasured_line_poisons_the_offsets_after_it(self) -> None:
        """A gap nobody measured means every later offset would be a guess."""

        lines = [DialogueLine("l1", "one"), DialogueLine("l2", "two"), DialogueLine("l3", "three")]
        plan = plan_line_synthesis(lines, cache_dir="/cache", file_exists=lambda _: True)
        manifest = plan.manifest({"l1": 1.0, "l2": None, "l3": 2.0})
        assert manifest[0].get("offset_seconds") == 0
        assert "offset_seconds" not in manifest[1]
        assert "offset_seconds" not in manifest[2]

    def test_the_manifest_says_which_lines_this_run_rebuilt(self) -> None:
        lines = [DialogueLine("l1", "one"), DialogueLine("l2", "two")]
        plan = plan_line_synthesis(
            lines,
            cache_dir="/cache",
            regenerate_ids=["l2"],
            file_exists=lambda path: "l1" in os.path.basename(path),
        )
        manifest = plan.manifest({"l1": 1.0, "l2": 1.0})
        assert [entry["regenerated"] for entry in manifest] == [False, True]
        assert [entry["text"] for entry in manifest] == ["one", "two"]
