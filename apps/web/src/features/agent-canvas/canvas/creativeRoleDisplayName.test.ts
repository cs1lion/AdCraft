import { describe, expect, it } from "vitest";

import { creativeRoleDisplayName } from "./creativeRoleDisplayName.ts";

describe("creativeRoleDisplayName", () => {
  it("names the previs clip role after the canvas family label", () => {
    expect(creativeRoleDisplayName("scene_3d_previs_clip")).toBe("3D Previs Clip");
  });

  it("still title-cases roles without an override", () => {
    expect(creativeRoleDisplayName("storyboard_video")).toBe("Storyboard Video");
  });
});
