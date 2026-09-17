/**
 * Timeline types (ADR 0007)
 *
 * Timeline is the orchestration layer above nodes: it defines when each
 * asset (video / voice / bgm / sfx / camera / subtitle) plays on a
 * time-axis, and how clips are trimmed / transitioned / mixed.
 */

export type TimelineTrackTypeV1 =
  | "video"
  | "voice"
  | "bgm"
  | "sfx"
  | "camera"
  | "subtitle";

export type TimelineTransitionTypeV1 =
  | "none"
  | "fade"
  | "dissolve"
  | "wipe"
  | "slide";

/**
 * Sidechain auto-ducking settings persisted on the timeline.
 * `null` means auto: renderer defaults apply when both voice and BGM exist.
 */
export interface TimelineDuckingConfigV1 {
  enabled: boolean;
  threshold_db: number;
  ratio: number;
  attack_ms: number;
  release_ms: number;
  makeup_gain_db: number;
}

/** Subset of V2MediaToolchainCapabilities the timeline UI consumes. */
export interface MediaToolchainCapabilitiesV2 {
  status: "ready" | "degraded" | "unsupported";
  feature_flags: Record<string, boolean>;
  missing_requirements?: string[];
}

/**
 * A surfaced editing export degradation (event `editing_export_audio_degraded`).
 * Read straight from the workflow events REST endpoint.
 */
export interface TimelineAudioDegradationEventV1 {
  seq: number;
  created_at: string;
  payload: {
    export_id?: string;
    degradations?: string[];
  } | null;
}

export interface TimelineClipV1 {
  clip_id: string;
  track_id: string;
  start_time: number;
  duration: number;
  source_start: number | null;
  source_duration: number | null;
  asset_id: string | null;
  asset_version_id: string | null;
  source_node_id: string | null;
  fade_in: number | null;
  fade_out: number | null;
  transition_in_type: TimelineTransitionTypeV1 | null;
  transition_in_duration: number | null;
  transition_out_type: TimelineTransitionTypeV1 | null;
  transition_out_duration: number | null;
  bound_character_id: string | null;
  label: string | null;
  color: string | null;
  created_at: string;
  updated_at: string;
}

export interface TimelineTrackV1 {
  track_id: string;
  timeline_id: string;
  type: TimelineTrackTypeV1;
  name: string;
  muted: boolean;
  volume: number;
  locked: boolean;
  display_order: number;
  clips: TimelineClipV1[];
  created_at: string;
  updated_at: string;
}

export interface TimelineV1 {
  timeline_id: string;
  workflow_id: string;
  duration_seconds: number;
  fps: number;
  /** Null/absent = renderer auto-defaults; explicit object = user override. */
  ducking?: TimelineDuckingConfigV1 | null;
  tracks: TimelineTrackV1[];
  created_at: string;
  updated_at: string;
}

export interface TimelineClipCreateV1 {
  track_id: string;
  start_time: number;
  duration: number;
  asset_id?: string | null;
  asset_version_id?: string | null;
  source_node_id?: string | null;
  source_start?: number | null;
  source_duration?: number | null;
  fade_in?: number | null;
  fade_out?: number | null;
  label?: string | null;
  color?: string | null;
}

export interface TimelineClipUpdateV1 {
  start_time?: number;
  duration?: number;
  source_start?: number | null;
  source_duration?: number | null;
  fade_in?: number | null;
  fade_out?: number | null;
  transition_in_type?: TimelineTransitionTypeV1 | null;
  transition_in_duration?: number | null;
  transition_out_type?: TimelineTransitionTypeV1 | null;
  transition_out_duration?: number | null;
  bound_character_id?: string | null;
  label?: string | null;
  color?: string | null;
}

export interface TimelineClipMoveV1 {
  track_id?: string;
  start_time?: number;
}

export interface TimelineTrackUpdateV1 {
  name?: string;
  muted?: boolean;
  volume?: number;
  locked?: boolean;
  display_order?: number;
}

export interface TimelineUpdateV1 {
  duration_seconds?: number;
  fps?: number;
  /**
   * Explicit-null semantics: include `ducking: null` to reset to renderer
   * auto-defaults; omit the field entirely to leave stored settings untouched.
   */
  ducking?: TimelineDuckingConfigV1 | null;
}
