import type { SceneScriptRoot } from "../../../types/scene-script";

/**
 * 3D scene-script draft persistence (handoff D6).
 *
 * The edit surface's draft lives in React state and a page refresh used to wipe
 * it silently ("刷新即丢"). We keep a disposable copy in localStorage, namespaced
 * per node, so a refresh restores unsaved work with an explicit notice. Mirrors
 * `agentCanvasViewport.ts`: same `adcraft:agent-canvas:` namespace, injectable
 * `storage` for tests, and a write that must never block editing.
 */
export function scene3dDraftStorageKey(workflowId: string, nodeId: string): string {
  return `adcraft:agent-canvas:scene3d-draft:${workflowId}:${nodeId}`;
}

function looksLikeSceneScript(value: unknown): value is SceneScriptRoot {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<SceneScriptRoot>;
  // Minimal structural sanity so a corrupt/foreign entry can never crash the editor.
  return Boolean(candidate.scene) && Array.isArray(candidate.cameras);
}

export function readScene3dDraft(
  workflowId: string,
  nodeId: string,
  storage: Pick<Storage, "getItem"> = window.localStorage,
): SceneScriptRoot | null {
  try {
    const value = storage.getItem(scene3dDraftStorageKey(workflowId, nodeId));
    if (!value) return null;
    const parsed: unknown = JSON.parse(value);
    return looksLikeSceneScript(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function writeScene3dDraft(
  workflowId: string,
  nodeId: string,
  draft: SceneScriptRoot,
  storage: Pick<Storage, "setItem"> = window.localStorage,
): void {
  try {
    storage.setItem(scene3dDraftStorageKey(workflowId, nodeId), JSON.stringify(draft));
  } catch {
    // Draft persistence is disposable and must never block editing.
  }
}

export function clearScene3dDraft(
  workflowId: string,
  nodeId: string,
  storage: Pick<Storage, "removeItem"> = window.localStorage,
): void {
  try {
    storage.removeItem(scene3dDraftStorageKey(workflowId, nodeId));
  } catch {
    // Best-effort: a stale draft the next load simply discards if malformed.
  }
}
