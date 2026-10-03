import { describe, expect, it } from "vitest";
import type { CanvasNodeV2 } from "../../../types-v2.ts";
import { canvasProgressModel } from "./canvasProgressModel.ts";

const nodes = (...statuses: CanvasNodeV2["status"][]) =>
  statuses.map((status) => ({ status }) as CanvasNodeV2);

describe("canvas progress honesty", () => {
  it("does not label unprepared drafts as complete", () => {
    expect(canvasProgressModel(nodes("ready", "draft")))
      .toMatchObject({ complete: false, percent: 50, draft: 1, waiting: 1 });
  });
  it("only marks a nonempty fully ready workflow complete", () => {
    expect(canvasProgressModel(nodes("ready", "ready")).complete).toBe(true);
    expect(canvasProgressModel([]).complete).toBe(false);
  });
  it("keeps failures and running work distinct from waiting work", () => {
    expect(canvasProgressModel(nodes("failed", "working", "draft")))
      .toMatchObject({ failed: 1, working: 1, waiting: 1, complete: false });
  });
});
