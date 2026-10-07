import { describe, expect, it } from "vitest";

import {
  CONTINUOUS_CYCLE_SECONDS,
  DOOR_SWING_SECONDS,
  MOTION_STRIDE_METRES,
  cyclePhaseForFrame,
  isNonHumanAction,
  objectMotionAt,
} from "./objectMotion.ts";

/**
 * `DOOR_SWING_OPEN_RADIANS` is module-private in objectMotion.ts (nothing
 * outside the module needs it), so the tests mirror the constant with a comment
 * naming where the real one lives. If the swing distance ever changes there,
 * this is the line that has to change with it.
 */
const DOOR_SWING_OPEN_RADIANS = 1.75;

describe("door_swing_open", () => {
  it("opens smoothly from closed to open across one swing", () => {
    // The swing is one-shot: phase 0 is the authored (closed) rest pose and the
    // far end of the cycle is fully open, so the door starts and ends at a pose
    // a viewer can name rather than mid-way through a motion.
    const closed = objectMotionAt("door_swing_open", 0).rotation;
    expect(closed).toEqual([0, 0, 0]);

    // Phase 1 IS the fully-open rotation. A one-shot clamps rather than wraps,
    // so the end of the swing genuinely holds: a door that has finished
    // opening stays open, instead of snapping shut and starting a second swing
    // on the very next frame.
    const open = objectMotionAt("door_swing_open", 1).rotation;
    expect(open?.[1]).toBeCloseTo(DOOR_SWING_OPEN_RADIANS, 6);

    const mid = objectMotionAt("door_swing_open", 0.5).rotation;
    expect(mid?.[1]).toBeGreaterThan(0);
    expect(mid?.[1]).toBeLessThan(DOOR_SWING_OPEN_RADIANS);
  });

  it("eases in rather than sliding at a constant rate", () => {
    // A hinge has to accelerate: a door a quarter of the way through its swing
    // is nowhere near a quarter open. Asserting the value stays under 0.3 of the
    // full swing catches a swap from smoothstep to a linear ramp, which is the
    // failure that reads as a drawer instead of a door.
    const quarter = objectMotionAt("door_swing_open", 0.25).rotation?.[1] ?? 0;
    expect(quarter).toBeGreaterThan(0);
    expect(quarter).toBeLessThan(0.3 * DOOR_SWING_OPEN_RADIANS);
  });

  it("does not translate; a hinge moves the panel, not the building", () => {
    // A door that slides along its own wall is an entirely different prop.
    for (const phase of [0, 0.25, 0.5, 0.75]) {
      expect(objectMotionAt("door_swing_open", phase).translation).toBeUndefined();
    }
  });
});

describe("spin", () => {
  it("spins at a constant rate: equal phase, equal rotation", () => {
    // Constant angular velocity. The three samples must sit in arithmetic
    // progression — an easing curve would make the deltas grow or shrink, which
    // reads as a wheel speeding up on its own.
    const a = objectMotionAt("spin", 0.25).rotation?.[0] ?? 0;
    const b = objectMotionAt("spin", 0.5).rotation?.[0] ?? 0;
    const c = objectMotionAt("spin", 0.75).rotation?.[0] ?? 0;
    expect(b - a).toBeCloseTo(c - b, 10);
    expect(b - a).toBeGreaterThan(0);
  });

  it("does not translate", () => {
    // A spinning wheel on an axle stays put. A wheel that also travels has been
    // given `drive`'s motion by mistake.
    expect(objectMotionAt("spin", 0.5).translation).toBeUndefined();
  });
});

describe("drive", () => {
  it("translates along +Y and nothing else, one stride per cycle", () => {
    const quarter = objectMotionAt("drive", 0.25).translation;
    expect(quarter).toEqual([0, MOTION_STRIDE_METRES.drive * 0.25, 0]);

    // One full cycle carries exactly the stride. Phase wraps — phase 1 is phase
    // 0 again — so the end of the cycle is the limit approaching 1, which is
    // what the last frame of a 2s drive actually queries.
    const travel = objectMotionAt("drive", 1 - 1e-9).translation?.[1] ?? 0;
    expect(travel).toBeCloseTo(MOTION_STRIDE_METRES.drive, 6);
  });
});

describe("flyover", () => {
  it("crosses laterally at a fixed height", () => {
    const end = objectMotionAt("flyover", 1 - 1e-9).translation;
    expect(end?.[0]).toBeCloseTo(MOTION_STRIDE_METRES.flyover, 6);
    // Height is the camera's business. A pass that also climbs reads as a leaf
    // rather than an aircraft.
    expect(end?.[2]).toBe(0);
  });
});

describe("unknown actions", () => {
  it("returns the zero motion instead of throwing", () => {
    // A script naming an action this build does not implement must render the
    // object at rest — visible and debuggable — rather than fail the frame.
    for (const action of ["walk", null, undefined]) {
      expect(objectMotionAt(action, 0.5)).toEqual({});
    }
  });
});

