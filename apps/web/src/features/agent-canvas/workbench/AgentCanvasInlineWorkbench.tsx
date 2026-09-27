import { useEffect, useMemo, useRef } from "react";

import { mediaAssetPreviewPath } from "../../../workflow/mediaPreview.ts";
import { mediaAssetContentPath } from "../../../workflow/mediaPreview.ts";

import { PatchScopeNote } from "../canvas/PatchScopeNote.tsx";
import { EditingWorkbench } from "./EditingWorkbench.tsx";
import { LocalEngineWorkbench } from "./LocalEngineWorkbench.tsx";
import { MediaPromptWorkbench } from "./MediaPromptWorkbench.tsx";
import { NodeReferenceStrip } from "./NodeReferenceStrip.tsx";
import { NodePromptPreparationState } from "./NodePromptPreparationState.tsx";
import { NodeWorkbenchShell } from "./NodeWorkbenchShell.tsx";
import { ScriptWorkbench } from "./ScriptWorkbench.tsx";
import { TextWorkbench } from "./TextWorkbench.tsx";
import { useNodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";
import type { AgentCanvasInlineWorkbenchProps } from "./workbenchTypes.ts";
import { promptPreparationForNode } from "../model/promptPreparation.ts";
import "./agent-canvas-inline-workbench.css";

export function AgentCanvasInlineWorkbench(props: AgentCanvasInlineWorkbenchProps) {
  return <VisibleAgentCanvasInlineWorkbench {...props} />;
}

function VisibleAgentCanvasInlineWorkbench(props: AgentCanvasInlineWorkbenchProps) {
  const {
    workflow,
    node,
    runtime = null,
    deleteBinding,
    providerModels = [],
    providerDefaultModelRef = null,
    providerModelsLoading = false,
    providerModelsError = null,
    modelResolution = null,
    onClose,
    onWorkflowRefresh,
    onOpenAssets,
    onUploadReferences,
    onOpenEditing,
  } = props;
  const draft = useNodeWorkbenchDraft(props);
  const promptEditorRef = useRef<HTMLTextAreaElement>(null);

  // The node's own output asset (what the workbench previews: the generated
  // audio bed for voice-cast). Null until the node has produced media.
  const outputAsset = useMemo(
    () =>
      (node.output_asset_id
        ? workflow.assets.find((asset) => asset.asset_id === node.output_asset_id)
        : null) ?? null,
    [node.output_asset_id, workflow.assets],
  );

  // Prop and scene assets for the SAME lock, one kind further out (V0.2 §5):
  // the backend schema carries ``prop_asset_id`` / ``scene_asset_id`` and the
  // executor even stamps them when a reference is unambiguous, so the editor
  // needs the options to show a stamp and to let the author bind one by hand.
  const propAssetOptions = useMemo(
    () =>
      workflow.assets
        .filter(
          (asset) =>
            asset.media_type === "image"
            && (asset.semantic_type ?? "").startsWith("product_"),
        )
        .map((asset) => ({
          asset_id: asset.asset_id,
          display_name: asset.display_name,
          preview_url: mediaAssetPreviewPath(asset),
        })),
    [workflow.assets],
  );
  const sceneAssetOptions = useMemo(
    () =>
      workflow.assets
        .filter(
          (asset) =>
            asset.media_type === "image"
            && (asset.semantic_type ?? "").startsWith("scene_"),
        )
        .map((asset) => ({
          asset_id: asset.asset_id,
          display_name: asset.display_name,
          preview_url: mediaAssetPreviewPath(asset),
        })),
    [workflow.assets],
  );
  // Character assets the 3D editor can bind for identity consistency: the
  // workflow's own assets whose semantic type marks them as character designs
  // (character_main_image / character_three_view).
  const characterAssetOptions = useMemo(
    () =>
      workflow.assets
        .filter(
          (asset) =>
            asset.media_type === "image"
            && (asset.semantic_type ?? "").startsWith("character_"),
        )
        .map((asset) => ({
          asset_id: asset.asset_id,
          display_name: asset.display_name,
          // The reference image the inspector shows for the bound identity;
          // the shared preview helper prefers the backend's derived preview.
          preview_url: mediaAssetPreviewPath(asset),
        })),
    [workflow.assets],
  );

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  if (node.execution_mode === "source_only") {
    return null;
  }


  const references = node.node_type === "editing" ? null : (
    <NodeReferenceStrip
      workflow={workflow}
      node={node}
      deleteBinding={deleteBinding}
      pending={draft.pending}
      perform={draft.perform}
    />
  );
  const requiresPreparedPrompt = ["text", "script", "image", "video", "audio"].includes(node.node_type)
    && !(node.node_type === "text" && node.creative_role === "world_setting");
  const preparationStatus = promptPreparationForNode(node)?.status;
  const isManualBlankPromptNode = requiresPreparedPrompt
    && node.status === "draft"
    && !node.generation_prompt?.trim()
    && !node.summary_prompt?.trim()
    && (node.prompt_preparation === null || node.prompt_preparation?.status === "waiting_user");
  const promptPreparing = requiresPreparedPrompt
    && !isManualBlankPromptNode
    && preparationStatus !== undefined
    && preparationStatus !== "ready"
    && preparationStatus !== "not_applicable";
  const preparingVideoPrompt = node.node_type === "video"
    && (preparationStatus === "queued" || preparationStatus === "working");

  return (
    <NodeWorkbenchShell
      nodeType={node.node_type}
    >
      {/* ADR 0009 决策 2: say what this node's last edit affected — including
          (especially) when the answer is "nothing". */}
      <PatchScopeNote nodeId={node.node_id} />
      {references}
      {promptPreparing && node.node_type !== "image" && node.node_type !== "text" ? (
        <NodePromptPreparationState
          node={node}
          onWorkflowRefresh={onWorkflowRefresh}
          onRevise={() => promptEditorRef.current?.focus()}
          hideActiveStatus={preparingVideoPrompt}
        />
      ) : null}
      {node.node_type === "text" ? (
        <TextWorkbench
          node={node}
          draft={draft}
          models={providerModels}
          defaultModelRef={providerDefaultModelRef}
          modelsLoading={providerModelsLoading}
          modelsError={providerModelsError}
          modelResolution={modelResolution}
          promptEditorRef={promptEditorRef}
        />
      ) : null}
      {node.node_type === "script" ? (
        <ScriptWorkbench
          node={node}
          status={node.status}
          draft={draft}
          models={providerModels}
          modelsLoading={providerModelsLoading}
          modelsError={providerModelsError}
          modelResolution={modelResolution}
          promptEditorRef={promptEditorRef}
        />
      ) : null}
      {["image", "video", "audio"].includes(node.node_type) ? (
        <MediaPromptWorkbench
          node={node}
          runtime={runtime}
          draft={draft}
          models={providerModels}
          defaultModelRef={providerDefaultModelRef}
          modelsLoading={providerModelsLoading}
          modelsError={providerModelsError}
          modelResolution={modelResolution}
          onOpenAssets={onOpenAssets}
          onUploadReferences={onUploadReferences}
          promptEditorRef={promptEditorRef}
          preparingPrompt={preparingVideoPrompt}
        />
      ) : null}
      {["voice-cast", "scene-3d"].includes(node.node_type) ? (
        <LocalEngineWorkbench
          node={node}
          runtime={runtime}
          draft={draft}
          promptEditorRef={promptEditorRef}
          patchNode={props.patchNode}
          characterAssets={characterAssetOptions}
          propAssets={propAssetOptions}
          sceneAssets={sceneAssetOptions}
          outputAsset={outputAsset}
          alignedSpeechLines={props.alignedSpeechLines ?? null}
          onLinesAligned={props.onSpeechLinesAligned}
        />
      ) : null}
      {node.node_type === "editing" ? (
        <EditingWorkbench workflow={workflow} node={node} onOpenEditing={onOpenEditing} />
      ) : null}
    </NodeWorkbenchShell>
  );
}
