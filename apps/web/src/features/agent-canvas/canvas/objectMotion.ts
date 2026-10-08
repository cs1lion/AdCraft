/**
 * ObjectMotion — what a NON-HUMAN actor does, per frame.
 *
 * WHY THIS IS SEPARATE FROM characterPose.ts
 * `characterPose.ts` answers "how does this seven-box figure stand, walk, sit".
 * That presumes a body: legs to swing, a torso to lean, a head to tilt. A door,
 * a wheel and a dropship have none of those, and forcing them into
 * `SegmentPose`'s vocabulary would mean pretending a hinge is a hip.
 *
 * So this module is one level down: it produces a DELTA applied to an object's
 * own rest pose — a rotation about an axis, a translation, a scale. A human
 * figure's walk is one special case of that (each box rotating about its top end
 * is a rotation), which is why the two modules coexist without one being a
 * rewrite of the other. Unifying them is a real option and deliberately not
 * taken: it would mean rewriting the walk that already works to serve four
 * motions that do not exist yet.
 *
 * PHASE, NOT TIME
 * Like `segmentPoseAt`, every function takes `phase` in 0..1 (one full cycle)
 * rather than a frame. The caller derives phase from what the action is — a
 * door's from how long it has been opening, a wheel's from the wall clock — so
 * nothing here needs to know about frames and every curve is testable without
 * a clock.
 *
 * FIDELITY
 * Sines and ramps. At white-model previs fidelity that is the point: a wheel
 * spinning at a constant rate reads as a wheel, and a curve that can be checked
 * beats one that is slightly better and cannot be. If fidelity ever needs to
 * rise, the curves live in exactly one place.
 */

/** A per-frame delta from the object's authored rest pose. */
export interface ObjectMotion {
  /** Radians about [x, y, z], applied at the object's pivot. */
  rotation?: [number, number, number];
  /** Metres added to the authored position. */
  translation?: [number, number, number];
}

export type NonHumanAction =
  | "door_swing_open"
  | "spin"
  | "drive"
  | "flyover";

import { OBJECT_MOTION_CONSTANTS } from "../../../types/scene-script.generated";

const {
  driveStrideMetres: DRIVE_STRIDE_METRES,
  flyoverStrideMetres: FLYOVER_STRIDE_METRES,
  doorSwingSeconds: DOOR_SWING_SECONDS,
  continuousCycleSeconds: CONTINUOUS_CYCLE_SECONDS,
  doorSwingOpenRadians: DOOR_SWING_OPEN_RADIANS,
} = OBJECT_MOTION_CONSTANTS;

/** How far one cycle carries a moving actor, in metres. */
export const MOTION_STRIDE_METRES: Record<"drive" | "flyover", number> = {
  drive: DRIVE_STRIDE_METRES,
  flyover: FLYOVER_STRIDE_METRES,
};

// Re-exported so a caller can reason about the phase without recomputing it -- and so
// the parity fixture cannot silently lose a value by importing a name that is no
// longer exported and having JSON.stringify drop the resulting undefined.
export { DOOR_SWING_SECONDS, CONTINUOUS_CYCLE_SECONDS, DOOR_SWING_OPEN_RADIANS };

/**
 * The motion for `action` at `phase` (0..1, one full cycle).
 *
 * Cyclic actions (spin, drive, flyover) wrap at one cycle — a wheel that
 * stopped at phase 1 would read as broken, not as turning. One-shot actions
 * (door_swing_open) clamp instead: phase past 1 holds the end state, because
 * a door that has finished opening has nothing left to do.
 *
 * Returns the zero motion for an unrecognised action rather than throwing: a
 * script naming an action this build does not implement should render the
 * object at its rest pose, which is visible and debuggable, rather than fail
 * the whole frame over one prop.
 */
export function objectMotionAt(
  action: string | null | undefined,
  phase: number,
): ObjectMotion {
  // WHY wrap and clamp differ: phase is elapsed-time-over-cycle, so only a
  // motion that repeats can use the whole range. A wheel must keep turning
  // past phase 1, so cyclic actions wrap; a door must not — wrapping a
  // one-shot counts a second cycle and swings the finished door shut again
  // on the very next frame (a door that reopens is a metronome). Clamping a
  // one-shot to [0, 1] holds the end state instead of restarting.
  const p =
    action === "door_swing_open"
      ? Math.min(1, Math.max(0, phase))
      : ((phase % 1) + 1) % 1;
  switch (action) {
    case "door_swing_open":
      // Ease-in-out: a door starts and ends slowly, which is most of what
      // separates a hinge from a linear slide. Smoothstep, because it needs no
      // trig and is trivially checkable.
      return { rotation: [0, smoothstep(p) * DOOR_SWING_OPEN_RADIANS, 0] };

    case "spin":
      // Constant rate. A wheel that accelerates mid-frame reads as a bug, not
      // as a vehicle starting up.
      return { rotation: [p * Math.PI * 2, 0, 0] };

    case "drive":
      return { translation: [0, p * MOTION_STRIDE_METRES.drive, 0] };

    case "flyover":
      // Crosses the frame laterally while holding height, which is what a
      // flyover reads as. Rise and fall is left to the camera work; a pass that
      // also bobs reads as a leaf, not an aircraft.
      return { translation: [p * MOTION_STRIDE_METRES.flyover, 0, 0] };

    default:
      return {};
  }
}

/**
 * Cycle phase from a frame and a cycle length in seconds.
 *
 * The distance-driven variant used by the human rig (`cyclePhaseForDistance`)
 * exists because a walking figure must not skate. A non-human actor's motion is
 * defined in cycles per second here: a door opens once across its shot, a wheel
 * turns continuously. Neither is distance-derived, so neither should pretend
 * to be.
 */
export function cyclePhaseForFrame(
  action: string | null | undefined,
  frame: number,
  frameRate: number,
): number {
  const seconds =
    action === "door_swing_open" ? DOOR_SWING_SECONDS : CONTINUOUS_CYCLE_SECONDS;
  if (!Number.isFinite(seconds) || seconds <= 0 || frameRate <= 0) return 0;
  return frame / frameRate / seconds;
}

/** True when `action` is one this module can drive. */
export function isNonHumanAction(
  action: string | null | undefined,
): action is NonHumanAction {
  return (
    action === "door_swing_open"
    || action === "spin"
    || action === "drive"
    || action === "flyover"
  );
}

/** Cubic smoothstep, 0 at 0 and 1 at 1, zero slope at both ends. */
function smoothstep(t: number): number {
  const x = Math.min(1, Math.max(0, t));
  return x * x * (3 - 2 * x);
}
