/**
 * Timeline API client (ADR 0007)
 */

import type {
  MediaToolchainCapabilitiesV2,
  TimelineAudioDegradationEventV1,
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
