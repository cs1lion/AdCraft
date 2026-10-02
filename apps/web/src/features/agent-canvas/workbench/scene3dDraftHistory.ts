/**
 * Single-step undo for the 3D workbench draft (F1).
 *
 * Every interactive edit channel (language builder, director commands and
 * nudges, lip-sync apply, image intake) funnels through `commit`, so one
 * undo restores the pre-edit draft no matter which tool produced it —
 * instead of the old all-or-nothing "revert to last save".
 *
 * History resets whenever the draft changes from OUTSIDE the hook (node
 * rerun/reload, localStorage draft restore, revert-to-saved): a stale
 * snapshot would resurrect an edit the author already discarded.
 */

import { useCallback, useRef, useState } from "react";

import type { SceneScriptRoot } from "../../../types/scene-script";

const HISTORY_LIMIT = 20;

export interface Scene3dDraftHistory {
  /** Apply an edit through the history: the pre-edit draft becomes undoable. */
  commit: (next: SceneScriptRoot) => void;
  /** Restore the previous draft (no-op when there is nothing to undo). */
  undo: () => void;
  canUndo: boolean;
  /** Undoable steps (for the button label). */
  depth: number;
}

export function useScene3dDraftHistory(
  draftScript: SceneScriptRoot | null,
  setDraftScript: (script: SceneScriptRoot | null) => void,
): Scene3dDraftHistory {
  const [stack, setStack] = useState<SceneScriptRoot[]>([]);
  const lastSeenRef = useRef<SceneScriptRoot | null>(draftScript);

  if (draftScript !== lastSeenRef.current) {
    // External draft change (rerun/restore/revert) — React's documented
    // adjust-state-during-render pattern: reset before this render commits.
    lastSeenRef.current = draftScript;
    setStack([]);
  }

  const commit = useCallback(
    (next: SceneScriptRoot) => {
      if (draftScript !== null) {
        setStack((current) => [...current.slice(-(HISTORY_LIMIT - 1)), draftScript]);
      }
      lastSeenRef.current = next;
      setDraftScript(next);
    },
    [draftScript, setDraftScript],
  );

  const undo = useCallback(() => {
    if (!stack.length) return;
    const previous = stack[stack.length - 1];
    lastSeenRef.current = previous;
    setStack(stack.slice(0, -1));
    setDraftScript(previous);
  }, [stack, setDraftScript]);

  return { commit, undo, canUndo: stack.length > 0, depth: stack.length };
}
