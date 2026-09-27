"""Tests for speech-driven shot advisories (dialogue-led editing).

Locks the advisory contract: every finding carries a remedy, the mid-line cut
is offered as a CHOICE (L-cut vs. cutting in the pause) rather than declared
a defect, and nothing fires on clean input.
"""

from __future__ import annotations

from app.schemas.scene_script import SceneShot
from app.services.scene3d.shot_advisor import (
    SOUND_BRIDGE_PROPOSAL_IDS,
    advise_shots_from_speech,
)
from app.services.scene3d.speech_boundaries import SPEECH_CUT_TARGET_SECONDS
from app.services.scene3d.speech_orchestration import SpeechSegment


def _shots(*pairs: tuple[str, int, int]) -> list[SceneShot]:
    return [
        SceneShot(id=shot_id, camera="cam1", start_frame=start, end_frame=end)
        for shot_id, start, end in pairs
    ]


def _line(
    character_id: str,
    text: str,
    start: float,
    end: float,
    segment_id: str = "seg_0",
) -> SpeechSegment:
    return SpeechSegment(
        segment_id=segment_id,
        character_id=character_id,
        text=text,
        start_time=start,
        end_time=end,
    )


class TestLineCrossesCut:
    def test_a_line_spanning_a_cut_is_offered_as_a_choice(self) -> None:
        """The V0.2 research: a mid-line cut is often RIGHT (L-cut), so the
        advisory states the fact and offers both readings."""

        advisories = advise_shots_from_speech(
            shots=_shots(("shot1", 0, 44), ("shot2", 45, 179)),
            segments=[_line("char_a", "就是这里，信号源在墙后面。", 0.0, 3.0)],
            frame_rate=30,
            scene_duration=6,
        )

        codes = [advisory.code for advisory in advisories]
        assert codes == ["line_crosses_cut"]
        advisory = advisories[0]
        assert advisory.shot_id == "shot1"
        assert "L-cut" in advisory.remedy  # deliberate sound-bridge reading
        assert "3.0s 之后" in advisory.remedy  # extend-the-shot alternative
        assert advisory.time_start == 0.0
        assert advisory.time_end == 3.0

    def test_a_cut_in_the_pause_gets_no_advisory(self) -> None:
        """Silence is a design element: cutting in a pause is correct."""

        advisories = advise_shots_from_speech(
            shots=_shots(("shot1", 0, 89), ("shot2", 90, 179)),
            segments=[
                _line("char_a", "第一句。", 0.0, 1.0),
                _line("char_b", "第二句。", 2.0, 2.8),
            ],
            frame_rate=30,
            scene_duration=6,
        )

        # The 3.0s boundary sits in the 1.0–2.0 pause: no finding at all.
        assert advisories == []

    def test_serializes_for_the_lipsync_summary(self) -> None:
        advisories = advise_shots_from_speech(
            shots=_shots(("shot1", 0, 44), ("shot2", 45, 179)),
            segments=[_line("char_a", "长台词", 0.0, 3.0)],
            frame_rate=30,
            scene_duration=6,
        )

        payload = advisories[0].to_dict()
        assert payload["code"] == "line_crosses_cut"
        assert payload["severity"] == "warning"  # advisory, never blocking
        assert payload["shot_id"] == "shot1"
        assert isinstance(payload["message"], str) and payload["message"]

    def test_the_remedy_names_the_proposals_that_execute_it(self) -> None:
        """V0.2 §15: the advisor is wired to the Transition Intent picker —
        the finding carries the ids of the readings that do what the remedy
        says, so the front-end can jump from 提醒 straight to 补救."""

        advisories = advise_shots_from_speech(
            shots=_shots(("shot1", 0, 44), ("shot2", 45, 179)),
            segments=[_line("char_a", "长台词", 0.0, 3.0)],
            frame_rate=30,
            scene_duration=6,
        )

        payload = advisories[0].to_dict()
        assert payload["proposal_ids"] == list(SOUND_BRIDGE_PROPOSAL_IDS)
        assert set(payload["proposal_ids"]) == {"sound_bridge", "cut_after_line", "time_jump"}

    def test_advisories_without_a_cut_remedy_carry_no_proposal_ids(self) -> None:
        """Only the crossing finding maps to cut moves; other findings keep
        their prose remedy and a empty proposal list (no dead links)."""

        advisories = advise_shots_from_speech(
            shots=_shots(("shot1", 0, 89)),
            segments=[
                # Both lines sit INSIDE the single shot (they end before its
                # 2.97s boundary), so no crossing finding fires — only the
                # cross-talk one, which has no cut remedy.
                _line("char_a", "你说什么？", 0.5, 1.2, "seg_a"),
                _line("char_b", "（同时）我说——", 0.8, 1.6, "seg_b"),
            ],
            frame_rate=30,
            scene_duration=6,
            shot_types={"cam1": "closeup"},
        )

        assert [advisory.code for advisory in advisories] == ["cross_talk_in_tight_shot"]
        for advisory in advisories:
            assert advisory.proposal_ids == ()


