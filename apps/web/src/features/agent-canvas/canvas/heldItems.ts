/**
 * Held items — the client half of the Continuity State prop dimension.
 *
 * Parity module for `apps/api/app/services/scene3d/held_items.py`: keep the
 * constants and the math in lockstep (the test file pins both sides). The
 * point of the whole feature (V0.2 §5): "Scene 01 里女孩右手拿伞，Scene 02
 * 变成左手" must stop being POSSIBLE — a held prop rides the holder's hand on
 * every surface (this preview and the Blender render), so there is one item
 * in one hand for the whole scene.
 *
 * SceneScript yaw convention: 0 = facing +Y, 90 = facing +X, so facing is
 * (sin yaw, cos yaw) and the right hand is facing rotated -90 degrees
 * (cos yaw, -sin yaw) — face north, right hand east.
 */

import type { SceneProp, SceneScriptRoot } from "../../../types/scene-script";
import type { SceneVec3 } from "./sceneScriptAxes";
import { characterStateAtFrame } from "./sceneScriptEditModel";
import {
  CHARACTER_RIG_FRACTIONS_MIRROR,
  HOLD_GRIP,
} from "../../../types/scene-script.generated";

/**
 * DEPRECATED as a constant, kept so the name still resolves. This was a fixed 0.32 m
 * and matched the rig only for a 1.75 m figure -- see `heldItemGripGeometry`.
 */
export const HAND_REACH_M = 0.32;
/** An authored position this far from the holder's path is a stale rest position. */
export const AUTHORED_POSITION_SLACK_M = 2.5;

export type HeldSide = "left" | "right";

/** The hand offset in SceneScript space for a character pose. */
/**
 * One arm's chain, from the rig's own proportions.
 *
 * The arm is a rigid box pivoting at the shoulder, so the hand sits on a circle of
 * radius ``length`` about it: pitched forward by ``armPitch`` it reaches
 * ``length*sin(armPitch)`` in front of the chest axis and rises to
 * ``shoulder - length*cos(armPitch)``. Both scale with height, which is why the
 * held-item offset used to be wrong for everyone except a 1.75 m figure.
 *
 * The fractions come from the generated mirror of the rig's own table rather than
 * being repeated here, so a change to the rig cannot leave this stale.
 */
export interface HeldItemGripGeometry {
  /** Shoulder height in metres. */
  shoulderHeight: number;
  /** Where the hand hangs with the arm down. */
  restHandHeight: number;
  /** Arm length in metres: hip-to-wrist with the arm straight. */
  length: number;
  /** Out to the side of the chest axis. */
  lateral: number;
  /** In front of the chest axis once the arm is raised to the grip. */
  forward: number;
  /** Forward pitch, radians, that brings the hand up to the grip. */
  armPitch: number;
}

/** Hand height as a share of the character's authored height. */
export const HAND_HEIGHT_RATIO = HOLD_GRIP.gripHeightRatio;

export function heldItemGripGeometry(height: number): HeldItemGripGeometry {
  const f = CHARACTER_RIG_FRACTIONS_MIRROR;
  const torsoTop = (f.leg + f.torso) * height;
  const length = f.arm * height;
  const shoulderHeight = torsoTop - length * f.armHang + length / 2;
  const lateral = (f.torsoWidth * height) / 2 + f.limbWidth * height * f.armOutset;
  // Both the shoulder and the grip target are proportional to height, so this
  // ratio is the same number for every figure -- hence the constant in HOLD_GRIP
  // rather than a per-character recomputation.
  const ratio = (shoulderHeight - height * HOLD_GRIP.gripHeightRatio) / length;
  const armPitch = Math.acos(Math.max(-1, Math.min(1, ratio)));
  return {
    shoulderHeight,
    restHandHeight: shoulderHeight - length,
    length,
    lateral,
    forward: length * Math.sin(armPitch),
    armPitch,
  };
}

/**
 * Where a held item sits, so its GRIP lands in the carrying hand.
 *
 * Every component is DERIVED from the rig (`heldItemGripGeometry`), not typed in.
 * The old version used a fixed 0.32 m reach, which matches the rig's arm lateral for
 * a 1.75 m figure and for no other size -- so a 1.1 m character's weapon sat 60%
 * further outboard than their hand, and nothing noticed because neither this file
 * nor the pose library said where the arm ended.
 */
export function heldHandOffset(
  rotationY: number,
  side: HeldSide | null | undefined,
  height: number,
  /** The held prop's kind and scale, so its GRIP lands in the hand, not its origin. */
  kind?: string,
  scale = 1,
): SceneVec3 {
  const yaw = (rotationY * Math.PI) / 180;
  const sign = side === "left" ? -1 : 1;
  const arm = heldItemGripGeometry(height);
  // The two horizontal components the rig actually produces, rotated into the
  // character's facing: lateral is out to the side, forward is how far in front of
  // the chest axis a raised arm ends up.
  const lateral = arm.lateral * Math.cos(yaw) - arm.forward * Math.sin(yaw);
  const forward = arm.lateral * Math.sin(yaw) + arm.forward * Math.cos(yaw);
  // A prop's origin is where it stands, not where it is held: a `weapon` carries its
  // grip 0.32 of its scale above its origin with the blade a metre above that, so
  // without this the first render of the grip fix held the sword BY THE BLADE.
  const gripRatio = HOLD_GRIP.kindGripRatio[kind as "weapon"] ?? 0;
  return [sign * lateral, sign * forward, height * HAND_HEIGHT_RATIO - gripRatio * scale];
}

/**
 * Where a held prop sits at `frame` (the holder's hand). Returns null when
 * the prop is not held or its holder is missing — callers keep the authored
 * position in that case.
 */
export function heldItemPositionAtFrame(
  script: SceneScriptRoot,
  prop: SceneProp,
  frame: number,
): SceneVec3 | null {
  if (!prop.held_by) return null;
  const character = script.characters.find((candidate) => candidate.id === prop.held_by);
  if (!character) return null;
  const state = characterStateAtFrame(character, frame);
  const offset = heldHandOffset(
    state.rotationY,
    prop.held_side ?? "right",
    character.appearance?.height ?? 1.7,
    prop.type,
    prop.scale ?? 1,
  );
  return [
    state.position[0] + offset[0],
    state.position[1] + offset[1],
    state.position[2] + offset[2],
  ];
}

/**
 * The effective render position for a prop at `frame`: the hand position when
 * held, the authored position otherwise. One function both the preview and
 * the tests call, so "where does the umbrella render" has one answer.
 */
export function effectivePropPositionAtFrame(
  script: SceneScriptRoot,
  prop: SceneProp,
  frame: number,
): SceneVec3 {
  return heldItemPositionAtFrame(script, prop, frame) ?? prop.position;
}
