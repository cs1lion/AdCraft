"""Speech orchestration layer for lip-sync and dialogue timing.

Provides data structures and utilities for managing speech segments,
arranging them on a timeline, detecting overlaps/gaps, and generating
lip-sync keyframes that can be integrated into SceneScript character
animations.

This implements the speech-track coupling described in ADR 0003 and the
voice-driven lip-sync extension discussed during 3D previs planning.

Architecture:
    SpeechSegment (character, text, start, end, audio)
        │
        ▼
    SpeechTimeline (collection of segments, overlap/gap detection)
        │
        ▼
    LipSyncGenerator (segments → character mouth keyframes)
        │
        ▼
    SceneScript integration (merge lip-sync keyframes into character keyframes)

TTS integration is via a pluggable interface (TTSEngine); concrete
implementations can be added for specific providers (Azure, OpenAI,
ElevenLabs, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.schemas.scene_script import (
    SceneScriptRoot,
    SceneCharacter,
    CharacterKeyframe,
    SpeechBinding,
)
from app.schemas.scene_script import _RADIAN_THRESHOLD


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class SpeechSegment:
    """A single speech segment (one line of dialogue).

    Attributes:
        segment_id: Unique identifier.
        character_id: ID of the speaking character (must match SceneCharacter.id).
        text: The spoken text.
        start_time: Start time in seconds.
        end_time: End time in seconds.
        audio_path: Path to generated TTS audio (optional, filled after TTS).
        emotion: Emotion/tone hint (e.g., "happy", "angry", "calm").
        metadata: Arbitrary metadata.
    """

    segment_id: str
    character_id: str
    text: str
    start_time: float
    end_time: float
    audio_path: str | None = None
    emotion: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # Word-level timings (whisperX forced alignment), each {"text", "start",
    # "end"} in seconds. Optional: the estimated aligner has none, and the
    # lip-sync generator falls back to its syllable metronome. With them, the
    # mouth opens per WORD instead of on a metronome — the difference between
    # "the mouth flaps while sound exists" and "the mouth flaps with the
    # words" (V0.2 §14.9: the preview must be judgeable).
    word_timings: tuple[dict[str, Any], ...] | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)

    def overlaps(self, other: "SpeechSegment") -> bool:
        """Check if this segment overlaps with another."""
        return self.start_time < other.end_time and other.start_time < self.end_time

    def contains(self, time: float) -> bool:
        """Check if a time point falls within this segment."""
        return self.start_time <= time <= self.end_time


# ---------------------------------------------------------------------------
# TTS Engine interface
# ---------------------------------------------------------------------------


@runtime_checkable
class TTSEngine(Protocol):
    """Pluggable TTS engine interface.

    Concrete implementations should generate audio from text and return
    the path to the generated audio file.
    """

    def synthesize(
        self,
        text: str,
        character_id: str,
        output_path: str,
        emotion: str | None = None,
        voice_id: str | None = None,
    ) -> str:
        """Synthesize speech from text.

        Args:
            text: The text to synthesize.
            character_id: Character ID (for voice selection).
            output_path: Where to save the audio file.
            emotion: Optional emotion/tone.
            voice_id: Optional explicit voice ID.

        Returns:
            Path to the generated audio file.
        """
        ...


class SimpleTTSEngine:
    """Placeholder TTS engine that estimates duration from text length.

    This does NOT generate actual audio. It estimates speech duration based
    on text length (average 15 characters/second for English, 5 chars/sec
    for Chinese) and returns a placeholder. Use a real TTSEngine for
    production.
    """

    def __init__(self, chars_per_second: float = 8.0):
        self.chars_per_second = chars_per_second

    def estimate_duration(self, text: str) -> float:
        """Estimate speech duration in seconds.

        Estimates: CJK characters are read at roughly 4 chars/second,
        non-CJK text at roughly 15 chars/second, with a minimum of 0.5s.
        """
        # Count CJK characters vs other characters
        cjk_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - cjk_chars
        duration = cjk_chars / 4.0 + other_chars / 15.0
        return max(0.5, duration + 0.3)  # +0.3s padding

    def synthesize(
        self,
        text: str,
        character_id: str,
        output_path: str,
        emotion: str | None = None,
        voice_id: str | None = None,
    ) -> str:
        """Placeholder: returns output_path without generating audio."""
        return output_path


class StepFunTTSEngine:
    """Step Fun TTS engine for StepAudio (e.g. stepaudio-2.5-tts).

    Wraps a Step Fun HTTP endpoint that accepts
    {"model", "voice", "input"} and returns audio bytes or a base64/URL
    payload. Uses SimpleTTSEngine-style duration estimation when no audio
    file can be probed.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str = "stepaudio-2.5-tts",
        voice: str = "cixingnansheng",
        sample_rate: int = 24000,
        response_format: str = "mp3",
        chars_per_second: float = 8.0,
        timeout_seconds: float = 60.0,
    ):
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.sample_rate = sample_rate
        self.response_format = response_format
        self.timeout_seconds = timeout_seconds
        self._estimator = SimpleTTSEngine(chars_per_second=chars_per_second)

    def estimate_duration(self, text: str) -> float:
        return self._estimator.estimate_duration(text)

    def synthesize(
        self,
        text: str,
        character_id: str,
        output_path: str,
        emotion: str | None = None,
        voice_id: str | None = None,
    ) -> str:
        """POST the dialogue line to Step Fun and write the audio bytes."""
        import json
        import os
        import urllib.request

        payload = {
            "model": self.model,
            "voice": voice_id or self.voice,
            "input": text,
            "sample_rate": self.sample_rate,
            "response_format": self.response_format,
        }
        if emotion:
            # StepAudio 2.5 supports a natural-language instruction for tone
            payload["instruction"] = emotion

        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read()
        except Exception as exc:  # noqa: BLE001 - surface provider errors to caller
            raise RuntimeError(f"stepfun_tts_failed: {exc}") from exc

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "wb") as handle:
            handle.write(body)
        return output_path


