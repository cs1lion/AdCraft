/**
 * Camera motion presets — the "参考运镜" library for the 3D workbench.
 *
 * Hand-authoring an orbit or a push-in means computing keyframes by hand;
 * a preset writes them for you. Two design rules make them trustworthy:
 *
 * 1. SAMPLED, not two-point: the renderer interpolates camera keyframes
 *    LINEARLY, so an orbit described by start + end would cut a chord across
 *    the arc. Each preset emits samples along the real path (every
 *    ``sample_step_frames``), so linear playback traces the curve.
 * 2. The preset owns its window: it replaces keyframes INSIDE
 *    [start, start + duration] and leaves everything else untouched, so
 *    re-applying a longer move over a shorter one extends it instead of
 *    stacking contradictory keys.
 *
 * Coordinates are SceneScript space (Blender Z-up: x=right, y=forward,
 * z=up); the single conversion point (sceneScriptAxes) happens at render.
 */

import type { CameraKeyframe, SceneScriptRoot } from "../../../types/scene-script.ts";

export type CameraMotionPresetId =
  | "push_in"
  | "pull_out"
  | "orbit_left"
  | "orbit_right"
  | "pan_left"
  | "pan_right"
  | "crane_up"
  | "crane_down";

export interface CameraMotionPreset {
  id: CameraMotionPresetId;
  /** UI label (Chinese, like the rest of the workbench). */
  label: string;
  /** One-line explanation of what the camera will do. */
  description: string;
}

export const CAMERA_MOTION_PRESETS: readonly CameraMotionPreset[] = [
  { id: "push_in", label: "推近", description: "机位向注视点推进，压迫感/聚焦" },
  { id: "pull_out", label: "拉远", description: "机位退离注视点，揭示环境" },
  { id: "orbit_left", label: "左环绕", description: "绕注视点水平逆时针环绕，展示空间关系" },
  { id: "orbit_right", label: "右环绕", description: "绕注视点水平顺时针环绕" },
  { id: "pan_left", label: "左摇", description: "机位不动，注视点左移，扫视" },
  { id: "pan_right", label: "右摇", description: "机位不动，注视点右移" },
  { id: "crane_up", label: "升臂", description: "机位抬升，注视点跟随下沉" },
  { id: "crane_down", label: "降臂", description: "机位下降，注视点跟随上抬" },
];

/** Keyframe density along the path (30fps: 15 frames = 0.5s per sample). */
export const CAMERA_MOTION_SAMPLE_STEP_FRAMES = 15;

export class UnknownCameraPresetError extends Error {
  readonly code = "camera_preset_unknown";

  constructor(presetId: string) {
    super(`Unknown camera motion preset: ${presetId}`);
    this.name = "UnknownCameraPresetError";
  }
}

export interface CameraMotionOptions {
  /** First frame of the move (inclusive). */
  startFrame: number;
  /** Move length in frames (>= 1). */
  durationFrames: number;
}

function distance(a: readonly number[], b: readonly number[]): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

function normalize(v: readonly number[]): [number, number, number] {
  const length = Math.hypot(v[0], v[1], v[2]);
  if (length < 1e-9) return [0, 0, 0];
  return [v[0] / length, v[1] / length, v[2] / length];
}

/**
 * The keyframe governing `startFrame` — the motion's anchor. Falls back to
 * the first keyframe so the preset still works on a camera whose authored
 * keys start later (the move then begins from that authored pose).
 */
function anchorKeyframe(cameraKeyframes: readonly CameraKeyframe[], startFrame: number) {
  if (cameraKeyframes.length === 0) {
    return { frame: startFrame, position: [0, 0, 0] as [number, number, number], look_at: [0, 0, 1] as [number, number, number] };
  }
  const atOrBefore = [...cameraKeyframes]
    .filter((keyframe) => keyframe.frame <= startFrame)
    .sort((a, b) => b.frame - a.frame)[0];
  const chosen = atOrBefore ?? cameraKeyframes[0];
  return {
    frame: chosen.frame,
    position: [...chosen.position] as [number, number, number],
    look_at: [...(chosen.look_at ?? [0, 0, 1])] as [number, number, number],
  };
}

/**
 * Sample the preset path from the anchor pose. Returns keyframes covering
 * [startFrame, startFrame + duration] inclusive of both ends.
 */
