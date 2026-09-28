import { describe, expect, it } from "vitest";
import { LOD_TIERS, objectLodTier, resolveLodTier } from "./sceneFidelity.ts";

describe("resolveLodTier", () => {
  it("passes known tiers through", () => {
    for (const tier of LOD_TIERS) {
      expect(resolveLodTier(tier)).toBe(tier);
    }
  });

  it("degrades unknown values to standard", () => {
    expect(resolveLodTier("ultra")).toBe("standard");
    expect(resolveLodTier(null)).toBe("standard");
    expect(resolveLodTier(undefined)).toBe("standard");
  });
});

describe("objectLodTier", () => {
  it("reads the tier from an object when declared", () => {
    expect(objectLodTier({ lod_tier: "rough" })).toBe("rough");
    expect(objectLodTier({ lod_tier: "detailed" })).toBe("detailed");
  });

  it("defaults to standard when the field is absent or the object is null", () => {
    expect(objectLodTier({})).toBe("standard");
    expect(objectLodTier(null)).toBe("standard");
    expect(objectLodTier(undefined)).toBe("standard");
  });
});
