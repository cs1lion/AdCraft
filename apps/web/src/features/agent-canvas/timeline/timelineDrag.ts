/**
 * Pure drag geometry for the timeline panel (cross-track moves + edge snapping).
 *
 * Kept free of React/DOM so the rules can be unit tested directly:
 * - {@link canMoveClipToTrack}: audio-class compatibility gate
 * - {@link collectSnapCandidates}: other clips' start/end edges
 * - {@link applyEdgeSnap}: candidate -> constraint -> nearest-valid selection
 * - {@link withClipRelocated}: optimistic cross-track state transform
 *
 * Snapping never forces a clip onto an invalid candidate: when no candidate
 * passes the constraints the caller's frame-snapped result is kept.
 */

import type {
  TimelineClipV1,
  TimelineTrackTypeV1,
  TimelineTrackV1,
} from "./timelineTypes";

export type ClipDragMode = "move" | "resize-left" | "resize-right";

const AUDIO_TRACK_TYPES = new Set<TimelineTrackTypeV1>(["voice", "bgm", "sfx"]);

/** Pointer distance (px) treated as an edge-snap zone. */
export const EDGE_SNAP_PX_THRESHOLD = 10;

export type SnapGridId = "frame" | "tenth" | "half" | "second";

/** User-selectable drag quantization; null seconds means the timeline frame. */
export const SNAP_GRID_PRESETS: ReadonlyArray<{
  id: SnapGridId;
  label: string;
  seconds: number | null;
}> = [
  { id: "frame", label: "Frame", seconds: null },
  { id: "tenth", label: "0.1s", seconds: 0.1 },
  { id: "half", label: "0.5s", seconds: 0.5 },
  { id: "second", label: "1s", seconds: 1 },
];

export function snapGridSeconds(id: SnapGridId, fps: number): number {
  const preset = SNAP_GRID_PRESETS.find((candidate) => candidate.id === id);
  return preset?.seconds ?? 1 / fps;
}

/** Round a non-negative time onto the selected grid (frame when null). */
export function snapToTimeGrid(
  value: number,
  fps: number,
  gridSeconds: number | null,
): number {
  const step = gridSeconds ?? 1 / fps;
  return Math.max(0, Math.round(value / step) * step);
}

/** Floating-point tolerant interval overlap; clips merely touching do not overlap. */
export function intervalsOverlap(
  startA: number,
  durationA: number,
  startB: number,
  durationB: number,
): boolean {
  const epsilon = 1e-6;
  return (
    startA < startB + durationB - epsilon
    && startB < startA + durationA - epsilon
  );
}

/**
 * Return the first clip on the target track overlapped by the dragged
 * interval, or null. The dragged clip itself must be filtered out by the
 * caller. Touching edges are allowed (back-to-back placement).
 */
export function findClipOverlap(
  startTime: number,
  duration: number,
  others: readonly TimelineClipV1[],
): TimelineClipV1 | null {
  return (
    others.find((clip) =>
      intervalsOverlap(
        startTime,
        duration,
        clip.start_time,
        clip.duration,
      ),
    ) ?? null
  );
}

/** IDs of every clip participating in a same-track overlap (both sides). */
export function collectOverlappingClipIds(
  tracks: readonly TimelineTrackV1[],
): ReadonlySet<string> {
  const overlaps = new Set<string>();
  for (const track of tracks) {
    const ordered = [...track.clips].sort(
      (a, b) => a.start_time - b.start_time,
    );
    for (let i = 0; i < ordered.length; i += 1) {
      for (let j = i + 1; j < ordered.length; j += 1) {
        const current = ordered[i];
        const later = ordered[j];
        if (later.start_time >= current.start_time + current.duration - 1e-6) {
          break;
        }
        overlaps.add(current.clip_id);
        overlaps.add(later.clip_id);
      }
    }
  }
  return overlaps;
}

/**
 * Cross-track compatibility rule: audio clips (voice/bgm/sfx) may only land
 * on audio tracks; visual clips (video/camera/subtitle) may move freely among
 * the non-audio tracks.
 */
export function canMoveClipToTrack(
  sourceType: TimelineTrackTypeV1,
  targetType: TimelineTrackTypeV1,
): boolean {
  return AUDIO_TRACK_TYPES.has(sourceType) === AUDIO_TRACK_TYPES.has(targetType);
}

