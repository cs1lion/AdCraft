/**
 * SceneScript extraction utilities for canvas nodes.
 *
 * SceneScript JSON is stored in canvas node structured_content or metadata.
 * These helpers extract and validate it for the 3D preview component.
 */

import type { CanvasNodeV2 } from "../../../types-v2";
import type { SceneScriptRoot } from "../../../types/scene-script";

/** Key used to store SceneScript JSON in node structured_content. */
export const SCENE_SCRIPT_CONTENT_KEY = "scene_script";

/** Key used to store SceneScript JSON in node metadata. */
export const SCENE_SCRIPT_METADATA_KEY = "scene_script";

/**
 * Extract SceneScript from a canvas node.
 * Checks structured_content first, then metadata.
 * Returns null if not found or invalid.
 */
export function extractSceneScriptFromNode(node: CanvasNodeV2): SceneScriptRoot | null {
  // Try structured_content first
  const fromContent = node.structured_content?.[SCENE_SCRIPT_CONTENT_KEY];
  if (fromContent) {
    return parseSceneScript(fromContent);
  }

  // Try metadata
  const fromMetadata = node.metadata?.[SCENE_SCRIPT_METADATA_KEY];
  if (fromMetadata) {
    return parseSceneScript(fromMetadata);
  }

  // Try generation_prompt (some agents may embed JSON in prompt)
  return null;
}

/**
 * Parse a SceneScript value (object or JSON string) into a typed object.
 * Returns null if parsing fails or required fields are missing.
 */
export function parseSceneScript(value: unknown): SceneScriptRoot | null {
  if (!value) return null;

  let obj: unknown;
  if (typeof value === "string") {
    try {
      obj = JSON.parse(value);
    } catch {
      return null;
    }
  } else if (typeof value === "object") {
    obj = value;
  } else {
    return null;
  }

  // Basic validation - check required top-level fields
  const script = obj as Record<string, unknown>;
  if (!script.scene || typeof script.scene !== "object") return null;
  if (!Array.isArray(script.characters)) return null;
  if (!Array.isArray(script.cameras)) return null;
  if (!Array.isArray(script.shots)) return null;

  return script as unknown as SceneScriptRoot;
}

/**
 * Check if a canvas node is a scene-3d previs node.
 * Detects by creative_role or presence of SceneScript in content.
 */
export function isScene3DNode(node: CanvasNodeV2): boolean {
  return extractSceneScriptFromNode(node) !== null;
}

/**
 * Get total frame count from a SceneScript.
 */
export function getTotalFrames(sceneScript: SceneScriptRoot): number {
  return Math.round(sceneScript.scene.duration * sceneScript.scene.frame_rate);
}

/**
 * Get active camera ID for a given frame.
 */
export function getActiveCameraId(sceneScript: SceneScriptRoot, frame: number): string {
  for (const shot of sceneScript.shots) {
    if (frame >= shot.start_frame && frame <= shot.end_frame) {
      return shot.camera;
    }
  }
  return sceneScript.shots[0]?.camera ?? "";
}
