"""Speech alignment: recovering per-line timings from a mixed audio bed.

The C-mode foundation from the design doc (§2.3): a StepAudio 3 Gen bed is
one take mixing dialogue, SFX, ambience and BGM — the model returns no
timestamps, so "who speaks when" must be recovered afterwards. Forced
alignment does that: audio + the known lines -> per-line (start, end,
confidence).

Two engines behind one contract:

- ``WhisperXAligner`` — real forced alignment (whisper transcription +
  wav2vec2 alignment). Optional heavy dependency: imported lazily, so the
  module (and the service) load without torch/transformers installed. When
  the import fails the factory falls back — and SAYS so via ``align_source``.
- ``EstimatedSpeechAligner`` — deterministic fallback that lays the lines
  out sequentially using per-line duration estimates, scaled to the probed
  bed duration so one-take drift is absorbed. Honest label:
  ``align_source="estimated"``; confidence below the real-alignment band so
  a consumer can require better before driving lip-sync.

Confidence is never invented: an engine that cannot measure it reports a
conservative band (engineering standard §4 — queryable, never silent).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import Settings


ALIGN_SOURCE_WHISPERX = "whisperx"
ALIGN_SOURCE_ESTIMATED = "estimated"

# The estimated engine cannot hear pauses: its confidence sits in a
# conservative band (ordering is right, boundaries are not).
ESTIMATED_CONFIDENCE = 0.4
LOW_CONFIDENCE_THRESHOLD = 0.6


class SpeechAlignmentError(RuntimeError):
    """Raised when alignment fails (missing audio, engine failure)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AlignedSegment:
    """One dialogue line placed on the timeline."""

    segment_id: str
    character_id: str
    text: str
    start_time: float
    end_time: float
    confidence: float
    align_source: str
    # B-mode regeneration provenance (V0.2 §14.3: a line may be re-measured
    # without the rest of the take changing). None = not regenerated.
    regenerated: bool = False
    duration_source: str | None = None
    # Word-level timings from the forced alignment, each {"text", "start",
    # "end"} in seconds. None when the engine has none (the estimated
    # aligner): the lip-sync generator then keeps its syllable metronome.
    # This is what makes a mouth move WITH the words.
    word_timings: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "character_id": self.character_id,
            "text": self.text,
            "start_time": round(self.start_time, 3),
            "end_time": round(self.end_time, 3),
            "confidence": round(self.confidence, 3),
            "align_source": self.align_source,
            "regenerated": self.regenerated,
            "duration_source": self.duration_source,
            "word_timings": self.word_timings,
        }


class SpeechAligner(Protocol):
    """Recovers per-line timings for a known script from one audio take."""

    name: str

    def align(
        self,
        *,
        audio_path: str,
        lines: list[dict[str, str]],
        speech_only: bool = True,
    ) -> list[AlignedSegment]: ...