describe("phase", () => {
  it("wraps for cyclic actions: 1 is 0, and 1.25 is 0.25", () => {
    // Cyclic motions repeat, so their phase is closed at both ends: a caller
    // handing over an unwrapped phase gets the in-cycle value, and phase 1 is
    // phase 0 again rather than running off the end of the curve. That is why
    // the "end of the cycle" assertions for drive and flyover sample 1 - 1e-9.
    expect(objectMotionAt("drive", 1).translation).toEqual(
      objectMotionAt("drive", 0).translation,
    );

    const spin = objectMotionAt("spin", 1.25).rotation;
    const spinQuarter = objectMotionAt("spin", 0.25).rotation;
    expect(spin?.[0]).toBeCloseTo(spinQuarter?.[0] ?? -1, 10);
  });

  it("clamps for the one-shot door: it holds open past its swing", () => {
    // The regression this pins. Phase arrives as elapsed-time-over-cycle, so a
    // door that has been opening longer than its swing shows up with a phase
    // past 1. Wrapping would count that as a second cycle and swing the
    // finished door shut again on the very next frame; clamping holds the end
    // state. Phases 2 and 5 are several whole cycles past the end of the
    // swing — every one of them must still read as fully open.
    for (const phase of [1, 1.25, 2, 5]) {
      const open = objectMotionAt("door_swing_open", phase).rotation;
      expect(open?.[1]).toBeCloseTo(DOOR_SWING_OPEN_RADIANS, 10);
    }

    // Side by side, so neither behaviour can be "fixed" by making everything
    // clamp or everything wrap: drive is cyclic, so the SAME phases wrap back
    // to the start of the cycle — translation back near 0, not held at the end
    // of the stride the way the door holds its end state above.
    for (const phase of [1, 2, 5]) {
      const travel = objectMotionAt("drive", phase).translation?.[1] ?? -1;
      expect(travel).toBeCloseTo(0, 10);
    }

    // ...and a phase between cycles wraps INTO the cycle rather than clamping
    // at its end: 1.25 behaves as 0.25, a stride and a quarter in, where a
    // clamped drive would sit pinned at the far end of the stride.
    const wrapInCycle = objectMotionAt("drive", 1.25).translation?.[1] ?? -1;
    expect(wrapInCycle).toBeCloseTo(MOTION_STRIDE_METRES.drive * 0.25, 10);

    // The clamp is a clamp, not "always the end state": mid-swing is still
    // mid-swing, so the door's closed and half-way assertions elsewhere in
    // this file are what keep the clamp honest.
    const mid = objectMotionAt("door_swing_open", 0.5).rotation?.[1] ?? -1;
    expect(mid).toBeGreaterThan(0);
    expect(mid).toBeLessThan(DOOR_SWING_OPEN_RADIANS);
  });
});

describe("cyclePhaseForFrame", () => {
  it("maps frames onto one cycle, per action length", () => {
    // The human rig derives phase from distance so a walker cannot skate; a
    // non-human actor is defined in cycles per second, so the same function is
    // keyed off the frame clock instead.
    const frameRate = 30;
    expect(cyclePhaseForFrame("spin", 0, frameRate)).toBe(0);
    expect(
      cyclePhaseForFrame("spin", frameRate * CONTINUOUS_CYCLE_SECONDS, frameRate),
    ).toBeCloseTo(1, 10);

    // The door's own duration, not the shared cycle length: half of a 3s swing
    // is phase 0.5, which a 2s continuous cycle would have gotten wrong.
    expect(
      cyclePhaseForFrame(
        "door_swing_open",
        (frameRate * DOOR_SWING_SECONDS) / 2,
        frameRate,
      ),
    ).toBeCloseTo(0.5, 10);
  });
});

describe("isNonHumanAction", () => {
  it("accepts the four non-human actions and rejects human ones", () => {
    for (const action of ["door_swing_open", "spin", "drive", "flyover"]) {
      expect(isNonHumanAction(action)).toBe(true);
    }
    // These belong to characterPose.ts; letting them through would send a
    // human action down the object path and silently render the actor at rest.
    for (const action of ["walk", "stand", "sit", "wave", null]) {
      expect(isNonHumanAction(action)).toBe(false);
    }
  });
});

describe("degenerate inputs", () => {
  it("returns finite phases rather than NaN or Infinity", () => {
    // A zero frame rate is a real state (a paused timeline), and negative frames
    // are what a caller rewinding produces. Neither may poison the caller with
    // NaN, because NaN in a transform is a silently invisible object.
    const frameRate = 30;
    for (const phase of [
      cyclePhaseForFrame("spin", 0, 0),
      cyclePhaseForFrame("door_swing_open", 0, 0),
      cyclePhaseForFrame("spin", -10, frameRate),
      cyclePhaseForFrame("door_swing_open", -10, frameRate),
      cyclePhaseForFrame("spin", 10, -30),
    ]) {
      expect(Number.isFinite(phase)).toBe(true);
    }
    expect(cyclePhaseForFrame("spin", 0, 0)).toBe(0);
  });
});
