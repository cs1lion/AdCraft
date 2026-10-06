/**
 * Low-poly human rig — the browser half of the character silhouette.
 *
 * Ported 1:1 from the Blender converter's ``_build_lowpoly_human``
 * (``apps/api/app/services/scene3d/blender_converter.py``). That builder is the
 * source of truth: the same seven segments, at the same fractions of the
 * script's own ``height``, so a 1.65 m character and a 1.9 m character differ
 * the way two people do rather than the way two boxes do.
 *
 * Why the numbers live in their own module: they are a contract with the
 * renderer, not a styling choice. ``lowPolyHumanRig.test.ts`` asserts the
 * contract directly — segment count, feet on the ground, crown at ~height,
 * leg length tracking ``height`` — so the day the preview and the converter
 * disagree about what a person looks like, a unit test fails instead of a
 * reviewer noticing a silhouette in the deliverable.
 *
 * The rig is data, not JSX: the preview maps each segment onto the intrinsics
 * the lean canvas already ships, and nothing here imports three.
 *
 * Axis note: SceneScript (and Blender) are Z-up, so a Blender ``(x, y, z)``
 * lands here as ``[x, z, y]`` — see ``sceneScriptAxes.ts``. Limb depth is
 * symmetric about the spine, so only the height (y) and the left/right (x)
 * carry meaning for the silhouette.
 */

/**
 * Segment boundaries as a fraction of ``height * scale``, mirroring the
 * converter's ``_build_lowpoly_human`` constants one for one.
 */
export const CHARACTER_RIG_FRACTIONS = {
  /** Legs: feet at 0, hip at 0.50 of the figure. */
  leg: 0.5,
  /** Torso: hip to shoulder, 0.30 of the figure. */
  torso: 0.3,
  /** Neck: a 0.03 column between shoulder and head. */
  neck: 0.03,
  /** Head radius: 0.11 of the figure — a stylised 7.5-head body. */
  headRadius: 0.11,
  /** Arms: 0.30 of the figure, centred 0.55 of an arm below the shoulder. */
  arm: 0.3,
  armHang: 0.55,
  /** Limb cross-section width. */
  limbWidth: 0.055,
  /** Torso cross-section. */
  torsoWidth: 0.3,
  torsoDepth: 0.16,
  /** The head sphere sits 0.85 radii above the top of the neck. */
  headSeat: 0.85,
  /** Legs straddle the spine by ±0.075; arms start 0.6 limb widths outside the torso wall. */
  legSpread: 0.075,
  armOutset: 0.6,
  /** Legs are deeper than they are wide; arms are square. */
  legDepthFactor: 1.2,
  armWidthFactor: 0.8,
  /** The neck column is just over half a limb width across. */
  neckRadiusFactor: 0.55,
} as const;

/** Converter fallbacks, kept here so the rig alone is a complete answer. */
export const DEFAULT_CHARACTER_COLOR = "#8B4513";
export const DEFAULT_CHARACTER_HEIGHT = 1.7;
export const DEFAULT_CHARACTER_SCALE = 1.0;
/**
 * Head (and neck) skin. The converter paints the head with a fixed skin tone
 * and everything else with the character's own colour; the neck rides with the
 * head here because Blender leaves it on its default material, which reads as
 * a grey collar bug rather than as a design.
 */
export const CHARACTER_SKIN_COLOR = "#E8D5C4";

/** The parts the converter emits, in the order it emits them. */
export const CHARACTER_SEGMENT_PARTS = [
  "torso",
  "LegL",
  "LegR",
  "ArmL",
  "ArmR",
  "neck",
  "head",
] as const;

export type CharacterSegmentPart = (typeof CHARACTER_SEGMENT_PARTS)[number];

/**
 * Which colour a segment takes: the body colour from the script's appearance,
 * or the fixed skin tone (head and neck).
 */
export type CharacterSegmentPaint = "body" | "skin";

export type CharacterSegmentGeometry =
  | { kind: "box"; size: [number, number, number] }
  | { kind: "cylinder"; radius: number; depth: number }
  | { kind: "sphere"; radius: number };

export interface CharacterSegment {
  part: CharacterSegmentPart;
  paint: CharacterSegmentPaint;
  /**
   * three.js local position ``[right, up, forward]``. The rig stands on y=0 in
   * its own frame; the caller places the whole figure in the scene.
   */
  position: [number, number, number];
  geometry: CharacterSegmentGeometry;
}

