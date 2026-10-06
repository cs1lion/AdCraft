import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SceneCamera, SceneScriptRoot, SceneShot } from "../../../types/scene-script";
import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import type { PublishedPrevisClipEntryV2 } from "../../../types-v2.ts";
import { PrevisFilmStage } from "./PrevisFilmStage";

// The stage resolves its own clip URLs from the project asset list; mock the
// hook so the reel's data is explicit rather than dependent on a fetch.
vi.mock("../assets/useAgentCanvasAssets.ts", () => ({
  useAgentCanvasAssets: () => ({
    items: mockedItems,
    loading: false,
    error: null,
    uploading: false,
    uploadError: null,
    retry: () => Promise.resolve(),
    uploadFiles: () => Promise.resolve([]),
    uploadFilesWithReceipts: () => Promise.resolve([]),
  }),
}));

// The reel is laid out on the timeline's video track, so the fetch is mocked
// too — what is under test is what the stage DOES with the track.
vi.mock("../timeline/timelineApi.ts", () => ({
  getTimeline: () => Promise.resolve(mockedTimeline),
}));

let mockedItems: { projectAsset: ProjectAssetSummaryV2 | null }[] = [];
/** null = the fetch failed / no timeline; the stage must still play. */
let mockedTimeline: unknown = null;

afterEach(() => {
  cleanup();
  mockedItems = [];
  mockedTimeline = null;
});

const camera = (id: string, display_name: string | null = null): SceneCamera => ({
  id,
  shot_type: "medium",
  display_name,
  keyframes: [{ frame: 0, position: [0, 0, 0], look_at: [0, 0, 1] }],
});

const shot = (id: string, camera_id: string, start_frame: number, end_frame: number): SceneShot => ({
  id,
  camera: camera_id,
  start_frame,
  end_frame,
});

const clip = (shotId: string, assetId: string): PublishedPrevisClipEntryV2 => ({
  node_id: `video-${shotId}`,
  shot_id: shotId,
  clip_asset_id: assetId,
  take_id: null,
});

const asset = (assetId: string): ProjectAssetSummaryV2 => ({
  asset_id: assetId,
  version_id: `ver-${assetId}`,
  media_type: "video",
  display_name: assetId,
}) as ProjectAssetSummaryV2;

/** The hook's project-scope items wrap the asset row; that wrapper is what the
 *  reel reads, so the fixture mirrors it exactly. */
const videoItem = (assetId: string) => ({ projectAsset: asset(assetId) });

const script: SceneScriptRoot = {
  scene: { name: "lab", environment: "indoor", lighting: "cool", duration: 6, frame_rate: 30 },
  characters: [],
  props: [],
  environment: [],
  cameras: [camera("cam_1", "双人全景"), camera("cam_2", "飞船俯瞰")],
  shots: [
    shot("shot_1", "cam_1", 0, 149),
    shot("shot_2", "cam_2", 150, 179),
  ],
  speech_bindings: [],
};

function stage(overrides: Partial<Parameters<typeof PrevisFilmStage>[0]> = {}) {
  return (
    <PrevisFilmStage
      workflowId="wf_1"
      shots={script.shots}
      cameras={script.cameras}
      clips={[]}
      frameRate={script.scene.frame_rate}
      {...overrides}
    />
  );
}

