import { describe, expect, it } from "vitest";

import {
  applyEdgeSnap,
  canMoveClipToTrack,
  collectSnapCandidates,
  EDGE_SNAP_PX_THRESHOLD,
  withClipRelocated,
} from "./timelineDrag.ts";
import type { TimelineTrackV1 } from "./timelineTypes.ts";

const fps = 30;
const thresholdSeconds = EDGE_SNAP_PX_THRESHOLD / 40;

function makeTrack(
  trackId: string,
  type: TimelineTrackV1["type"],
  clips: TimelineTrackV1["clips"] = [],
): TimelineTrackV1 {
  return {
    track_id: trackId,
    timeline_id: "tl_1",
    type,
    name: trackId,
    muted: false,
    volume: 1,
    locked: false,
    display_order: 0,
    clips,
    created_at: "2026-09-17T00:00:00Z",
    updated_at: "2026-09-17T00:00:00Z",
  };
}

function makeClip(clipId: string, trackId: string, start: number, duration: number) {
  return {
    clip_id: clipId,
    track_id: trackId,
    start_time: start,
    duration,
    source_start: null,
    source_duration: null,
    asset_id: null,
    asset_version_id: null,
    source_node_id: null,
    fade_in: null,
    fade_out: null,
    transition_in_type: null,
    transition_in_duration: null,
    transition_out_type: null,
    transition_out_duration: null,
    bound_character_id: null,
    label: null,
    color: null,
    created_at: "2026-09-17T00:00:00Z",
    updated_at: "2026-09-17T00:00:00Z",
  };
}

describe("canMoveClipToTrack", () => {
  it("allows audio clips across all audio track types", () => {
    expect(canMoveClipToTrack("voice", "bgm")).toBe(true);
    expect(canMoveClipToTrack("bgm", "sfx")).toBe(true);
    expect(canMoveClipToTrack("sfx", "voice")).toBe(true);
  });

  it("allows visual clips among video/camera/subtitle", () => {
    expect(canMoveClipToTrack("video", "camera")).toBe(true);
    expect(canMoveClipToTrack("camera", "subtitle")).toBe(true);
    expect(canMoveClipToTrack("subtitle", "video")).toBe(true);
  });

  it("blocks moves between the audio and visual classes", () => {
    expect(canMoveClipToTrack("voice", "video")).toBe(false);
    expect(canMoveClipToTrack("video", "bgm")).toBe(false);
    expect(canMoveClipToTrack("sfx", "subtitle")).toBe(false);
    expect(canMoveClipToTrack("camera", "voice")).toBe(false);
  });
});

describe("collectSnapCandidates", () => {
  it("emits start/end edges of other clips plus extras, excluding the dragged clip", () => {
    const tracks = [
      makeTrack("t_video", "video", [
        makeClip("c_drag", "t_video", 1, 2),
        makeClip("c_other", "t_video", 4, 1.5),
      ]),
      makeTrack("t_bgm", "bgm", [makeClip("c_bgm", "t_bgm", 0, 8)]),
    ];
    const edges = collectSnapCandidates(tracks, "c_drag", [0, 12]);
    expect(edges).toEqual([0, 12, 4, 5.5, 0, 8]);
  });
});

