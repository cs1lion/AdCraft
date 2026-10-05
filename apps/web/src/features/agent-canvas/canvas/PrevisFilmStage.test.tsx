import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

let mockedItems: { projectAsset: ProjectAssetSummaryV2 | null }[] = [];

afterEach(() => {
  cleanup();
  mockedItems = [];
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

  it("says the scene has no shots rather than rendering an empty reel", () => {
    render(stage({ shots: [] }));
    expect(screen.getByTestId("previs-film").textContent).toContain("还没有分镜");
  });
});
