"""Unit tests for speech_orchestration (P7: speech + lip-sync)."""

from __future__ import annotations

from typing import Any

import pytest

from app.schemas.scene_script import (
    SceneScriptRoot,
    SceneCharacter,
    CharacterKeyframe,
    CharacterAppearance,
)
from app.services.scene3d.shot_templates import generate_dialogue_shot_reverse
from app.services.scene3d.speech_orchestration import (
    SpeechSegment,
    SpeechTimeline,
    SimpleTTSEngine,
    LipSyncGenerator,
    build_timeline_from_script,
)


# ---------------------------------------------------------------------------
# SpeechSegment tests
# ---------------------------------------------------------------------------


class TestSpeechSegment:
    def test_duration(self) -> None:
        seg = SpeechSegment("s1", "char1", "hello", 0.0, 2.5)
        assert seg.duration == pytest.approx(2.5)

    def test_duration_zero(self) -> None:
        seg = SpeechSegment("s1", "char1", "hi", 1.0, 1.0)
        assert seg.duration == 0.0

    def test_overlaps_true(self) -> None:
        a = SpeechSegment("a", "c1", "hello", 0.0, 2.0)
        b = SpeechSegment("b", "c2", "world", 1.0, 3.0)
        assert a.overlaps(b)
        assert b.overlaps(a)

    def test_overlaps_false_adjacent(self) -> None:
        a = SpeechSegment("a", "c1", "hello", 0.0, 2.0)
        b = SpeechSegment("b", "c2", "world", 2.0, 4.0)
        assert not a.overlaps(b)

    def test_overlaps_false_separate(self) -> None:
        a = SpeechSegment("a", "c1", "hello", 0.0, 1.0)
        b = SpeechSegment("b", "c2", "world", 2.0, 3.0)
        assert not a.overlaps(b)

    def test_contains(self) -> None:
        seg = SpeechSegment("s1", "c1", "hello", 0.0, 2.0)
        assert seg.contains(0.0)
        assert seg.contains(1.0)
        assert seg.contains(2.0)
        assert not seg.contains(2.1)
        assert not seg.contains(-0.1)


# ---------------------------------------------------------------------------
# SimpleTTSEngine tests
# ---------------------------------------------------------------------------


class TestSimpleTTSEngine:
    def test_estimate_duration_chinese(self) -> None:
        engine = SimpleTTSEngine()
        duration = engine.estimate_duration("你好世界")
        assert duration > 0.5
        assert duration < 5.0

    def test_estimate_duration_english(self) -> None:
        engine = SimpleTTSEngine()
        duration = engine.estimate_duration("Hello world")
        assert duration > 0.5
        assert duration < 5.0

    def test_estimate_duration_empty(self) -> None:
        engine = SimpleTTSEngine()
        duration = engine.estimate_duration("")
        assert duration == pytest.approx(0.5)  # max(0.5, 0 + 0.3)

    def test_synthesize_returns_path(self) -> None:
        engine = SimpleTTSEngine()
        result = engine.synthesize("hello", "char1", "/tmp/test.wav")
        assert result == "/tmp/test.wav"


# ---------------------------------------------------------------------------
# SpeechTimeline tests
# ---------------------------------------------------------------------------