# ---------------------------------------------------------------------------
# Speech Timeline
# ---------------------------------------------------------------------------


@dataclass
class TimelineIssue:
    """An issue detected in the speech timeline."""

    issue_type: str  # "overlap" | "gap" | "out_of_bounds" | "empty_text"
    description: str
    segments: list[str] = field(default_factory=list)
    time_start: float | None = None
    time_end: float | None = None


class SpeechTimeline:
    """Manages a collection of speech segments on a shared timeline.

    Provides overlap/gap detection, character-specific segment queries,
    and timeline validation.
    """

    def __init__(self, segments: list[SpeechSegment] | None = None):
        self._segments: list[SpeechSegment] = list(segments or [])

    def add(self, segment: SpeechSegment) -> None:
        """Add a segment to the timeline."""
        self._segments.append(segment)

    def remove(self, segment_id: str) -> bool:
        """Remove a segment by ID. Returns True if found and removed."""
        for i, seg in enumerate(self._segments):
            if seg.segment_id == segment_id:
                del self._segments[i]
                return True
        return False

    def get(self, segment_id: str) -> SpeechSegment | None:
        """Get a segment by ID."""
        return next((s for s in self._segments if s.segment_id == segment_id), None)

    @property
    def segments(self) -> list[SpeechSegment]:
        """All segments, sorted by start time."""
        return sorted(self._segments, key=lambda s: s.start_time)

    @property
    def total_duration(self) -> float:
        """Total timeline duration (max end time)."""
        if not self._segments:
            return 0.0
        return max(s.end_time for s in self._segments)

    def segments_for_character(self, character_id: str) -> list[SpeechSegment]:
        """Get all segments for a specific character, sorted by start time."""
        return sorted(
            [s for s in self._segments if s.character_id == character_id],
            key=lambda s: s.start_time,
        )

    def segments_at_time(self, time: float) -> list[SpeechSegment]:
        """Get all segments active at a given time."""
        return [s for s in self._segments if s.contains(time)]

    def active_character_at_time(self, time: float) -> str | None:
        """Get the character ID speaking at a given time (None if multiple or none)."""
        active = self.segments_at_time(time)
        if len(active) == 1:
            return active[0].character_id
        return None

    def detect_overlaps(self) -> list[TimelineIssue]:
        """Detect overlapping segments (same or different characters)."""
        issues = []
        sorted_segs = self.segments
        for i, seg_a in enumerate(sorted_segs):
            for seg_b in sorted_segs[i + 1:]:
                if seg_b.start_time >= seg_a.end_time:
                    break  # No more overlaps possible
                if seg_a.overlaps(seg_b):
                    same_char = seg_a.character_id == seg_b.character_id
                    issue_type = "overlap_same_character" if same_char else "overlap_cross_talk"
                    issues.append(TimelineIssue(
                        issue_type=issue_type,
                        description=(
                            f"Segments '{seg_a.segment_id}' and '{seg_b.segment_id}' overlap "
                            f"({seg_a.start_time:.1f}s-{seg_a.end_time:.1f}s vs "
                            f"{seg_b.start_time:.1f}s-{seg_b.end_time:.1f}s)"
                        ),
                        segments=[seg_a.segment_id, seg_b.segment_id],
                        time_start=max(seg_a.start_time, seg_b.start_time),
                        time_end=min(seg_a.end_time, seg_b.end_time),
                    ))
        return issues

    def detect_gaps(self, min_gap: float = 0.5) -> list[TimelineIssue]:
        """Detect gaps longer than min_gap between consecutive segments."""
        issues = []
        sorted_segs = self.segments
        for i in range(len(sorted_segs) - 1):
            gap = sorted_segs[i + 1].start_time - sorted_segs[i].end_time
            if gap > min_gap:
                issues.append(TimelineIssue(
                    issue_type="gap",
                    description=(
                        f"Gap of {gap:.1f}s between '{sorted_segs[i].segment_id}' "
                        f"(ends {sorted_segs[i].end_time:.1f}s) and "
                        f"'{sorted_segs[i+1].segment_id}' (starts {sorted_segs[i+1].start_time:.1f}s)"
                    ),
                    segments=[sorted_segs[i].segment_id, sorted_segs[i + 1].segment_id],
                    time_start=sorted_segs[i].end_time,
                    time_end=sorted_segs[i + 1].start_time,
                ))
        return issues

    def validate(self, scene_duration: float | None = None) -> list[TimelineIssue]:
        """Run all timeline validations."""
        issues = []
        issues.extend(self.detect_overlaps())
        issues.extend(self.detect_gaps())

        # Check for empty text
        for seg in self._segments:
            if not seg.text.strip():
                issues.append(TimelineIssue(
                    issue_type="empty_text",
                    description=f"Segment '{seg.segment_id}' has empty text",
                    segments=[seg.segment_id],
                ))

        # Check out of bounds
        if scene_duration is not None:
            for seg in self._segments:
                if seg.end_time > scene_duration:
                    issues.append(TimelineIssue(
                        issue_type="out_of_bounds",
                        description=(
                            f"Segment '{seg.segment_id}' ends at {seg.end_time:.1f}s, "
                            f"exceeding scene duration {scene_duration:.1f}s"
                        ),
                        segments=[seg.segment_id],
                        time_start=scene_duration,
                        time_end=seg.end_time,
                    ))

        return issues

    def to_speech_bindings(self) -> list[SpeechBinding]:
        """Convert timeline segments to SceneScript SpeechBinding list."""
        bindings = []
        for seg in self.segments:
            bindings.append(SpeechBinding(
                character=seg.character_id,
                speech_asset=f"speech_audio:{seg.segment_id}",
                mode="bound",
            ))
        return bindings


