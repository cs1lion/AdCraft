"""Tests for the speech ↔ cut geometry shared by advisor and proposals.

The wire between "提醒" and "补救" is structural: both consumers import
these primitives, so these tests lock the fact both depend on.
"""

from __future__ import annotations

from app.schemas.scene_script import SceneShot
from app.services.scene3d.speech_boundaries import (
    SPEECH_CUT_TARGET_SECONDS,
    first_line_crossing_boundary,
    line_crosses_boundary,
    nearest_pause,
)
from app.services.scene3d.speech_orchestration import SpeechSegment


def _segment(
    segment_id: str,
    start: float,
    end: float,
    text: str = "台词",
) -> SpeechSegment:
    return SpeechSegment(
        segment_id=segment_id,
        character_id="lin",
        text=text,
        start_time=start,
        end_time=end,
    )


class TestLineCrossesBoundary:
    def test_a_line_straddling_the_cut_crosses(self) -> None:
        segment = _segment("a", 1.9, 2.4)
        assert line_crosses_boundary(segment, 2.0) is True

    def test_a_line_entirely_before_the_cut_does_not_cross(self) -> None:
        segment = _segment("a", 0.5, 1.9)
        assert line_crosses_boundary(segment, 2.0) is False

    def test_a_line_entirely_after_the_cut_does_not_cross(self) -> None:
        segment = _segment("a", 2.1, 3.0)
        assert line_crosses_boundary(segment, 2.0) is False

    def test_a_line_ending_exactly_on_the_cut_does_not_cross(self) -> None:
        # Frame-quantised timings land on the cut by rounding alone; that is
        # not a crossing (the line finished as the picture changed).
        segment = _segment("a", 1.0, 2.0)
        assert line_crosses_boundary(segment, 2.0) is False

    def test_a_line_starting_exactly_on_the_cut_does_not_cross(self) -> None:
        segment = _segment("a", 2.0, 3.0)
        assert line_crosses_boundary(segment, 2.0) is False


class TestFirstLineCrossingBoundary:
    def test_returns_the_earliest_crossing_line(self) -> None:
        segments = [
            _segment("late", 5.0, 6.0),
            _segment("early", 1.9, 2.4),
            _segment("later", 3.1, 4.2),
        ]
        crossing = first_line_crossing_boundary(segments, 2.0)
        assert crossing is not None
        assert crossing.segment_id == "early"

    def test_returns_none_when_nothing_crosses(self) -> None:
        segments = [_segment("a", 0.0, 1.0), _segment("b", 3.0, 4.0)]
        assert first_line_crossing_boundary(segments, 2.0) is None

    def test_empty_segments_return_none(self) -> None:
        assert first_line_crossing_boundary([], 2.0) is None


class TestNearestPause:
    def test_picks_the_closest_silence_that_can_hide_a_cut(self) -> None:
        # Pause 1: 1.0–4.0s; pause 2: 4.5–7.0s. The cut sits at 4.6s, so
        # the closing edge of the second pause (4.65s) is nearest.
        segments = [
            _segment("a", 0.0, 1.0),
            _segment("b", 4.0, 4.5),
            _segment("c", 7.0, 9.0),
        ]
        pause = nearest_pause(segments, around_seconds=4.6, scene_duration=9.0)
        assert pause is not None
        assert 4.5 <= pause <= 7.0 - SPEECH_CUT_TARGET_SECONDS

    def test_a_gap_shorter_than_the_target_is_not_a_hiding_place(self) -> None:
        segments = [_segment("a", 0.0, 1.0), _segment("b", 1.2, 2.0)]
        pause = nearest_pause(segments, around_seconds=1.0, scene_duration=2.0)
        assert pause is None

    def test_the_trailing_silence_counts(self) -> None:
        segments = [_segment("a", 0.0, 1.0)]
        pause = nearest_pause(
            segments, around_seconds=1.5, scene_duration=3.0
        )
        assert pause is not None
        assert 1.0 <= pause <= 3.0 - SPEECH_CUT_TARGET_SECONDS

    def test_no_segments_no_pause(self) -> None:
        assert nearest_pause([], around_seconds=1.0, scene_duration=5.0) is None

    def test_the_pause_finder_agrees_with_a_shot_boundary_query(self) -> None:
        # The advisor asks around a shot boundary expressed in frames; the
        # finder is time-based, so callers convert once. Lock the conversion
        # contract: frame / fps.
        shot = SceneShot(id="s1", camera="cam1", start_frame=0, end_frame=138)
        segments = [_segment("a", 0.0, 1.0), _segment("b", 5.0, 6.0)]
        boundary = shot.end_frame / 30.0
        pause = nearest_pause(segments, around_seconds=boundary, scene_duration=6.0)
        assert pause is not None
        assert 1.0 <= pause <= 5.0 - SPEECH_CUT_TARGET_SECONDS