class TestSpeechTimeline:
    @pytest.fixture
    def sample_timeline(self) -> SpeechTimeline:
        tl = SpeechTimeline()
        tl.add(SpeechSegment("s1", "char1", "Hello there", 0.0, 2.0))
        tl.add(SpeechSegment("s2", "char2", "Hi yourself", 2.5, 4.0))
        tl.add(SpeechSegment("s3", "char1", "How are you?", 4.5, 6.0))
        return tl

    def test_add_and_get(self, sample_timeline: SpeechTimeline) -> None:
        seg = sample_timeline.get("s1")
        assert seg is not None
        assert seg.text == "Hello there"

    def test_get_not_found(self, sample_timeline: SpeechTimeline) -> None:
        assert sample_timeline.get("nonexistent") is None

    def test_remove(self, sample_timeline: SpeechTimeline) -> None:
        assert sample_timeline.remove("s1") is True
        assert sample_timeline.get("s1") is None
        assert sample_timeline.remove("s1") is False

    def test_segments_sorted(self, sample_timeline: SpeechTimeline) -> None:
        segs = sample_timeline.segments
        assert [s.segment_id for s in segs] == ["s1", "s2", "s3"]

    def test_total_duration(self, sample_timeline: SpeechTimeline) -> None:
        assert sample_timeline.total_duration == pytest.approx(6.0)

    def test_segments_for_character(self, sample_timeline: SpeechTimeline) -> None:
        char1_segs = sample_timeline.segments_for_character("char1")
        assert len(char1_segs) == 2
        assert [s.segment_id for s in char1_segs] == ["s1", "s3"]

    def test_segments_at_time(self, sample_timeline: SpeechTimeline) -> None:
        assert len(sample_timeline.segments_at_time(1.0)) == 1
        assert len(sample_timeline.segments_at_time(3.0)) == 1
        assert len(sample_timeline.segments_at_time(2.2)) == 0  # gap

    def test_active_character_at_time(self, sample_timeline: SpeechTimeline) -> None:
        assert sample_timeline.active_character_at_time(1.0) == "char1"
        assert sample_timeline.active_character_at_time(3.0) == "char2"
        assert sample_timeline.active_character_at_time(2.2) is None

    def test_detect_overlaps_none(self, sample_timeline: SpeechTimeline) -> None:
        assert sample_timeline.detect_overlaps() == []

    def test_detect_overlaps_found(self) -> None:
        tl = SpeechTimeline()
        tl.add(SpeechSegment("s1", "char1", "hello", 0.0, 2.0))
        tl.add(SpeechSegment("s2", "char2", "world", 1.0, 3.0))
        overlaps = tl.detect_overlaps()
        assert len(overlaps) == 1
        assert overlaps[0].issue_type == "overlap_cross_talk"

    def test_detect_overlaps_same_character(self) -> None:
        tl = SpeechTimeline()
        tl.add(SpeechSegment("s1", "char1", "hello", 0.0, 2.0))
        tl.add(SpeechSegment("s2", "char1", "world", 1.0, 3.0))
        overlaps = tl.detect_overlaps()
        assert len(overlaps) == 1
        assert overlaps[0].issue_type == "overlap_same_character"

    def test_detect_gaps_none(self) -> None:
        tl = SpeechTimeline()
        tl.add(SpeechSegment("s1", "c1", "a", 0.0, 1.0))
        tl.add(SpeechSegment("s2", "c2", "b", 1.1, 2.0))
        assert tl.detect_gaps(min_gap=0.5) == []

    def test_detect_gaps_found(self, sample_timeline: SpeechTimeline) -> None:
        gaps = sample_timeline.detect_gaps(min_gap=0.3)
        assert len(gaps) == 2  # gaps between s1-s2 and s2-s3

    def test_validate_no_issues(self, sample_timeline: SpeechTimeline) -> None:
        issues = sample_timeline.validate(scene_duration=10.0)
        # Should have gaps (0.5s) but no overlaps
        overlap_issues = [i for i in issues if "overlap" in i.issue_type]
        assert len(overlap_issues) == 0

    def test_validate_empty_text(self) -> None:
        tl = SpeechTimeline()
        tl.add(SpeechSegment("s1", "c1", "   ", 0.0, 1.0))
        issues = tl.validate()
        assert any(i.issue_type == "empty_text" for i in issues)

    def test_validate_out_of_bounds(self) -> None:
        tl = SpeechTimeline()
        tl.add(SpeechSegment("s1", "c1", "hello", 0.0, 10.0))
        issues = tl.validate(scene_duration=5.0)
        assert any(i.issue_type == "out_of_bounds" for i in issues)

    def test_to_speech_bindings(self, sample_timeline: SpeechTimeline) -> None:
        bindings = sample_timeline.to_speech_bindings()
        assert len(bindings) == 3
        assert bindings[0].character == "char1"
        assert bindings[0].mode == "bound"


# ---------------------------------------------------------------------------
# LipSyncGenerator tests
# ---------------------------------------------------------------------------


