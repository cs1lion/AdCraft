/**
 * Compare-grade ("微调") nudge commands for the director command bar.
 *
 * The highest-frequency director commands aren't presets ("orbit 90°") but
 * small relative tweaks against the current state of the selected object:
 * "大一点" "往左" "升高" "转 90 度". These are pure, deterministic, one-step
 * edits that need no LLM and no backend round trip — they ride the editor's
 * existing onChange pipeline (the same channel a drag uses), so undo/save and
 * the consistency mirror treat them exactly like any other local edit.
 *
 * Axes: X = right, Y = forward, Z = up (scene coords, per ADR 0005 §1 and
 * sceneScriptAxes.ts). "升高" therefore adds to Z, not Y.
 */

import type { SceneScriptRoot } from "../../../types/scene-script";
import type { SceneVec3 } from "./sceneScriptAxes.ts";
import type { SceneObjectRef } from "./sceneScriptEditModel.ts";
import {
  characterStateAtFrame,
  moveCharacterAtFrame,
  moveCameraAtFrame,
  moveProp,
  moveEnvironment,
  rotateCharacterAtFrame,
  rotateStaticObject,
  scaleStaticObject,
} from "./sceneScriptEditModel.ts";

/** A relative tweak the director can issue against the selected object. */
export type NudgeCommand =
  | "bigger"
  | "smaller"
  | "left"
  | "right"
  | "forward"
  | "backward"
  | "raise"
  | "lower"
  | "turn_left"
  | "turn_right";

export const NUDGE_COMMANDS: readonly NudgeCommand[] = [
  "bigger",
  "smaller",
  "left",
  "right",
  "forward",
  "backward",
  "raise",
  "lower",
  "turn_left",
  "turn_right",
];

export const NUDGE_LABELS: Record<NudgeCommand, string> = {
  bigger: "大一点",
  smaller: "小一点",
  left: "往左",
  right: "往右",
  forward: "往前",
  backward: "往后",
  raise: "升高",
  lower: "降低",
  turn_left: "左转",
  turn_right: "右转",
};

/** Per-command step, in meters (translate) or degrees (turn) or scale factor. */
const TRANSLATE_STEP = 0.25;
const LIFT_STEP = 0.2;
const TURN_STEP = 45;

/** Which commands are available for a given object kind. */
export function availableNudgesFor(kind: SceneObjectRef["kind"]): NudgeCommand[] {
  switch (kind) {
    case "prop":
    case "environment":
      return [
        "bigger",
        "smaller",
        "left",
        "right",
        "forward",
        "backward",
        "raise",
        "lower",
        "turn_left",
        "turn_right",
      ];
    case "camera":
      // A camera translates and lifts; it aims via look_at, not a rotation
      // field, so no turn commands.
      return [
        "left",
        "right",
        "forward",
        "backward",
        "raise",
        "lower",
      ];
    case "character":
      // A character translates on the ground plane and turns; it has no
      // scale field in the schema (scale is appearance, not motion).
      return [
        "left",
        "right",
        "forward",
        "backward",
        "turn_left",
        "turn_right",
      ];
  }
}

/**
 * Apply a nudge to the script. Returns a NEW script (never mutates) via the
 * edit model's kind-appropriate primitive, so the object's current position
 * is the basis ("以当前状态为基准").
 *
 * @param script the current scene
 * @param ref which object to nudge
 * @param frame the playhead frame (for characters/cameras whose pose is
 *   per-frame; ignored for static props/environment whose position is fixed)
 * @param command the nudge
 */
export function applyNudge(
  script: SceneScriptRoot,
  ref: SceneObjectRef,
  frame: number,
  command: NudgeCommand,
): SceneScriptRoot {
  const delta: SceneVec3 = [0, 0, 0];
  const isTurn = command === "turn_left" || command === "turn_right";
  const sign =
    command === "left" || command === "turn_right"
      ? -1
      : command === "right" || command === "turn_left"
        ? 1
        : 0;

  switch (command) {
    case "left":
      delta[0] = -TRANSLATE_STEP;
      break;
    case "right":
      delta[0] = TRANSLATE_STEP;
      break;
    case "forward":
      delta[1] = TRANSLATE_STEP;
      break;
    case "backward":
      delta[1] = -TRANSLATE_STEP;
      break;
    case "raise":
      delta[2] = LIFT_STEP;
      break;
    case "lower":
      delta[2] = -LIFT_STEP;
      break;
    case "bigger":
    case "smaller":
    case "turn_left":
    case "turn_right":
      // handled below
      break;
  }

  switch (ref.kind) {
    case "prop":
    case "environment": {
      const object =
        ref.kind === "prop"
          ? script.props.find((candidate) => candidate.id === ref.id)
          : script.environment.find((candidate) => candidate.id === ref.id);
      if (!object) return script;
      if (command === "bigger") {
        const baseScale = object.scale ?? 1;
        return scaleStaticObject(script, "prop", ref.id, baseScale * 1.25);
      }
      if (command === "smaller") {
        const baseScale = object.scale ?? 1;
        return scaleStaticObject(script, "prop", ref.id, baseScale * 0.8);
      }
      if (command === "turn_left" || command === "turn_right") {
        const baseRotation = object.rotation_y ?? 0;
        const next = baseRotation + (command === "turn_left" ? -TURN_STEP : TURN_STEP);
        return rotateStaticObject(script, ref.kind, ref.id, next);
      }
      const next: SceneVec3 = [
        object.position[0] + delta[0],
        object.position[1] + delta[1],
        object.position[2] + delta[2],
      ];
      return ref.kind === "prop" ? moveProp(script, ref.id, next) : moveEnvironment(script, ref.id, next);
    }

    case "camera": {
      const camera = script.cameras.find((candidate) => candidate.id === ref.id);
      if (!camera) return script;
      // A camera's resting position is its frame-0 keyframe; nudge that.
      const base = camera.keyframes[0]?.position ?? [0, 0, 1.6];
      const next: SceneVec3 = [
        base[0] + delta[0],
        base[1] + delta[1],
        base[2] + delta[2],
      ];
      return moveCameraAtFrame(script, ref.id, 0, next);
    }

    case "character": {
      const character = script.characters.find((candidate) => candidate.id === ref.id);
      if (!character) return script;
      if (command === "turn_left" || command === "turn_right") {
        const currentYaw = characterStateAtFrame(character, frame).rotationY;
        const next = currentYaw + (command === "turn_left" ? -TURN_STEP : TURN_STEP);
        return rotateCharacterAtFrame(script, ref.id, frame, next);
      }
      const current = characterStateAtFrame(character, frame).position;
      const next: SceneVec3 = [
        current[0] + delta[0],
        current[1] + delta[1],
        current[2] + delta[2],
      ];
      return moveCharacterAtFrame(script, ref.id, frame, next);
    }
  }
}

/** Whether a nudge is legal for the selected kind (drives button enabling). */
export function nudgeAvailable(
  kind: SceneObjectRef["kind"],
  command: NudgeCommand,
): boolean {
  return availableNudgesFor(kind).includes(command);
}
