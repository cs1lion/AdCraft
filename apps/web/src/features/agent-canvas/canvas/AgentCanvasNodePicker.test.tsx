import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentCanvasNodePicker } from "./AgentCanvasNodePicker.tsx";

afterEach(() => cleanup());

describe("AgentCanvasNodePicker", () => {
  it("offers every canonical authoring node type including Script", () => {
    const onSelect = vi.fn();
    const { container } = render(
      <AgentCanvasNodePicker
        menuLabel="Add node types"
        onSelect={onSelect}
      />,
    );

    // 规范节点类型集已扩到 9（复刻/3D/配音三条线依赖它们可从面板加）——
    // 此前停在 6 是 P5 台账里的过期断言，非产品回退。
    expect(screen.getAllByRole("menuitem")).toHaveLength(9);
    expect(screen.getByRole("menuitem", { name: "Add Script node" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "Add Replica node" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "Add 3D Previs node" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "Add Voice Cast node" })).toBeTruthy();
    expect(Array.from(container.querySelectorAll(".agent-canvas-node-icon")).map((icon) => icon.getAttribute("data-icon-source"))).toEqual([
      "/imgs/node-icons/text.svg",
      "/imgs/node-icons/text.svg",
      "/imgs/node-icons/picture.svg",
      "/imgs/node-icons/video.svg",
      "/imgs/node-icons/audio.svg",
      "/imgs/node-icons/video.svg",
      "/imgs/node-icons/video.svg",
      "/imgs/node-icons/audio.svg",
      "/imgs/node-icons/solar-star-outline.svg",
    ]);

    fireEvent.click(screen.getByRole("menuitem", { name: "Add Script node" }));
    expect(onSelect).toHaveBeenCalledWith("script");
  });
});
