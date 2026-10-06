/**
 * Low-poly human rig — the ported proportions, tested as the contract they are.
 *
 * These numbers are not a styling choice: they are the Blender converter's
 * ``_build_lowpoly_human`` segment boundaries, and the preview must agree with
 * the render or a reviewer signs off on a deliverable whose silhouette is not
 * the one they approved (docs/plans/threejs-renderer-replacement.md §3.6).
 * The browser spec proves the meshes really draw; this file proves the rig is
 * a person at any height.
 */

import { describe, expect, it } from "vitest";

import {
  CHARACTER_RIG_FRACTIONS,
  CHARACTER_SEGMENT_PARTS,
  CHARACTER_SKIN_COLOR,
  characterRig,
  DEFAULT_CHARACTER_COLOR,
  DEFAULT_CHARACTER_HEIGHT,
  DEFAULT_CHARACTER_SCALE,
  segmentExtent,
  segmentHalfWidth,
  type CharacterSegment,
  type CharacterSegmentPart,
} from "./lowPolyHumanRig";

/** One appearance, the way SceneScript hands it over. */
function appearance(overrides: { color?: string; height?: number; scale?: number } = {}) {
  return {
    color: "#E74C3C",
    height: 1.7,
    scale: 1,
    ...overrides,
  };
}

function segment(part: CharacterSegmentPart, height = 1.7, scale = 1): CharacterSegment {
  const found = characterRig(appearance({ height, scale })).segments.find((entry) => entry.part === part);
  if (!found) throw new Error(`no segment ${part}`);
  return found;
}

/** Total vertical extent of a segment, from its box/cylinder/sphere geometry. */
function segmentHeight(entry: CharacterSegment): number {
  const [, top] = segmentExtent(entry);
  const [bottom] = segmentExtent(entry);
  return top - bottom;
}

describe("low-poly human rig: the converter's seven segments", () => {
  it("emits exactly the segments Blender emits, in the converter's order", () => {
    // torso + neck + head + LegL/LegR + ArmL/ArmR. A rig that gains or loses a
    // part here has drifted from the render, and the deliverable drifts with it.
    expect(characterRig(appearance()).segments.map((entry) => entry.part)).toEqual([
      ...CHARACTER_SEGMENT_PARTS,
    ]);
    expect(characterRig(appearance()).segments).toHaveLength(7);
  });

  it("stands on the ground with the crown at the scripted height", () => {
    const rig = characterRig(appearance({ height: 1.8 }));
    const legs = rig.segments.filter((entry) => entry.part.startsWith("Leg"));
    for (const leg of legs) {
      const [bottom] = segmentExtent(leg);
      expect(bottom).toBeCloseTo(0, 10);
    }
    // Feet at 0, crown (head top) at ~height*scale — the figure is as tall as
    // the script says it is.
    const [headBottom, headTop] = segmentExtent(segment("head", 1.8));
    expect(headBottom).toBeGreaterThan(rig.height * 0.75);
    expect(headTop).toBeGreaterThanOrEqual(rig.height * 0.98);
    expect(headTop).toBeLessThan(rig.height * 1.05);
  });

  it("stacks the segments without gaps or overlaps the converter does not have", () => {
    const rig = characterRig(appearance());
    const torso = segment("torso");
    const leg = segment("LegL");
    const neck = segment("neck");
    const [torsoBottom, torsoTop] = segmentExtent(torso);
    const legTop = segmentExtent(leg)[1];
    // The torso starts exactly where the legs end.
    expect(torsoBottom).toBeCloseTo(legTop, 10);
    // The neck bridges shoulder to head: its top meets the head sphere.
    const [neckBottom, neckTop] = segmentExtent(neck);
    expect(neckBottom).toBeCloseTo(torsoTop, 10);
    const [headBottom] = segmentExtent(segment("head"));
    expect(neckTop).toBeGreaterThan(headBottom);
    expect(neckTop).toBeLessThan(rig.headY);
    // The arms hang beside the torso: the converter centres them 55% of an arm
    // length below the shoulder, so they overlap the torso band and reach just
    // past the hip — where a person's wrists are.
    const [armBottom, armTop] = segmentExtent(segment("ArmL"));
    expect(armTop).toBeLessThan(torsoTop);
    expect(armTop).toBeGreaterThan(torsoBottom);
    expect(armBottom).toBeLessThan(torsoTop);
    expect(armBottom).toBeGreaterThan(torsoBottom - 0.05 * rig.height);
  });

  it("reads as a silhouette: legs outside the arms' reach, arms outside the torso", () => {
    const rig = characterRig(appearance({ height: 1.9 }));
    const torso = segment("torso", 1.9);
    const torsoHalfWidth = segmentHalfWidth(torso);
    for (const arm of ["ArmL", "ArmR"] as const) {
      // Arms sit outside the torso wall — the shoulders are visible.
      expect(segmentHalfWidth(segment(arm, 1.9))).toBeGreaterThan(torsoHalfWidth);
    }
    for (const leg of ["LegL", "LegR"] as const) {
      // Legs straddle the spine inside the torso's width, so the figure has a
      // waist rather than a plinth.
      expect(segmentHalfWidth(segment(leg, 1.9))).toBeLessThan(torsoHalfWidth);
    }
    // Left and right are mirrored about the spine.
    const left = segment("LegL", 1.9);
    const right = segment("LegR", 1.9);
    expect(left.position[0]).toBeCloseTo(-right.position[0], 10);
    expect(segmentHalfWidth(left)).toBeCloseTo(segmentHalfWidth(right), 10);
    expect(rig.torsoTop).toBeGreaterThan(0);
  });
});