describe("PrevisFilmStage", () => {
  it("plays the published clips in shot order", () => {
    mockedItems = [videoItem("asset-1"), videoItem("asset-2")];
    render(
      stage({
        clips: [clip("shot_1", "asset-1"), clip("shot_2", "asset-2")],
      }),
    );
    const video = screen.getByTestId("previs-film-video") as HTMLVideoElement;
    expect(video.getAttribute("src")).toContain("asset-1");
    // The HUD names the cut the way the reference framework does.
    expect(screen.getByTestId("previs-film-title").textContent).toBe("机位01 | 双人全景");
    expect(screen.getByTestId("previs-film-count").textContent).toContain("1/2");
    expect(screen.getByTestId("previs-film-count").textContent).toContain("可播 2");
  });

  it("advances to the next shot when a clip ends", () => {
    mockedItems = [videoItem("asset-1"), videoItem("asset-2")];
    render(stage({ clips: [clip("shot_1", "asset-1"), clip("shot_2", "asset-2")] }));
    fireEvent.ended(screen.getByTestId("previs-film-video"));
    expect(
      (screen.getByTestId("previs-film-video") as HTMLVideoElement).getAttribute("src"),
    ).toContain("asset-2");
    expect(screen.getByTestId("previs-film-title").textContent).toBe("机位02 | 飞船俯瞰");
  });

  it("stops instead of wrapping past the last shot", () => {
    mockedItems = [videoItem("asset-2")];
    render(stage({ clips: [clip("shot_2", "asset-2")] }));
    // Start on the last shot, then let it end.
    fireEvent.click(screen.getByLabelText("跳到 机位02 | 飞船俯瞰"));
    expect(screen.getByTestId("previs-film-count").textContent).toContain("2/2");
    fireEvent.ended(screen.getByTestId("previs-film-video"));
    const play = screen.getByTestId("previs-film-play") as HTMLButtonElement;
    // Playback stops; the reel stays on the last cut rather than wrapping.
    expect(play.getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByTestId("previs-film-count").textContent).toContain("2/2");
    expect(screen.getByTestId("previs-film-title").textContent).toBe("机位02 | 飞船俯瞰");
  });

  it("names a shot whose lineage exists but bytes are still resolving", () => {
    mockedItems = [];
    render(stage({ clips: [clip("shot_1", "asset-1")] }));
    expect(screen.getByTestId("previs-film-placeholder").textContent).toContain(
      "血缘已在，素材解析中",
    );
    expect(screen.queryByTestId("previs-film-video")).toBeNull();
  });

  it("counts unpublished shots in the reel rather than hiding them", () => {
    mockedItems = [videoItem("asset-1")];
    render(stage({ clips: [clip("shot_1", "asset-1")] }));
    // Two shots, one playable: the gap must be stated, not papered over.
    expect(screen.getByTestId("previs-film-notice").textContent).toContain("1 个镜头还没有预演片段");
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[1].getAttribute("data-has-clip")).toBe("false");
  });

  it("seeks the owning playhead into the shot it is showing", () => {
    mockedItems = [videoItem("asset-1"), videoItem("asset-2")];
    const onSeekFrame = vi.fn();
    render(
      stage({ clips: [clip("shot_1", "asset-1"), clip("shot_2", "asset-2")], onSeekFrame }),
    );
    // Mount lands on shot_1's first frame.
    expect(onSeekFrame).toHaveBeenCalledWith(0);
    fireEvent.ended(screen.getByTestId("previs-film-video"));
    expect(onSeekFrame).toHaveBeenCalledWith(150);
  });

  it("offers per-shot transport", () => {
    mockedItems = [videoItem("asset-1"), videoItem("asset-2")];
    render(stage({ clips: [clip("shot_1", "asset-1"), clip("shot_2", "asset-2")] }));
    const prev = screen.getByTestId("previs-film-prev") as HTMLButtonElement;
    const next = screen.getByTestId("previs-film-next") as HTMLButtonElement;
    expect(prev.disabled).toBe(true);
    fireEvent.click(next);
    expect(screen.getByTestId("previs-film-title").textContent).toBe("机位02 | 飞船俯瞰");
    expect((screen.getByTestId("previs-film-prev") as HTMLButtonElement).disabled).toBe(false);
  });

  it("falls back to the camera id when the camera is not in the script", () => {
    // A shot pointing at a camera that was removed must not crash the reel.
    const orphanShots: SceneShot[] = [{ id: "shot_x", camera: "cam_gone", start_frame: 0, end_frame: 9 }];
    render(stage({ shots: orphanShots }));
    expect(screen.getByTestId("previs-film-title").textContent).toBe("cam_gone");
  });

  it("draws a fixed second ruler, independent of the shots", async () => {
    // The reference axis reads 0s/5s/10s…/25s. It is a pacing ruler: it does
    // not move when shots are added, so the author can tell "this cut lands on
    // second 10" without knowing how many cuts there are.
    mockedItems = [videoItem("asset-1"), videoItem("asset-2")];
    mockedTimeline = null;
    render(stage({ clips: [clip("shot_1", "asset-1"), clip("shot_2", "asset-2")] }));

    const ruler = await screen.findByTestId("previs-film-ruler");
    const ticks = ruler.querySelectorAll(".previs-film__ruler-tick");
    const labels = Array.from(ticks).map((tick) => tick.textContent);
    // shot_1 is 5s (frames 0..149), shot_2 is 1s (150..179) → the film is 6s.
    // Ruler = 0, 5, then the closing 6 (a partial step still gets a label, or
    // the last second of the film has no tick at all).
    expect(labels).toEqual(["0s", "5s", "6s"]);
  });

  it("labels each shot with its own duration", async () => {
    // 00:02 / 00:04 style labels in the reference: a cut reads as a LENGTH.
    // Position alone makes two shots and six shots look equally fast.
    mockedItems = [videoItem("asset-1"), videoItem("asset-2")];
    mockedTimeline = null;
    render(stage({ clips: [clip("shot_1", "asset-1"), clip("shot_2", "asset-2")] }));

    const durations = await screen.findAllByTestId("previs-film-reel-duration");
    const byText = new Map(durations.map((node) => [node.textContent, node]));
    // shot_1 is frames 0..149 = 150 frames = 5s; shot_2 is 150..179 = 1s.
    expect(byText.has("5s")).toBe(true);
    expect(byText.has("1s")).toBe(true);
  });

  it("says the scene has no shots rather than rendering an empty reel", () => {
    render(stage({ shots: [] }));
    expect(screen.getByTestId("previs-film").textContent).toContain("还没有分镜");
  });
});

