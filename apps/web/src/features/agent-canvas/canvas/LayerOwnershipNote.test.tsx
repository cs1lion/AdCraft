/**
 * LayerOwnershipNote tests (V0.2 §14.13).
 *
 * The point of the surface: a lock nobody knows about is indistinguishable
 * from no lock. These tests lock that both layers are named, that each says
 * what a redo of the OTHER one cannot damage, and that the redo guidance is
 * present (where to change what).
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LayerOwnershipNote } from "./LayerOwnershipNote.tsx";

afterEach(cleanup);

describe("LayerOwnershipNote", () => {
  it("names both layers and what each owns", () => {
    render(<LayerOwnershipNote />);
    expect(screen.getByTestId("layer-ownership-note")).toBeTruthy();
    expect(screen.getByTestId("layer-ownership-audio").textContent).toContain(
      "台词驱动",
    );
    expect(screen.getByTestId("layer-ownership-visual").textContent).toContain(
      "走位与运镜预设驱动",
    );
  });

  it("says what the other layer's redo cannot damage", () => {
    render(<LayerOwnershipNote />);
    // Re-doing the mouth must not break the walk...
    expect(screen.getByTestId("layer-ownership-audio").textContent).toContain(
      "走位不会被踩碎",
    );
    // ...and re-doing the body must not close the mouth.
    expect(screen.getByTestId("layer-ownership-visual").textContent).toContain(
      "不会把嘴闭上",
    );
  });

  it("tells the author where to change what", () => {
    render(<LayerOwnershipNote />);
    expect(screen.getByTestId("layer-ownership-redo").textContent).toContain(
      "重做 Audio 层",
    );
    expect(screen.getByTestId("layer-ownership-redo").textContent).toContain(
      "重做 Visual 层",
    );
  });
});
