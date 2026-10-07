import { describe, expect, it } from "vitest";

import {
  bobOffset,
  cyclePhaseForDistance,
  segmentPoseAt,
  travelledMetres,
  walkLegAmplitude,
  walkStrideMetres,
} from "./characterPose";
import { characterRig, type CharacterAppearanceLike } from "./lowPolyHumanRig";
import { characterStateAtFrame } from "./sceneScriptEditModel";

/**
 * A walk whose feet slide is not a walk.
 *
 * Every other pose test samples the pose and checks its shape -- signs, opposition,
 * continuity, magnitude. All of those passed while the figure skated, because a
 * sliding walk and a planted one have the same shape at every sampled instant; only
 * the foot's POSITION IN THE WORLD distinguishes them, and nothing was looking
 * there.
 *
 * So this asserts the foot itself. It reconstructs each leg's foot from the
 * renderer's own transform chain -- segment position, the proximal pivot group, the
 * pitch -- rather than re-deriving the pose, so a change to either side shows up
 * here. The chain is `SceneScript3DPreview.tsx`: the group sits at
 * `segment.position + (0, reach, 0)` and rotates by the pitch, and the mesh hangs
 * `reach` below it, putting the foot `2*reach` under the group before rotation.
 */

const TRAVEL_METRES = 3.6;
const TRAVEL_FRAMES = 89;
const TRAVEL_PER_FRAME = TRAVEL_METRES / TRAVEL_FRAMES;

interface Leg {
  pitch: number;
  /** Height of the foot above z = 0, in metres. */
  height: number;
  /** Position along the direction of travel, in metres. */
  forward: number;
}

function walker(height: number) {
  const appearance: CharacterAppearanceLike = { height, scale: 1 };
  const rig = characterRig(appearance);
  return {
    rig,
    character: {
      id: "walker",
      type: "lowpoly_human",
      appearance: { color: "#4A5568", height, scale: 1 },
      keyframes: [
        { frame: 0, position: [0, 0, 0] as [number, number, number], rotation_y: 0, action: "walk" },
        {
          frame: TRAVEL_FRAMES,
          position: [TRAVEL_METRES, 0, 0] as [number, number, number],
          rotation_y: 0,
          action: "walk",
        },
      ],
    },
  };
}

function legAt(
  character: ReturnType<typeof walker>["character"],
  rig: ReturnType<typeof characterRig>,
  frame: number,
  part: "LegL" | "LegR",
): Leg {
  const segment = rig.segments.find((candidate) => candidate.part === part);
  if (!segment) throw new Error(`rig has no ${part}`);
  const distance = travelledMetres(
    character.keyframes.map((keyframe) => keyframe.position),
    character.keyframes.map((keyframe) => keyframe.frame),
    frame,
  );
  const pose = segmentPoseAt("walk", cyclePhaseForDistance(distance, rig.legLength), {
    legLengthMetres: rig.legLength,
  });
  const bob = bobOffset(pose, rig);
  const pitch = part === "LegL" ? (pose.legL ?? 0) : (pose.legR ?? 0);
  const reach =
    segment.geometry.kind === "box"
      ? segment.geometry.size[1] / 2
      : segment.geometry.kind === "cylinder"
        ? segment.geometry.depth / 2
        : 0;
  const root = characterStateAtFrame(character as never, frame).position;
  return {
    pitch,
    height: segment.position[1] + reach - 2 * reach * Math.cos(pitch) + bob,
    forward: root[0] + segment.position[2] - 2 * reach * Math.sin(pitch),
  };
}

/** The planted foot is the lower of the two, which is the one bearing weight. */
function plantedLegAt(
  character: ReturnType<typeof walker>["character"],
  rig: ReturnType<typeof characterRig>,
  frame: number,
) {
  const left = legAt(character, rig, frame, "LegL");
  const right = legAt(character, rig, frame, "LegR");
  return { left, right, planted: left.height <= right.height ? left : right };
}