describe("PrevisFilmStage — the reel as a time axis", () => {
  /** A timeline whose video track puts shot 2 BEFORE shot 1. Publish order was
   *  shot 2 first; the assembled film must still open on shot 1. */
  function timelineWithVideoTrack() {
    return {
      timeline_id: "tl_1",
      version: 1,
      duration_seconds: 9,
      aspect_ratio: "16:9",
      resolution: { width: 1280, height: 720 },
      fps: 30,
      workflow_id: "wf_1",
      tracks: [
        {
          track_id: "track_video",
          timeline_id: "tl_1",
          type: "video",
          name: "Video",
          muted: false,
          volume: 1,
          locked: false,
          display_order: 1,
          clips: [
            {
              clip_id: "clip_shot2",
              track_id: "track_video",
              start_time: 6,
              duration: 3,
              // The publisher's clip node is the lineage back to the shot.
              source_node_id: "video-shot_2",
              source_start: 0,
              source_duration: 3,
              asset_id: "asset-2",
              asset_version_id: "ver-asset-2",
              fade_in: null,
              fade_out: null,
              transition_in_type: null,
              transition_in_duration: null,
              transition_out_type: null,
              transition_out_duration: null,
              bound_character_id: null,
              label: "预演片段 · shot 2",
              color: null,
              subtitle_text: null,
              subtitle_style: null,
              created_at: "2026-10-05T00:00:00+00:00",
              updated_at: "2026-10-05T00:00:00+00:00",
            },
            {
              clip_id: "clip_shot1",
              track_id: "track_video",
              start_time: 0,
              duration: 6,
              source_node_id: "video-shot_1",
              source_start: 0,
              source_duration: 6,
              asset_id: "asset-1",
              asset_version_id: "ver-asset-1",
              fade_in: null,
              fade_out: null,
              transition_in_type: null,
              transition_in_duration: null,
              transition_out_type: null,
              transition_out_duration: null,
              bound_character_id: null,
              label: "预演片段 · shot 1",
              color: null,
              subtitle_text: null,
              subtitle_style: null,
              created_at: "2026-10-05T00:00:00+00:00",
              updated_at: "2026-10-05T00:00:00+00:00",
            },
          ],
        },
      ],
      ducking: null,
      created_at: "2026-10-05T00:00:00+00:00",
      updated_at: "2026-10-05T00:00:00+00:00",
    };
  }

  it("lays each shot out at the position the timeline gave it", async () => {
    mockedItems = [videoItem("asset-1"), videoItem("asset-2")];
    mockedTimeline = timelineWithVideoTrack();
    render(
      stage({ clips: [clip("shot_1", "asset-1"), clip("shot_2", "asset-2")] }),
    );

    const items = await screen.findAllByRole("listitem");
    const byLabel = new Map(
      items.map((item) => [
        item.querySelector(".previs-film__reel-label")?.textContent,
        (item as HTMLElement).style.left,
      ]),
    );
    // 40px/秒. Shot 2 was PUBLISHED first but the timeline placed it at 6s, so
    // the axis reads in play order, not publish order.
    expect(byLabel.get("机位02 | 飞船俯瞰")).toBe("240px");
    expect(byLabel.get("机位01 | 双人全景")).toBe("0px");
    expect(
      (screen.getByTestId("previs-film-reel") as HTMLElement).dataset.totalSeconds,
    ).toBe("9.00");
  });

  it("marks shots that have not reached the timeline yet", async () => {
    mockedItems = [videoItem("asset-1")];
    // Only shot 1 is on the track.
    mockedTimeline = timelineWithVideoTrack();
    const track = (mockedTimeline as { tracks: { clips: unknown[] }[] }).tracks[0]!;
    track.clips = track.clips.filter((entry) => (entry as { clip_id: string }).clip_id === "clip_shot1");
    render(stage({ clips: [clip("shot_1", "asset-1"), clip("shot_2", "asset-2")] }));

    const items = await screen.findAllByRole("listitem");
    const onTrack = items.find((item) =>
      item.querySelector(".previs-film__reel-label")?.textContent?.includes("机位01"),
    );
    const offTrack = items.find((item) =>
      item.querySelector(".previs-film__reel-label")?.textContent?.includes("机位02"),
    );
    expect(onTrack?.getAttribute("data-on-timeline")).toBe("true");
    expect(offTrack?.getAttribute("data-on-timeline")).toBe("false");
  });

  it("still plays when the timeline cannot be read", async () => {
    // No timeline: the stage falls back to the shot's own frame start rather
    // than packing everything against zero.
    mockedItems = [videoItem("asset-1"), videoItem("asset-2")];
    mockedTimeline = null;
    render(stage({ clips: [clip("shot_1", "asset-1"), clip("shot_2", "asset-2")] }));

    await waitFor(() => expect(screen.getByTestId("previs-film-video")).toBeTruthy());
    const items = screen.getAllByRole("listitem");
    const byLabel = new Map(
      items.map((item) => [
        item.querySelector(".previs-film__reel-label")?.textContent,
        (item as HTMLElement).style.left,
      ]),
    );
    // shot_2 starts at frame 150 of 30fps = 5s.
    expect(byLabel.get("机位02 | 飞船俯瞰")).toBe("200px");
    expect(byLabel.get("机位01 | 双人全景")).toBe("0px");
  });
});