# ---------------------------------------------------------------------------
# Lip-sync keyframe generator
# ---------------------------------------------------------------------------


def _interpolated_pose_at(character: SceneCharacter, frame: int) -> tuple[list[float], float]:
    """The pose the renderer SHOWS at ``frame`` (linear interpolation).

    Same semantics as the frontend's ``characterStateAtFrame``: before the
    first keyframe it holds it, after the last it holds it, and between two it
    interpolates linearly — which is exactly how the preview and the Blender
    renderer play a SceneScript back. The lip-sync merge uses this so that
    inserting frames never changes the motion the author authored (V0.2 §14.13).

    One deliberate exception for the YAW: an interpolated angle can land in
    the schema's radian blind zone (0 < |yaw| <= 2pi, where
    ``_validate_rotation_y`` refuses the value because a tiny degree value is
    indistinguishable from a radian one). Such frames fall back to the
    at-or-before keyframe's yaw — a small turn may quantize at its very start,
    while positions (the visibly expensive channel) never do.
    """

    keyframes = sorted(character.keyframes, key=lambda keyframe: keyframe.frame)
    if not keyframes:
        return [0.0, 0.0, 0.0], 0.0
    if frame <= keyframes[0].frame:
        first = keyframes[0]
        return list(first.position), float(first.rotation_y)
    last = keyframes[-1]
    if frame >= last.frame:
        return list(last.position), float(last.rotation_y)
    for index in range(len(keyframes) - 1):
        a = keyframes[index]
        b = keyframes[index + 1]
        if a.frame <= frame <= b.frame:
            span = b.frame - a.frame or 1
            t = (frame - a.frame) / span
            position = [
                a.position[0] + (b.position[0] - a.position[0]) * t,
                a.position[1] + (b.position[1] - a.position[1]) * t,
                a.position[2] + (b.position[2] - a.position[2]) * t,
            ]
            yaw = a.rotation_y + (b.rotation_y - a.rotation_y) * t
            if 0 < abs(yaw) <= _RADIAN_THRESHOLD:
                # Schema blind zone (see docstring): hold the authored yaw.
                yaw = a.rotation_y
            return position, float(yaw)
    return list(last.position), float(last.rotation_y)


