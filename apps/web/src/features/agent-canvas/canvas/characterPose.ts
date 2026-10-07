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
  walk: {
    /**
     * Arms counter-swing the legs. Expressed as a fraction of the leg amplitude so
     * the opposition is exact by construction rather than by two sines happening to
     * be out of phase: the arm swings with the same rhythm as the SAME-SIDE leg,
     * in the opposite direction.
     */
    armOverLeg: 0.75,
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

/** Metres per stride cycle for the reference figure. A normal adult walk. */
export const WALK_STRIDE_METRES = 1.4;

/** The leg of the figure {@link WALK_STRIDE_METRES} was measured on: height 1.85. */
const REFERENCE_LEG_LENGTH_METRES = 0.925;

/** How much of the cycle a leg spends with its foot on the ground. */
const STANCE_FRACTION = 0.5;

/**
 * Steepest leg swing allowed, radians (~36 degrees).
 *
 * A leg that would need more than this covers a shorter stride instead. Previs
 * figures are sometimes very short, and a 90-degree hip reads as a breakdancer
 * rather than a walk.
 */
const WALK_MAX_LEG_RADIANS = 0.62;

/** Leg length assumed when a caller does not know the rig. Height 1.7, so 0.5 x 1.7. */
const DEFAULT_LEG_LENGTH_METRES = 0.85;

/**
 * The stride a leg of this length covers, in metres.
 *
 * Proportional to the leg, because a stride is a reach: scaling it keeps
 * ``stride / (4L)`` -- and therefore the leg angle -- the same for every figure, so
 * a child takes shorter steps rather than swinging harder. Since the phase comes
 * from distance travelled, this is also what decides how many steps per metre a
 * figure takes, so it must be the SAME number the amplitude is derived from.
 *
 * Derived separately in two places it was the source of a measured defect: the
 * phase advanced as if the stride were 1.4 m while the geometry only supported less,
 * and a 1.1 m figure skated at 19% of its own travel.
 */
export function walkStrideMetres(legLengthMetres = DEFAULT_LEG_LENGTH_METRES): number {
  const length = legLengthMetres > 0 ? legLengthMetres : DEFAULT_LEG_LENGTH_METRES;
  const proportional = (WALK_STRIDE_METRES * length) / REFERENCE_LEG_LENGTH_METRES;
  // The longest stride this leg could plant without exceeding the angle limit.
  const reachable = 4 * length * Math.sin(WALK_MAX_LEG_RADIANS);
  return Math.min(proportional, reachable);
}

/**
 * The leg angle a no-slide walk needs, for a given leg length.
 *
 * A planted foot does not move, so over one stance the hip must advance exactly as
 * far as ``L*sin(theta)`` retreats: ``2*L*sin(A) = stride/2``, hence
 * ``sin(A) = stride / (4L)``.
 *
 * This is not a stylistic constant. With the previous fixed 0.56 rad the stance
 * foot slid 134 mm per frame while the body moved 40 mm -- the figure skated 332%
 * faster than it walked, which is what "moonwalk" means. Deriving the angle from
 * the stride and the leg is what pins the foot down.
 */
export function walkLegAmplitude(legLengthMetres = DEFAULT_LEG_LENGTH_METRES): number {
  const length = legLengthMetres > 0 ? legLengthMetres : DEFAULT_LEG_LENGTH_METRES;
  return Math.asin(Math.min(1, walkStrideMetres(legLengthMetres) / (4 * length)));
}

/**
 * Leg angle as a fraction of the amplitude, over one cycle.
 *
 * The sign is the whole of the no-slide property, so it is worth stating. A
 * planted foot means ``hip - L*sin(theta)`` is constant, so ``L*sin(theta)`` must
 * RISE as the hip advances: the leg starts at ``-A`` with the foot AHEAD of the
 * hip at heel strike, and ends at ``+A`` with the foot behind it at toe off. Get
 * this backwards and the stance foot skates forward at 212% of the body's own
 * travel -- the same defect, only with the sign flipped.
 *
 * Stance is LINEAR and swing a raised cosine, and the split matters as much as the
 * sign: a sine is steepest exactly where the foot meets the ground, so it slides
 * hardest at the contact it is supposed to be planting. A linear stance sweeps
 * ``-A`` to ``+A`` at the rate that keeps the foot still; the swing then eases the
 * leg forward, fastest through vertical where it has to clear.
 */
function walkLegShape(q: number): number {
  const t = ((q % 1) + 1) % 1;
  if (t < STANCE_FRACTION) return -1 + (2 * t) / STANCE_FRACTION;
  const swing = (t - STANCE_FRACTION) / (1 - STANCE_FRACTION);
  return 1 - 2 * (0.5 - 0.5 * Math.cos(Math.PI * swing));
}

/**
 * The pose for `action` at `cyclePhase` (0..1, one full cycle).
 *
 * `cyclePhase` is supplied rather than computed here so this stays pure and
 * testable; `cyclePhaseFor` is the part that knows about frames.
 *
 * `legLengthMetres` is the rig's own leg length, and `walk` needs it: the leg
 * amplitude is derived from the stride and the leg so the stance foot stays put
 * (see `walkLegAmplitude`). Omitting it falls back to an average adult leg, which
 * is right for a test and wrong for a 1.1 m child.
 */
export function segmentPoseAt(
  action: string | null | undefined,
  cyclePhase: number,
  options: { legLengthMetres?: number } = {},
): SegmentPose {
  const phase = ((cyclePhase % 1) + 1) % 1;
  // theta runs 0..2π across the cycle, so the figures start at a double contact
  // pose (both feet down) rather than mid-stride.
  const theta = phase * Math.PI * 2;
  const sine = Math.sin(theta);
  const cosine = Math.cos(theta);

  switch (action) {
    case "walk": {
      const { armOverLeg, torso } = POSE.walk;
      const amplitude = walkLegAmplitude(options.legLengthMetres);
      const left = walkLegShape(phase);
      const right = walkLegShape(phase + STANCE_FRACTION);
      const legL = amplitude * left;
      const legR = amplitude * right;
      // Whichever leg is on the ground drives the hip. A rigid leg's reach is
      // shortest when it points straight down, so holding the hip still would lift
      // the planted foot by L*(1-cos A) -- 69 mm on a 1.85 m figure. Letting the hip
      // follow puts the foot back on the floor and, as a side effect, produces the
      // real thing: the body dips at each double contact and rises at each
      // mid-stance, so the bob runs at twice the leg rate.
      const stance = phase < STANCE_FRACTION ? left : right;
      return {
        legL,
        legR,
        // Same rhythm, opposite direction, scaled off the leg's own shape.
        armL: -amplitude * armOverLeg * left,
        armR: -amplitude * armOverLeg * right,
        // Fraction of body height; the leg is half of it, hence the 0.5.
        bob: -0.5 * (1 - Math.cos(amplitude * stance)),
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
 *
 * `legLengthMetres` must be the same rig the pose is built with, because the stride
 * is proportional to the leg: it decides both how many steps per metre a figure
 * takes and the angle that plants the foot, and the two only agree when they come
 * from one number.
 */
export function cyclePhaseForDistance(
  distanceMetres: number,
  legLengthMetres = DEFAULT_LEG_LENGTH_METRES,
): number {
  if (!(distanceMetres > 0) || !Number.isFinite(distanceMetres)) return 0;
  return distanceMetres / walkStrideMetres(legLengthMetres);
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