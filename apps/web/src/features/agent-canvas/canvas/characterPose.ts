/**
 * Action poses — what the seven segments do for each `CharacterAction`.
 *
 * WHY THIS EXISTS
 * `SceneCharacter.keyframes[].action` declares one of stand / talk / walk / sit /
 * gesture, and until this module existed exactly two of the five did anything:
 * `talk` opened the mouth, `gesture` tilted the head 15°. `walk` — the one that
 * matters most in a previs — slid the whole body along the ground with its limbs
 * welded in place, because the rig built the limbs once and never rotated them
 * again. The schema has said "walk" all along; nothing translated it.
 *
 * WHAT A POSE IS, AND WHY IT IS NOT "JOINT ANGLES"
 * A pose here is a small set of PITCHES in radians about the segment's proximal
 * end, per segment, plus a phase. Not a skeleton: the rig is seven boxes
 * (`lowPolyHumanRig.ts`), there are no bones to rotate, and inventing a skeleton
 * would be a much larger change than the problem needs. Rotating each box about
 * its top end gives a limb that swings from the hip or shoulder, which is what a
 * walk cycle actually reads as.
 *
 * The curves are sines. At previs fidelity that is deliberate: a white-model
 * figure at 2 m on screen does not need a heel strike, and a cycle that is easy
 * to state and easy to verify beats one that is slightly better and cannot be
 * checked. If it ever needs to be better, the data is already in one place.
 *
 * PHASE, AND THE SLIDING QUESTION
 * `action` is a STEP: a keyframe's action governs frames at and after it, never
 * before (`characterActionAtFrame`). Position and yaw INTERPOLATE
 * (`characterStateAtFrame`). Those two are deliberate and are not changed here.
 *
 * A walking figure must not moonwalk, so the cycle advances with how far the
 * character has actually travelled rather than with wall-clock time: a character
 * whose keyframes hold it still keeps both feet down, and one that moves gets
 * steps proportional to its speed. Stride length is therefore a function of
 * distance, which is what makes the feet appear to stay on the ground.
 */

import type { CharacterRig } from "./lowPolyHumanRig";

/** The actions the schema declares. Every one of these must have a pose. */
export const CHARACTER_ACTIONS = ["stand", "talk", "walk", "sit", "gesture"] as const;
export type CharacterAction = (typeof CHARACTER_ACTIONS)[number];

/**
 * Radians of pitch about the segment's proximal end, per segment.
 *
 * Pitch is about the axis across the figure's facing direction, so a positive
 * value swings the segment FORWARD. Every field defaults to 0, so an action that
 * only moves one limb says so and leaves the rest alone.
 */
export interface SegmentPose {
  /** Hips: positive swings the segment forward, negative swings it back. */
  legL?: number;
  legR?: number;
  /** Shoulders: same sense as the legs. */
  armL?: number;
  armR?: number;
  /** Whole upper body, about the hip line. Small values only. */
  torso?: number;
  /** About the neck, where the head hangs. */
  head?: number;
  /** About the waist — the torso's own hinge, so the body can lean. */
  spine?: number;
  /** Vertical offset as a fraction of body height; a walk bobs. */
  bob?: number;
}

/**
 * How long one full cycle of each action takes, in seconds.
 *
 * `Infinity` for the actions that are a held shape rather than a cycle: a
 * standing figure's legs are not "mid-stride", they are together. Treating a
 * static pose as a zero-amplitude cycle would be equivalent, but naming it says
 * what is meant.
 */
export const ACTION_CYCLE_SECONDS: Record<CharacterAction, number> = {
  stand: Infinity,
  talk: Infinity,
  sit: Infinity,
  gesture: Infinity,
  walk: 1.0,
};

/** Amplitudes, in radians, per action. Kept beside the curves so both are one read. */
const POSE = {
  /** Half a stride: legs 32 degrees out, arms counter-swinging. */
  walk: {
    leg: 0.56,
    arm: 0.42,
    /** One step of vertical travel per full cycle — the body's own rise and fall. */
    bob: 0.018,
    /** A little counter-rotation, which is most of what makes a walk read as one. */
    torso: 0.06,
  },
  /** Held: feet slightly apart, arms down and a little forward. */
  stand: { legSpread: 0.05, armRest: 0.08 },
  /** Held, plus the gesture: one arm up and out, torso leaning into it. */
  gesture: { armRaise: 0.9, armOut: 0.35, torso: 0.12, head: -0.2 },
  /** Held: knees bent and torso tipped forward, as if on something low. */
  sit: { thighLift: 1.15, torso: 0.22, head: 0.05 },
  /** Held: one hand forward at waist height, as if mid-explanation. */
  talk: { arm: 0.35, torso: 0.04 },
} as const;

/** Metres per stride cycle. A 1 s cycle at this length is a normal adult walk. */
export const WALK_STRIDE_METRES = 1.4;

/**
 * The pose for `action` at `cyclePhase` (0..1, one full cycle).
 *
 * `cyclePhase` is supplied rather than computed here so this stays pure and
 * testable; `cyclePhaseFor` is the part that knows about frames.
 */