describe("applyEdgeSnap", () => {
  it("snaps a moved clip's left edge to the nearest candidate within threshold", () => {
    const result = applyEdgeSnap({
      mode: "move",
      startTime: 2.05,
      duration: 1,
      fps,
      thresholdSeconds,
      candidates: [2],
    });
    expect(result.guide).toBe(2);
    expect(result.startTime).toBe(2);
    expect(result.duration).toBe(1);
  });

  it("snaps a moved clip's right edge, deriving the new start", () => {
    const result = applyEdgeSnap({
      mode: "move",
      startTime: 6.9,
      duration: 1.2,
      fps,
      thresholdSeconds,
      candidates: [8],
    });
    expect(result.guide).toBe(8);
    expect(result.startTime).toBeCloseTo(6.8, 10);
  });

  it("keeps the frame-snapped position (no guide) beyond the threshold", () => {
    const result = applyEdgeSnap({
      mode: "move",
      startTime: 2.5,
      duration: 1,
      fps,
      thresholdSeconds,
      candidates: [2],
    });
    expect(result.guide).toBeNull();
    expect(result.startTime).toBe(2.5);
  });

  it("ignores a right-edge alignment that would push the clip before zero", () => {
    const result = applyEdgeSnap({
      mode: "move",
      startTime: 0.1,
      duration: 2,
      fps,
      thresholdSeconds: 0.5,
      candidates: [0],
    });
    // Left alignment (start -> 0) wins.
    expect(result.startTime).toBe(0);
    expect(result.guide).toBe(0);
  });

  it("snaps resize-left edges but respects the original right-edge bound", () => {
    const origStart = 2;
    const origDuration = 3;
    const result = applyEdgeSnap({
      mode: "resize-left",
      startTime: 3.05,
      duration: 1.95,
      fps,
      thresholdSeconds,
      candidates: [3],
      maxStartTime: origStart + origDuration - 1 / fps,
    });
    expect(result.startTime).toBe(3);
    expect(result.guide).toBe(3);

    // Candidate beyond the bound is rejected even if geometrically nearest.
    const blocked = applyEdgeSnap({
      mode: "resize-left",
      startTime: 4.9,
      duration: 0.1,
      fps,
      thresholdSeconds: 0.25,
      candidates: [5],
      maxStartTime: origStart + origDuration - 1 / fps,
    });
    expect(blocked.guide).toBeNull();
    expect(blocked.startTime).toBe(4.9);
  });

  it("snaps resize-right edges and enforces a one-frame minimum", () => {
    const result = applyEdgeSnap({
      mode: "resize-right",
      startTime: 1,
      duration: 2.05,
      fps,
      thresholdSeconds,
      candidates: [3],
    });
    expect(result.duration).toBe(2);
    expect(result.guide).toBe(3);
  });

  it("chooses the nearest valid candidate", () => {
    const result = applyEdgeSnap({
      mode: "move",
      startTime: 3.97,
      duration: 1,
      fps,
      thresholdSeconds,
      candidates: [3.9, 4.1],
    });
    expect(result.guide).toBe(3.9);
    expect(result.startTime).toBe(3.9);
  });
});

describe("withClipRelocated", () => {
  it("moves a clip to another track and keeps clips start-ordered", () => {
    const tracks = [
      makeTrack("t_video", "video", [
        makeClip("c_a", "t_video", 0, 2),
        makeClip("c_move", "t_video", 3, 1),
      ]),
      makeTrack("t_camera", "camera", [makeClip("c_b", "t_camera", 1, 1)]),
    ];
    const next = withClipRelocated(tracks, "c_move", "t_camera", {
      start_time: 0.5,
    });
    expect(next[0].clips.map((c) => c.clip_id)).toEqual(["c_a"]);
    expect(next[1].clips.map((c) => c.clip_id)).toEqual(["c_move", "c_b"]);
    expect(next[1].clips[0].track_id).toBe("t_camera");
    expect(next[1].clips[0].start_time).toBe(0.5);
    // Input tracks are not mutated.
    expect(tracks[0].clips).toHaveLength(2);
  });

  it("returns an unchanged copy when the clip or target track is missing", () => {
    const tracks = [makeTrack("t_video", "video", [makeClip("c_a", "t_video", 0, 2)])];
    expect(withClipRelocated(tracks, "c_missing", "t_video", {}).map((t) => t.track_id))
      .toEqual(["t_video"]);
    const unchanged = withClipRelocated(tracks, "c_a", "t_missing", {});
    expect(unchanged[0].clips).toHaveLength(1);
    expect(unchanged[0].clips[0].track_id).toBe("t_video");
  });
});
