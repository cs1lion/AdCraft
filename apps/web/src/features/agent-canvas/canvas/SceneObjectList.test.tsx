import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script";
import { SceneObjectList } from "./SceneObjectList.tsx";

afterEach(cleanup);

const script: SceneScriptRoot = {
  scene: { name: "lab", environment: "indoor", lighting: "cool", duration: 3, frame_rate: 30 },
  characters: [],
  props: [{ id: "crate1", type: "crate", position: [1, 1, 0], scale: 1 }],
  environment: [{ id: "wall1", type: "wall", position: [0, 3, 0], scale: 1 }],
  cameras: [
    { id: "cam_1", shot_type: "wide", display_name: "双人全景", keyframes: [{ frame: 0, position: [0, 0, 0], look_at: [0, 0, 1] }] },
    { id: "cam_2", shot_type: "closeup", keyframes: [{ frame: 60, position: [0, 0, 0], look_at: [0, 0, 1] }] },
  ],
  shots: [{ id: "shot_1", camera: "cam_1", start_frame: 0, end_frame: 89 }],
  speech_bindings: [],
};

function renderList(selected: Parameters<typeof SceneObjectList>[0]["selected"] = null) {
  const onSelect = vi.fn();
  render(<SceneObjectList sceneScript={script} selected={selected} onSelect={onSelect} />);
  return { onSelect };
}

describe("SceneObjectList", () => {
  it("lists every object the scene contains", () => {
    // The panel's job: the scene's contents are readable at a glance, so an
    // author does not have to find each object in the viewport by eye.
    renderList();
    const items = screen.getAllByTestId("scene-object-list-item");
    expect(items).toHaveLength(4); // 2 cameras + 1 prop + 1 environment
    const labels = items.map((item) => item.textContent);
    expect(labels.some((text) => text?.includes("机位01 | 双人全景"))).toBe(true);
    expect(labels.some((text) => text?.includes("机位02"))).toBe(true);
    expect(labels.some((text) => text?.includes("crate1"))).toBe(true);
  });

  it("selects on click, with kind and label", () => {
    const { onSelect } = renderList();
    fireEvent.click(screen.getAllByTestId("scene-object-list-item")[2]);
    expect(onSelect).toHaveBeenCalledWith({ kind: "prop", id: "crate1" });
  });

  it("marks the selected row so the panel and the viewport agree", () => {
    renderList({ kind: "prop", id: "crate1" });
    const rows = screen.getAllByTestId("scene-object-list-item");
    const selected = rows.find((row) => row.textContent?.includes("crate1"));
    expect(selected?.getAttribute("data-selected")).toBe("true");
    expect(selected?.getAttribute("aria-current")).toBe("true");
    // The others must NOT be marked, or "which one is selected" is unreadable.
    expect(rows.filter((row) => row.getAttribute("data-selected") === "true")).toHaveLength(1);
  });

  it("says the scene is empty instead of rendering an empty list", () => {
    render(
      <SceneObjectList
        sceneScript={{ ...script, cameras: [], props: [], environment: [] }}
        selected={null}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByTestId("scene-object-list").textContent).toContain("场景里还没有对象");
    expect(screen.queryAllByTestId("scene-object-list-item")).toHaveLength(0);
  });
});