export function segmentPoseAt(
  action: string | null | undefined,
  cyclePhase: number,
): SegmentPose {
  const phase = ((cyclePhase % 1) + 1) % 1;
  // theta runs 0..2π across the cycle, so the figures start at a double contact
  // pose (both feet down) rather than mid-stride.
  const theta = phase * Math.PI * 2;
  const sine = Math.sin(theta);
  const cosine = Math.cos(theta);

  switch (action) {
    case "walk": {
      const { leg, arm, bob, torso } = POSE.walk;
      return {
        // Legs half a cycle apart; the knees never bend at this fidelity.
        legL: leg * sine,
        legR: -leg * sine,
        // Arms counter-swing the legs. Without this the figure reads as a
        // scissoring puppet, which is the whole difference between "walking"
        // and "sliding".
        armL: -arm * sine,
        armR: arm * sine,
        // Highest at mid-stance, lowest at the double contact.
        bob: -bob * (0.5 - 0.5 * cosine),
        torso: torso * sine,
        head: -torso * sine * 0.5,
      };
    }
    case "gesture": {
      const { armRaise, armOut, torso, head } = POSE.gesture;
      return {
        armR: armRaise,
        armL: -armOut,
        torso,
        head,
      };
    }
    case "talk": {
      const { arm, torso } = POSE.talk;
      return { armR: arm, armL: -arm * 0.4, torso, head: -torso };
    }
    case "sit": {
      const { thighLift, torso, head } = POSE.sit;
      return { legL: thighLift, legR: thighLift, torso, head };
    }
    case "stand":
    default: {
      const { legSpread, armRest } = POSE.stand;
      return {
        legL: legSpread,
        legR: -legSpread,
        armL: armRest,
        armR: -armRest,
      };
    }
  }
}

/**
 * The cycle phase for a character that has travelled `distanceMetres` since the
 * animation began.
 *
 * Distance, not time: a character that stands still must keep both feet on the
 * ground, and a character that runs takes more steps per second than one that
 * walks. Distance gives both for free, and it cannot desynchronise from the
 * motion the way a wall clock does.
 */
export function cyclePhaseForDistance(distanceMetres: number): number {
  if (!(distanceMetres > 0) || !Number.isFinite(distanceMetres)) return 0;
  return distanceMetres / WALK_STRIDE_METRES;
}

/**
 * How far a character has travelled from `start` to `frame`, following the same
 * interpolation the preview uses for position. Keeping this on the same curve as
 * `characterStateAtFrame` is the point: if the two disagreed, the feet would
 * skate.
 */
export function travelledMetres(
  positions: readonly (readonly [number, number, number])[],
  frames: readonly number[],
  frame: number,
): number {
  if (positions.length < 2) return 0;
  const ordered = positions
    .map((position, index) => ({ frame: frames[index], position }))
    .sort((left, right) => left.frame - right.frame);
  // Before the first keyframe the character has not started moving. Without this
  // the tail below measures from the LAST keyframe back to the start and
  // reports the whole path twice over — a character standing at frame 0 came out
  // as having already walked 16 m, which put its walk cycle at phase 11 and its
  // legs in a pose determined by nothing.
  if (frame <= ordered[0].frame) return 0;
  const total = (at: number): readonly [number, number, number] => {
    if (at <= ordered[0].frame) return ordered[0].position;
    const last = ordered[ordered.length - 1];
    if (at >= last.frame) return last.position;
    for (let index = 0; index < ordered.length - 1; index += 1) {
      const a = ordered[index];
      const b = ordered[index + 1];
      if (at >= a.frame && at <= b.frame) {
        const span = b.frame - a.frame || 1;
        const t = (at - a.frame) / span;
        return [0, 1, 2].map((axis) =>
          a.position[axis] + (b.position[axis] - a.position[axis]) * t,
        ) as [number, number, number];
      }
    }
    return last.position;
  };
  // Walk the keyframes in order and stop at the ones the playhead has passed.
  // Summing the WHOLE path and then measuring back from the end (which this did)
  // double-counts: a character a third of the way through reported 14 m of travel
  // when it had made 2, putting the walk cycle at a phase determined by frames
  // that have not happened yet.
  let distance = 0;
  let previous = ordered[0].position;
  for (let index = 1; index < ordered.length; index += 1) {
    const step = ordered[index];
    if (step.frame >= frame) break;
    distance += Math.hypot(
      step.position[0] - previous[0],
      step.position[1] - previous[1],
      step.position[2] - previous[2],
    );
    previous = step.position;
  }
  const tail = total(frame);
  distance += Math.hypot(
    tail[0] - previous[0],
    tail[1] - previous[1],
    tail[2] - previous[2],
  );
  return distance;
}

/**
 * The vertical offset a pose implies, in metres, for a rig of this height.
 *
 * Separate from the pitch table because a bob is a TRANSLATION and everything
 * else is a rotation: multiplying a bob by a limb length is how a walk ends up
 * bouncing a metre off the ground.
 */
export function bobOffset(pose: SegmentPose, rig: CharacterRig): number {
  return (pose.bob ?? 0) * rig.height;
}