/**
 * Timeline drag-in contract (ADR 0007 Phase 3.6: "drag assets onto tracks").
 *
 * One payload shape travels through HTML5 drag-and-drop from every source
 * (asset library cards, canvas node media) to the timeline's track drop
 * zones. Keeping the contract in one module means:
 * - sources and the drop zone agree on the MIME marker (a plain
 *   `application/json` would collide with other drags on the page);
 * - the media-type -> track-type compatibility rule is testable without a
 *   DOM;
 * - the drop position -> start-time quantization (snap grid) is one
 *   function, not duplicated per drop handler.
 */

import type { TimelineTrackTypeV1 } from "./timelineTypes.ts";

/** Drag payload kinds: a library/workflow asset, or a scene-3d camera move. */
export type TimelineDropKind = "asset" | "camera";

/** Media kinds a drop can carry. "camera" is the ADR 0007 camera track. */
export type TimelineDropMediaType = "video" | "audio" | "image" | "camera";

export interface TimelineDropPayload {
  kind: TimelineDropKind;
  /** Asset id for asset drops (required); for camera drops the scene-3d node id. */
  asset_id: string;
  asset_version_id?: string | null;
  media_type: TimelineDropMediaType;
  label?: string | null;
  duration_seconds?: number | null;
  source_node_id?: string | null;
  /** Camera drops only: the scene-3d node whose trajectory to import. */
  camera_node_id?: string | null;
}

/** Custom MIME marker: survives `dataTransfer.types` checks in dragover. */
export const TIMELINE_DROP_MIME = "application/x-adcraft-timeline-drop";

/** Track types each dropped media kind may land on, in preference order. */
const COMPATIBLE_TRACKS: Record<TimelineDropMediaType, TimelineTrackTypeV1[]> = {
  video: ["video"],
  image: ["video"],
  audio: ["voice", "bgm", "sfx"],
  camera: ["camera"],
};

export function serializeTimelineDrop(payload: TimelineDropPayload): string {
  return JSON.stringify(payload);
}

/**
 * Parse a drag payload, rejecting anything that is not ours or is missing the
 * required fields (a corrupted/foreign payload must not create a clip).
 */
export function parseTimelineDrop(raw: string | null | undefined): TimelineDropPayload | null {
  if (!raw || !raw.trim()) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;
  const record = parsed as Record<string, unknown>;
  const kind = record.kind;
  const mediaType = record.media_type;
  const assetId = record.asset_id;
  if (kind !== "asset" && kind !== "camera") return null;
  if (
    mediaType !== "video"
    && mediaType !== "audio"
    && mediaType !== "image"
    && mediaType !== "camera"
  ) {
    return null;
  }
  if (typeof assetId !== "string" || !assetId.trim()) return null;
  const payload: TimelineDropPayload = {
    kind,
    asset_id: assetId,
    media_type: mediaType,
  };
  if (typeof record.asset_version_id === "string") payload.asset_version_id = record.asset_version_id;
  if (typeof record.label === "string") payload.label = record.label;
  if (typeof record.duration_seconds === "number" && Number.isFinite(record.duration_seconds)) {
    payload.duration_seconds = record.duration_seconds;
  }
  if (typeof record.source_node_id === "string") payload.source_node_id = record.source_node_id;
  if (typeof record.camera_node_id === "string") payload.camera_node_id = record.camera_node_id;
  return payload;
}

/** Track types a payload may land on, preference order. */
export function compatibleTrackTypes(payload: TimelineDropPayload): TimelineTrackTypeV1[] {
  return COMPATIBLE_TRACKS[payload.media_type];
}

export function isDropCompatibleWithTrack(
  payload: TimelineDropPayload,
  trackType: TimelineTrackTypeV1,
): boolean {
  return compatibleTrackTypes(payload).includes(trackType);
}

export interface DropTargetResolution {
  trackId: string;
  trackType: TimelineTrackTypeV1;
}

/**
 * Pick the track a payload lands on: the hovered track when compatible,
 * otherwise the first existing track of a compatible type. Returns null when
 * the timeline has no compatible track at all (caller surfaces an error).
 */
export function resolveDropTrack(
  payload: TimelineDropPayload,
  tracks: { track_id: string; type: TimelineTrackTypeV1 }[],
  hoveredTrackId?: string | null,
): DropTargetResolution | null {
  const compatible = compatibleTrackTypes(payload);
  const hovered = hoveredTrackId
    ? tracks.find((track) => track.track_id === hoveredTrackId)
    : undefined;
  if (hovered && compatible.includes(hovered.type)) {
    return { trackId: hovered.track_id, trackType: hovered.type };
  }
  for (const trackType of compatible) {
    const match = tracks.find((track) => track.type === trackType);
    if (match) return { trackId: match.track_id, trackType: match.type };
  }
  return null;
}

export interface DropTimeOptions {
  /** Pixels per second used by the panel's time scale. */
  pixelsPerSecond: number;
  /** Quantize the start time to this many seconds (0 = no quantization). */
  snapSeconds?: number;
  /** Never place past the end of the timeline. */
  maxStartTime?: number;
}

/**
 * Convert a drop x-position (client coordinates) into a timeline start time.
 *
 * The content element's left edge is time 0; the label column is excluded by
 * measuring against the content element itself (the drop zone), not the row.
 */
export function computeDropStartTime(
  clientX: number,
  contentElement: { getBoundingClientRect: () => DOMRect } | null,
  options: DropTimeOptions,
): number {
  // Defensive: a synthesized event without coordinates must not produce NaN
  // (the API would reject it, or worse, store it).
  if (!Number.isFinite(clientX) || !contentElement || options.pixelsPerSecond <= 0) {
    return 0;
  }
  const rect = contentElement.getBoundingClientRect();
  const offsetPixels = clientX - rect.left;
  const rawSeconds = Math.max(0, offsetPixels) / options.pixelsPerSecond;
  const snap = options.snapSeconds ?? 0;
  const quantized = snap > 0 ? Math.round(rawSeconds / snap) * snap : rawSeconds;
  const rounded = Math.round(quantized * 1000) / 1000;
  if (options.maxStartTime != null) {
    return Math.min(rounded, Math.max(0, options.maxStartTime));
  }
  return rounded;
}

/** Default duration for a dropped clip when the source duration is unknown. */
export const TIMELINE_DROP_DEFAULT_DURATION_SECONDS = 3;

export function resolveDropDuration(payload: TimelineDropPayload): number {
  const duration = payload.duration_seconds;
  if (typeof duration === "number" && Number.isFinite(duration) && duration > 0) {
    return duration;
  }
  return TIMELINE_DROP_DEFAULT_DURATION_SECONDS;
}
