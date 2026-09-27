/**
 * Axis conversion between SceneScript and three.js coordinates.
 *
 * SceneScript (and Blender) are Z-up right-handed: ``[x, y, z]`` is
 * ``[right, forward, up]``. three.js is Y-up: ``[x, y, z]`` is
 * ``[right, up, back]`` (z grows toward the viewer). The browser preview and
 * any interactive editing must agree with Blender on what a position means,
 * or a wall placed at Blender ``z=3`` shows up 3 m *up* in the browser and a
 * drag written back lands in the wrong axis entirely.
 *
 * ``sceneScriptGeometry.tsx`` documents this swap; this module is the single
 * tested place that actually performs it. The transform is an involution
 * (applying it twice is the identity), but both directions are named
 * explicitly so call sites read unambiguously.
 */

export type SceneVec3 = [number, number, number];

/**
 * SceneScript/Blender ``[x, y, z]`` (right, forward, up) ->
 * three.js ``[x, y, z]`` (right, up, back).
 */
export function sceneToThreePosition(position: SceneVec3): SceneVec3 {
  return [position[0], position[2], position[1]];
}

/**
 * three.js ``[x, y, z]`` (right, up, back) ->
 * SceneScript/Blender ``[x, y, z]`` (right, forward, up).
 */
export function threeToScenePosition(position: SceneVec3): SceneVec3 {
  return [position[0], position[2], position[1]];
}

/**
 * Scene yaw (degrees, 0 = facing +Y/forward) -> three.js y rotation (radians).
 *
 * A rotation about the up axis maps unchanged in magnitude: only the units
 * differ (SceneScript uses degrees for LLM friendliness, per ADR 0005).
 */
export function sceneYawToThreeRotation(rotationYDegrees: number): number {
  return (rotationYDegrees * Math.PI) / 180;
}

/** three.js y rotation (radians) -> SceneScript yaw degrees. */
export function threeRotationToSceneYaw(rotationYRadians: number): number {
  return (rotationYRadians * 180) / Math.PI;
}
