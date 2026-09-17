import type { CanvasRuntimeEventV2 } from "../../../types-v2.ts";

/**
 * Runtime events that can mutate timeline content server-side.
 * `node_output_published` fires the auto-clip creator after every node run,
 * which either creates a clip or refreshes an existing one in place.
 */
export const TIMELINE_REFRESH_EVENT_TYPES: ReadonlySet<string> = new Set([
  "node_output_published",
]);

/**
 * Derive a monotonic refresh nonce from the live SSE event log of one
 * workflow. The timeline panel refetches whenever the nonce grows.
 *
 * Using the maximum event {@code seq} (instead of an event count) makes
 * duplicate delivery across the chat/document streams harmless.
 */
export function timelineRefreshNonce(
  events: readonly CanvasRuntimeEventV2[],
  workflowId: string,
): number {
  if (!workflowId) {
    return 0;
  }
  let nonce = 0;
  for (const event of events) {
    if (
      event.workflow_id === workflowId
      && TIMELINE_REFRESH_EVENT_TYPES.has(event.event_type)
      && event.seq > nonce
    ) {
      nonce = event.seq;
    }
  }
  return nonce;
}
