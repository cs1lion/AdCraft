import type { RefObject } from "react";

import { SendIcon } from "../../../icons.tsx";
import type { CanvasNodeV2, NodeRuntimeV2 } from "../../../types-v2.ts";
import { FourLinePromptEditor } from "./FourLinePromptEditor.tsx";
import { NodeWorkbenchError } from "./NodeWorkbenchError.tsx";
import type { NodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";

const PLACEHOLDERS: Partial<Record<CanvasNodeV2["node_type"], string>> = {
  "voice-cast": "Enter the dialogue to be spoken.",
  "scene-3d": "Describe the scene: setting, characters, camera, and action.",
};

const RUN_LABELS: Partial<Record<CanvasNodeV2["node_type"], string>> = {
  "voice-cast": "Run voice-cast node",
  "scene-3d": "Run scene-3d node",
};

/**
 * Prompt composer for local-engine nodes (voice-cast, scene-3d).
 *
 * These nodes do not select a catalog provider — speech is synthesized
 * locally and scenes are rendered by Blender — so the panel only offers
 * the prompt editor and a Run button, reusing the shared draft machinery.
 */
export function LocalEngineWorkbench({
  node,
  runtime = null,
  draft,
  promptEditorRef,
}: {
  node: CanvasNodeV2;
  runtime?: NodeRuntimeV2 | null;
  draft: NodeWorkbenchDraft;
  promptEditorRef?: RefObject<HTMLTextAreaElement | null>;
}) {
  const publishing = runtime?.phase === "publishing";
  const runDisabled = draft.pending
    || !draft.prompt.trim()
    || node.status === "working"
    || (node.status === "ready" && publishing);

  return (
    <div className="agent-node-workbench__body">
      <label className="agent-node-workbench__composer">
        <FourLinePromptEditor
          ariaLabel="Generation prompt"
          value={draft.prompt}
          disabled={draft.pending}
          placeholder={PLACEHOLDERS[node.node_type] ?? "Describe what to create."}
          onChange={(event) => draft.setPrompt(event.currentTarget.value)}
          editorRef={promptEditorRef}
        />
      </label>

      <NodeWorkbenchError draft={draft} />

      <footer className="agent-node-workbench__footer agent-node-workbench__footer--composer">
        <div className="agent-node-workbench__composer-actions">
          <button
            type="button"
            className="agent-node-workbench__run"
            aria-label={RUN_LABELS[node.node_type] ?? "Run node"}
            title="Run node"
            disabled={runDisabled}
            onClick={() => void draft.run()}
          >
            <SendIcon />
          </button>
        </div>
      </footer>
    </div>
  );
}