function samplePreset(
  presetId: CameraMotionPresetId,
  anchor: { position: [number, number, number]; look_at: [number, number, number] },
  options: CameraMotionOptions,
): CameraKeyframe[] {
  const { startFrame, durationFrames } = options;
  const step = Math.max(1, CAMERA_MOTION_SAMPLE_STEP_FRAMES);
  const frames: number[] = [];
  for (let frame = startFrame; frame <= startFrame + durationFrames; frame += step) {
    frames.push(frame);
  }
  if (frames[frames.length - 1] !== startFrame + durationFrames) {
    frames.push(startFrame + durationFrames);
  }

  const [px, py, pz] = anchor.position;
  const [lx, ly, lz] = anchor.look_at;
  const radius = Math.max(distance(anchor.position, anchor.look_at), 0.001);

  return frames.map((frame) => {
    const t = durationFrames === 0 ? 0 : (frame - startFrame) / durationFrames;
    let position: [number, number, number] = [px, py, pz];
    let lookAt: [number, number, number] = [lx, ly, lz];

    switch (presetId) {
      case "push_in": {
        const dir = normalize([lx - px, ly - py, lz - pz]);
        const offset = radius * 0.5 * t;
        position = [px + dir[0] * offset, py + dir[1] * offset, pz + dir[2] * offset];
        break;
      }
      case "pull_out": {
        const dir = normalize([px - lx, py - ly, pz - lz]);
        const offset = radius * 0.5 * t;
        position = [px + dir[0] * offset, py + dir[1] * offset, pz + dir[2] * offset];
        break;
      }
      case "orbit_left":
      case "orbit_right": {
        // Horizontal orbit around the look-at point (x=right, y=forward).
        const angle = (Math.PI / 2) * t * (presetId === "orbit_left" ? 1 : -1);
        const dx = px - lx;
        const dy = py - ly;
        const cos = Math.cos(angle);
        const sin = Math.sin(angle);
        position = [lx + dx * cos - dy * sin, ly + dx * sin + dy * cos, pz];
        break;
      }
      case "pan_left":
      case "pan_right": {
        // Camera stays; the gaze sweeps around the vertical axis through it.
        const angle = (Math.PI / 3) * t * (presetId === "pan_left" ? 1 : -1);
        const dx = lx - px;
        const dy = ly - py;
        const cos = Math.cos(angle);
        const sin = Math.sin(angle);
        lookAt = [px + dx * cos - dy * sin, py + dx * sin + dy * cos, lz];
        break;
      }
      case "crane_up":
      case "crane_down": {
        const rise = 1.2 * t * (presetId === "crane_up" ? 1 : -1);
        position = [px, py, pz + rise];
        // The gaze follows the rise by half, so the horizon drifts instead of
        // whipping when the arm extends.
        lookAt = [lx, ly, lz + rise * 0.5];
        break;
      }
    }
    return { frame, position, look_at: lookAt };
  });
}

/**
 * Apply a motion preset to a camera, replacing keyframes inside the window.
 * Pure: returns a new SceneScriptRoot; unknown presets fail loud.
 */
export function applyCameraMotionPreset(
  sceneScript: SceneScriptRoot,
  cameraId: string,
  presetId: CameraMotionPresetId,
  options: CameraMotionOptions,
): SceneScriptRoot {
  if (!CAMERA_MOTION_PRESETS.some((preset) => preset.id === presetId)) {
    throw new UnknownCameraPresetError(presetId);
  }
  const camera = sceneScript.cameras.find((candidate) => candidate.id === cameraId);
  if (!camera) {
    throw new Error(`Camera not found: ${cameraId}`);
  }
  const startFrame = Math.max(0, Math.round(options.startFrame));
  const durationFrames = Math.max(1, Math.round(options.durationFrames));
  const anchor = anchorKeyframe(camera.keyframes, startFrame);
  const sampled = samplePreset(presetId, anchor, { startFrame, durationFrames });

  const endFrame = startFrame + durationFrames;
  return replaceCameraKeyframesInWindow(
    sceneScript,
    cameraId,
    sampled,
    { startFrame, durationFrames },
  );
}

/**
 * Merge authored keyframes into a camera's [start, start + duration] window:
 * keys inside the window are replaced, everything outside survives, and the
 * result stays frame-ordered with no duplicates. The single merge point for
 * EVERY camera keyframe writer (presets, gesture paths, future importers) —
 * one implementation means one set of invariants.
 */
export function replaceCameraKeyframesInWindow(
  sceneScript: SceneScriptRoot,
  cameraId: string,
  keyframes: readonly CameraKeyframe[],
  window: { startFrame: number; durationFrames: number },
): SceneScriptRoot {
  const camera = sceneScript.cameras.find((candidate) => candidate.id === cameraId);
  if (!camera) {
    throw new Error(`Camera not found: ${cameraId}`);
  }
  const endFrame = window.startFrame + window.durationFrames;
  const outside = camera.keyframes.filter(
    (keyframe) => keyframe.frame < window.startFrame || keyframe.frame > endFrame,
  );
  const nextKeyframes = [...outside, ...keyframes].sort((a, b) => a.frame - b.frame);
  return {
    ...sceneScript,
    cameras: sceneScript.cameras.map((candidate) =>
      candidate.id === cameraId ? { ...candidate, keyframes: nextKeyframes } : candidate,
    ),
  };
}
