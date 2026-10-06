import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script";
import type { SceneEditReport } from "./shotLabels.ts";
import { PrevisDeliveryOverlay } from "./PrevisDeliveryOverlay.tsx";

afterEach(cleanup);

const script: SceneScriptRoot = {
  scene: { name: "广寒站保卫战", environment: "outdoor", lighting: "dramatic", duration: 3, frame_rate: 30 },
  characters: [],
  props: [],
  environment: [],
  cameras: [
    { id: "cam_1", shot_type: "wide", display_name: "双人全景", keyframes: [{ frame: 0, position: [0, 0, 0], look_at: [0, 0, 1] }] },
    { id: "cam_2", shot_type: "closeup", display_name: "飞船起飞", keyframes: [{ frame: 60, position: [0, 0, 0], look_at: [0, 0, 1] }] },
  ],
  shots: [
    { id: "shot_1", camera: "cam_1", start_frame: 0, end_frame: 59 },
    { id: "shot_2", camera: "cam_2", start_frame: 60, end_frame: 119 },
  ],
  speech_bindings: [],
};

const clip = (shotId: string) => ({
  node_id: `video-${shotId}`,
  shot_id: shotId,
  clip_asset_id: `asset-${shotId}`,
  take_id: null,
});

function overlay(overrides: Partial<Parameters<typeof PrevisDeliveryOverlay>[0]> = {}) {
  return (
    <PrevisDeliveryOverlay
      sceneScript={script}
      clips={[]}
      onDismiss={vi.fn()}
      {...overrides}
    />
  );
}

const editReport: SceneEditReport = {
  changes: { cam_1: ["camera_moved"] },
  shots: [
    {
      id: "shot_1",
      camera_id: "cam_1",
      camera_label: "机位01 | 双人全景",
      start_seconds: 0,
      end_seconds: 2,
      changes: ["camera_moved"],
      objects_touched: ["cam_1"],
    },
  ],
  shot_count: 2,
  change_count: 1,
  labels: { camera_moved: "机位移动" },
};

describe("PrevisDeliveryOverlay", () => {
  it("answers with the scene's real delivery numbers", () => {
    // The reference card's headline line: duration, shot count, coverage. All
    // computed from the script — never a claim about work performed.
    render(overlay({ clips: [clip("shot_1")] }));
    const meta = screen.getByText(/个分镜/);
    expect(meta.textContent).toContain("2 个分镜");
    expect(meta.textContent).toContain("4.0s");
    expect(meta.textContent).toContain("1/2 已发布片段");
  });

  it("lists every shot with its span and published state", () => {
    render(overlay({ clips: [clip("shot_2")] }));
    const items = screen.getAllByRole("listitem");
    // header line is not a listitem; the two shots are.
    expect(items).toHaveLength(2);
    const published = items.find((item) => item.getAttribute("data-shot-id") === "shot_2");
    expect(published?.textContent).toContain("机位02 | 飞船起飞");
    expect(published?.textContent).toContain("2–4s");
    expect(published?.getAttribute("data-published")).toBe("true");
    const missing = items.find((item) => item.getAttribute("data-shot-id") === "shot_1");
    expect(missing?.getAttribute("data-published")).toBe("false");
  });

  it("shows what an edit changed, above the whole-film summary", () => {
    // Order matters: the specific answer to "what did I just do" comes before
    // the general state of the scene.
    render(overlay({ editReport }));
    const changes = screen.getByTestId("previs-delivery-changes");
    expect(changes.textContent).toContain("机位01 | 双人全景 的 0s–2s");
    expect(changes.textContent).toContain("机位移动");
    const shots = screen.getByTestId("previs-delivery-shots");
    expect(
      changes.compareDocumentPosition(shots) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("says the instruction is unwired, naming the target it would have hit", () => {
    // Never "已执行" — that asserts an agent ran. This build has no such
    // channel, so the card says so in the place the author is already looking.
    render(
      overlay({
        pendingSubject: { label: "机位02 | 飞船起飞", scope: "shot" },
      }),
    );
    const pending = screen.getByTestId("previs-delivery-pending");
    expect(pending.textContent).toContain("指令尚未接线");
    expect(pending.textContent).toContain("机位02 | 飞船起飞");
    expect(screen.queryByText(/已执行/)).toBeNull();
  });

  it("closes on the dismiss button", () => {
    const onDismiss = vi.fn();
    render(overlay({ onDismiss }));
    fireEvent.click(screen.getByLabelText("关闭交付报告"));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape", () => {
    // The card covers the viewport; a keyboard escape is not a nicety.
    const onDismiss = vi.fn();
    render(overlay({ onDismiss }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
