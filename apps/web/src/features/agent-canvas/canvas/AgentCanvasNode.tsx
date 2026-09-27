import {
  Handle,
  NodeToolbar,
  Position,
  useUpdateNodeInternals,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { memo, useCallback, useLayoutEffect, useRef, useState, type ReactNode } from "react";

import { PlayIcon } from "../../../icons.tsx";
import type {
  CanvasNodeStatusV2,
  CanvasNodeTypeV2,
  CanvasNodeV2,
  NodeRuntimeV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import { AgentCanvasAudioPlayer } from "./AgentCanvasAudioPlayer.tsx";
import { AgentCanvasMediaGenerationLoader } from "./AgentCanvasMediaGenerationLoader.tsx";
import { AgentCanvasNodeContent } from "./AgentCanvasNodeContent.tsx";
import { AgentCanvasNodeHeader } from "./AgentCanvasNodeHeader.tsx";
import { EditingNodeSurface } from "./EditingNodeSurface.tsx";
import { SceneScriptPanel } from "./SceneScriptPanel.tsx";
import { ReplicaBlueprintPanel } from "./ReplicaBlueprintPanel.tsx";
import {
  TIMELINE_DROP_MIME,
  serializeTimelineDrop,
} from "../timeline/timelineDropPayload.ts";
import {
  CANVAS_DROP_MIME,
  cardAcceptsCanvasDrop,
  canvasDropMimeFor,
  parseCanvasDropPayload,
} from "./canvasDrop.ts";
import { extractSceneScriptFromNode } from "../model/sceneScriptUtils.ts";
import { creativeRoleDisplayName } from "./creativeRoleDisplayName.ts";
import { areAgentCanvasNodePropsEqual } from "./agentCanvasNodeRenderModel.ts";
import { requestNativeVideoFirstFrame } from "./nativeVideoFirstFrame.ts";
import { mediaAssetContentPath, mediaAssetPreviewPath } from "../../../workflow/mediaPreview.ts";
import { StableMediaPreview } from "../../../workflow/StableMediaPreview.tsx";
import {
  agentCanvasNodeSize,
  scriptNodeHeightForContent,
  validAgentCanvasMediaDimensions,
  type AgentCanvasMediaDimensions,
} from "./nodeGeometry.ts";
import { useAgentCanvasVideoPoster } from "./useAgentCanvasVideoPoster.ts";
import "./AgentCanvasNode.css";

export const NODE_TYPE_LABELS: Record<CanvasNodeTypeV2, string> = {
  text: "Text",
  script: "Script",
  image: "Image",
  video: "Video",
  audio: "Audio",
  editing: "Editing",
  "scene-3d": "3D Previs",
  "voice-cast": "Voice Cast",
  replica: "Replica",
};

const NODE_STATUS_LABELS: Record<CanvasNodeStatusV2, string> = {
  draft: "Draft",
  working: "Working",
  ready: "Ready",
  failed: "Failed",
};

export interface AgentCanvasNodeCallbacks {
  /** An image asset dropped on this card: bind it as the node's reference. */
  onAssetDroppedAsReference?: (
    nodeId: string,
    assetId: string,
    displayName: string,
  ) => void;
  onRun?: (nodeId: string) => void;
  onRetry?: (nodeId: string) => void;
  onExport?: (nodeId: string) => void;
  onOpenEditing?: (nodeId: string) => void;
  onOpenVideoPreview?: (nodeId: string, asset: ProjectAssetSummaryV2) => void;
  renderWorkbench?: (node: CanvasNodeV2, runtime: NodeRuntimeV2 | null) => ReactNode;
  onOpenConnectedNodeMenu?: (
    nodeId: string,
    direction: "upstream" | "downstream",
    point: { x: number; y: number },
  ) => void;
}

export interface AgentCanvasNodeData extends Record<string, unknown>, AgentCanvasNodeCallbacks {
  node: CanvasNodeV2;
  asset?: ProjectAssetSummaryV2 | null;
  runtime?: NodeRuntimeV2 | null;
  workbenchActive?: boolean;
  disabled?: boolean;
  showInputHandle?: boolean;
  showOutputHandle?: boolean;
}

export type AgentCanvasFlowNode = Node<AgentCanvasNodeData, "agentCanvas">;

type AgentCanvasNodeRendererProps = NodeProps<AgentCanvasFlowNode>;

/**
 * Speaker names declared by a voice-cast node's audio bed, in first-appearance
 * order. A bed is ONE take with every speaker mixed in, so the timeline clip
 * it produces is deliberately NOT bound to a single character — the names
 * travel in the clip label instead (the director-phase intent signal).
 */
function voiceBedSpeakerNames(node: CanvasNodeV2): string[] {
  const bed = node.structured_content?.audio_bed;
  const scripts =
    bed && typeof bed === "object" ? (bed as { scripts?: unknown }).scripts : null;
  if (!Array.isArray(scripts)) return [];
  const names: string[] = [];
  for (const entry of scripts) {
    if (!entry || typeof entry !== "object") continue;
    const speaker = String((entry as { speaker?: unknown }).speaker ?? "").trim();
    if (speaker && !names.includes(speaker)) names.push(speaker);
  }
  return names;
}

function VoiceCastAudioSurface({
  node,
  status,
  asset,
}: {
  node: CanvasNodeV2;
  status: CanvasNodeV2["status"];
  asset?: ProjectAssetSummaryV2 | null;
}) {
  const speakers = voiceBedSpeakerNames(node);
  const outputAssetId = node.output_asset_id;
  // Nothing to drag before the bed exists: the card stays inert rather than
  // offering a drop the timeline would reject as a missing asset.
  if (!outputAssetId) {
    return <AgentCanvasAudioPlayer node={node} status={status} asset={asset} />;
  }
  return (
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- Drag SOURCE surface (HTML5 drag-and-drop, no click semantics); the player keeps its own controls.
    <div
      draggable
      data-testid={`voice-cast-drag-source-${node.node_id}`}
      title={
        speakers.length > 0
          ? `拖入时间线的 voice 轨：音频床（说话人：${speakers.join("、")}）`
          : "拖入时间线的 voice 轨：音频床"
      }
      onDragStart={(event) => {
        event.dataTransfer.setData(
          TIMELINE_DROP_MIME,
          serializeTimelineDrop({
            kind: "asset",
            asset_id: outputAssetId,
            media_type: "audio",
            label:
              speakers.length > 0
                ? `音频床 · ${speakers.join(" / ")}`
                : node.title || "音频床",
            source_node_id: node.node_id,
          }),
        );
        event.dataTransfer.effectAllowed = "copy";
      }}
    >
      <AgentCanvasAudioPlayer node={node} status={status} asset={asset} />
    </div>
  );
}

interface AgentCanvasNodeCardProps extends AgentCanvasNodeCallbacks {
  node: CanvasNodeV2;
  asset?: ProjectAssetSummaryV2 | null;
  runtime?: NodeRuntimeV2 | null;
  selected?: boolean;
  disabled?: boolean;
  onMediaDimensionsResolved?: (dimensions: { width: number; height: number }) => void;
  onScriptContentHeightResolved?: (height: number) => void;
  mediaDimensions?: { width: number; height: number } | null;
}

function MediaSurface({
  node,
  asset,
  onOpenVideoPreview,
  onMediaDimensionsResolved,
  label,
}: {
  node: CanvasNodeV2;
  asset?: ProjectAssetSummaryV2 | null;
  onOpenVideoPreview?: AgentCanvasNodeCallbacks["onOpenVideoPreview"];
  onMediaDimensionsResolved?: AgentCanvasNodeCardProps["onMediaDimensionsResolved"];
  label: string;
}) {
  const mediaUrl = asset
    ? asset.media_type === "image" ? mediaAssetContentPath(asset) : mediaAssetPreviewPath(asset)
    : null;
  const videoUrl = asset?.media_type === "video" ? mediaAssetContentPath(asset) : null;
  const videoRef = useRef<HTMLVideoElement>(null);
  const videoPosterUrl = useAgentCanvasVideoPoster(asset, videoRef);
  if (node.node_type === "video" && videoUrl && asset) {
    return (
      <div className="agent-canvas-node__video-stage">
        <video
          ref={videoRef}
          className="agent-canvas-node__media agent-canvas-node__media--cover"
          src={videoUrl}
          poster={videoPosterUrl ?? undefined}
          aria-label={asset.display_name || "Video output"}
          muted
          playsInline
          preload="metadata"
          onLoadedMetadata={({ currentTarget }) => {
            if (!Number.isFinite(currentTarget.duration) || currentTarget.duration <= 0) return;
            void requestNativeVideoFirstFrame(currentTarget);
          }}
        />
        {onOpenVideoPreview ? (
          <button
            className="agent-canvas-node__video-play nodrag nopan"
            type="button"
            aria-label="Play video output"
            title="Play video"
            onPointerDown={(event) => event.stopPropagation()}
            onDoubleClick={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation();
              onOpenVideoPreview(node.node_id, asset);
            }}
          >
            <PlayIcon />
          </button>
        ) : null}
      </div>
    );
  }

  if (!mediaUrl) {
    return <div className="agent-canvas-node__media-placeholder" aria-hidden="true" />;
  }

  return (
    <StableMediaPreview
      className={`agent-canvas-node__media agent-canvas-node__media--${node.node_type === "image" ? "contain" : "cover"}`}
      src={mediaUrl}
      alt={asset?.display_name || `${NODE_TYPE_LABELS[node.node_type]} output`}
      draggable={false}
      loading="lazy"
      decoding="async"
      onLoad={(event) => {
        const { naturalWidth, naturalHeight } = event.currentTarget;
        if (naturalWidth > 0 && naturalHeight > 0) {
          onMediaDimensionsResolved?.({ width: naturalWidth, height: naturalHeight });
        }
      }}
    />
  );
}
function NodeSurface({
  node,
  asset,
  status,
  onOpenVideoPreview,
  onOpenEditing,
  onMediaDimensionsResolved,
  onScriptContentHeightResolved,
  label,
}: Pick<AgentCanvasNodeCardProps, "node" | "asset" | "onOpenVideoPreview" | "onOpenEditing" | "onMediaDimensionsResolved" | "onScriptContentHeightResolved"> & { status: CanvasNodeStatusV2; label: string }) {
  if (node.node_type === "replica") {
    return <ReplicaBlueprintPanel node={node} height={320} />;
  }
  const sceneScript = extractSceneScriptFromNode(node);
  if (sceneScript) {
    const narration = typeof node.structured_content?.narration === "string"
      ? node.structured_content.narration
      : undefined;
    const narrationVoice = typeof node.structured_content?.narration_voice === "string"
      ? node.structured_content.narration_voice
      : "default";
    return (
      // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- Drag SOURCE surface: the gesture is HTML5 drag-and-drop (no click semantics); the panel below keeps its own interactive affordances, and the wrapper exists only to start the camera-move drag.
      <div
        draggable
        data-testid={`scene-3d-drag-source-${node.node_id}`}
        title="拖入时间线的 camera 轨以引用该场景的运镜"
        onDragStart={(event) => {
          // Camera drop: the timeline resolves it to the camera track and
          // links the clip back to this scene-3d node.
          event.dataTransfer.setData(
            TIMELINE_DROP_MIME,
            serializeTimelineDrop({
              kind: "camera",
              asset_id: node.node_id,
              media_type: "camera",
              label: node.title || "scene-3d camera move",
              camera_node_id: node.node_id,
              source_node_id: node.node_id,
            }),
          );
          event.dataTransfer.effectAllowed = "copy";
        }}
      >
        <SceneScriptPanel
          sceneScript={sceneScript}
          narration={narration}
          narrationVoice={narrationVoice}
          height={320}
          workflowId={node.workflow_id}
        />
      </div>
    );
  }
  if (node.node_type === "text" || node.node_type === "script") {
    return (
      <AgentCanvasNodeContent
        node={node}
        onScriptContentHeightResolved={onScriptContentHeightResolved}
      />
    );
  }
  if (node.node_type === "voice-cast") {
    return <VoiceCastAudioSurface node={node} status={status} asset={asset} />;
  }
  if (node.node_type === "audio") {
    return <AgentCanvasAudioPlayer node={node} status={status} asset={asset} />;
  }
  if (node.node_type === "editing") {
    return <EditingNodeSurface onOpenEditing={onOpenEditing ? () => onOpenEditing(node.node_id) : undefined} />;
  }
  return (
    <MediaSurface
      node={node}
      asset={asset}
      label={label}
      onOpenVideoPreview={onOpenVideoPreview}
      onMediaDimensionsResolved={onMediaDimensionsResolved}
    />
  );
}

export function AgentCanvasNodeCard({
  node,
  asset,
  runtime,
  selected = false,
  onOpenVideoPreview,
  onOpenEditing,
  onMediaDimensionsResolved,
  onScriptContentHeightResolved,
  mediaDimensions,
  onRetry,
  onOpenConnectedNodeMenu,
  onRun,
  onAssetDroppedAsReference,
}: AgentCanvasNodeCardProps) {
  const status = runtime?.visible_status ?? node.status;
  const label = creativeRoleDisplayName(node.creative_role);
  const resolvedMediaDimensions = mediaDimensions
    ?? (validAgentCanvasMediaDimensions(asset)
      ? { width: asset.width, height: asset.height }
      : null);
  const usedDeterministicFallback = node.metadata.materialization_mode === "deterministic_fallback"
    && node.metadata.warning_code === "specialist_materialization_fallback";
  const omittedOptionalInputsCount = Array.isArray(runtime?.omitted_optional_inputs)
    ? runtime.omitted_optional_inputs.length
    : 0;

  // A library asset dropped ON the card (V0.2 §2.2: 卡片内部 = 素材归属):
  // an image lands as this node's reference input. The typed MIME is checked
  // in dragover (the payload is unreadable before the drop), and the drop
  // re-validates rather than trusting the cursor. React Flow's own node drag
  // carries a different MIME, so this never fires while moving cards.
  const handleCardDragOver = useCallback(
    (event: React.DragEvent<HTMLElement>) => {
      if (!event.dataTransfer.types.includes(canvasDropMimeFor("image"))) return;
      if (!cardAcceptsCanvasDrop("image", node.node_type)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    },
    [node.node_type],
  );

  const handleCardDrop = useCallback(
    (event: React.DragEvent<HTMLElement>) => {
      const raw = event.dataTransfer.getData(canvasDropMimeFor("image"));
      if (!raw) return;
      // Stop the pane's handler: a drop on a card belongs to the card, not
      // to "create a new node here".
      event.preventDefault();
      event.stopPropagation();
      const payload = parseCanvasDropPayload(raw);
      if (!payload || payload.media_type !== "image") return;
      if (!cardAcceptsCanvasDrop(payload.media_type, node.node_type)) return;
      onAssetDroppedAsReference?.(node.node_id, payload.asset_id, payload.display_name);
    },
    [node.node_id, node.node_type, onAssetDroppedAsReference],
  );

  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- Drop TARGET surface: the gesture is HTML5 drag-and-drop (no click semantics); the card's own interactive affordances are inside and keep their handlers.
    <article
      className={[
        "agent-canvas-node",
        `agent-canvas-node--${node.node_type}`,
        `agent-canvas-node--${status}`,
        selected ? "agent-canvas-node--selected" : "",
      ].filter(Boolean).join(" ")}
      data-testid={`agent-canvas-node-${node.node_id}`}
      data-node-type={node.node_type}
      data-node-status={status}
      aria-label={`${label} node, ${NODE_STATUS_LABELS[status]}`}
      onDragOver={handleCardDragOver}
      onDrop={handleCardDrop}
    >
      <AgentCanvasNodeHeader node={node} status={status} runtime={runtime} dimensions={resolvedMediaDimensions} onOpenConnectedNodeMenu={onOpenConnectedNodeMenu} />
      <div className="agent-canvas-node__surface">
        <NodeSurface
          node={node}
          asset={asset}
          status={status}
          label={label}
          onOpenVideoPreview={onOpenVideoPreview}
          onOpenEditing={onOpenEditing}
          onMediaDimensionsResolved={onMediaDimensionsResolved}
          onScriptContentHeightResolved={onScriptContentHeightResolved}
        />
        {status === "working" && (node.node_type === "image" || node.node_type === "video") ? (
          <AgentCanvasMediaGenerationLoader mediaType={node.node_type} nodeId={node.node_id} />
        ) : status === "working" && node.node_type !== "audio" ? (
          <div className="agent-canvas-node__working" aria-label={`${node.node_type} node is working`}>
            <span className="agent-canvas-node__working-orbit" aria-hidden="true" />
            <span className="agent-canvas-node__working-sheen" aria-hidden="true" />
          </div>
        ) : status === "failed" && onRetry ? (
          <button
            type="button"
            className="agent-canvas-node__retry-button"
            onClick={() => onRetry(node.node_id)}
            aria-label={`Retry ${label} node`}
          >
            <span className="agent-canvas-node__retry-icon" aria-hidden="true">↻</span>
            Retry
          </button>
        ) : null}
      </div>

      {usedDeterministicFallback ? (
        <span className="agent-canvas-node__fallback-warning" role="status">
          Created with a simplified fallback
        </span>
      ) : null}

      {omittedOptionalInputsCount > 0 ? (
        <span className="agent-canvas-node__omitted-warning" role="status" title={`${omittedOptionalInputsCount} optional input(s) were not ready and were skipped`}>
          {omittedOptionalInputsCount} optional input skipped
        </span>
      ) : null}

      {status === "failed" && runtime?.error ? (
        <span
          className="agent-canvas-node__error-message"
          role="alert"
          title={typeof runtime.error === "string" ? runtime.error : runtime.error.message || JSON.stringify(runtime.error)}
        >
          {typeof runtime.error === "string"
            ? runtime.error
            : runtime.error.message || "Execution failed"}
        </span>
      ) : null}

    </article>
  );
}

function AgentCanvasNodeRendererComponent({
  id,
  data,
  selected,
  isConnectable,
}: AgentCanvasNodeRendererProps) {
  const updateNodeInternals = useUpdateNodeInternals();
  const [intrinsicDimensions, setIntrinsicDimensions] = useState<(
    AgentCanvasMediaDimensions & { assetId: string | null }
  ) | null>(null);
  const [scriptContentHeight, setScriptContentHeight] = useState(0);
  const label = creativeRoleDisplayName(data.node.creative_role);
  const workbench = data.node.node_type === "editing"
    ? null
    : data.renderWorkbench?.(data.node, data.runtime ?? null);
  const assetDimensions = validAgentCanvasMediaDimensions(data.asset)
    ? { width: data.asset.width, height: data.asset.height }
    : intrinsicDimensions?.assetId === (data.asset?.asset_id ?? null)
      ? intrinsicDimensions
      : null;
  const baseNodeSize = agentCanvasNodeSize(data.node.node_type, assetDimensions);
  const nodeSize = data.node.node_type === "script"
    ? { ...baseNodeSize, height: scriptNodeHeightForContent(scriptContentHeight) }
    : baseNodeSize;
  const handleScriptContentHeightResolved = useCallback((height: number) => {
    setScriptContentHeight((current) => current === height ? current : height);
  }, []);

  useLayoutEffect(() => {
    updateNodeInternals(id);
  }, [id, nodeSize.height, nodeSize.width, updateNodeInternals]);

  return (
    <div
      className="agent-canvas-node-shell"
      style={{ width: nodeSize.width, height: nodeSize.height }}
    >
      {data.showInputHandle !== false ? (
        <Handle
          id="input"
          className="agent-canvas-node__handle agent-canvas-node__handle--input nodrag"
          type="target"
          position={Position.Left}
          isConnectable={isConnectable}
          title="拖到另一个节点可建立连接" 
          aria-label={`${label} node input`}
        />
      ) : null}
      <AgentCanvasNodeCard
        node={data.node}
        asset={data.asset}
        runtime={data.runtime}
        selected={selected}
        onOpenVideoPreview={data.onOpenVideoPreview}
        onOpenEditing={data.onOpenEditing}
        onMediaDimensionsResolved={validAgentCanvasMediaDimensions(data.asset)
          ? undefined
          : ({ width, height }) => setIntrinsicDimensions({
              assetId: data.asset?.asset_id ?? null,
              width,
              height,
            })}
        onScriptContentHeightResolved={data.node.node_type === "script"
          ? handleScriptContentHeightResolved
          : undefined}
        mediaDimensions={validAgentCanvasMediaDimensions(assetDimensions) ? assetDimensions : null}
      />
      {workbench ? (
        <NodeToolbar
          nodeId={id}
          isVisible
          position={Position.Bottom}
          offset={18}
          align="center"
          className="agent-canvas-node-workbench-toolbar nodrag nopan nowheel"
          onDoubleClick={(event) => event.stopPropagation()}
        >
          {workbench}
        </NodeToolbar>
      ) : null}
      {data.showOutputHandle !== false ? (
        <Handle
          id="output"
          className="agent-canvas-node__handle agent-canvas-node__handle--output nodrag"
          type="source"
          position={Position.Right}
          isConnectable={isConnectable}
          title="拖到另一个节点可建立连接" 
          aria-label={`${label} node output`}
        />
      ) : null}
    </div>
  );
}

export const AgentCanvasNodeRenderer = memo(
  AgentCanvasNodeRendererComponent,
  areAgentCanvasNodePropsEqual,
);