def _as_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def word_mouth_frames(
    segment: SpeechSegment,
    *,
    frame_rate: int,
    line_frame_start: int,
) -> list[tuple[int, str]]:
    """Mouth frames for one line, driven by WORD timings when they exist.

    Each word opens the mouth at its start and closes it at its end; the
    frames land inside the line's window. When the word timings are missing,
    degenerate (backwards or zero-length), or fall outside the line, this
    returns an empty list and the caller keeps its syllable metronome — the
    upgrade is strictly additive: bad data never makes the mouth worse than
    the metronome was.
    """

    if not segment.word_timings:
        return []
    fps = frame_rate if frame_rate > 0 else 30
    frames: list[tuple[int, str]] = []
    for word in segment.word_timings:
        start = _as_float(word.get("start"))
        end = _as_float(word.get("end"))
        if start is None or end is None or end <= start:
            continue
        if end <= segment.start_time or start >= segment.end_time:
            continue  # the word is not inside this line's window
        open_frame = line_frame_start + int(round((start - segment.start_time) * fps))
        close_frame = line_frame_start + int(round((end - segment.start_time) * fps))
        if close_frame <= open_frame:
            close_frame = open_frame + 1
        frames.append((max(0, open_frame), "talk"))
        frames.append((max(0, close_frame), "stand"))
    # A word gate per frame: the same frame never gets two actions.
    deduplicated: dict[int, str] = {}
    for frame, action in frames:
        deduplicated.setdefault(frame, action)
    return sorted(deduplicated.items())


