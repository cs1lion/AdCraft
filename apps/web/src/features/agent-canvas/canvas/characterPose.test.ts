import { describe, expect, it } from "vitest";

import {
  ACTION_CYCLE_SECONDS,
  CHARACTER_ACTIONS,
  bobOffset,
  cyclePhaseForDistance,
  segmentPoseAt,
  travelledMetres,
} from "./characterPose";
import { characterRig, DEFAULT_CHARACTER_HEIGHT } from "./lowPolyHumanRig";

/**
 * The walk cycle is the whole point of this module, so most of what is asserted
 * here is about motion rather than about numbers.
 *
 * Two failure modes get a dedicated test because both produce a figure that
 * looks alive-ish and is wrong:
 *
 *   - the limbs not counter-swinging, which reads as a scissoring puppet;
 *   - the cycle advancing with WALL CLOCK rather than with distance travelled,
 *     which makes a standing character march on the spot and a fast one waddle.
 *
 * The second one is why `cyclePhaseForDistance` takes metres rather than
 * seconds. Asserting on "phase advances when time passes" would have locked in
 * exactly the wrong design.
 */

const DEGREES = 180 / Math.PI;

describe("every declared action has a pose", () => {
  it.each(CHARACTER_ACTIONS)("%s produces a pose", (action) => {
    // `stand` is the fallback, so a typo'd action would pass this by landing on
    // it. The per-action tests below are what make the five distinct.
    const pose = segmentPoseAt(action, 0.25);
    expect(pose).toBeTypeOf("object");
  });

  it("an unknown action falls back to standing rather than throwing", () => {
    // The schema is `extra="forbid"`, so this cannot come from a valid script —
    // but a missing pose must not take the whole render down with it.
    expect(() => segmentPoseAt("moonwalk", 0.5)).not.toThrow();
  });

  it("only walk has a cycle; the rest are held shapes", () => {
    // Naming the static ones Infinity says what is meant. Treating "stand" as a
    // zero-amplitude cycle would compute the same numbers and mean nothing.
    for (const action of CHARACTER_ACTIONS) {
      const expected = action === "walk" ? 1.0 : Infinity;
      expect(ACTION_CYCLE_SECONDS[action]).toBe(expected);
    }
  });
});

describe("walk", () => {
  it("swings the legs in opposite directions", () => {
    const quarter = segmentPoseAt("walk", 0.25);
    expect(quarter.legL).toBeGreaterThan(0.2);
    expect(quarter.legR).toBeLessThan(-0.2);
  });

  it("counter-swings the arms against the legs", () => {
    // Without this the figure is a scissoring puppet, which is the difference
    // between "walking" and "sliding" and the reason this module exists.
    for (const phase of [0.125, 0.375, 0.625, 0.875]) {
      const pose = segmentPoseAt("walk", phase);
      expect(Math.sign(pose.armL ?? 0)).toBe(-Math.sign(pose.legL ?? 0));
      expect(Math.sign(pose.armR ?? 0)).toBe(-Math.sign(pose.legR ?? 0));
    }
  });

  it("stands both feet down at the start and end of a cycle", () => {
    // Phase 0 and 1 are the same instant — a double contact. If they differ,
    // the loop is not a loop and a standing character visibly jumps.
    const start = segmentPoseAt("walk", 0);
    const end = segmentPoseAt("walk", 1);
    expect(start.legL).toBeCloseTo(end.legL ?? 0, 9);
    expect(start.legR).toBeCloseTo(end.legR ?? 0, 9);
  });

  it("is continuous across the wrap", () => {
    // Compare the STEP across the wrap with the step of the same size elsewhere,
    // rather than comparing two samples that are two hundredths of a cycle
    // apart and expecting them equal. A sine at phase 0.999 and 0.001 differs by
    // a real, tiny amount; what must not happen is a JUMP, and a jump shows up as
    // the wrap step being larger than an interior step of the same width.
    const width = 0.002;
    const step = (from: number) =>
      Math.abs((segmentPoseAt("walk", from + width).legL ?? 0) - (segmentPoseAt("walk", from).legL ?? 0));
    const acrossWrap = step(1 - width);
    const interior = Math.max(step(0.25), step(0.5), step(0.75));
    expect(acrossWrap).toBeLessThanOrEqual(interior * 1.05);
  });

  it("bobs by centimetres, not by metres", () => {
    // A bob is a translation. Scaling it by a limb length instead is how a walk
    // ends up bouncing the figure off the ground.
    const rig = characterRig({ height: DEFAULT_CHARACTER_HEIGHT, scale: 1 });
    const extremes = [0, 0.25, 0.5, 0.75].map(
      (phase) => Math.abs(bobOffset(segmentPoseAt("walk", phase), rig)),
    );
    const largest = Math.max(...extremes);
    expect(largest).toBeGreaterThan(0);
    expect(largest).toBeLessThan(0.05);
  });
});

