/**
 * Client-side mirror of the scene-3d consistency gate.
 *
 * The backend (`apps/api/app/services/scene3d/scene_consistency.py`) is the
 * gate of record — the node executor publishes its report and the
 * `/scene-3d/consistency-check` endpoint is the pre-render gate. This module
 * mirrors its five checks for LIVE feedback in the workbench: the author
 * sees "character_unbound" the moment they build a second shot, not after
 * they hit render.
 *
 * Keep the codes in lockstep with the backend module (same code strings, same
 * trigger conditions); the test file pins both the codes and the parity
 * expectations. If the backend adds a check, this mirror must too — the
 * banner is only useful when it tells the same truth as the gate.
 */

import type { SceneScriptRoot } from "../../../types/scene-script";
import {
  AUTHORED_POSITION_SLACK_M,
  heldItemPositionAtFrame,
} from "./heldItems";

export type SceneConsistencySeverity = "error" | "warning";

export interface SceneConsistencyIssue {
  code: string;
  severity: SceneConsistencySeverity;
  /** The object id (or a human label like "frames 51-99") the issue is about. */
  subject: string;
  message: string;
  remedy: string;
}

export function checkSceneScriptConsistency(
  script: SceneScriptRoot,
): SceneConsistencyIssue[] {
  const issues: SceneConsistencyIssue[] = [];
  const multiShot = script.shots.length > 1;

  // 1. Unbound characters in multi-shot scenes (the Dramagic core check).
  if (multiShot) {
    for (const character of script.characters) {
      if (!character.character_asset_id) {
        issues.push({
          code: "character_unbound",
          severity: "warning",
          subject: character.id,
          message: `角色「${character.id}」在 ${script.shots.length} 个镜头的场景里没有绑定角色资产。`,
          remedy: "在检查器里绑定角色资产，让后续镜头与视频模型保持同一身份。",
        });
      }
    }
  }

  // 2. Color collisions: color IS the identity channel in low-fidelity.
  const byColor = new Map<string, string[]>();
  for (const character of script.characters) {
    const color = (character.appearance?.color ?? "").trim().toLowerCase();
    if (!color) continue;
    const bucket = byColor.get(color) ?? [];
    bucket.push(character.id);
    byColor.set(color, bucket);
  }
  for (const [color, ids] of byColor) {
    if (ids.length > 1) {
      issues.push({
        code: "character_color_collision",
        severity: "warning",
        subject: [...ids].sort().join(", "),
        message: `角色 ${[...ids].sort().join("、")} 使用同一外观色 ${color}，低保真预览无法区分。`,
        remedy: "为每个角色设置不同的外观色。",
      });
    }
  }

  // 3. Cameras no shot references.
  const usedCameras = new Set(script.shots.map((shot) => shot.camera));
  for (const camera of script.cameras) {
    if (!usedCameras.has(camera.id)) {
      issues.push({
        code: "camera_unused",
        severity: "warning",
        subject: camera.id,
        message: `相机「${camera.id}」没有被任何镜头引用。`,
        remedy: "从某个镜头引用它，或移除它。",
      });
    }
  }

  // 4. Shot coverage gaps over the full timeline.
  const totalFrames = Math.round(script.scene.duration * script.scene.frame_rate);
  const covered = script.shots
    .map((shot) => [shot.start_frame, shot.end_frame] as [number, number])
    .sort((a, b) => a[0] - b[0]);
  const gaps: [number, number][] = [];
  let cursor = 0;
  for (const [start, end] of covered) {
    if (start > cursor) gaps.push([cursor, start - 1]);
    cursor = Math.max(cursor, end + 1);
  }
  if (cursor <= totalFrames - 1) gaps.push([cursor, totalFrames - 1]);
  for (const [start, end] of gaps) {
    issues.push({
      code: "shot_coverage_gap",
      severity: "warning",
      subject: `frames ${start}-${end}`,
      message: `第 ${start}-${end} 帧（共 ${totalFrames} 帧）没有任何镜头覆盖。`,
      remedy: "延长某个镜头的范围，或为这段空缺添加镜头。",
    });
  }

  // 5. Empty scenes.
  if (
    script.characters.length === 0
    && script.props.length === 0
    && script.environment.length === 0
  ) {
    issues.push({
      code: "scene_empty",
      severity: "warning",
      subject: "scene",
      message: "场景里没有角色、道具或环境物体。",
      remedy: "渲染预演前至少添加一个物体。",
    });
  }

  // 6. Held items (Continuity State's prop dimension, V0.2 §5) — mirror of
  //    `held_items.py`'s declaration checks; the FOLLOW itself (the prop
  //    riding the holder's hand) lives in heldItems.ts and is applied by the
  //    preview and the Blender converter, so it needs no advisory.
  const heldProps = script.props.filter((prop) => prop.held_by);
  if (heldProps.length > 0) {
    const handClaims = new Map<string, string[]>();
    for (const prop of heldProps) {
      const key = `${prop.held_by}/${prop.held_side ?? "right"}`;
      const bucket = handClaims.get(key) ?? [];
      bucket.push(prop.id);
      handClaims.set(key, bucket);
    }
    for (const [key, propIds] of handClaims) {
      if (propIds.length <= 1) continue;
      const [characterId, side] = key.split("/");
      const sorted = [...propIds].sort();
      issues.push({
        code: "held_item_hand_conflict",
        severity: "warning",
        subject: sorted.join(", "),
        message: `道具 ${sorted.join("、")} 都声明由角色「${characterId}」的${
          side === "left" ? "左" : "右"
        }手持有：一只手放不下两件东西。`,
        remedy: "把其中一件改成另一只手，或取消它的持有者。",
      });
    }
    for (const prop of heldProps) {
      const character = script.characters.find(
        (candidate) => candidate.id === prop.held_by,
      );
      if (!character) continue;
      const distances = held_keyframe_distances(script, prop, character);
      if (distances.length > 0 && Math.min(...distances) > AUTHORED_POSITION_SLACK_M) {
        issues.push({
          code: "held_item_authored_position_far",
          severity: "warning",
          subject: prop.id,
          message: `道具「${prop.id}」声明由角色「${character.id}」持有，但它的位置离该角色的全部关键帧至少 ${Math.min(
            ...distances,
          ).toFixed(2)}m：渲染将以角色手部为准，手写位置只是未持有时的地方。`,
          remedy: "如需固定摆放，取消它的持有者；确认持有则忽略此条。",
        });
      }
    }
  }

  return issues;
}

/** The codes the backend gate can emit (parity contract for this mirror). */
export const SCENE_CONSISTENCY_CODES = [
  "character_unbound",
  "character_color_collision",
  "camera_unused",
  "shot_coverage_gap",
  "scene_empty",
  "held_item_hand_conflict",
  "held_item_authored_position_far",
] as const;

/**
 * Distance from the prop's authored position to every hand position along the
 * holder's path (one per authored keyframe — the same frames the Blender
 * converter writes). Local helper so the mirror needs no extra export.
 */
function held_keyframe_distances(
  script: SceneScriptRoot,
  prop: SceneScriptRoot["props"][number],
  character: SceneScriptRoot["characters"][number],
): number[] {
  return character.keyframes.map((keyframe) => {
    const hand = heldItemPositionAtFrame(script, prop, keyframe.frame) ?? prop.position;
    return Math.hypot(
      prop.position[0] - hand[0],
      prop.position[1] - hand[1],
      prop.position[2] - hand[2],
    );
  });
}
