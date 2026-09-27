/**
 * Cross-shot blocking continuity — the computable core of Continuity State.
 *
 * V0.2 §5 names scene consistency a core problem and gives the exact failure:
 * "上一镜人物向右运动，下一镜突然向左，且没有叙事意图". Two shots that are
 * each fine can still fail the CUT, and the most common way is a character's
 * pose silently disagreeing across the boundary.
 *
 * This module compares, for every adjacent shot pair, each character's EXIT
 * pose (end of A) with their ENTRY pose (start of B):
 *
 * - a FACING flip beyond a threshold (the character apparently turned around
 *   between two shots that share no turn);
 * - a POSITION jump farther than the character could have walked in the gap.
 *
 * Advisory only, like every other check in this family: it never blocks, and
 * every finding carries the remedy (usually "add the keyframe that makes the
 * move real" — the motion presets write it for you).
 *
 * Parity module: `apps/api/app/services/scene3d/blocking_continuity.py`
 * computes the same codes for the pre-render gate; keep them in lockstep.
 */

import type { SceneScriptRoot } from "../../../types/scene-script";
import { characterStateAtFrame } from "./sceneScriptEditModel";

export type ContinuitySeverity = "warning";

export interface BlockingContinuityIssue {
  code: "facing_flip" | "position_jump";
  severity: ContinuitySeverity;
  /** character id. */
  subject: string;
  /** The boundary: "shot_a→shot_b". */
  boundary: string;
  message: string;
  remedy: string;
}

/** A turn larger than this across a cut reads as an unexplained reversal. */
export const FACING_FLIP_THRESHOLD_DEGREES = 90;

/** Comfortable walking speed used to price a gap crossing (m/s). */
export const WALK_SPEED_MPS = 1.2;

/** Slack for keyframe rounding and authored offsets before we call it a jump. */
export const POSITION_JUMP_TOLERANCE_M = 0.35;

/** Shortest absolute angle between two yaws in degrees (0..180). */
export function yawDeltaDegrees(from: number, to: number): number {
  const delta = Math.abs(((to - from + 540) % 360) - 180);
  return delta > 180 ? 360 - delta : delta;
}
function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

export function checkBlockingContinuity(script: SceneScriptRoot): BlockingContinuityIssue[] {
  const shots = [...script.shots].sort((a, b) => a.start_frame - b.start_frame);
  if (shots.length < 2) return [];
  const fps = script.scene.frame_rate > 0 ? script.scene.frame_rate : 30;
  const issues: BlockingContinuityIssue[] = [];

  for (let index = 0; index < shots.length - 1; index += 1) {
    const shotA = shots[index];
    const shotB = shots[index + 1];
    const gapSeconds = Math.max(0, shotB.start_frame - shotA.end_frame) / fps;

    for (const character of script.characters) {
      if (character.keyframes.length === 0) continue;
      const exitPose = characterStateAtFrame(character, shotA.end_frame);
      const entryPose = characterStateAtFrame(character, shotB.start_frame);

      const flip = yawDeltaDegrees(exitPose.rotationY, entryPose.rotationY);
      if (flip > FACING_FLIP_THRESHOLD_DEGREES) {
        issues.push({
          code: "facing_flip",
          severity: "warning",
          subject: character.id,
          boundary: `${shotA.id}→${shotB.id}`,
          message:
            `角色「${character.id}」在 ${shotA.id} 结尾朝 ${round2(exitPose.rotationY)}°，`
            + `到 ${shotB.id} 开头变成 ${round2(entryPose.rotationY)}°（差 ${round2(flip)}°），`
            + "两个镜头之间没有转身。",
          remedy:
            `用「转身面向」预设在两镜之间补一段转身，或在 ${shotB.id} 开头捕获一个关键帧——`
            + "让朝向变化成为有意的表演。",
        });
      }

      const distance = Math.hypot(
        entryPose.position[0] - exitPose.position[0],
        entryPose.position[1] - exitPose.position[1],
        entryPose.position[2] - exitPose.position[2],
      );
      const walkable = WALK_SPEED_MPS * gapSeconds + POSITION_JUMP_TOLERANCE_M;
      if (distance > walkable) {
        issues.push({
          code: "position_jump",
          severity: "warning",
          subject: character.id,
          boundary: `${shotA.id}→${shotB.id}`,
          message:
            `角色「${character.id}」在 ${shotA.id}→${shotB.id} 之间移动了 ${round2(distance)}m，`
            + `而两镜只隔 ${round2(gapSeconds)}s（步行约 ${round2(walkable)}m）：位置跳变了。`,
          remedy:
            "用「走到」预设在两镜之间补一段走位；如果这是有意的时空跳跃，"
            + "就用「时间/空间跳跃」衔接方案把剪切点放进停顿里。",
        });
      }
    }
  }

  return issues;
}