describe("a walk does not skate", () => {
  it("keeps the planted foot within a few millimetres of where it was", () => {
    const { rig, character } = walker(1.85);
    // Measured, not reasoned: the residual is sin() being mildly non-linear across
    // the stance even when the stance itself is linear. The figure this replaced
    // slid 134 mm per frame against a body travel of 40 mm -- 332% -- so the ceiling
    // here has room to be generous and still fail on the old behaviour.
    const drift: number[] = [];
    for (let frame = 1; frame <= TRAVEL_FRAMES; frame += 1) {
      const previous = plantedLegAt(character, rig, frame - 1);
      const current = plantedLegAt(character, rig, frame);
      const sameFootStillPlanted =
        (previous.planted === previous.left) === (current.planted === current.left);
      if (sameFootStillPlanted) {
        drift.push(Math.abs(current.planted.forward - previous.planted.forward));
      }
    }
    const worst = Math.max(...drift);
    expect(worst / TRAVEL_PER_FRAME).toBeLessThan(0.1);
  });

  it("holds the planted foot on the ground rather than stopping in mid-air", () => {
    // Slide was only half of it: a foot that no longer moves but hangs 12 cm up is
    // just as wrong, and cheaper to assert than to spot by eye.
    const { rig, character } = walker(1.85);
    const heights: number[] = [];
    for (let frame = 0; frame <= TRAVEL_FRAMES; frame += 1) {
      heights.push(Math.max(0, plantedLegAt(character, rig, frame).planted.height));
    }
    expect(Math.max(...heights)).toBeLessThan(0.005);
  });

  it("plants one foot and swings the other, never both at once", () => {
    // A double contact is correct at the two ends of a stride and wrong everywhere
    // else. Sampling the whole cycle must find both, and must not find the figure
    // standing on two planted feet for long stretches.
    const { rig, character } = walker(1.85);
    let airborne = 0;
    for (let frame = 0; frame <= TRAVEL_FRAMES; frame += 1) {
      const { left, right } = plantedLegAt(character, rig, frame);
      const gap = Math.abs(left.forward - right.forward);
      if (gap > 0.2) airborne += 1;
    }
    // The rig has no knee, so the swing foot briefly passes through vertical at
    // ground level instead of clearing it. What must not happen is the feet being
    // together for the whole cycle, which is what "no animation" looks like.
    expect(airborne).toBeGreaterThan(TRAVEL_FRAMES * 0.5);
  });
});

describe("the walk amplitude follows the leg it has to plant", () => {
  it("swings every figure by the same angle and shortens the stride instead", () => {
    // stride / (4L) is what sets the angle, and the stride is proportional to L, so
    // the angle cancels out: everyone swings about 22 degrees and a child simply
    // covers less ground per step. This is why a 1.1 m figure in jinghai no longer
    // skates -- it did when the angle was a constant and the stride was not scaled.
    expect(walkLegAmplitude(0.925)).toBeCloseTo(Math.asin(1.4 / (4 * 0.925)), 9);
    expect(walkLegAmplitude(0.55)).toBeCloseTo(walkLegAmplitude(0.925), 9);
    expect(walkStrideMetres(0.55)).toBeLessThan(walkStrideMetres(0.925));
  });

  it("shortens the stride rather than exceeding the leg's reach", () => {
    // A leg too short for a 1.4 m stride must take smaller steps, not impossible
    // angles. The invariant that matters is that it still does not skate.
    const { rig, character } = walker(1.1);
    expect(rig.legLength).toBeLessThan(0.6);
    const drift: number[] = [];
    for (let frame = 1; frame <= TRAVEL_FRAMES; frame += 1) {
      const previous = plantedLegAt(character, rig, frame - 1);
      const current = plantedLegAt(character, rig, frame);
      if ((previous.planted === previous.left) === (current.planted === current.left)) {
        drift.push(Math.abs(current.planted.forward - previous.planted.forward));
      }
    }
    expect(Math.max(...drift) / TRAVEL_PER_FRAME).toBeLessThan(0.1);
  });

  it("survives a degenerate rig rather than dividing by zero", () => {
    expect(walkLegAmplitude(0)).toBeGreaterThan(0);
    expect(Number.isFinite(walkLegAmplitude(-1))).toBe(true);
    expect(Number.isFinite(walkLegAmplitude(Number.NaN))).toBe(true);
  });
});

describe("a standing character does not walk", () => {
  it("keeps both feet down and neither sliding, whatever the phase", () => {
    // Phase comes from distance, so a character whose keyframes hold it still never
    // advances the cycle -- it holds the double contact at phase 0 for the whole
    // shot. Its feet stay apart by a stride, which is correct: the script says
    // `walk`, so a walk stance is the honest reading, and pretending otherwise would
    // hide a script that wanted `stand`.
    const rig = characterRig({ height: 1.85, scale: 1 });
    const character = {
      id: "still",
      type: "lowpoly_human",
      appearance: { color: "#4A5568", height: 1.85, scale: 1 },
      keyframes: [
        { frame: 0, position: [0, 0, 0] as [number, number, number], rotation_y: 0, action: "walk" },
        {
          frame: TRAVEL_FRAMES,
          position: [0, 0, 0] as [number, number, number],
          rotation_y: 0,
          action: "walk",
        },
      ],
    };
    const first = legAt(character, rig, 0, "LegL");
    for (const frame of [10, 40, 89]) {
      const left = legAt(character, rig, frame, "LegL");
      expect(left.forward).toBeCloseTo(first.forward, 9);
      expect(left.height).toBeLessThan(0.005);
    }
    // And the separation is a constant stride, not growing: the figure is not
    // quietly taking steps on the spot.
    const separation = Math.abs(
      legAt(character, rig, 89, "LegL").forward - legAt(character, rig, 89, "LegR").forward,
    );
    expect(separation).toBeCloseTo(
      Math.abs(
        legAt(character, rig, 0, "LegL").forward - legAt(character, rig, 0, "LegR").forward,
      ),
      9,
    );
  });
});