describe("low-poly human rig: proportional to the script's own height", () => {
  it("scales every segment with height", () => {
    const short = characterRig(appearance({ height: 1.65 }));
    const tall = characterRig(appearance({ height: 1.9 }));
    // Leg length is half the figure, for BOTH figures — and the tall one's legs
    // really are longer, the way two people's are.
    expect(segmentHeight(segment("LegL", 1.65))).toBeCloseTo(0.5 * 1.65, 10);
    expect(segmentHeight(segment("LegL", 1.9))).toBeCloseTo(0.5 * 1.9, 10);
    expect(segmentHeight(segment("LegL", 1.9)) / segmentHeight(segment("LegL", 1.65))).toBeCloseTo(
      1.9 / 1.65,
      10,
    );
    // The whole rig scales together: head, torso and arms included.
    expect(tall.height / short.height).toBeCloseTo(1.9 / 1.65, 10);
    expect(tall.headRadius / short.headRadius).toBeCloseTo(1.9 / 1.65, 10);
    expect(segmentHeight(segment("torso", 1.9))).toBeCloseTo(
      CHARACTER_RIG_FRACTIONS.torso * 1.9,
      10,
    );
    expect(segmentHeight(segment("ArmL", 1.9))).toBeCloseTo(CHARACTER_RIG_FRACTIONS.arm * 1.9, 10);
    expect(segmentHeight(segment("neck", 1.9))).toBeCloseTo(
      CHARACTER_RIG_FRACTIONS.neck * 1.9,
      10,
    );
  });

  it("applies the appearance scale multiplier to the whole figure", () => {
    const plain = characterRig(appearance({ height: 1.7, scale: 1 }));
    const doubled = characterRig(appearance({ height: 1.7, scale: 2 }));
    // A 2x-scale character is a 2x character: every dimension doubles, and the
    // feet still sit on the ground.
    expect(doubled.height).toBeCloseTo(plain.height * 2, 10);
    expect(doubled.headY).toBeCloseTo(plain.headY * 2, 10);
    expect(segmentHeight(segment("LegL", 1.7, 2))).toBeCloseTo(
      segmentHeight(segment("LegL", 1.7, 1)) * 2,
      10,
    );
    for (const entry of doubled.segments) {
      const [bottom] = segmentExtent(entry);
      expect(bottom).toBeGreaterThanOrEqual(-1e-10);
    }
  });

  it("falls back to the converter's own defaults when the script omits them", () => {
    const rig = characterRig({});
    expect(rig.height).toBeCloseTo(DEFAULT_CHARACTER_HEIGHT * DEFAULT_CHARACTER_SCALE, 10);
    expect(rig.segments).toHaveLength(7);
    const partial = characterRig({ height: 2 });
    expect(partial.height).toBeCloseTo(2 * DEFAULT_CHARACTER_SCALE, 10);
    expect(DEFAULT_CHARACTER_COLOR).toBe("#8B4513");
  });
});

describe("low-poly human rig: paint", () => {
  it("paints the body with the character's colour and the head with skin", () => {
    const rig = characterRig(appearance({ color: "#E74C3C" }));
    const paints = Object.fromEntries(rig.segments.map((entry) => [entry.part, entry.paint]));
    expect(paints.torso).toBe("body");
    expect(paints.LegL).toBe("body");
    expect(paints.LegR).toBe("body");
    expect(paints.ArmL).toBe("body");
    expect(paints.ArmR).toBe("body");
    expect(paints.neck).toBe("skin");
    expect(paints.head).toBe("skin");
    expect(CHARACTER_SKIN_COLOR).toBe("#E8D5C4");
  });
});
