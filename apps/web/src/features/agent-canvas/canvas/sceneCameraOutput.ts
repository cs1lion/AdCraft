import type { CSSProperties } from "react";
import type { PerspectiveCamera } from "three";
import { Vector3 } from "three";
import type { SceneVec3 } from "./sceneScriptAxes";

export const SCENE_OUTPUT_ASPECT = 16 / 9;
// blender_converter uses camera_add defaults: 50 mm, 36 mm sensor, AUTO fit.
// On the 16:9 render AUTO fits the horizontal sensor; Three wants vertical FOV.
export const SCENE_OUTPUT_VERTICAL_FOV = (2 * Math.atan(36 / (2 * 50 * SCENE_OUTPUT_ASPECT)) * 180) / Math.PI;
export const SCENE_OUTPUT_WORLD_SCALE: SceneVec3 = [1, 1, -1];

/** Proper rotation from Blender Z-up to Three Y-up, used for camera output. */
export function sceneCameraOutputPosition(position: SceneVec3): SceneVec3 {
  return [position[0], position[2], -position[1]];
}

/** Keep the editor's existing axis swap; compensate its reflection at output. */
export function applySceneOutputCamera(
  camera: PerspectiveCamera,
  pose: { position: SceneVec3; lookAt: SceneVec3 },
  target: Vector3,
): void {
  camera.position.set(...sceneCameraOutputPosition(pose.position));
  camera.up.set(0, 1, 0);
  camera.lookAt(target.set(...sceneCameraOutputPosition(pose.lookAt)));
  if (camera.aspect !== SCENE_OUTPUT_ASPECT || camera.fov !== SCENE_OUTPUT_VERTICAL_FOV) {
    camera.aspect = SCENE_OUTPUT_ASPECT;
    camera.fov = SCENE_OUTPUT_VERTICAL_FOV;
    camera.updateProjectionMatrix();
  }
  camera.updateMatrixWorld();
}

/** A narrow node letterboxes the complete lens instead of changing its crop. */
export function sceneCameraOutputCanvasStyle(height: number, editMode: boolean): CSSProperties {
  return editMode
    ? { width: "100%", height: "100%" }
    : { width: `min(100%, ${height * SCENE_OUTPUT_ASPECT}px)`, height: "auto", aspectRatio: "16 / 9" };
}
