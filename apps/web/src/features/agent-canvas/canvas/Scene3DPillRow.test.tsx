import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Scene3DPillRow } from "./Scene3DPillRow.tsx";

afterEach(cleanup);

function withTarget(testid: string) {
  const container = document.createElement("div");
  container.innerHTML = `<section data-testid="${testid}"></section>`;
  document.body.appendChild(container);
  return () => container.remove();
}

describe("Scene3DPillRow", () => {
  it("offers only the pills whose capability exists in this repo", () => {
    render(<Scene3DPillRow />);
    // 参考 / 角色库 / 运镜 are real surfaces here.
    expect(screen.getByTestId("scene-3d-pill-scene-image-intake-drop")).toBeTruthy();
    expect(screen.getByTestId("scene-3d-pill-scene-asset-tray")).toBeTruthy();
    expect(screen.getByTestId("scene-3d-pill-scene-script-3d-director")).toBeTruthy();
    // 标记 / 特效 do not exist; rendering a pill for them would be a control
    // that opens nothing.
    expect(screen.queryByText("标记")).toBeNull();
    expect(screen.queryByText("特效")).toBeNull();
  });

  it("says why there are three pills instead of the reference's five", () => {
    render(<Scene3DPillRow />);
    expect(screen.getByTestId("scene-3d-pill-row-note").textContent).toContain(
      "本仓暂无此能力",
    );
  });

  it("scrolls the target into view and flashes it", () => {
    const remove = withTarget("scene-asset-tray");
    const target = document.querySelector('[data-testid="scene-asset-tray"]') as HTMLElement;
    const scrollIntoView = vi.fn();
    target.scrollIntoView = scrollIntoView;
    render(<Scene3DPillRow />);
    fireEvent.click(screen.getByTestId("scene-3d-pill-scene-asset-tray"));
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    // The flash is what tells the author WHERE the pill took them.
    expect(target.getAttribute("data-pill-flash")).toBe("true");
    remove();
  });

  it("stays inert when its target is not mounted", () => {
    // A pill whose surface has not rendered yet must not throw.
    expect(() => {
      render(<Scene3DPillRow />);
      fireEvent.click(screen.getByTestId("scene-3d-pill-scene-asset-tray"));
    }).not.toThrow();
  });

  it("is disabled while the scene is saving", () => {
    render(<Scene3DPillRow disabled />);
    const pill = screen.getByTestId("scene-3d-pill-scene-image-intake-drop") as HTMLButtonElement;
    expect(pill.disabled).toBe(true);
  });
});
