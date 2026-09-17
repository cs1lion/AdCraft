import { describe, expect, it } from "vitest";

import type { CanvasRuntimeEventV2 } from "../../../types-v2.ts";
import {
  TIMELINE_REFRESH_EVENT_TYPES,
  timelineRefreshNonce,
} from "./timelineRefresh.ts";

function makeEvent(
  seq: number,
  eventType: string,
  workflowId = "wf_live",
): CanvasRuntimeEventV2 {
  return {
    seq,
    workflow_id: workflowId,
    event_type: eventType,
    project_id: null,
    execution_id: null,
    node_id: null,
    asset_id: null,
    binding_id: null,
    conversation_id: null,
    turn_id: null,
    action_id: null,
    trace_id: null,
    span_id: null,
  } as CanvasRuntimeEventV2;
}

describe("timelineRefreshNonce", () => {
  it("starts at zero without events or workflow", () => {
    expect(timelineRefreshNonce([], "wf_live")).toBe(0);
    expect(timelineRefreshNonce([makeEvent(9, "node_output_published")], "")).toBe(0);
  });

  it("tracks node_output_published as a timeline-mutating event", () => {
    expect(TIMELINE_REFRESH_EVENT_TYPES.has("node_output_published")).toBe(true);
  });

  it("uses the maximum seq of matching events in the workflow", () => {
    const events = [
      makeEvent(3, "node_ready"),
      makeEvent(5, "node_output_published"),
      makeEvent(9, "node_failed"),
      makeEvent(11, "node_output_published"),
    ];
    expect(timelineRefreshNonce(events, "wf_live")).toBe(11);
  });

  it("ignores events belonging to other workflows", () => {
    const events = [
      makeEvent(5, "node_output_published", "wf_other"),
      makeEvent(7, "node_output_published", "wf_live"),
    ];
    expect(timelineRefreshNonce(events, "wf_live")).toBe(7);
  });

  it("is duplicate-safe when chat and document streams carry the same event", () => {
    const event = makeEvent(13, "node_output_published");
    expect(timelineRefreshNonce([event, event, event], "wf_live")).toBe(13);
  });

  it("never decreases when later events are unrelated", () => {
    const events = [
      makeEvent(21, "node_output_published"),
      makeEvent(22, "execution_completed"),
      makeEvent(23, "node_ready"),
    ];
    expect(timelineRefreshNonce(events, "wf_live")).toBe(21);
  });
});