class LipSyncGenerator:
    """Generates lip-sync keyframes from speech segments.

    Creates character keyframes with mouth movement based on speech timing.
    Uses a simple mouth-open/closed pattern synced to speech segments,
    with variation based on text length for natural-looking movement.

    For production-quality lip-sync, replace with a phoneme-level analyzer
    (e.g., Oculus LipSync, Rhubarb Lip Sync) that generates precise mouth
    shapes from audio.
    """

    def __init__(
        self,
        frame_rate: int = 30,
        mouth_open_action: str = "talk",
        mouth_closed_action: str = "stand",
        syllables_per_second: float = 4.0,
    ):
        self.frame_rate = frame_rate
        self.mouth_open_action = mouth_open_action
        self.mouth_closed_action = mouth_closed_action
        self.syllables_per_second = syllables_per_second

    def generate_for_character(
        self,
        character_id: str,
        timeline: SpeechTimeline,
        total_frames: int,
    ) -> list[CharacterKeyframe]:
        """Generate lip-sync keyframes for one character.

        Creates keyframes at speech boundaries and at syllable intervals
        for natural mouth movement.

        Args:
            character_id: Character to generate keyframes for.
            timeline: Speech timeline containing segments.
            total_frames: Total number of frames in the scene.

        Returns:
            List of CharacterKeyframe objects sorted by frame.
        """
        segments = timeline.segments_for_character(character_id)
        if not segments:
            return []

        keyframes: list[CharacterKeyframe] = []
        base_position = [0.0, 0.0, 0.0]  # Will be merged with existing position
        base_rotation = 0.0

        for seg in segments:
            start_frame = int(seg.start_time * self.frame_rate)
            end_frame = int(seg.end_time * self.frame_rate)
            duration_frames = max(1, end_frame - start_frame)

            # Mouth open at start
            keyframes.append(CharacterKeyframe(
                frame=max(0, start_frame),
                position=base_position,
                rotation_y=base_rotation,
                action=self.mouth_open_action,
            ))

            # Word-level variation when the alignment supplied word timings
            # (whisperX): the mouth opens and closes WITH the words instead
            # of on a metronome. Degenerate timings fall through to the
            # syllable alternation below — never worse than before.
            word_frames = word_mouth_frames(
                seg,
                frame_rate=self.frame_rate,
                line_frame_start=start_frame,
            )
            if word_frames:
                for frame, action in word_frames:
                    if frame <= max(0, start_frame):
                        continue
                    keyframes.append(CharacterKeyframe(
                        frame=frame,
                        position=base_position,
                        rotation_y=base_rotation,
                        action=action,
                    ))
                continue

            # Syllable-level variation (open/close alternation)
            num_syllables = max(1, int(seg.duration * self.syllables_per_second))
            for i in range(1, num_syllables):
                frame = start_frame + int(duration_frames * i / num_syllables)
                action = self.mouth_closed_action if i % 2 == 0 else self.mouth_open_action
                keyframes.append(CharacterKeyframe(
                    frame=min(total_frames - 1, frame),
                    position=base_position,
                    rotation_y=base_rotation,
                    action=action,
                ))

            # Mouth close at end
            keyframes.append(CharacterKeyframe(
                frame=min(total_frames - 1, end_frame),
                position=base_position,
                rotation_y=base_rotation,
                action=self.mouth_closed_action,
            ))

        # Deduplicate frames (keep last) and sort
        seen_frames: dict[int, CharacterKeyframe] = {}
        for kf in keyframes:
            seen_frames[kf.frame] = kf
        return sorted(seen_frames.values(), key=lambda kf: kf.frame)

    def merge_into_scene_script(
        self,
        scene_script: SceneScriptRoot,
        timeline: SpeechTimeline,
    ) -> SceneScriptRoot:
        """Merge lip-sync keyframes into a SceneScript.

        For each character with speech segments, generates lip-sync keyframes
        and merges them with the character's existing keyframes (preserving
        position/rotation from existing keyframes, only updating action).

        Args:
            scene_script: Original SceneScript.
            timeline: Speech timeline with segments.

        Returns:
            New SceneScriptRoot with merged lip-sync keyframes.
        """
        total_frames = scene_script.total_frames
        updated_characters = []

        for char in scene_script.characters:
            lip_keyframes = self.generate_for_character(
                char.id, timeline, total_frames
            )

            if not lip_keyframes:
                updated_characters.append(char)
                continue

            # Merge: authored keyframes first; then each lip keyframe
            # OVERWRITES the action at its frame, inheriting the pose the
            # character ALREADY HAS at that frame.
            #
            # The inheritance is the INTERPOLATED pose, not the at-or-before
            # keyframe's raw values: the renderer interpolates linearly, so a
            # lip frame that copied the keyframe at-or-before it would turn a
            # smooth walk into hold-at-origin-then-jump — an audio redo
            # silently degrading the visual layer (V0.2 §14.13: 锁 Visual 重做
            # Audio). Sitting ON the authored path means inserting frames is
            # invisible to the motion.
            #
            # The previous implementation updated a side dict for colliding
            # frames while the output list was copied from the authored
            # keyframes BEFORE the loop — so a lip frame colliding with an
            # authored keyframe (e.g. the ubiquitous frame-0 keyframe) silently
            # lost its action. Keying the merge by frame makes the overwrite
            # structural instead of incidental.
            authored = {kf.frame: kf for kf in char.keyframes}
            merged_by_frame: dict[int, CharacterKeyframe] = dict(authored)

            for lip_kf in lip_keyframes:
                position, rotation_y = _interpolated_pose_at(char, lip_kf.frame)

                merged_by_frame[lip_kf.frame] = CharacterKeyframe(
                    frame=lip_kf.frame,
                    position=position,
                    rotation_y=rotation_y,
                    action=lip_kf.action,
                )

            final_keyframes = sorted(merged_by_frame.values(), key=lambda kf: kf.frame)

            updated_char = SceneCharacter(
                id=char.id,
                type=char.type,
                appearance=char.appearance,
                # The Dramagic identity binding must SURVIVE the lip-sync
                # merge: rebuilding the character without it silently strips
                # the asset reference the consistency gate depends on.
                character_asset_id=char.character_asset_id,
                keyframes=final_keyframes,
            )
            updated_characters.append(updated_char)

        # Update speech_bindings from timeline
        speech_bindings = timeline.to_speech_bindings()

        return SceneScriptRoot(
            scene=scene_script.scene,
            characters=updated_characters,
            props=scene_script.props,
            environment=scene_script.environment,
            cameras=scene_script.cameras,
            shots=scene_script.shots,
            speech_bindings=speech_bindings,
        )


