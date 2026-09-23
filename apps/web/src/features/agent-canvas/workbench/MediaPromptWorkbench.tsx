import type { RefObject } from "react";

import { SendIcon } from "../../../icons.tsx";
import type { ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";
import type {
  CanvasNodeV2,
  CanvasRuntimeModelResolutionV2,
  NodeRuntimeV2,
} from "../../../types-v2.ts";
import { CanvasModelPicker } from "./CanvasModelPicker.tsx";
import { FourLinePromptEditor } from "./FourLinePromptEditor.tsx";
import { NodeWorkbenchError } from "./NodeWorkbenchError.tsx";
import { NodeAssetActions } from "./NodeAssetActions.tsx";
import type { NodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";
import {
  canRetryNodeExecution,
  failureUserAction,
  nodeActionableFailure,
} from "../chat/actionableFailure.ts";

export function MediaPromptWorkbench({
  node,
  runtime = null,
  draft,
  models,
  defaultModelRef,
  modelsLoading,
  modelsError,
  modelResolution,
  onOpenAssets,
  onUploadReferences,
  promptEditorRef,
  preparingPrompt = false,
}: {
  node: CanvasNodeV2;
  runtime?: NodeRuntimeV2 | null;
  draft: NodeWorkbenchDraft;
  models: ProviderModelSummaryV1[];
  defaultModelRef: string | null;
  modelsLoading: boolean;
  modelsError: string | null;
  modelResolution: CanvasRuntimeModelResolutionV2 | null;
  onOpenAssets: () => void;
  onUploadReferences: () => void;
  promptEditorRef?: RefObject<HTMLTextAreaElement | null>;
  preparingPrompt?: boolean;
}) {
  const canConfigureProvider = node.status === "draft" || draft.isReadyMedia;
  const regenerating = node.status === "failed"
    && failureUserAction(nodeActionableFailure(node)) === "regenerate";
  const retryingExecution = node.status === "failed" && canRetryNodeExecution(node);
  const runAction = node.status === "ready" || regenerating
    ? "regenerate"
    : retryingExecution || node.status === "failed"
      ? "retry"
      : "run";
  const runLabel = `${runAction === "run" ? "Run" : runAction === "retry" ? "Retry" : "Regenerate"} ${node.node_type} node`;
  const runTitle = runAction === "run"
    ? "Run node"
    : runAction === "retry"
      ? "Retry node"
      : "Regenerate node";
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
          placeholder={`Describe the ${node.node_type} you want to create.`}
          onChange={(event) => draft.setPrompt(event.currentTarget.value)}
          editorRef={promptEditorRef}
        />
      </label>
      {preparingPrompt && !draft.prompt.trim() ? (
        <span className="agent-node-workbench__preparing-prompt">提示词正在准备...</span>
      ) : null}

      <NodeWorkbenchError draft={draft} />

      {(node.node_type === "image" || node.node_type === "video" || node.node_type === "audio") && draft.isReadyMedia ? (
        <div className="agent-node-workbench__library-save">
          <input
            type="text"
            className="agent-node-workbench__library-name-input"
            placeholder="Asset name"
            value={draft.libraryName}
            onChange={(event) => draft.setLibraryName(event.currentTarget.value)}
            disabled={draft.librarySaved}
          />
          {draft.librarySaved ? (
            <span className="agent-node-workbench__library-saved">Saved to library</span>
          ) : (
            <button
              type="button"
              className="agent-node-workbench__library-save-btn"
              disabled={draft.pending || !draft.libraryName.trim()}
              onClick={() => void draft.saveImageToLibrary()}
            >
              {draft.pending ? "Saving..." : "Save to library"}
            </button>
          )}
        </div>
      ) : null}

      <footer className="agent-node-workbench__footer agent-node-workbench__footer--composer">
        <NodeAssetActions
          disabled={draft.pending}
          showUpload={false}
          onUpload={onUploadReferences}
          onOpenAssets={onOpenAssets}
        />
        <div className="agent-node-workbench__composer-actions">
          {canConfigureProvider ? (
            <div className="agent-node-workbench__options agent-node-workbench__options--inline" aria-label="Generation options">
              <CanvasModelPicker
                models={models}
                defaultModelRef={defaultModelRef}
                loading={modelsLoading}
                error={modelsError}
                selectionMode={draft.modelSelectionMode}
                modelRef={draft.modelRef}
                modelSummary={node.model_summary}
                modelResolution={modelResolution}
                disabled={draft.pending}
                onChange={draft.setModelSelection}
              />
              {node.node_type === "video" ? (
                <label>
                  <span>Duration</span>
                  <input
                    aria-label="Requested video duration"
                    type="number"
                    min="1"
                    step="1"
                    value={typeof draft.parameters.duration_seconds === "number"
                      ? draft.parameters.duration_seconds
                      : ""}
                    disabled={draft.pending}
                    onChange={(event) => {
                      const next = { ...draft.parameters };
                      const duration = Number(event.currentTarget.value);
                      if (
                        event.currentTarget.value
                        && Number.isInteger(duration)
                        && duration > 0
                      ) {
                        next.duration_seconds = duration;
                      } else {
                        delete next.duration_seconds;
                      }
                      delete next.requested_duration_seconds;
                      delete next.effective_duration_seconds;
                      draft.setParameters(next);
                    }}
                  />
                </label>
              ) : null}
            </div>
          ) : null}
          <button
            type="button"
            className="agent-node-workbench__run"
            aria-label={runLabel}
            title={runTitle}
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