export interface CharacterRig {
  /** Standing height in metres: feet at 0, crown just above ``height*scale``. */
  height: number;
  /** Hip-to-shoulder line: where the legs end, the torso ends and the arms hang from. */
  torsoTop: number;
  /** Head sphere centre height. */
  headY: number;
  headRadius: number;
  /** All seven segments, converter order: torso, legs, arms, neck, head. */
  segments: CharacterSegment[];
}

/** The slice of ``appearance`` the rig reads. */
export interface CharacterAppearanceLike {
  color?: string | null;
  height?: number | null;
  scale?: number | null;
}

/** One line box: full ``size``, centred at ``position``. */
function box(
  part: CharacterSegmentPart,
  paint: CharacterSegmentPaint,
  position: [number, number, number],
  size: [number, number, number],
): CharacterSegment {
  return { part, paint, position, geometry: { kind: "box", size } };
}

/**
 * Build the seven-segment rig for one character.
 *
 * Pure and total: the same appearance always produces the same segments, and
 * a missing ``height``/``scale`` falls back to the converter's own defaults so
 * a script that omits them still stands at a person's height.
 */
export function characterRig(appearance: CharacterAppearanceLike): CharacterRig {
  const f = CHARACTER_RIG_FRACTIONS;
  const h = (appearance.height ?? DEFAULT_CHARACTER_HEIGHT) * (appearance.scale ?? DEFAULT_CHARACTER_SCALE);

  const legHeight = f.leg * h;
  const torsoHeight = f.torso * h;
  const torsoBottom = legHeight;
  const torsoTop = torsoBottom + torsoHeight;
  const neckHeight = f.neck * h;
  const headRadius = f.headRadius * h;
  const headY = torsoTop + neckHeight + headRadius * f.headSeat;
  const armHeight = f.arm * h;
  const armY = torsoTop - armHeight * f.armHang;
  const limbWidth = f.limbWidth * h;
  const torsoWidth = f.torsoWidth * h;
  const torsoDepth = f.torsoDepth * h;

  const segments: CharacterSegment[] = [
    box("torso", "body", [0, torsoBottom + torsoHeight / 2, 0], [torsoWidth, torsoHeight, torsoDepth]),
    box(
      "LegL",
      "body",
      [-f.legSpread * h, legHeight / 2, 0],
      [limbWidth, legHeight, limbWidth * f.legDepthFactor],
    ),
    box(
      "LegR",
      "body",
      [f.legSpread * h, legHeight / 2, 0],
      [limbWidth, legHeight, limbWidth * f.legDepthFactor],
    ),
    box(
      "ArmL",
      "body",
      [-(torsoWidth / 2 + limbWidth * f.armOutset), armY, 0],
      [limbWidth * f.armWidthFactor, armHeight, limbWidth * f.armWidthFactor],
    ),
    box(
      "ArmR",
      "body",
      [torsoWidth / 2 + limbWidth * f.armOutset, armY, 0],
      [limbWidth * f.armWidthFactor, armHeight, limbWidth * f.armWidthFactor],
    ),
    {
      part: "neck",
      paint: "skin",
      position: [0, torsoTop + neckHeight / 2, 0],
      geometry: { kind: "cylinder", radius: limbWidth * f.neckRadiusFactor, depth: neckHeight },
    },
    {
      part: "head",
      paint: "skin",
      position: [0, headY, 0],
      geometry: { kind: "sphere", radius: headRadius },
    },
  ];

  return { height: h, torsoTop, headY, headRadius, segments };
}

/**
 * Vertical extent of one segment: ``[bottom, top]`` in the rig's own frame.
 * The unit test uses this to prove the segments stack without gaps, which is
 * the difference between a person and a pile of parts.
 */
export function segmentExtent(segment: CharacterSegment): [number, number] {
  const { position, geometry } = segment;
  if (geometry.kind === "box") {
    return [position[1] - geometry.size[1] / 2, position[1] + geometry.size[1] / 2];
  }
  if (geometry.kind === "cylinder") {
    return [position[1] - geometry.depth / 2, position[1] + geometry.depth / 2];
  }
  return [position[1] - geometry.radius, position[1] + geometry.radius];
}

/** Half-width of a segment along x — how far it reaches from the spine. */
export function segmentHalfWidth(segment: CharacterSegment): number {
  const { position, geometry } = segment;
  if (geometry.kind === "box") return Math.abs(position[0]) + geometry.size[0] / 2;
  // Cylinders and spheres are both radially symmetric about their axis.
  return Math.abs(position[0]) + geometry.radius;
}
