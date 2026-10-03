import { describe, expect, it } from "vitest";
import { scene3dDraftSignature } from "./scene3dDraftEquality.ts";

describe("scene draft equality after a real persistence round trip", () => {
  it("ignores backend-sorted object keys at every depth", () => {
    const draft = { scene: { name: "A", frame_rate: 12 }, cameras: [{ id: "cam", position: [1, 2, 3] }] };
    const saved = { cameras: [{ position: [1, 2, 3], id: "cam" }], scene: { frame_rate: 12, name: "A" } };
    expect(scene3dDraftSignature(draft)).toBe(scene3dDraftSignature(saved));
  });
  it("still detects real edits and ordered shot/keyframe changes", () => {
    expect(scene3dDraftSignature({ keyframes: [0, 12] })).not.toBe(scene3dDraftSignature({ keyframes: [12, 0] }));
    expect(scene3dDraftSignature({ scene: { name: "A" } })).not.toBe(scene3dDraftSignature({ scene: { name: "B" } }));
  });
});
