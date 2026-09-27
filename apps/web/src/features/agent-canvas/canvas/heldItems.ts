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

/** Horizontal distance from the character's centre to the carrying hand (m). */
export const HAND_REACH_M = 0.32;
/** Hand height as a share of the character's authored height. */
export const HAND_HEIGHT_RATIO = 0.72;
/** An authored position this far from the holder's path is a stale rest position. */
export const AUTHORED_POSITION_SLACK_M = 2.5;

export type HeldSide = "left" | "right";

/** The hand offset in SceneScript space for a character pose. */
export function heldHandOffset(
  rotationY: number,
  side: HeldSide | null | undefined,
  height: number,
): SceneVec3 {
  const yaw = (rotationY * Math.PI) / 180;
  const sign = side === "left" ? -1 : 1;
  return [
    sign * HAND_REACH_M * Math.cos(yaw),
    -sign * HAND_REACH_M * Math.sin(yaw),
    height * HAND_HEIGHT_RATIO,
  ];
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