describe("the held poses are distinguishable", () => {
  it("gesture raises an arm; stand does not", () => {
    const gesture = segmentPoseAt("gesture", 0.5);
    const stand = segmentPoseAt("stand", 0.5);
    expect((gesture.armR ?? 0) * DEGREES).toBeGreaterThan(45);
    expect(Math.abs(stand.armR ?? 0) * DEGREES).toBeLessThan(10);
  });

  it("sit bends both legs far more than stand does", () => {
    const sit = segmentPoseAt("sit", 0.5);
    const stand = segmentPoseAt("stand", 0.5);
    expect(Math.abs(sit.legL ?? 0)).toBeGreaterThan(Math.abs(stand.legL ?? 0) + 0.5);
  });

  it("none of the held poses bobs", () => {
    // Only walking has vertical travel. A bobbing standing figure is a tell.
    for (const action of ["stand", "talk", "sit", "gesture"]) {
      expect(segmentPoseAt(action, 0.33).bob ?? 0).toBe(0);
    }
  });

  it("a held pose does not depend on the cycle phase", () => {
    // The strongest statement that they are held: sampling anywhere gives the
    // same numbers, so passing a moving phase to them is harmless.
    for (const action of ["stand", "talk", "sit", "gesture"]) {
      const first = segmentPoseAt(action, 0.1);
      const second = segmentPoseAt(action, 0.9);
      expect(first).toEqual(second);
    }
  });
});

describe("cycle phase comes from distance, not from the clock", () => {
  it("a character that has not moved stands still", () => {
    expect(cyclePhaseForDistance(0)).toBe(0);
    expect(cyclePhaseForDistance(-3)).toBe(0);
    expect(cyclePhaseForDistance(Number.NaN)).toBe(0);
  });

  it("takes one full stride per cycle length", () => {
    expect(cyclePhaseForDistance(1.4)).toBeCloseTo(1, 9);
  });

  it("travels the same distance per cycle whatever the speed", () => {
    // A fast character takes more steps per second, which is what distance-based
    // phase gives for free and what a wall clock cannot.
    expect(cyclePhaseForDistance(2.8)).toBeCloseTo(2, 9);
  });
});

describe("travelledMetres follows the same interpolation the preview uses", () => {
  const positions: [number, number, number][] = [
    [0, 0, 0],
    [0, 4, 0],
    [0, 8, 0],
  ];
  const frames = [0, 60, 120];

  it("is zero at the first keyframe", () => {
    expect(travelledMetres(positions, frames, 0)).toBe(0);
  });

  it("sums the authored path", () => {
    expect(travelledMetres(positions, frames, 120)).toBeCloseTo(8, 6);
  });

  it("is proportional in between, so the feet do not skate", () => {
    // Halfway through the first leg is half of it — which is the property that
    // makes distance-based phase agree with the interpolated position.
    expect(travelledMetres(positions, frames, 30)).toBeCloseTo(2, 6);
  });

  it("handles keyframes given out of order", () => {
    const shuffled: [number, number, number][] = [
      [0, 8, 0],
      [0, 0, 0],
      [0, 4, 0],
    ];
    const shuffledFrames = [120, 0, 60];
    expect(travelledMetres(shuffled, shuffledFrames, 120)).toBeCloseTo(8, 6);
  });

  it("is zero for a character with a single keyframe", () => {
    expect(travelledMetres([[1, 1, 1]], [0], 30)).toBe(0);
  });
});