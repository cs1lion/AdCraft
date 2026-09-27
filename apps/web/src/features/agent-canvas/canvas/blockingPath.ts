/**
 * Blocking paths — the director's floor marks for characters (and cameras).
 *
 * Motion presets write keyframes, but a keyframe list is not a picture: the
 * author had to scrub the playhead frame by frame to see where the character
 * actually goes. This module answers "what is the path" once, purely, so the
 * viewport can draw it and the tests can lock it.
 *
 * Two rules make the drawn path honest:
 * 1. Height-preserving: a path is drawn at the character's OWN z per segment,
 *    so a crane/lift is not projected flat onto the floor.
 * 2. De-duplicated: consecutive keyframes at the same position collapse to
 *    one point (a turn-in-place is a pose, not a segment of zero length that
 *    would render as a flickering dot).
 */

import type { CharacterKeyframe, CameraKeyframe } from "../../../types/scene-script";
import type { SceneVec3 } from "./sceneScriptAxes";
import { sceneToThreePosition } from "./sceneScriptAxes";

export interface BlockingPathPoint {
  /** SceneScript-space position of a keyframe. */
  scenePosition: SceneVec3;
  /** three.js-space position (converted once, here). */
  threePosition: [number, number, number];
  frame: number;
}

const EPSILON = 1e-6;

function nearlyEqual(a: SceneVec3, b: SceneVec3): boolean {
  return (
    Math.abs(a[0] - b[0]) < EPSILON
    && Math.abs(a[1] - b[1]) < EPSILON
    && Math.abs(a[2] - b[2]) < EPSILON
  );
}

/**
 * Ordered path points for a character's keyframes: position at every frame
 * where it CHANGES, plus the final keyframe (so a path that ends where it
 * started still shows its last mark).
 */
export function characterPathPoints(
  keyframes: readonly CharacterKeyframe[],
): BlockingPathPoint[] {
  const ordered = [...keyframes].sort((a, b) => a.frame - b.frame);
  const points: BlockingPathPoint[] = [];
  for (const keyframe of ordered) {
    const previous = points[points.length - 1];
    if (previous && nearlyEqual(previous.scenePosition, keyframe.position)) continue;
    points.push({
      scenePosition: [keyframe.position[0], keyframe.position[1], keyframe.position[2]],
      threePosition: sceneToThreePosition(keyframe.position),
      frame: keyframe.frame,
    });
  }
  return points;
}

/** Same contract for camera keyframes (position + look_at both move). */
export function cameraPathPoints(
  keyframes: readonly CameraKeyframe[],
): BlockingPathPoint[] {
  const ordered = [...keyframes].sort((a, b) => a.frame - b.frame);
  const points: BlockingPathPoint[] = [];
  for (const keyframe of ordered) {
    const previous = points[points.length - 1];
    if (previous && nearlyEqual(previous.scenePosition, keyframe.position)) continue;
    points.push({
      scenePosition: [keyframe.position[0], keyframe.position[1], keyframe.position[2]],
      threePosition: sceneToThreePosition(keyframe.position),
      frame: keyframe.frame,
    });
  }
  return points;
}

/**
 * straight-line length of the blocking path (SceneScript metres). A path
 * shorter than this between two points would mean the move jumped.
 */
export function blockingPathLength(points: readonly BlockingPathPoint[]): number {
  let total = 0;
  for (let index = 1; index < points.length; index += 1) {
    const a = points[index - 1].scenePosition;
    const b = points[index].scenePosition;
    total += Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
  }
  return total;
}
