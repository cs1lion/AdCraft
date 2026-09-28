/**
 * Director motion vocabulary shared by the left 3D preview and backend ops.
 *
 * This module adds the intent-level bridge from the earlier discussion:
 * natural-language camera/character intents are expanded into the same
 * deterministic presets already shipped in cameraMotionPresets and
 * characterMotionPresets. The preview can apply the result optimistically,
 * while the director command bar sends the same intent through the existing
 * backend apply-operations contract.
 */

import type {
  CameraKeyframe,
  CharacterKeyframe,
  SceneScriptRoot,
} from "../../../types/scene-script";
import type { SceneVec3 } from "./sceneScriptAxes.ts";
import {
  applyCameraMotionPreset,
  CAMERA_MOTION_PRESETS,
  type CameraMotionPresetId,
  type CameraMotionOptions,
} from "./cameraMotionPresets.ts";
import {
  applyCharacterMotionPreset,
  CHARACTER_MOTION_PRESETS,
  type CharacterMotionOptions,
  type CharacterMotionPresetId,
} from "./characterMotionPresets.ts";

export type DirectorMotionIntent = "camera_motion" | "character_motion";

export interface DirectorMotionCommand {
  intent: DirectorMotionIntent;
  targetId: string;
  presetId: string;
  startFrame: number;
  durationFrames: number;
  targetPosition?: SceneVec3;
  stopDistance?: number;
  /** The backend's POST /director-motion request body (single source of truth). */
  request: {
    intent: DirectorMotionIntent;
    target_id: string;
    preset_id: string;
    start_frame: number;
    duration_frames: number;
    target_position?: SceneVec3;
    stop_distance?: number;
  };
  operations: unknown[];
  previewScript: SceneScriptRoot;
}

export interface DirectorMotionOptions {
  intent: DirectorMotionIntent;
  targetId: string;
  presetId: string;
  startFrame?: number;
  durationFrames?: number;
  targetPosition?: SceneVec3;
  stopDistance?: number;
}

export function listDirectorMotionPresetIds(intent: DirectorMotionIntent): string[] {
  if (intent === "camera_motion") {
    return CAMERA_MOTION_PRESETS.map((preset) => preset.id);
  }
  return CHARACTER_MOTION_PRESETS.map((preset) => preset.id);
}

export function expandDirectorMotionIntent(
  sceneScript: SceneScriptRoot,
  options: DirectorMotionOptions,
): DirectorMotionCommand {
  const {
    intent,
    targetId,
    presetId,
    startFrame = 0,
    durationFrames = 30,
    targetPosition = [0, 0, 0],
    stopDistance,
  } = options;

  if (intent === "camera_motion") {
    const previewScript = applyCameraMotionPreset(
      sceneScript,
      targetId,
      presetId as CameraMotionPresetId,
      { startFrame, durationFrames } satisfies CameraMotionOptions,
    );
    const operations = cameraMotionOps(targetId, presetId, startFrame, durationFrames, previewScript);
    const request: DirectorMotionCommand["request"] = {
      intent: "camera_motion",
      target_id: targetId,
      preset_id: presetId,
      start_frame: startFrame,
      duration_frames: durationFrames,
    };
    if (stopDistance != null) request.stop_distance = stopDistance;

    return {
      intent,
      targetId,
      presetId,
      startFrame,
      durationFrames,
      request,
      operations,
      previewScript,
    };
  }

  const previewScript = applyCharacterMotionPreset(
    sceneScript,
    targetId,
    presetId as CharacterMotionPresetId,
    {
      startFrame,
      durationFrames,
      target: targetPosition as unknown as SceneVec3,
      stopDistance,
    } satisfies CharacterMotionOptions,
  );
  const operations = characterMotionOps(
    targetId,
    presetId,
    startFrame,
    durationFrames,
    targetPosition,
    previewScript,
  );
  return {
    intent,
    targetId,
    presetId,
    startFrame,
    durationFrames,
    targetPosition,
    stopDistance,
    request: {
      intent: "character_motion",
      target_id: targetId,
      preset_id: presetId,
      start_frame: startFrame,
      duration_frames: durationFrames,
      target_position: targetPosition,
      stop_distance: stopDistance ?? 1.2,
    },
    operations,
    previewScript,
  };
}

function cameraMotionOps(
  cameraId: string,
  presetId: string,
  startFrame: number,
  durationFrames: number,
  previewScript: SceneScriptRoot,
): Record<string, unknown>[] {
  const camera = previewScript.cameras.find((candidate) => candidate.id === cameraId);
  if (!camera) {
    return [];
  }
  const keyframes = camera.keyframes
    .filter(
      (keyframe: CameraKeyframe) =>
        keyframe.frame >= startFrame && keyframe.frame <= startFrame + durationFrames,
    )
    .sort((a, b) => a.frame - b.frame);
  return keyframes.map((keyframe: CameraKeyframe) => ({
    op: "add_keyframe",
    kind: "camera",
    id: cameraId,
    frame: keyframe.frame,
    position: keyframe.position,
    look_at: keyframe.look_at,
  }));
}

function characterMotionOps(
  characterId: string,
  presetId: string,
  startFrame: number,
  durationFrames: number,
  targetPosition: SceneVec3,
  previewScript: SceneScriptRoot,
): Record<string, unknown>[] {
  const character = previewScript.characters.find((candidate) => candidate.id === characterId);
  if (!character) {
    return [];
  }
  const keyframes = character.keyframes
    .filter(
      (keyframe: CharacterKeyframe) =>
        keyframe.frame >= startFrame && keyframe.frame <= startFrame + durationFrames,
    )
    .sort((a, b) => a.frame - b.frame);
  return keyframes.map((keyframe: CharacterKeyframe) => ({
    op: "add_keyframe",
    kind: "character",
    id: characterId,
    frame: keyframe.frame,
    position: keyframe.position,
    rotation_y: keyframe.rotation_y,
    action: keyframe.action,
  }));
}
