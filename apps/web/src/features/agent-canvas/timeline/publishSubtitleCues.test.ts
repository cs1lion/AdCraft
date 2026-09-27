/**
 * publishSubtitleCues — replace-on-republish semantics.
 *
 * A second publish after an alignment re-run must REPLACE this node's earlier
 * cues, not stack duplicates. The published clips carry the scene node's id
 * as their source_node_id: that trace is what makes the difference between
 * idempotence and drift.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { createClip, deleteClip, getTimeline, listTracks } from "./timelineApi.ts";
import { publishSubtitleCues, SubtitleTrackMissingError } from "./publishSubtitleCues.ts";
import type { TimelineV1 } from "./timelineTypes.ts";

vi.mock("./timelineApi.ts", () => ({
  listTracks: vi.fn(),
  getTimeline: vi.fn(),
  createClip: vi.fn(),
  deleteClip: vi.fn(),
}));

const CUES = [
  { start_time: 0.5, duration: 1.5, subtitle_text: "第一句。", label: "lin: 第一句。" },
  { start_time: 3, duration: 1, subtitle_text: "第二句。", label: "su: 第二句。" },
];

function timelineWith(subtitleClips: { clip_id: string; source_node_id: string | null }[]) {
  return {
    tracks: [
      {
        track_id: "track_sub",
        timeline_id: "tl-1",
        type: "subtitle",
        name: "Subtitles",
        clips: subtitleClients(subtitleClips),
      },
    ],
  } as unknown as TimelineV1;
}

function subtitleClients(clips: { clip_id: string; source_node_id: string | null }[]) {
  return clips.map((clip) => ({
    clip_id: clip.clip_id,
    source_node_id: clip.source_node_id,
  }));
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listTracks).mockResolvedValue([
    { track_id: "track_sub", type: "subtitle", name: "Subtitles" },
  ] as never);
  vi.mocked(createClip).mockResolvedValue({} as never);
  vi.mocked(deleteClip).mockResolvedValue(undefined as never);
});

describe("publishSubtitleCues", () => {
  it("replaces this node's previous cues instead of stacking duplicates", async () => {
    vi.mocked(getTimeline).mockResolvedValue(
      timelineWith([
        { clip_id: "clip_old_1", source_node_id: "scene-node" },
        { clip_id: "clip_old_2", source_node_id: "scene-node" },
      ]),
    );

    const result = await publishSubtitleCues("wf-1", CUES, { sourceNodeId: "scene-node" });

    expect(vi.mocked(deleteClip).mock.calls.map((call) => call[1])).toEqual([
      "clip_old_1",
      "clip_old_2",
    ]);
    expect(result.replaced).toBe(2);
    expect(result.created).toBe(2);
    // The new clips carry the trace so the NEXT publish replaces these.
    expect(
      vi.mocked(createClip).mock.calls.map((call) => call[1].source_node_id),
    ).toEqual(["scene-node", "scene-node"]);
  });

  it("leaves other nodes' cues (and unowned clips) untouched", async () => {
    vi.mocked(getTimeline).mockResolvedValue(
      timelineWith([
        { clip_id: "clip_other", source_node_id: "another-scene-node" },
        { clip_id: "clip_manual", source_node_id: null },
        { clip_id: "clip_mine", source_node_id: "scene-node" },
      ]),
    );

    await publishSubtitleCues("wf-1", CUES, { sourceNodeId: "scene-node" });

    expect(vi.mocked(deleteClip).mock.calls.map((call) => call[1])).toEqual(["clip_mine"]);
  });

  it("creates without deleting on the first publish", async () => {
    vi.mocked(getTimeline).mockResolvedValue(timelineWith([]));

    const result = await publishSubtitleCues("wf-1", CUES, { sourceNodeId: "scene-node" });

    expect(vi.mocked(deleteClip)).not.toHaveBeenCalled();
    expect(result).toEqual({ created: 2, replaced: 0, failed: [] });
  });

  it("stays usable without a source node id (anonymous publish)", async () => {
    const result = await publishSubtitleCues("wf-1", CUES);

    expect(vi.mocked(getTimeline)).not.toHaveBeenCalled();
    expect(vi.mocked(deleteClip)).not.toHaveBeenCalled();
    expect(result.created).toBe(2);
  });

  it("reports per-cue creation failures without losing the successes", async () => {
    vi.mocked(getTimeline).mockResolvedValue(timelineWith([]));
    vi.mocked(createClip)
      .mockResolvedValueOnce({} as never)
      .mockRejectedValueOnce(new Error("Timeline API 400: invalid duration"));

    const result = await publishSubtitleCues("wf-1", CUES, { sourceNodeId: "scene-node" });

    expect(result.created).toBe(1);
    expect(result.failed).toEqual([{ index: 1, message: "Timeline API 400: invalid duration" }]);
  });

  it("still publishes fresh cues when the previous set cannot be read", async () => {
    vi.mocked(getTimeline).mockRejectedValue(new Error("network down"));

    const result = await publishSubtitleCues("wf-1", CUES, { sourceNodeId: "scene-node" });

    // The author sees the new cues; a possible stale duplicate is visible and
    // removable — never a silent failure.
    expect(result.replaced).toBe(0);
    expect(result.created).toBe(2);
    expect(vi.mocked(createClip)).toHaveBeenCalledTimes(2);
  });

  it("fails loudly when the timeline has no subtitle track", async () => {
    vi.mocked(listTracks).mockResolvedValue([
      { track_id: "track_voice", type: "voice", name: "Voice" },
    ] as never);

    await expect(
      publishSubtitleCues("wf-1", CUES, { sourceNodeId: "scene-node" }),
    ).rejects.toBeInstanceOf(SubtitleTrackMissingError);
  });
});