def probe_audio_duration_seconds(audio_path: str, ffprobe_path: str = "ffprobe") -> float | None:
    """Probe an audio file's duration (None when ffprobe cannot read it)."""

    command = [
        ffprobe_path,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        audio_path,
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    try:
        return float(payload["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        return None


class EstimatedSpeechAligner:
    """Deterministic fallback: sequential layout, scaled to the bed.

    Each line's share of the bed is its estimated duration over the sum of
    all estimates, so the layout always spans exactly the probed duration.
    Lines may carry an explicit ``start_time`` (a known cue) — those anchors
    are honoured and the remaining lines fill the gaps proportionally.
    """

    name = ALIGN_SOURCE_ESTIMATED

    def __init__(self, duration_estimator: Any | None = None) -> None:
        self._estimator = duration_estimator or _default_estimator()

    def align(
        self,
        *,
        audio_path: str,
        lines: list[dict[str, str]],
        speech_only: bool = True,
    ) -> list[AlignedSegment]:
        del speech_only  # The estimator has nothing to filter with.
        if not lines:
            return []
        estimates = [
            max(0.5, float(self._estimator(str(line.get("text") or ""))))
            for line in lines
        ]
        total_estimate = sum(estimates)
        bed_duration = probe_audio_duration_seconds(audio_path)
        span = bed_duration if bed_duration and bed_duration > 0 else total_estimate

        # Anchored lines keep their cue; unanchored ones share what's left.
        anchors: dict[int, tuple[float, float]] = {}
        for index, line in enumerate(lines):
            start = line.get("start_time")
            if start is None:
                continue
            try:
                start_value = float(start)
            except (TypeError, ValueError):
                continue
            end = line.get("end_time")
            try:
                end_value = float(end) if end is not None else start_value + estimates[index]
            except (TypeError, ValueError):
                end_value = start_value + estimates[index]
            anchors[index] = (max(0.0, start_value), max(start_value + 0.1, end_value))

        # The next anchored start after each index: unanchored lines fill up
        # to the next cue, never through it.
        anchor_starts = sorted(start for start, _ in anchors.values())
        cursor = 0.0
        segments: list[AlignedSegment] = []
        for index, line in enumerate(lines):
            if index in anchors:
                start_time, end_time = anchors[index]
            else:
                # Unanchored lines fill the room up to the NEXT cue (or the
                # end of the bed), never through a cue.
                limit = next(
                    (start for start in anchor_starts if start > cursor + 1e-6),
                    span,
                )
                available = max(0.0, min(span, limit) - cursor)
                # Share of the REMAINING room proportional to the REMAINING
                # estimates: earlier lines have already taken their share.
                remaining = sum(
                    estimates[i]
                    for i in range(index, len(lines))
                    if i not in anchors
                )
                share = available * (estimates[index] / remaining) if remaining > 0 else 0.0
                start_time = cursor
                end_time = min(span, start_time + max(0.1, share))
            cursor = max(cursor, end_time)
            segments.append(
                AlignedSegment(
                    segment_id=str(line.get("segment_id") or f"seg_{index:03d}"),
                    character_id=str(line.get("character_id") or f"char_{index}"),
                    text=str(line.get("text") or ""),
                    start_time=round(start_time, 3),
                    end_time=round(end_time, 3),
                    confidence=ESTIMATED_CONFIDENCE,
                    align_source=self.name,
                )
            )
        return segments


class WhisperXAligner:
    """Forced alignment via whisperX (optional dependency).

    whisperX is imported lazily inside ``align`` so importing this module
    never requires torch. Word-level probabilities are averaged per line for
    the segment confidence; SFX-only spans naturally land between lines.
    """

    name = ALIGN_SOURCE_WHISPERX

    def __init__(
        self,
        settings: Settings,
        *,
        model_name: str | None = None,
        device: str = "cpu",
        compute_type: str = "int8",
        batch_size: int = 8,
    ) -> None:
        self._settings = settings
        self._model_name = model_name or getattr(settings, "whisperx_model", None) or "large-v3"
        self._device = device
        self._compute_type = compute_type
        self._batch_size = batch_size
        self._model = None

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            import whisperx
        except ImportError as exc:
            raise SpeechAlignmentError(
                "alignment_engine_unavailable",
                "whisperX is not installed: uv pip install whisperx",
            ) from exc
        try:
            self._model = whisperx.load_model(
                self._model_name,
                device=self._device,
                compute_type=self._compute_type,
            )
        except Exception as exc:  # noqa: BLE001 - coded fail-closed.
            raise SpeechAlignmentError(
                "alignment_model_load_failed",
                f"whisperX model load failed: {str(exc)[:200]}",
            ) from exc
        return self._model

    def align(
        self,
        *,
        audio_path: str,
        lines: list[dict[str, str]],
        speech_only: bool = True,
    ) -> list[AlignedSegment]:
        del speech_only
        model = self._ensure_model()
        try:
            transcription = model.transcribe(audio_path, batch_size=self._batch_size)
            import whisperx

            align_model, metadata = whisperx.load_align_model(
                language_code=transcription.get("language", "zh"),
                device=self._device,
            )
            aligned = whisperx.align(
                transcription["segments"],
                align_model,
                metadata,
                audio_path,
                self._device,
                return_char_alignments=False,
            )
        except SpeechAlignmentError:
            raise
        except Exception as exc:  # noqa: BLE001 - coded fail-closed.
            raise SpeechAlignmentError(
                "alignment_failed",
                f"whisperX alignment failed: {str(exc)[:200]}",
            ) from exc

        # Map the model's word stream onto the KNOWN script lines: the lines
        # are the truth (the bed was generated from them), whisperX supplies
        # the timing. Match greedily in order.
        words: list[dict[str, Any]] = []
        for segment in aligned.get("segments", []):
            words.extend(segment.get("words", []) or [])

        segments: list[AlignedSegment] = []
        word_index = 0
        for index, line in enumerate(lines):
            text = str(line.get("text") or "")
            needed = max(1, len([c for c in text if not c.isspace()]) // 2)
            taken = words[word_index : word_index + needed]
            if not taken:
                continue
            word_index += len(taken)
            start = float(taken[0].get("start", 0.0))
            end = float(taken[-1].get("end", start + 0.1))
            probabilities = [
                float(word.get("score", 0.0))
                for word in taken
                if word.get("score") is not None
            ]
            confidence = (
                sum(probabilities) / len(probabilities) if probabilities else 0.5
            )
            segments.append(
                AlignedSegment(
                    segment_id=str(line.get("segment_id") or f"seg_{index:03d}"),
                    character_id=str(line.get("character_id") or f"char_{index}"),
                    text=text,
                    start_time=round(start, 3),
                    end_time=round(end, 3),
                    confidence=round(confidence, 3),
                    align_source=self.name,
                    # The words whisperX matched are exactly what the
                    # word-level lip-sync needs; they were computed here and
                    # thrown away. Carrying them costs nothing.
                    word_timings=[
                        {
                            "text": str(word.get("word") or "").strip(),
                            "start": round(float(word.get("start", start)), 3),
                            "end": round(float(word.get("end", end)), 3),
                        }
                        for word in taken
                    ]
                    or None,
                )
            )
        return segments


def build_speech_aligner(settings: Settings) -> SpeechAligner:
    """WhisperX when the deployment opts in and the import exists, else the
    deterministic estimated aligner (the report says which ran)."""

    if getattr(settings, "speech_alignment_engine", "estimated") == "whisperx":
        try:
            import whisperx  # noqa: F401
        except ImportError:
            return EstimatedSpeechAligner()
        return WhisperXAligner(settings)
    return EstimatedSpeechAligner()


def _default_estimator() -> Any:
    """A callable duration estimator (the aligner calls it per line)."""

    from app.services.scene3d.speech_orchestration import SimpleTTSEngine

    return SimpleTTSEngine().estimate_duration


def low_confidence_ids(segments: list[AlignedSegment]) -> list[str]:
    """Segments whose alignment is too weak to drive lip-sync silently."""

    return [
        segment.segment_id
        for segment in segments
        if segment.confidence < LOW_CONFIDENCE_THRESHOLD
    ]


def to_dialogue_lines(segments: list[AlignedSegment]) -> list[dict[str, Any]]:
    """Convert aligned segments into the dialogue-lines shape the lip-sync
    service consumes (``apply_dialogue_lip_sync``): explicit start/end times
    carry the alignment through instead of re-estimating."""

    return [
        {
            "character_id": segment.character_id,
            "text": segment.text,
            "start_time": segment.start_time,
            "end_time": segment.end_time,
            # The word timings ride along so the scene side can drive the
            # mouth per word instead of per metronome tick.
            **({"word_timings": segment.word_timings} if segment.word_timings else {}),
        }
        for segment in segments
    ]


# ---------------------------------------------------------------------------
# B-mode regeneration: a weak line is re-measured, not trusted
# ---------------------------------------------------------------------------

# A regenerated line keeps at least this much room to speak in.
MIN_REGENERATED_DURATION = 0.1


@dataclass(frozen=True)
class RegenerationPlan:
    """What the regeneration WOULD do to one segment (pure, testable)."""

    segment_id: str
    start_time: float
    end_time: float
    clamped: bool


def plan_segment_regeneration(
    segment: AlignedSegment,
    *,
    measured_duration: float,
    room_end: float | None,
) -> RegenerationPlan:
    """Plan one line's B-mode re-measure.

    The alignment's START is kept (that is what the aligner actually found);
    what gets replaced is the line's DURATION, now measured on its own instead
    of inferred from a low-confidence boundary. The new end may not run past
    ``room_end`` — the next line's start, or the bed's end for the last line —
    so a measurement longer than the room is clamped and reported. Silently
    overlapping the neighbour (or running past the take) is the one outcome
    this function refuses to produce. ``room_end=None`` means unclamped.
    """

    duration = max(MIN_REGENERATED_DURATION, float(measured_duration))
    end_time = segment.start_time + duration
    clamped = room_end is not None and end_time > room_end + 1e-6
    if clamped and room_end is not None:
        end_time = max(segment.start_time + MIN_REGENERATED_DURATION, room_end)
    return RegenerationPlan(
        segment_id=segment.segment_id,
        start_time=segment.start_time,
        end_time=round(end_time, 3),
        clamped=clamped,
    )

@dataclass(frozen=True)
class RegenerationResult:
    """The outcome of a regeneration pass (degradation reported)."""

    segments: list[AlignedSegment]
    regenerated_ids: list[str]
    duration_source: str | None
    warnings: list[str]


def regenerate_low_confidence_segments(
    segments: list[AlignedSegment],
    *,
    duration_estimator: Any,
    duration_source: str,
    threshold: float = LOW_CONFIDENCE_THRESHOLD,
    bed_duration: float | None = None,
) -> RegenerationResult:
    """Re-measure every low-confidence line on its own (B mode, V0.2 §14.3).

    ``duration_source`` names the measurement honestly: "measured" when a real
    TTS engine produced the durations, "estimated" for the deterministic
    fallback — the caller decides from its engine configuration and the report
    carries it through, so a reviewer knows which lines are actually measured.
    Overruns are clamped and reported; nothing overlaps silently.
    """

    ordered = sorted(segments, key=lambda segment: segment.start_time)
    regenerated: list[AlignedSegment] = []
    warnings: list[str] = []
    regenerated_ids: list[str] = []

    for index, segment in enumerate(ordered):
        if segment.confidence >= threshold:
            regenerated.append(segment)
            continue
        measured = duration_estimator(segment.text or "")
        # The room is the next line's start, or the bed's end for the last
        # line, or unclamped when neither is known.
        if index + 1 < len(ordered):
            room_end: float | None = ordered[index + 1].start_time
        elif bed_duration and bed_duration > 0:
            room_end = bed_duration
        else:
            room_end = None
        plan = plan_segment_regeneration(
            segment,
            measured_duration=measured,
            room_end=room_end,
        )
        if plan.clamped:
            warnings.append(
                f"台词「{segment.text[:18]}」的实测时长超出与下一句之间的间隔，"
                f"已钳制到 {plan.end_time:.1f}s（B 模式重测，来源：{duration_source}）。"
            )
        regenerated.append(
            AlignedSegment(
                segment_id=segment.segment_id,
                character_id=segment.character_id,
                text=segment.text,
                start_time=plan.start_time,
                end_time=plan.end_time,
                # The confidence stays low on purpose: re-measuring the LENGTH
                # does not make the START trustworthy. The report says so.
                confidence=segment.confidence,
                align_source=segment.align_source,
                regenerated=True,
                duration_source=duration_source,
            )
        )
        regenerated_ids.append(segment.segment_id)

    return RegenerationResult(
        segments=regenerated,
        regenerated_ids=regenerated_ids,
        duration_source=duration_source,
        warnings=warnings,
    )
