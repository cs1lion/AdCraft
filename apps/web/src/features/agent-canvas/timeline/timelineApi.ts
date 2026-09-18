/**
 * Timeline API client (ADR 0007)
 */

import type {
  MediaToolchainCapabilitiesV2,
  TimelineAudioDegradationEventV1,
  TimelineBeatAnalysisV1,
  TimelineClipCreateV1,
  TimelineClipMoveV1,
  TimelineClipUpdateV1,
  TimelineClipV1,
  TimelineTrackUpdateV1,
  TimelineTrackV1,
  TimelineUpdateV1,
  TimelineV1,
} from "./timelineTypes.ts";

const API_BASE = "/api/v2";

/** Runtime event type emitted when ducking could not be applied at render. */
export const AUDIO_DEGRADATION_EVENT_TYPE = "editing_export_audio_degraded";

/** Degradation code emitted by the renderer when sidechaincompress is missing. */
export const AUDIO_DUCKING_UNAVAILABLE = "audio_ducking_unavailable";

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Timeline API ${response.status}: ${text}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function getTimeline(workflowId: string): Promise<TimelineV1> {
  return request<TimelineV1>(`/workflows/${workflowId}/timeline`);
}

export function updateTimeline(
  workflowId: string,
  payload: TimelineUpdateV1,
): Promise<TimelineV1> {
  return request<TimelineV1>(`/workflows/${workflowId}/timeline`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function listTracks(workflowId: string): Promise<TimelineTrackV1[]> {
  return request<TimelineTrackV1[]>(`/workflows/${workflowId}/timeline/tracks`);
}

export function updateTrack(
  workflowId: string,
  trackId: string,
  payload: TimelineTrackUpdateV1,
): Promise<TimelineTrackV1> {
  return request<TimelineTrackV1>(
    `/workflows/${workflowId}/timeline/tracks/${trackId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
}

export function createClip(
  workflowId: string,
  payload: TimelineClipCreateV1,
): Promise<TimelineClipV1> {
  return request<TimelineClipV1>(`/workflows/${workflowId}/timeline/clips`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateClip(
  workflowId: string,
  clipId: string,
  payload: TimelineClipUpdateV1,
): Promise<TimelineClipV1> {
  return request<TimelineClipV1>(
    `/workflows/${workflowId}/timeline/clips/${clipId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
}

export function moveClip(
  workflowId: string,
  clipId: string,
  payload: TimelineClipMoveV1,
): Promise<TimelineClipV1> {
  return request<TimelineClipV1>(
    `/workflows/${workflowId}/timeline/clips/${clipId}/move`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function deleteClip(workflowId: string, clipId: string): Promise<void> {
  return request<void>(`/workflows/${workflowId}/timeline/clips/${clipId}`, {
    method: "DELETE",
  });
}

// --- Beat detection (Phase 4.4) ---

/** Beat-analysis failure carrying the API error code for UI messaging. */
export class BeatAnalysisRequestError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "BeatAnalysisRequestError";
    this.status = status;
    this.code = code;
  }
}

const BEAT_ERROR_MESSAGES: Record<string, string> = {
  beat_analysis_no_asset:
    "This clip has no linked audio asset to analyze.",
  beat_analysis_too_short:
    "Beat detection needs at least 2 seconds of audio.",
  beat_analysis_indeterminate:
    "Could not detect a steady beat in this audio.",
  beat_analysis_unavailable:
    "Beat analysis is unavailable (audio decoder failed).",
  asset_not_ready:
    "The audio asset is still processing; try again shortly.",
  asset_not_found: "The audio asset for this clip was not found.",
  timeline_clip_not_found: "Clip was not found.",
};

/**
 * Detect BPM and asset-relative beat times for an audio clip.
 * Throws {@link BeatAnalysisRequestError} with a UI-ready message on failure.
 */
export async function getClipBeats(
  workflowId: string,
  clipId: string,
): Promise<TimelineBeatAnalysisV1> {
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/workflows/${workflowId}/timeline/clips/${clipId}/beats`,
      { headers: { "Content-Type": "application/json" } },
    );
  } catch {
    throw new BeatAnalysisRequestError(
      0,
      "beat_analysis_unavailable",
      BEAT_ERROR_MESSAGES.beat_analysis_unavailable,
    );
  }
  if (response.ok) {
    return (await response.json()) as TimelineBeatAnalysisV1;
  }
  let code = "beat_analysis_unavailable";
  try {
    const body = (await response.json()) as { detail?: { code?: string } };
    if (typeof body.detail?.code === "string") code = body.detail.code;
  } catch {
    // Non-JSON error body; fall back to the generic code.
  }
  throw new BeatAnalysisRequestError(
    response.status,
    code,
    BEAT_ERROR_MESSAGES[code] ?? "Beat detection failed.",
  );
}

// --- Subtitle sidecar export ---

export type SubtitleExportFormatV1 = "srt" | "ass";

/** Relative URL for downloading subtitle cues (use with an anchor download). */
export function subtitleExportUrl(
  workflowId: string,
  format: SubtitleExportFormatV1,
): string {
  return `${API_BASE}/workflows/${workflowId}/timeline/subtitles?format=${format}`;
}

// --- Media toolchain capabilities & degradation observability ---

export function getMediaToolchainCapabilities(): Promise<MediaToolchainCapabilitiesV2> {
  return request<MediaToolchainCapabilitiesV2>("/system/media-toolchain/capabilities");
}

/**
 * Fetch the most recent `editing_export_audio_degraded` events for a workflow.
 * Degradation must never be silent: the timeline panel surfaces the latest one
 * as a banner, even after the export run has finished.
 */
export async function listLatestAudioDegradations(
  workflowId: string,
  signal?: AbortSignal,
): Promise<TimelineAudioDegradationEventV1[]> {
  const response = await fetch(
    `${API_BASE}/workflows/${workflowId}/events?after_seq=0&limit=200`,
    { signal },
  );
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Timeline API ${response.status}: ${text}`);
  }
  const body = (await response.json()) as {
    events?: Array<Partial<TimelineAudioDegradationEventV1> & { event_type?: string }>;
  };
  return (body.events ?? [])
    .filter((event) => event.event_type === AUDIO_DEGRADATION_EVENT_TYPE)
    .map((event) => ({
      seq: typeof event.seq === "number" ? event.seq : 0,
      created_at: typeof event.created_at === "string" ? event.created_at : "",
      payload:
        event.payload && typeof event.payload === "object"
          ? (event.payload as TimelineAudioDegradationEventV1["payload"])
          : null,
    }));
}