class TestLipSyncGenerator:
    @pytest.fixture
    def generator(self) -> LipSyncGenerator:
        return LipSyncGenerator(frame_rate=30)

    @pytest.fixture
    def dialogue_timeline(self) -> SpeechTimeline:
        tl = SpeechTimeline()
        tl.add(SpeechSegment("s1", "char1", "Hello there, how are you?", 0.0, 2.0))
        return tl

    def test_generate_for_character_basic(
        self, generator: LipSyncGenerator, dialogue_timeline: SpeechTimeline
    ) -> None:
        keyframes = generator.generate_for_character("char1", dialogue_timeline, 120)
        assert len(keyframes) >= 2  # At least start and end
        # First keyframe should be at or near frame 0
        assert keyframes[0].frame == 0
        # Last keyframe should be at or near frame 60 (2.0s * 30fps)
        assert keyframes[-1].frame <= 60

    def test_generate_for_character_no_segments(
        self, generator: LipSyncGenerator
    ) -> None:
        tl = SpeechTimeline()
        keyframes = generator.generate_for_character("char1", tl, 100)
        assert keyframes == []

    def test_generate_for_character_wrong_character(
        self, generator: LipSyncGenerator, dialogue_timeline: SpeechTimeline
    ) -> None:
        keyframes = generator.generate_for_character("char99", dialogue_timeline, 100)
        assert keyframes == []

    def test_generate_actions_include_talk(
        self, generator: LipSyncGenerator, dialogue_timeline: SpeechTimeline
    ) -> None:
        keyframes = generator.generate_for_character("char1", dialogue_timeline, 120)
        actions = [kf.action for kf in keyframes]
        assert "talk" in actions

    def test_merge_into_scene_script(self, generator: LipSyncGenerator) -> None:
        # Create a simple scene script with one character
        char = SceneCharacter(
            id="char1",
            type="lowpoly_human",
            appearance=CharacterAppearance(color="#FF0000"),
            keyframes=[
                CharacterKeyframe(frame=0, position=[0, 0, 0], rotation_y=0, action="stand"),
                CharacterKeyframe(frame=90, position=[1, 0, 0], rotation_y=0, action="stand"),
            ],
        )
        from app.schemas.scene_script import SceneInfo, SceneCamera, CameraKeyframe, SceneShot
        scene = SceneInfo(name="test", duration=3.0, frame_rate=30)
        cam = SceneCamera(
            id="cam1",
            shot_type="medium",
            keyframes=[CameraKeyframe(frame=0, position=[5, -5, 3], look_at=[0, 0, 1])],
        )
        shot = SceneShot(id="shot1", camera="cam1", start_frame=0, end_frame=90)
        script = SceneScriptRoot(
            scene=scene,
            characters=[char],
            cameras=[cam],
            shots=[shot],
        )

        tl = SpeechTimeline()
        tl.add(SpeechSegment("s1", "char1", "Hello", 0.5, 1.5))

        merged = generator.merge_into_scene_script(script, tl)

        # Character should have more keyframes after merge
        merged_char = merged.characters[0]
        assert len(merged_char.keyframes) > len(char.keyframes)

        # Speech bindings should be set
        assert len(merged.speech_bindings) == 1
        assert merged.speech_bindings[0].character == "char1"

    def test_merge_preserves_other_characters(self, generator: LipSyncGenerator) -> None:
        script = generate_dialogue_shot_reverse()
        tl = SpeechTimeline()
        tl.add(SpeechSegment("s1", "char1", "Hello", 0.0, 1.0))

        merged = generator.merge_into_scene_script(script, tl)
        assert len(merged.characters) == len(script.characters)


# ---------------------------------------------------------------------------
# build_timeline_from_script tests
# ---------------------------------------------------------------------------


class TestBuildTimelineFromScript:
    def test_basic(self) -> None:
        lines = [
            {"character_id": "char1", "text": "Hello there"},
            {"character_id": "char2", "text": "Hi yourself"},
        ]
        tl = build_timeline_from_script(lines)
        assert len(tl.segments) == 2
        assert tl.segments[0].character_id == "char1"
        assert tl.segments[1].character_id == "char2"

    def test_with_explicit_times(self) -> None:
        lines = [
            {"character_id": "char1", "text": "Hello", "start_time": 1.0, "end_time": 3.0},
        ]
        tl = build_timeline_from_script(lines)
        seg = tl.segments[0]
        assert seg.start_time == 1.0
        assert seg.end_time == 3.0

    def test_with_start_only(self) -> None:
        lines = [
            {"character_id": "char1", "text": "Hello", "start_time": 2.0},
        ]
        tl = build_timeline_from_script(lines)
        seg = tl.segments[0]
        assert seg.start_time == 2.0
        assert seg.end_time > 2.0

    def test_emotion_preserved(self) -> None:
        lines = [
            {"character_id": "char1", "text": "Hello", "emotion": "happy"},
        ]
        tl = build_timeline_from_script(lines)
        assert tl.segments[0].emotion == "happy"

    def test_segment_id_preserved(self) -> None:
        lines = [
            {"segment_id": "custom_id", "character_id": "char1", "text": "Hello"},
        ]
        tl = build_timeline_from_script(lines)
        assert tl.segments[0].segment_id == "custom_id"

    def test_empty_lines(self) -> None:
        tl = build_timeline_from_script([])
        assert len(tl.segments) == 0
        assert tl.total_duration == 0.0