/** All other clips' start/end times, plus any extras (e.g. playhead, 0). */
export function collectSnapCandidates(
  tracks: readonly TimelineTrackV1[],
  draggedClipId: string,
  extras: readonly number[] = [],
): number[] {
  const edges: number[] = [...extras];
  for (const track of tracks) {
    for (const clip of track.clips) {
      if (clip.clip_id === draggedClipId) continue;
      edges.push(clip.start_time);
      edges.push(clip.start_time + clip.duration);
    }
  }
  return edges;
}

export interface EdgeSnapInput {
  mode: ClipDragMode;
  /** Caller's grid-snapped / bounded candidate start. */
  startTime: number;
  /** Caller's grid-snapped / bounded candidate duration. */
  duration: number;
  fps: number;
  thresholdSeconds: number;
  candidates: readonly number[];
  /** For resize-left the dragged edge may not pass the original right edge. */
  maxStartTime?: number;
  /** Quantization for snapped results; defaults to one frame (1/fps). */
  quantizeSeconds?: number;
}

export interface EdgeSnapResult {
  startTime: number;
  duration: number;
  /** Timeline time to render the vertical guide at; null when not snapped. */
  guide: number | null;
}

interface SnapOption {
  distance: number;
  startTime: number;
  guide: number;
}

export function applyEdgeSnap(input: EdgeSnapInput): EdgeSnapResult {
  const { mode, startTime, duration, fps, thresholdSeconds, candidates } = input;
  const frame = 1 / fps;
  const quantize = input.quantizeSeconds ?? frame;
  const snapQuantized = (value: number) =>
    Math.max(0, Math.round(value / quantize) * quantize);

  const options: SnapOption[] = [];
  for (const edge of candidates) {
    if (mode === "move") {
      // Align dragged clip's left edge.
      if (edge >= 0) {
        options.push({
          distance: Math.abs(startTime - edge),
          startTime: edge,
          guide: edge,
        });
      }
      // Align dragged clip's right edge.
      const alignedStart = edge - duration;
      if (alignedStart >= 0) {
        options.push({
          distance: Math.abs(startTime + duration - edge),
          startTime: alignedStart,
          guide: edge,
        });
      }
    } else if (mode === "resize-left") {
      const withinBounds =
        edge >= 0 &&
        (input.maxStartTime === undefined || edge <= input.maxStartTime);
      if (withinBounds) {
        options.push({
          distance: Math.abs(startTime - edge),
          startTime: edge,
          guide: edge,
        });
      }
    } else {
      const newDuration = edge - startTime;
      if (newDuration >= frame) {
        options.push({
          distance: Math.abs(startTime + duration - edge),
          startTime,
          guide: edge,
        });
      }
    }
  }

  let best: SnapOption | null = null;
  for (const option of options) {
    if (
      option.distance <= thresholdSeconds &&
      (best === null || option.distance < best.distance)
    ) {
      best = option;
    }
  }

  if (best === null) {
    return { startTime, duration, guide: null };
  }

  if (mode === "resize-right") {
    const nextDuration = Math.max(frame, snapQuantized(best.guide - startTime));
    return {
      startTime,
      duration: nextDuration,
      guide: startTime + nextDuration,
    };
  }

  const nextStartTime = snapQuantized(best.startTime);
  return {
    startTime: nextStartTime,
    // resize-left duration is recomputed by the caller from original bounds.
    duration,
    guide: snapQuantized(best.guide),
  };
}

/**
 * Optimistically move a clip between tracks (or patch it on its own track).
 * Target-track clips stay ordered by start time. Returns the input array
 * untouched when the clip or target track cannot be found.
 */
export function withClipRelocated(
  tracks: readonly TimelineTrackV1[],
  clipId: string,
  targetTrackId: string,
  patch: Partial<TimelineClipV1>,
): TimelineTrackV1[] {
  const dragged = tracks
    .flatMap((track) => track.clips)
    .find((clip) => clip.clip_id === clipId);
  if (dragged === undefined) return [...tracks];
  if (!tracks.some((track) => track.track_id === targetTrackId)) {
    return [...tracks];
  }

  const moved: TimelineClipV1 = {
    ...dragged,
    ...patch,
    track_id: targetTrackId,
  };
  return tracks.map((track) => {
    if (track.track_id !== targetTrackId) {
      return {
        ...track,
        clips: track.clips.filter((clip) => clip.clip_id !== clipId),
      };
    }
    return {
      ...track,
      clips: [
        ...track.clips.filter((clip) => clip.clip_id !== clipId),
        moved,
      ].sort((a, b) => a.start_time - b.start_time),
    };
  });
}
