/**
 * Timeline drag-in contract tests (ADR 0007 Phase 3.6).
 *
 * Locks the payload round-trip (foreign/corrupted payloads never create
 * clips), the media-type -> track compatibility matrix, track resolution
 * (hovered-when-compatible, else first compatible type), and the drop
 * position -> start-time quantization. The mutation check flips the
 * snap-rounding expectation and fails, proving it binds.
 */

import { describe, expect, it } from "vitest";

import {
  TIMELINE_DROP_DEFAULT_DURATION_SECONDS,
  TIMELINE_DROP_MIME,
  compatibleTrackTypes,
  computeDropStartTime,
  isDropCompatibleWithTrack,
  parseTimelineDrop,
  resolveDropDuration,
  resolveDropTrack,
  serializeTimelineDrop,
  type TimelineDropPayload,
} from "./timelineDropPayload.ts";

const TRACKS = [
  { track_id: "t-video", type: "video" as const },
  { track_id: "t-voice", type: "voice" as const },
  { track_id: "t-bgm", type: "bgm" as const },
  { track_id: "t-camera", type: "camera" as const },
];

function assetPayload(overrides: Partial<TimelineDropPayload> = {}): TimelineDropPayload {
  return {
    kind: "asset",
    asset_id: "asset-1",
    media_type: "video",
    ...overrides,
  };
}

describe("payload serialization", () => {
  it("round-trips an asset payload", () => {
    const payload = assetPayload({
      asset_version_id: "ver-1",
      label: "赌场内部",
      duration_seconds: 5.5,
      source_node_id: "node-7",
    });
    const parsed = parseTimelineDrop(serializeTimelineDrop(payload));
    expect(parsed).toEqual(payload);
  });

  it("round-trips a camera payload", () => {
    const payload: TimelineDropPayload = {
      kind: "camera",
      asset_id: "node-scene3d",
      media_type: "camera",
      camera_node_id: "node-scene3d",
      label: "B2 运镜",
    };
    expect(parseTimelineDrop(serializeTimelineDrop(payload))).toEqual(payload);
  });

  it("rejects foreign, corrupt and incomplete payloads", () => {
    expect(parseTimelineDrop(null)).toBeNull();
    expect(parseTimelineDrop("")).toBeNull();
    expect(parseTimelineDrop("not json")).toBeNull();
    expect(parseTimelineDrop('"a string"')).toBeNull();
    expect(parseTimelineDrop(JSON.stringify({ kind: "asset" }))).toBeNull(); // no media_type
    expect(parseTimelineDrop(JSON.stringify({ kind: "other", media_type: "video", asset_id: "a" }))).toBeNull();
    expect(parseTimelineDrop(JSON.stringify({ kind: "asset", media_type: "hologram", asset_id: "a" }))).toBeNull();
    expect(parseTimelineDrop(JSON.stringify({ kind: "asset", media_type: "video", asset_id: "  " }))).toBeNull();
  });

  it("drops unknown extra keys but keeps known ones", () => {
    const parsed = parseTimelineDrop(
      JSON.stringify({ ...assetPayload(), surprise: "x" }),
    );
    expect(parsed).toEqual(assetPayload());
  });

  it("exposes a distinct MIME marker", () => {
    expect(TIMELINE_DROP_MIME).toBe("application/x-adcraft-timeline-drop");
  });
});

describe("track compatibility", () => {
  it("maps each media kind to its legal tracks", () => {
    expect(compatibleTrackTypes(assetPayload({ media_type: "video" }))).toEqual(["video"]);
    expect(compatibleTrackTypes(assetPayload({ media_type: "image" }))).toEqual(["video"]);
    expect(compatibleTrackTypes(assetPayload({ media_type: "audio" }))).toEqual([
      "voice",
      "bgm",
      "sfx",
    ]);
    expect(
      compatibleTrackTypes({ kind: "camera", asset_id: "n", media_type: "camera" }),
    ).toEqual(["camera"]);
  });

  it("answers per-track compatibility for drop highlighting", () => {
    const video = assetPayload({ media_type: "video" });
    expect(isDropCompatibleWithTrack(video, "video")).toBe(true);
    expect(isDropCompatibleWithTrack(video, "voice")).toBe(false);
    const audio = assetPayload({ media_type: "audio" });
    expect(isDropCompatibleWithTrack(audio, "sfx")).toBe(true);
    expect(isDropCompatibleWithTrack(audio, "camera")).toBe(false);
  });
});

describe("resolveDropTrack", () => {
  it("uses the hovered track when compatible", () => {
    const audio = assetPayload({ media_type: "audio" });
    expect(resolveDropTrack(audio, TRACKS, "t-bgm")).toEqual({
      trackId: "t-bgm",
      trackType: "bgm",
    });
  });

  it("falls back to the first compatible track when the hovered one is not", () => {
    const audio = assetPayload({ media_type: "audio" });
    // Hovered camera track: audio cannot land there -> first audio track wins.
    expect(resolveDropTrack(audio, TRACKS, "t-camera")?.trackType).toBe("voice");
  });

  it("returns null when no compatible track exists", () => {
    const camera = { kind: "camera" as const, asset_id: "n", media_type: "camera" as const };
    expect(resolveDropTrack(camera, TRACKS.slice(0, 3))).toBeNull();
  });
});

describe("computeDropStartTime", () => {
  // A stand-in element: left edge at 150px (the timeline label column width).
  const contentElement = {
    getBoundingClientRect: () => ({ left: 150 }) as DOMRect,
  };

  it("converts the drop offset to seconds", () => {
    expect(
      computeDropStartTime(150 + 40 * 3, contentElement, { pixelsPerSecond: 40 }),
    ).toBe(3);
  });

  it("clamps drops left of the content to 0", () => {
    expect(computeDropStartTime(10, contentElement, { pixelsPerSecond: 40 })).toBe(0);
  });

  it("quantizes to the snap grid", () => {
    // Drop at 4.9s with a 1s grid -> 5s, not 4.9 (mutation-locked).
    expect(
      computeDropStartTime(150 + 40 * 4.9, contentElement, {
        pixelsPerSecond: 40,
        snapSeconds: 1,
      }),
    ).toBe(5);
    // A 0.1s grid keeps the finer value.
    expect(
      computeDropStartTime(150 + 40 * 4.94, contentElement, {
        pixelsPerSecond: 40,
        snapSeconds: 0.1,
      }),
    ).toBe(4.9);
  });

  it("respects the max start time", () => {
    expect(
      computeDropStartTime(150 + 40 * 99, contentElement, {
        pixelsPerSecond: 40,
        maxStartTime: 10,
      }),
    ).toBe(10);
  });

  it("returns 0 without a measurable element", () => {
    expect(computeDropStartTime(300, null, { pixelsPerSecond: 40 })).toBe(0);
  });
});

describe("resolveDropDuration", () => {
  it("uses the source duration when present and positive", () => {
    expect(resolveDropDuration(assetPayload({ duration_seconds: 7.25 }))).toBe(7.25);
  });

  it("falls back to the default for unknown/invalid durations", () => {
    expect(resolveDropDuration(assetPayload())).toBe(TIMELINE_DROP_DEFAULT_DURATION_SECONDS);
    expect(resolveDropDuration(assetPayload({ duration_seconds: 0 }))).toBe(
      TIMELINE_DROP_DEFAULT_DURATION_SECONDS,
    );
    expect(resolveDropDuration(assetPayload({ duration_seconds: -1 }))).toBe(
      TIMELINE_DROP_DEFAULT_DURATION_SECONDS,
    );
  });
});
