/**
 * Draw-a-path camera motion — the gesture half of camera control.
 *
 * The parametric presets (cameraMotionPresets) cover the KNOWN moves: orbit,
 * push-in, crane. This module covers the other half of V0.2 §8.3: the author
 * DRAWS a trajectory and the system understands it as Camera Motion. A drawn
 * path is how you say "roughly like THIS" when no preset describes it.
 *
 * Three decisions make a hand-drawn path usable:
 *
 * 1. RESAMPLE BY ARC LENGTH. A pointer leaves irregular samples — dense where
 *    the hand slowed down, sparse where it flew. Keyframes taken at those raw
 *    samples would make the camera stutter and race. Resampling at a fixed
 *    spacing gives constant-speed motion, which is what "the camera moves
 *    along my line" means.
 * 2. LOOK AHEAD ALONG THE PATH. look_at is a point ahead of the camera, so the
 *    rig faces where it is going (and the final sample's look_at extrapolates
 *    the last segment, so the move does not end staring at its own feet).
 * 3. HEIGHT COMES FROM THE ANCHOR. The gesture is drawn on the ground plane;
 *    the camera's eye height is authored state and must survive the gesture,
 *    exactly like placement mode preserves it.
 */

import type { CameraKeyframe } from "../../../types/scene-script";
import type { SceneVec3 } from "./sceneScriptAxes";

/** Keyframe density along the drawn path (30fps: 15 frames = 0.5s). */
export const GESTURE_SAMPLE_STEP_FRAMES = 15;

/** How far ahead of the camera the gaze sits (metres). */
export const GESTURE_LOOK_AHEAD_METERS = 2.5;

const EPSILON = 1e-6;

export interface GesturePathOptions {
  startFrame: number;
  durationFrames: number;
  /** The camera's authored eye height (preserved through the gesture). */
  anchorHeight: number;
  frameRate: number;
}

export interface GesturePathResult {
  keyframes: CameraKeyframe[];
  /** Path length in metres (the UI shows it next to the drawing). */
  lengthMeters: number;
}

function distance2D(a: readonly number[], b: readonly number[]): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

/** Cumulative arc length of the polyline (2D: the gesture lives on the ground). */
function polylineLength(points: readonly SceneVec3[]): number {
  let total = 0;
  for (let index = 1; index < points.length; index += 1) {
    total += distance2D(points[index - 1], points[index]);
  }
  return total;
}

/** The polyline point at arc-length `s` (2D), plus the direction there. */
function pointAtArcLength(
  points: readonly SceneVec3[],
  s: number,
): { point: [number, number]; direction: [number, number] } | null {
  if (points.length === 0) return null;
  if (points.length === 1) {
    return { point: [points[0][0], points[0][1]], direction: [0, 1] };
  }
  let remaining = s;
  for (let index = 1; index < points.length; index += 1) {
    const a = points[index - 1];
    const b = points[index];
    const segment = distance2D(a, b);
    if (segment < EPSILON) continue;
    if (remaining <= segment || index === points.length - 1) {
      const t = Math.min(1, Math.max(0, remaining / segment));
      const dx = b[0] - a[0];
      const dy = b[1] - a[1];
      const magnitude = Math.hypot(dx, dy) || 1;
      return {
        point: [a[0] + dx * t, a[1] + dy * t],
        direction: [dx / magnitude, dy / magnitude],
      };
    }
    remaining -= segment;
  }
  const last = points[points.length - 1];
  return { point: [last[0], last[1]], direction: [0, 1] };
}

/**
 * Turn a drawn ground polyline into camera keyframes.
 *
 * A gesture with no travel (a click, or coincident points) is NOT a move: it
 * returns an empty list so the caller can say so instead of writing a
 * one-keyframe "path" that would freeze the camera.
 */
export function keyframesFromGesturePath(
  points: readonly SceneVec3[],
  options: GesturePathOptions,
): GesturePathResult {
  const distinct = points.filter((point, index) => {
    if (index === 0) return true;
    return distance2D(points[index - 1], point) > EPSILON;
  });
  const totalLength = polylineLength(distinct);
  if (distinct.length < 2 || totalLength < 0.05) {
    return { keyframes: [], lengthMeters: totalLength };
  }

  const { startFrame, durationFrames, anchorHeight, frameRate } = options;
  const fps = frameRate > 0 ? frameRate : 30;
  // Constant speed: the traverse takes `durationFrames` regardless of how the
  // hand moved, so the drawn shape — not the drawing speed — sets the pacing.
  const frames: number[] = [];
  const step = Math.max(1, GESTURE_SAMPLE_STEP_FRAMES);
  for (let frame = startFrame; frame <= startFrame + durationFrames; frame += step) {
    frames.push(frame);
  }
  if (frames[frames.length - 1] !== startFrame + durationFrames) {
    frames.push(startFrame + durationFrames);
  }

  const keyframes = frames.map((frame) => {
    const t = durationFrames === 0 ? 0 : (frame - startFrame) / durationFrames;
    const at = pointAtArcLength(distinct, totalLength * t);
    const position: [number, number, number] = [
      Math.round(((at?.point[0] ?? 0)) * 1000) / 1000,
      Math.round(((at?.point[1] ?? 0)) * 1000) / 1000,
      Math.round(anchorHeight * 1000) / 1000,
    ];
    const direction = at?.direction ?? [0, 1];
    const lookAt: [number, number, number] = [
      Math.round((position[0] + direction[0] * GESTURE_LOOK_AHEAD_METERS) * 1000) / 1000,
      Math.round((position[1] + direction[1] * GESTURE_LOOK_AHEAD_METERS) * 1000) / 1000,
      // The gaze dips slightly toward the ground so a fast traverse does not
      // stare at the horizon.
      Math.round((anchorHeight - 0.4) * 1000) / 1000,
    ];
    return { frame, position, look_at: lookAt };
  });

  return {
    keyframes,
    lengthMeters: Math.round(totalLength * 100) / 100,
  };
}