# ---------------------------------------------------------------------------
# Word-level lip-sync: the mouth moves WITH the words (V0.2 §14.9)
# ---------------------------------------------------------------------------


def _line_with_words(
    words: list[tuple[str, float, float]],
    *,
    start_time: float = 2.0,
    segment_id: str = "seg_0",
) -> dict[str, Any]:
    end = words[-1][2] if words else start_time + 1.0
    return {
        "character_id": "lin",
        "text": "".join(word[0] for word in words),
        "start_time": start_time,
        "end_time": end,
        "word_timings": [
            {"text": text, "start": start, "end": end} for text, start, end in words
        ],
    }


class TestWordMouthFrames:
    def test_each_word_opens_and_closes_the_mouth(self) -> None:
        from app.services.scene3d.speech_orchestration import (
            SpeechSegment,
            word_mouth_frames,
        )

        segment = SpeechSegment(
            segment_id="seg_0",
            character_id="lin",
            text="你终于来了",
            start_time=2.0,
            end_time=4.0,
            word_timings=(
                {"text": "你", "start": 2.0, "end": 2.4},
                {"text": "终于", "start": 2.5, "end": 3.2},
                {"text": "来了", "start": 3.3, "end": 3.9},
            ),
        )
        frames = word_mouth_frames(segment, frame_rate=10, line_frame_start=20)
        # 2.0s -> frame 20 opens; 2.4s -> frame 24 closes; and so on per word.
        assert frames == [
            (20, "talk"),
            (24, "stand"),
            (25, "talk"),
            (32, "stand"),
            (33, "talk"),
            (39, "stand"),
        ]

    def test_missing_word_timings_yield_no_frames(self) -> None:
        from app.services.scene3d.speech_orchestration import (
            SpeechSegment,
            word_mouth_frames,
        )

        segment = SpeechSegment(
            segment_id="seg_0",
            character_id="lin",
            text="你终于来了",
            start_time=2.0,
            end_time=4.0,
        )
        assert word_mouth_frames(segment, frame_rate=30, line_frame_start=60) == []

    def test_degenerate_words_are_skipped_not_crashed(self) -> None:
        from app.services.scene3d.speech_orchestration import (
            SpeechSegment,
            word_mouth_frames,
        )

        segment = SpeechSegment(
            segment_id="seg_0",
            character_id="lin",
            text="x",
            start_time=2.0,
            end_time=4.0,
            word_timings=(
                {"text": "backwards", "start": 3.0, "end": 2.0},
                {"text": "no-times"},
                {"text": "outside", "start": 9.0, "end": 9.5},
                {"text": "good", "start": 2.2, "end": 2.6},
            ),
        )
        frames = word_mouth_frames(segment, frame_rate=10, line_frame_start=20)
        assert frames == [(22, "talk"), (26, "stand")]


class TestTimelineCarriesWordTimings:
    def test_the_timeline_keeps_the_line_word_timings(self) -> None:
        from app.services.scene3d.speech_orchestration import build_timeline_from_script

        timeline = build_timeline_from_script(
            [
                _line_with_words(
                    [("你", 2.0, 2.4), ("来了", 2.5, 2.9)],
                )
            ],
            frame_rate=30,
        )
        segment = timeline.segments[0]
        assert segment.word_timings is not None
        assert [word["text"] for word in segment.word_timings] == ["你", "来了"]

    def test_a_line_without_word_timings_stays_none(self) -> None:
        from app.services.scene3d.speech_orchestration import build_timeline_from_script

        timeline = build_timeline_from_script(
            [{"character_id": "lin", "text": "就是这里", "start_time": 0.5}],
            frame_rate=30,
        )
        assert timeline.segments[0].word_timings is None
