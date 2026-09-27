/**
 * transitionVariants tests (V0.2 §9 局部分叉).
 *
 * The variants are how the author keeps several readings of one transition
 * side by side instead of overwriting them. These tests lock the tolerant
 * parse (a half-written block must not crash the panel, a script-less
 * variant must not restore a blank scene), the cap the research's own
 * branch-explosion warning demands, and the 方案 A/B/C labelling.
 */

import { describe, expect, it } from "vitest";

import {
  MAX_TRANSITION_VARIANTS,
  nextVariantLabel,
  parseTransitionVariants,
  serializeTransitionVariants,
  type TransitionVariant,
} from "./transitionVariants.ts";

function variant(id: string, label: string): TransitionVariant {
  return {
    id,
    label,
    proposal_id: "sound_bridge",
    scene_script: { scene: { name: "lab" } },
  };
}

describe("parseTransitionVariants", () => {
  it("round-trips a well-formed block", () => {
    const stored = serializeTransitionVariants([variant("v1", "方案 A")]);
    const parsed = parseTransitionVariants(stored);
    expect(parsed).toHaveLength(1);
    expect(parsed[0].id).toBe("v1");
    expect(parsed[0].label).toBe("方案 A");
    expect(parsed[0].proposal_id).toBe("sound_bridge");
    expect(parsed[0].scene_script).toEqual({ scene: { name: "lab" } });
  });

  it("returns an empty list for absent or unusable blocks", () => {
    expect(parseTransitionVariants(null)).toEqual([]);
    expect(parseTransitionVariants("nope")).toEqual([]);
    expect(parseTransitionVariants({})).toEqual([]);
  });

  it("skips a variant without a script (never restore a blank scene)", () => {
    const parsed = parseTransitionVariants([
      { id: "v1", label: "方案 A" },
      variant("v2", "方案 B"),
    ]);
    expect(parsed.map((entry) => entry.id)).toEqual(["v2"]);
  });

  it("defaults a missing label into the A/B/C series", () => {
    const parsed = parseTransitionVariants([
      { id: "v1", scene_script: { scene: {} } },
    ]);
    expect(parsed[0].label).toBe("方案 A");
  });

  it("keeps a null proposal id honest", () => {
    const parsed = parseTransitionVariants([
      { id: "v1", label: "方案 A", proposal_id: "", scene_script: {} },
    ]);
    expect(parsed[0].proposal_id).toBeNull();
  });
});

describe("serializeTransitionVariants", () => {
  it("caps the kept variants (the research's branch-explosion warning)", () => {
    const many = Array.from({ length: MAX_TRANSITION_VARIANTS + 3 }, (_, index) =>
      variant(`v${index}`, `方案 ${index}`),
    );
    const serialized = serializeTransitionVariants(many);
    expect(serialized).toHaveLength(MAX_TRANSITION_VARIANTS);
    // The NEWEST survives: dropping the oldest is the only cap that keeps
    // the reading the author just saved.
    expect(serialized[serialized.length - 1].id).toBe(`v${many.length - 1}`);
  });

  it("round-trips through the parser", () => {
    const serialized = serializeTransitionVariants([
      variant("v1", "方案 A"),
      variant("v2", "方案 B"),
    ]);
    expect(parseTransitionVariants(serialized)).toHaveLength(2);
  });
});

describe("nextVariantLabel", () => {
  it("starts at 方案 A and skips the taken labels", () => {
    expect(nextVariantLabel([])).toBe("方案 A");
    expect(nextVariantLabel([variant("v1", "方案 A")])).toBe("方案 B");
    expect(
      nextVariantLabel([variant("v1", "方案 A"), variant("v2", "方案 B")]),
    ).toBe("方案 C");
  });

  it("fills a hole rather than always appending", () => {
    expect(nextVariantLabel([variant("v1", "方案 B")])).toBe("方案 A");
  });
});
