/**
 * Dialogue-lip-sync summary → timeline subtitle cues.
 *
 * The subtitle track must ride the SAME boundaries the lip-sync used: the
 * cues are built from the service's per-segment timings (never re-estimated
 * here — a duplicate estimator would drift captions from mouths). What this
 * module adds is only the timeline-side hygiene:
 *
 * - overlap clamping: a cue ends at the next cue's start, so simultaneous
 *   cross-talk does not stack captions;
 * - non-positive durations are dropped, never silently stretched;
 * - every drop carries a reason the caller surfaces.
 */

/** One segment as published by `apply_dialogue_lip_sync`'s summary. */
export interface AlignedSpeechSegment {
  segment_id?: string;
  character_id: string;
  text: string;
  start_time: number;
  end_time: number;
}

export interface SubtitleCueRequest {
  start_time: number;
  duration: number;
  subtitle_text: string;
  /** Speaker id + text, so the clip inspector is searchable. */
  label: string;
}

export interface SubtitleCueSkip {
  segment_id: string | null;
  reason: "empty_text" | "non_positive_duration" | "invalid_times";
}

export interface SubtitleCueBuild {
  cues: SubtitleCueRequest[];
  skipped: SubtitleCueSkip[];
}

const MIN_CUE_SECONDS = 0.05;

/**
 * Build ordered, non-overlapping cue requests from aligned segments.
 *
 * `textLimit` truncates cue text (subtitle readability); the full line stays
 * in the lip-synced scene script. Segments must arrive ordered by
 * `start_time`; the builder sorts defensively so an unsorted summary cannot
 * produce overlapping cues.
 */
export function buildSubtitleCues(
  segments: readonly AlignedSpeechSegment[],
  textLimit = 60,
): SubtitleCueBuild {
  const ordered = [...segments].sort((a, b) => a.start_time - b.start_time);
  const cues: SubtitleCueRequest[] = [];
  const skipped: SubtitleCueSkip[] = [];

  ordered.forEach((segment, index) => {
    const text = (segment.text ?? "").trim();
    if (!text) {
      skipped.push({ segment_id: segment.segment_id ?? null, reason: "empty_text" });
      return;
    }
    if (
      !Number.isFinite(segment.start_time) ||
      !Number.isFinite(segment.end_time) ||
      segment.start_time < 0 ||
      segment.end_time <= segment.start_time
    ) {
      skipped.push({ segment_id: segment.segment_id ?? null, reason: "invalid_times" });
      return;
    }
    // Clamp to the next cue's start: real speech overlaps when characters
    // talk over each other, but stacked captions are unreadable.
    const next = ordered[index + 1];
    const end = next ? Math.min(segment.end_time, next.start_time) : segment.end_time;
    const duration = end - segment.start_time;
    if (duration < MIN_CUE_SECONDS) {
      skipped.push({ segment_id: segment.segment_id ?? null, reason: "non_positive_duration" });
      return;
    }
    cues.push({
      start_time: Math.round(segment.start_time * 1000) / 1000,
      duration: Math.round(duration * 1000) / 1000,
      subtitle_text: text.slice(0, textLimit),
      label: segment.character_id ? `${segment.character_id}: ${text}`.slice(0, 120) : text.slice(0, 120),
    });
  });

  return { cues, skipped };
}