class TestCrossTalkInTightShot:
    def test_overlapping_speakers_in_a_closeup_are_flagged(self) -> None:
        advisories = advise_shots_from_speech(
            shots=_shots(("shot1", 0, 89)),
            segments=[
                _line("char_a", "你说什么？", 1.0, 3.0, "seg_a"),
                _line("char_b", "（同时）我说——", 2.0, 4.0, "seg_b"),
            ],
            frame_rate=30,
            scene_duration=6,
            shot_types={"cam1": "closeup"},
        )

        codes = [advisory.code for advisory in advisories]
        assert "cross_talk_in_tight_shot" in codes
        advisory = next(a for a in advisories if a.code == "cross_talk_in_tight_shot")
        assert "char_a" in advisory.message and "char_b" in advisory.message

    def test_a_wide_shot_holding_cross_talk_is_fine(self) -> None:
        advisories = advise_shots_from_speech(
            shots=_shots(("shot1", 0, 89)),
            segments=[
                _line("char_a", "你说什么？", 1.0, 3.0, "seg_a"),
                _line("char_b", "（同时）我说——", 2.0, 4.0, "seg_b"),
            ],
            frame_rate=30,
            scene_duration=6,
            shot_types={"cam1": "wide"},
        )

        assert "cross_talk_in_tight_shot" not in [a.code for a in advisories]


class TestShotWithoutSpeech:
    def test_a_silent_shot_among_speaking_ones_is_noted(self) -> None:
        # Three shots: the first and last carry dialogue, the middle one is
        # silent — with two speech-bearing shots there is a baseline.
        advisories = advise_shots_from_speech(
            shots=_shots(("shot1", 0, 89), ("shot2", 90, 149), ("shot3", 150, 179)),
            segments=[
                _line("char_a", "第一句。", 1.0, 2.0),
                _line("char_a", "第三句。", 5.5, 5.9),
            ],
            frame_rate=30,
            scene_duration=6,
        )

        codes = [advisory.code for advisory in advisories]
        assert "shot_without_speech" in codes
        advisory = next(a for a in advisories if a.code == "shot_without_speech")
        # B-roll is legitimate, so the remedy is a question, not a command.
        assert "可以保留" in advisory.remedy

    def test_a_single_speaking_shot_proves_nothing(self) -> None:
        """With one speech-bearing shot there is no baseline to compare."""

        advisories = advise_shots_from_speech(
            shots=_shots(("shot1", 0, 89), ("shot2", 90, 179)),
            segments=[_line("char_a", "只有一句。", 1.0, 2.0)],
            frame_rate=30,
            scene_duration=6,
        )

        assert "shot_without_speech" not in [a.code for a in advisories]


class TestDegenerateInputs:
    def test_no_shots_or_no_speech_is_no_advice(self) -> None:
        assert (
            advise_shots_from_speech(
                shots=[],
                segments=[_line("char_a", "x", 0, 1)],
                frame_rate=30,
                scene_duration=6,
            )
            == []
        )
        assert (
            advise_shots_from_speech(
                shots=_shots(("shot1", 0, 89)),
                segments=[],
                frame_rate=30,
                scene_duration=6,
            )
            == []
        )
        assert (
            advise_shots_from_speech(
                shots=_shots(("shot1", 0, 89)),
                segments=[_line("char_a", "x", 0, 1)],
                frame_rate=30,
                scene_duration=0,
            )
            == []
        )

    def test_silence_threshold_is_documented_and_positive(self) -> None:
        assert SPEECH_CUT_TARGET_SECONDS > 0