# ---------------------------------------------------------------------------
# Timeline builder from script
# ---------------------------------------------------------------------------


def build_timeline_from_script(
    dialogue_lines: list[dict[str, Any]],
    frame_rate: int = 30,
    tts_engine: TTSEngine | None = None,
) -> SpeechTimeline:
    """Build a SpeechTimeline from a list of dialogue lines.

    Each line should have: character_id, text, start_time (optional),
    end_time (optional), emotion (optional). If start/end not provided,
    estimates duration from text and appends sequentially.

    Args:
        dialogue_lines: List of dialogue line dicts.
        frame_rate: Frame rate for time calculations.
        tts_engine: TTS engine for duration estimation (uses SimpleTTSEngine if None).

    Returns:
        Populated SpeechTimeline.
    """
    if tts_engine is None:
        tts_engine = SimpleTTSEngine()

    timeline = SpeechTimeline()
    current_time = 0.0

    for i, line in enumerate(dialogue_lines):
        character_id = line.get("character_id", f"char_{i}")
        text = line.get("text", "")
        emotion = line.get("emotion")
        raw_word_timings = line.get("word_timings")
        word_timings = (
            tuple(entry for entry in raw_word_timings if isinstance(entry, dict))
            if isinstance(raw_word_timings, list)
            else None
        )

        if "start_time" in line and "end_time" in line:
            start = float(line["start_time"])
            end = float(line["end_time"])
        elif "start_time" in line:
            start = float(line["start_time"])
            duration = tts_engine.estimate_duration(text) if hasattr(tts_engine, "estimate_duration") else len(text) / 10.0
            end = start + duration
        else:
            start = current_time
            duration = tts_engine.estimate_duration(text) if hasattr(tts_engine, "estimate_duration") else len(text) / 10.0
            end = start + duration
            current_time = end + 0.2  # 0.2s gap between lines

        segment = SpeechSegment(
            segment_id=line.get("segment_id", f"seg_{i:03d}"),
            character_id=character_id,
            text=text,
            start_time=start,
            end_time=end,
            emotion=emotion,
            word_timings=word_timings,
        )
        timeline.add(segment)

    return timeline
