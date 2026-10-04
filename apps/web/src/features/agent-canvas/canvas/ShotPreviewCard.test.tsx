import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script";
import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import type { PublishedPrevisClipEntryV2 } from "../../../types-v2.ts";
import { ShotPreviewCard } from "./ShotPreviewCard";
import { cameraLabel, shotForFrame } from "./shotLabels";

// vitest runs without `globals`, so Testing Library's automatic cleanup never
// registers itself — every render would otherwise leak into the next case.
afterEach(cleanup);

const script: SceneScriptRoot = {
  scene: { name: "lab", environment: "indoor", lighting: "cool", duration: 6, frame_rate: 30 },
  characters: [],
  props: [],
  environment: [],
  cameras: [
    { id: "cam_1", shot_type: "medium", display_name: "双人全景", keyframes: [{ frame: 0, position: [0, 0, 0], look_at: [0, 0, 1] }] },
    { id: "cam_2", shot_type: "closeup", keyframes: [{ frame: 150, position: [0, 0, 0], look_at: [0, 0, 1] }] },
  ],
  shots: [
    { id: "shot_1", camera: "cam_1", start_frame: 0, end_frame: 149 },
    { id: "shot_2", camera: "cam_2", start_frame: 150, end_frame: 179 },
  ],
  speech_bindings: [],
};

const clip = (shotId: string): PublishedPrevisClipEntryV2 => ({
  node_id: `video-${shotId}`,
  shot_id: shotId,
  clip_asset_id: `asset-${shotId}`,
  take_id: null,
});

function card(overrides: Partial<Parameters<typeof ShotPreviewCard>[0]> = {}) {
  const shot = shotForFrame(script, 0);
  return (
    <ShotPreviewCard
      label={cameraLabel(script.cameras[0], 0)}
      shot={shot}
      frameRate={script.scene.frame_rate}
      clip={null}
      active
      {...overrides}
    />
  );
}

describe("ShotPreviewCard", () => {
  it("titles itself with the shot's label and its duration", () => {
    render(card());
    expect(screen.getByTestId("shot-preview-card-title").textContent).toContain("机位01 | 双人全景");
    // shot_1 spans frames 0..149 at 30fps = 5s.
    expect(screen.getByTestId("shot-preview-card-duration").textContent).toContain("00:05");
  });

  it("says the shot has no clip yet and offers the publish action", () => {
    const onPublish = vi.fn();
    render(card({ onPublish }));
    expect(screen.getByTestId("shot-preview-card-empty")).toBeTruthy();
    expect(screen.queryByTestId("shot-preview-card-video")).toBeNull();
    fireEvent.click(screen.getByTestId("shot-preview-card-publish"));
    expect(onPublish).toHaveBeenCalledTimes(1);
  });

  it("labels the publish button with the shot it would publish", () => {
    render(card({ onPublish: vi.fn() }));
    expect(screen.getByTestId("shot-preview-card-publish").textContent).toContain(
      "发布机位01 | 双人全景",
    );
  });

  it("hides the publish button when nobody can be called", () => {
    render(card());
    expect(screen.queryByTestId("shot-preview-card-publish")).toBeNull();
  });

  it("disables the publish button mid-flight so a shot cannot be published twice", () => {
    render(card({ onPublish: vi.fn(), publishing: true }));
    const publish = screen.getByTestId("shot-preview-card-publish") as HTMLButtonElement;
    expect(publish.disabled).toBe(true);
    expect(publish.textContent).toContain("发布中…");
  });

  it("plays the clip once its asset resolves", () => {
    const asset = {
      asset_id: "asset-shot_1",
      version_id: "ver_1",
      media_type: "video",
      display_name: "shot_1 previs",
    } as ProjectAssetSummaryV2;
    render(card({ clip: clip("shot_1"), asset }));
    const video = screen.getByTestId("shot-preview-card-video") as HTMLVideoElement;
    expect(video).toBeTruthy();
    // The content endpoint is the immutable AssetVersion path the rest of the
    // canvas uses, so a re-published clip cannot be served from a stale URL.
    expect(video.getAttribute("src")).toContain("asset-shot_1");
    expect(video.getAttribute("src")).toContain("ver_1");
    expect(screen.queryByTestId("shot-preview-card-empty")).toBeNull();
  });

  it("says the clip is resolving rather than pretending there is none", () => {
    // clip present, asset not yet loaded: the lineage exists, the bytes do not.
    // Claiming "no clip" here would invite a duplicate publish.
    render(card({ clip: clip("shot_1"), asset: null }));
    expect(screen.getByTestId("shot-preview-card-empty").textContent).toContain("预演片段解析中");
    expect(screen.queryByTestId("shot-preview-card-publish")).toBeNull();
  });

  it("marks itself active so the author knows which shot the playhead is in", () => {
    render(card({ active: true }));
    expect(screen.getByTestId("shot-preview-card").getAttribute("data-active")).toBe("true");
  });

  it("survives a shot that resolves to nothing", () => {
    // A script whose shots emptied under it: the card must still render rather
    // than throw, because it is mounted beside an editor the author is using.
    render(card({ shot: null, label: null }));
    expect(screen.getByTestId("shot-preview-card-title").textContent).toContain("机位未命名");
    expect(screen.queryByTestId("shot-preview-card-duration")).toBeNull();
  });
});
