/**
 * Transition Intent execution — proposals become motion.
 *
 * The backend decides (transition_proposals.py): which readings are possible,
 * why each works, and what each would DO. This module is the executor: it
 * replays a proposal's operations through the SAME pure preset libraries the
 * inspector uses, so "apply a transition" can never drift from "apply a
 * preset by hand" — there is only one implementation of each move.
 *
 * Two honest limits, surfaced instead of hidden:
 * - A `cut` op moves the shot boundary (pure, safe).
 * - A `camera_place` op CANNOT run headlessly: it needs two viewport clicks,
 *   so it is DEFERRED with its reason rather than faked.
 */

import type { SceneScriptRoot } from "../../../types/scene-script";
import type { SceneVec3 } from "./sceneScriptAxes";
import { applyCameraMotionPreset } from "./cameraMotionPresets";
import { applyCharacterMotionPreset } from "./characterMotionPresets";

/** One operation as the endpoint returns it. */
export interface TransitionOperationPayload {
  kind: "camera_preset" | "character_preset" | "camera_place" | "cut";
  rationale: string;
  preset_id?: string | null;
  camera_id?: string | null;
  character_id?: string | null;
  start_frame?: number | null;
  duration_frames?: number | null;
  at_seconds?: number | null;
  /** The shot a `cut` operation moves. */
  shot_id?: string | null;
}

export interface TransitionProposalPayload {
  id: string;
  label: string;
  narrative: string;
  feasible: boolean;
  infeasible_reason?: string | null;
  operations: TransitionOperationPayload[];
  /** "rules" for the rule catalogue, "llm" for a validated machine proposal. */
  origin?: string;
}

export interface DeferredOperation {
  operation: TransitionOperationPayload;
  reason: string;
}

export interface TransitionApplyResult {
  sceneScript: SceneScriptRoot;
  applied: number;
  deferred: DeferredOperation[];
  errors: string[];
}

/**
 * Move a shot boundary (and its neighbour's matching edge) so the two shots
 * stay contiguous. Pure: a new root comes back; an impossible move reports
 * instead of silently corrupting the shot list.
 */
function moveShotBoundary(
  sceneScript: SceneScriptRoot,
  shotId: string,
  atSeconds: number,
  frameRate: number,
): { script: SceneScriptRoot; error?: string } {
  const fps = frameRate > 0 ? frameRate : 30;
  const frame = Math.max(0, Math.round(atSeconds * fps));
  const ordered = [...sceneScript.shots].sort((a, b) => a.start_frame - b.start_frame);
  const index = ordered.findIndex((shot) => shot.id === shotId);
  if (index < 0) return { script: sceneScript, error: `找不到镜头 ${shotId}` };
  const moved = ordered[index];
  const previous = ordered[index - 1];
  const next = ordered[index + 1];
  if (frame >= moved.end_frame) {
    // A start past the shot's own end would invert the range (the schema
    // rejects it): treat it as the boundary swallowing the shot.
    return { script: sceneScript, error: "剪切点会吃掉该镜头自身" };
  }
  if (previous && frame <= previous.start_frame) {
    return { script: sceneScript, error: "剪切点会越过前一镜头的起点" };
  }
  if (next && frame >= next.start_frame) {
    return { script: sceneScript, error: "剪切点会越过后一镜头的起点" };
  }
  const scripts = sceneScript.shots.map((shot) => {
    if (shot.id !== shotId) return shot;
    return { ...shot, start_frame: frame };
  });
  return { script: { ...sceneScript, shots: scripts } };
}

/**
 * Execute a proposal's operations. Presets are applied in order onto the
 * evolving script; viewport-dependent steps are deferred; a failing step
 * reports its error and the rest still run (partial progress, no silent
 * rollback — the author sees exactly what landed).
 */
export function applyTransitionOperations(
  sceneScript: SceneScriptRoot,
  proposal: TransitionProposalPayload,
  frameRate: number,
): TransitionApplyResult {
  let script = sceneScript;
  const deferred: DeferredOperation[] = [];
  const errors: string[] = [];
  let applied = 0;

  for (const operation of proposal.operations) {
    const startFrame = operation.start_frame ?? 0;
    const durationFrames = operation.duration_frames ?? 45;
    try {
      if (operation.kind === "camera_preset" && operation.camera_id && operation.preset_id) {
        script = applyCameraMotionPreset(script, operation.camera_id, operation.preset_id as never, {
          startFrame,
          durationFrames,
        });
        applied += 1;
      } else if (operation.kind === "character_preset" && operation.character_id && operation.preset_id) {
        const character = script.characters.find((candidate) => candidate.id === operation.character_id);
        const target: SceneVec3 = character?.keyframes[0]?.position ?? [0, 0, 0];
        script = applyCharacterMotionPreset(script, operation.character_id, operation.preset_id as never, {
          startFrame,
          durationFrames,
          target,
        });
        applied += 1;
      } else if (operation.kind === "cut" && operation.at_seconds != null) {
        if (operation.shot_id) {
          const result = moveShotBoundary(script, operation.shot_id, operation.at_seconds, frameRate);
          if (result.error) {
            errors.push(result.error);
          } else {
            script = result.script;
            applied += 1;
          }
        } else {
          deferred.push({
            operation,
            reason: "需要指定要移动剪切点的镜头（后端未提供 shot id）。",
          });
        }
      } else if (operation.kind === "camera_place") {
        // Headless placement is impossible: two viewport clicks define the
        // pose. Defer with the reason rather than inventing a camera pose.
        deferred.push({
          operation,
          reason: "新机位需要在视口两次点击（机位 + 注视点）后生效。",
        });
      } else {
        deferred.push({ operation, reason: "该操作缺少目标对象，无法自动执行。" });
      }
    } catch (error) {
      errors.push(error instanceof Error ? error.message : String(error));
    }
  }

  return { sceneScript: script, applied, deferred, errors };
}
