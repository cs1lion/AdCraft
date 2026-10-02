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
import { ModelParameterControls } from "./ModelParameterControls.tsx";
import { NodeWorkbenchError } from "./NodeWorkbenchError.tsx";
import { NodeAssetActions } from "./NodeAssetActions.tsx";
import { VideoAudioToggle } from "./VideoAudioToggle.tsx";
import { validateModelParameters } from "./modelParameterDescriptors.ts";
import type { NodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";
import {
  canRetryNodeExecution,
  failureUserAction,
  nodeActionableFailure,
} from "../chat/actionableFailure.ts";

/** Descriptor names rendered inline in the video toolbar (beside assets +
 * model picker); every other descriptor falls into the grid below the footer. */
const TOOLBAR_PARAMETERS = ["duration_seconds", "resolution", "aspect_ratio"];

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
  // 精确的 Execution 重试优先于 Ready 节点的笼统再生成：节点带着一条
  // failed + retryable 的最新尝试时，即使状态是 ready 也该是 Retry。
  const retryingExecution = canRetryNodeExecution(node);
  const runAction = retryingExecution
    ? "retry"
    : node.status === "ready" || regenerating
      ? "regenerate"
      : node.status === "failed"
        ? "retry"
        : "run";
  const runLabel = `${runAction === "run" ? "Run" : runAction === "retry" ? "Retry" : "Regenerate"} ${node.node_type} node`;
  const runTitle = runAction === "run"
    ? "Run node"
    : runAction === "retry"
      ? "Retry node"
      : "Regenerate node";
  const publishing = runtime?.phase === "publishing";

  // 概念断奶的参数工作台（2026-10-02 接线）：descriptor 驱动的参数控件。
  // 选中模型 = 显式选择 > 安装默认（defaultModelRef）> default 档第一个；
  // 绝不参考 node.model_summary（那是上一次产出的模型，不是可用的默认）。
  const isVideo = node.node_type === "video";
  const usesParameterControls = isVideo || node.node_type === "audio";
  const selectedModelRef = draft.modelSelectionMode === "explicit"
    ? draft.modelRef
    : defaultModelRef ?? models.find((model) => model.release_tier === "default")?.model_ref ?? null;
  const selectedModel = models.find((model) => model.model_ref === selectedModelRef) ?? null;
  const descriptors = usesParameterControls ? selectedModel?.parameter_descriptors ?? [] : [];
  const audioDescriptor = descriptors.find((descriptor) => descriptor.name === "generate_audio") ?? null;
  const toolbarDescriptors = descriptors.filter((descriptor) =>
    TOOLBAR_PARAMETERS.includes(descriptor.name));
  const gridDescriptors = descriptors.filter((descriptor) =>
    descriptor.name !== "generate_audio" && !TOOLBAR_PARAMETERS.includes(descriptor.name));
  const audioChecked = draft.parameters.generate_audio === undefined
    ? audioDescriptor?.default === true
    : draft.parameters.generate_audio === true;
  const audioDisabledReason = modelsLoading
    ? "Provider models are loading."
    : modelsError
      ? "Provider models are unavailable."
      : !audioDescriptor
        ? "The selected model does not declare audio generation."
        : null;
  // descriptor 校验不过（非整数/越界/必填缺失）→ 阻止 run。
  const parameterIssues = usesParameterControls
    ? validateModelParameters(descriptors, draft.parameters)
    : [];
  const runDisabled = draft.pending
    || !draft.prompt.trim()
    || node.status === "working"
    || (node.status === "ready" && publishing)
    || parameterIssues.length > 0;

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

      {/* 错误留在固定编辑布局之外、归属本节点类型的反馈区（alert 最近邻可查） */}
      <div className={`agent-node-workbench__${node.node_type}-feedback`}>
        <NodeWorkbenchError draft={draft} />
      </div>

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

      <footer
        className={`agent-node-workbench__footer agent-node-workbench__footer--composer${node.node_type === "image" ? " agent-node-workbench__footer--image" : ""}${isVideo ? " agent-node-workbench__video-toolbar" : ""}`}
      >
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
                appearance={node.node_type === "audio" ? "default" : "monochrome"}
                showOptionDetails={false}
              />
              {isVideo ? (
                <VideoAudioToggle
                  checked={audioChecked}
                  disabledReason={audioDisabledReason}
                  onChange={(next) => draft.setParameters({ ...draft.parameters, generate_audio: next })}
                />
              ) : null}
              {isVideo && toolbarDescriptors.length ? (
                <ModelParameterControls
                  descriptors={toolbarDescriptors}
                  parameters={draft.parameters}
                  disabled={draft.pending}
                  onChange={draft.setParameters}
                  layout="inline"
                />
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
      {/* 其余 descriptor（如 audio_mode）留在页脚外的参数网格；audio 节点用
          全量 descriptor 网格（generate_audio 以 checkbox 形态出现） */}
      {usesParameterControls && (isVideo ? gridDescriptors : descriptors).length ? (
        <ModelParameterControls
          descriptors={isVideo ? gridDescriptors : descriptors}
          parameters={draft.parameters}
          disabled={draft.pending}
          onChange={draft.setParameters}
        />
      ) : null}
    </div>
  );
}
