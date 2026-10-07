import { describe, expect, it } from "vitest";

import {
  ACTION_CYCLE_SECONDS,
  CHARACTER_ACTIONS,
  bobOffset,
  cyclePhaseForDistance,
  segmentPoseAt,
  travelledMetres,
  walkStrideMetres,
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
    // Sampled off the quarter cycle rather than ON it. A rigid leg passing through
    // vertical puts both legs at zero angle at phase 0.25 -- one at mid-stance, the
    // other at mid-swing -- so that instant says nothing about opposition. A real
    // knee would bend the swing leg clear of the floor there; this rig has none, so
    // the honest sample is where the legs are actually apart.
    for (const phase of [0.125, 0.375]) {
      const pose = segmentPoseAt("walk", phase);
      expect(Math.sign(pose.legL ?? 0)).toBe(-Math.sign(pose.legR ?? 0));
      // And they must be meaningfully apart, not merely oppositely signed at zero.
      expect(Math.abs(pose.legL ?? 0)).toBeGreaterThan(0.1);
    }
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

  it("bobs by centimetres, and by no more than the foot needs", () => {
    // The bob is not decoration: it is the hip compensation that holds the planted
    // foot on the floor. A rigid leg's reach is shortest when it points straight
    // down, so without it the stance foot lifts by L*(1-cos A) at heel strike.
    //
    // Its size is therefore pinned from below by that requirement rather than by a
    // taste judgement, and bounded above by plausibility. The old 5 cm ceiling was a
    // guess that happened to exclude the 6.9 cm the compensation actually needs on a
    // 1.85 m figure -- which is why it has to be derived, not guessed.
    const rig = characterRig({ height: DEFAULT_CHARACTER_HEIGHT, scale: 1 });
    const extremes = [0, 0.125, 0.25, 0.375, 0.5, 0.75].map(
      (phase) => Math.abs(bobOffset(segmentPoseAt("walk", phase, { legLengthMetres: rig.legLength }), rig)),
    );
    const largest = Math.max(...extremes);
    expect(largest).toBeGreaterThan(0);
    // Human hip travel over a stride is a few centimetres; a decimetre would be a
    // limp. See walkGait.test.ts for the measurement that this clears.
    expect(largest).toBeLessThan(0.1);
  });

  it("bobs at twice the leg rate, lowest at each double contact", () => {
    // One dip per cycle reads as limping. A walker passes through two double
    // supports per stride -- one at each end of each stance -- so the body dips
    // twice and rises at each mid-stance. Both facts fall out of the same
    // expression, so they are asserted together.
    const poseAt = (phase: number) => segmentPoseAt("walk", phase).bob ?? 0;
    const minimum = Math.min(...[0, 0.5].map(poseAt));
    const maximum = Math.max(...[0.25, 0.75].map(poseAt));
    expect(minimum).toBeLessThan(-0.01);
    expect(maximum).toBeGreaterThan(minimum);
    // And the peak must be strictly between the double supports, not at one.
    expect(poseAt(0.25)).toBeGreaterThan(poseAt(0));
    expect(poseAt(0.75)).toBeGreaterThan(poseAt(0.5));
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
    // The reference leg is passed explicitly because the stride is proportional to
    // the leg: on the figure `WALK_STRIDE_METRES` was measured on, one stride is
    // exactly one cycle, which is the property the tests below rely on.
    expect(cyclePhaseForDistance(1.4, 0.925)).toBeCloseTo(1, 9);
  });

  it("travels the same distance per cycle whatever the speed", () => {
    // A fast character takes more steps per second, which is what distance-based
    // phase gives for free and what a wall clock cannot.
    expect(cyclePhaseForDistance(2.8, 0.925)).toBeCloseTo(2, 9);
  });

  it("shortens the stride for a shorter leg, so it takes more steps per metre", () => {
    // One number decides both the phase and the leg angle, so a child covers less
    // ground per step instead of swinging its legs impossibly far.
    const adult = cyclePhaseForDistance(1.4, 0.925);
    const child = cyclePhaseForDistance(1.4, 0.5);
    expect(child).toBeGreaterThan(adult);
    expect(child).toBeCloseTo(1.4 / walkStrideMetres(0.5), 9);
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