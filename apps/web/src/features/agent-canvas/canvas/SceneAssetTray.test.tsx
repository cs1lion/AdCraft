/**
 * SceneAssetTray tests.
 *
 * The palette must cover EXACTLY the backend's declared vocabulary: a kind
 * with no tray entry is unreachable from the UI, and a tray entry without
 * backend geometry would render as a magenta placeholder. The generated
 * enums are the single source for both sides, so these tests assert the
 * tray exposes every member of each enum and routes clicks to the right
 * add callback.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ENVIRONMENT_TYPES, PROP_TYPES } from "../../../types/scene-script.generated";
import { SceneAssetTray } from "./SceneAssetTray.tsx";

afterEach(cleanup);

describe("SceneAssetTray", () => {
  it("exposes every declared environment and prop kind", () => {
    render(<SceneAssetTray onAddEnvironment={vi.fn()} onAddProp={vi.fn()} />);
    const kinds = Array.from(document.querySelectorAll("[data-tray-kind]")).map(
      (node) => node.getAttribute("data-tray-kind") as string,
    );
    expect(new Set(kinds)).toEqual(new Set([...ENVIRONMENT_TYPES, ...PROP_TYPES]));
  });

  it("routes clicks to the matching add callback", () => {
    const onAddEnvironment = vi.fn();
    const onAddProp = vi.fn();
    render(
      <SceneAssetTray onAddEnvironment={onAddEnvironment} onAddProp={onAddProp} />,
    );

    fireEvent.click(document.querySelector('[data-tray-kind="wall"]') as Element);
    expect(onAddEnvironment).toHaveBeenCalledWith("wall");
    expect(onAddProp).not.toHaveBeenCalled();

    fireEvent.click(document.querySelector('[data-tray-kind="chair"]') as Element);
    expect(onAddProp).toHaveBeenCalledWith("chair");
  });

  it("collapses and expands groups", () => {
    render(<SceneAssetTray onAddEnvironment={vi.fn()} onAddProp={vi.fn()} />);
    const toggle = screen.getByText(/环境（/);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(document.querySelector('[data-tray-kind="wall"]')).toBeNull();
    // The other group is untouched.
    expect(document.querySelector('[data-tray-kind="chair"]')).not.toBeNull();
  });

  it("disables every entry while a save is in flight", () => {
    render(
      <SceneAssetTray onAddEnvironment={vi.fn()} onAddProp={vi.fn()} disabled />,
    );
    const entries = Array.from(document.querySelectorAll("[data-tray-kind]"));
    expect(entries.length).toBeGreaterThan(0);
    expect(entries.every((node) => (node as HTMLButtonElement).disabled)).toBe(true);
  });
});
