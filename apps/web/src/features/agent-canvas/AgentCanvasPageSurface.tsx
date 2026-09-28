import { useSyncExternalStore } from "react";
import {
  applyNodeChanges,
  Controls,
  ReactFlow,
  type Connection,
  type Edge,
  type NodeChange,
  type ReactFlowInstance,
  type Viewport,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { Link } from "react-router-dom";

import { agentCanvasApi } from "../../api/agentCanvasApi.ts";
import { useApp } from "../../AppContextValue.ts";
import { createOperationKey } from "../../api/operationKey.ts";
import { timelineRefreshNonce } from "./timeline/timelineRefresh.ts";
import { timelineMutationRefreshStore } from "./timeline/timelineMutationRefresh.ts";
import type { TimelineClipV1 } from "./timeline/timelineTypes.ts";
import {
  AssetsIcon,
  LayoutIcon,
  PauseIcon,
  PlayIcon,
  PlusIcon,
} from "../../icons.tsx";
import { canvasCardDropIntent } from "./canvas/canvasDrop.ts";
import { addCharacterFromAsset } from "./canvas/sceneScriptEditModel.ts";
import {
  SCENE_SCRIPT_CONTENT_KEY,
  extractSceneScriptFromNode,
} from "./model/sceneScriptUtils.ts";
import type {
  AgentCanvasWorkflowV2,
  CanvasBindingInputRoleV2,
  WorkflowProgressResponse,
  CanvasConnectionPolicyV2,
  CanvasLayoutPositionV2,
  CanvasNodeV2,
  CanvasPositionV2,
  CreationFlowAssessmentResponse,
  NodeRuntimeV2,
  ProjectAssetSummaryV2,
  SaveAgentCanvasImageToLibraryRequestV2,
} from "../../types-v2.ts";
import type {
  AgentAssetReferenceSelection,
  AgentAssetSourceNodeSelection,
} from "./assets/AgentAssetBrowser.tsx";
import { toImageBindingSource } from "./assets/assetSelection.ts";
import {
  AgentCanvasNodeRenderer,
  NODE_TYPE_LABELS,
  type AgentCanvasFlowNode,
  type AgentCanvasNodeCallbacks,
} from "./canvas/AgentCanvasNode.tsx";
import { AgentCanvasConnectedNodeMenu } from "./canvas/AgentCanvasConnectedNodeMenu.tsx";
import type { AlignedLine } from "./canvas/DialogueAlignmentPanel.tsx";
import { PlayheadSyncProvider } from "./PlayheadSyncContext.tsx";
import { CreationFlowGuidance } from "./canvas/CreationFlowGuidance.tsx";
import { AgentCanvasContextMenu } from "./canvas/AgentCanvasContextMenu.tsx";
import { AgentCanvasLayoutConfirmation } from "./canvas/AgentCanvasLayoutConfirmation.tsx";
import { AgentCanvasNodePicker } from "./canvas/AgentCanvasNodePicker.tsx";
import { AgentCanvasPointerBackgrounds } from "./canvas/AgentCanvasPointerBackgrounds.tsx";
import { AgentCanvasConnectionLine } from "./canvas/AgentCanvasConnectionLine.tsx";
import { AgentCanvasEdge } from "./canvas/AgentCanvasEdge.tsx";
import {
  AGENT_CANVAS_CONNECTION_RADIUS,
  AGENT_CANVAS_EDGE_TYPE,
} from "./canvas/canvasConnectionGeometry.ts";
import {
  agentCanvasLayoutNodeFromFlowNode,
  computeAgentCanvasAutoLayout,
  enabledNodeLayoutEdges,
} from "./canvas/canvasAutoLayout.ts";
import { canvasAuthoringErrorMessage } from "./canvas/canvasErrorMessage.ts";
import { useCanvasPointerSpotlight } from "./canvas/canvasPointerSpotlight.ts";
import {
  createCanvasEdgeZoomController,
  type CanvasEdgeZoomController,
} from "./canvas/canvasEdgeRendering.ts";
import { FrozenCanvasEdgesOverlay } from "./canvas/FrozenCanvasEdgesOverlay.tsx";
import {
  CanvasPreviewPrefetcher,
  type CanvasPreviewPrefetchHandle,
} from "./canvas/CanvasPreviewPrefetcher.tsx";
import {
  captureFrozenCanvasEdges,
  partitionCanvasEdges,
  type FrozenCanvasEdgeSnapshot,
} from "./canvas/frozenCanvasEdges.ts";
import { shouldPersistAgentCanvasViewport } from "./canvas/canvasViewportPersistence.ts";
import {
  installAgentCanvasWorkflowViewport,
  readAgentCanvasViewport,
  writeAgentCanvasViewport,
} from "./canvas/agentCanvasViewport.ts";
import {
  beginNodeDrag,
  cancelNodeDrag,
  deferNodeSnapshotDuringDrag,
  finishNodeDrag,
} from "./canvas/draggingNodeState.ts";
import {
  findAvailableCanvasPosition,
  highlightNodeRelatedCanvasEdges,
  needsInitialCanvasLayout,
  patchAgentCanvasFlowNodes,
  reconcileCanvasFlowSnapshot,
  reconcileSelectableCanvasEdges,
  runtimeChangedCanvasNodeIds,
  reuseCanvasArray,
  toAgentCanvasFlowEdgesForNodeIds,
  toAgentCanvasFlowNodes,
} from "./canvas/canvasGraphModel.ts";
import {
  CANVAS_DROP_MIME,
  canvasDropCreateRequest,
  canvasNodeTypeForMedia,
  parseCanvasDropPayload,
} from "./canvas/canvasDrop.ts";
import {
  planRowGapInsert,
  snapCanvasDropPosition,
  snapDraggedNode,
  type SnapBox,
} from "./canvas/canvasSnap.ts";
import {
  AGENT_CANVAS_NODE_HORIZONTAL_GAP,
  agentCanvasNodePlacementSize,
} from "./canvas/nodeGeometry.ts";
import { connectionRuleForPair } from "./canvas/connectionPolicy.ts";
import { useOptimisticCanvasConnections } from "./canvas/useOptimisticCanvasConnections.ts";
import { deleteCanvasEntities } from "./canvas/deleteCanvasEntities.ts";
import {
  AGENT_CANVAS_FOCUS_MAX_ZOOM,
  useAgentCanvasNodeFocus,
} from "./canvas/useAgentCanvasNodeFocus.ts";
import { useAgentCanvasNodeRevealQueue } from "./canvas/useAgentCanvasNodeRevealQueue.ts";
import { useAgentCanvasLayoutPreview } from "./canvas/useAgentCanvasLayoutPreview.ts";
import {
  AGENT_CANVAS_ROLE_CONTRACT_VERSION,
  createDefaultCanvasNodeRequest,
  sourceAssetStructuredContent,
  type AgentCanvasVisibleNodeTypeV2,
} from "./model/nodeDefaults.ts";
import { hasPromptReadyDraft } from "./model/promptPreparation.ts";
import { useAgentCanvasProviderModels } from "./model/useAgentCanvasProviderModels.ts";
import { NodeRunBlockedError, useAgentCanvasRuntime } from "./runtime/useAgentCanvasRuntime.ts";
import { useAgentCanvasSession } from "./session/useAgentCanvasSession.ts";

const nodeTypes = { agentCanvas: AgentCanvasNodeRenderer };
const edgeTypes = { [AGENT_CANVAS_EDGE_TYPE]: AgentCanvasEdge };

const AgentAssetBrowser = lazy(() => import("./assets/AgentAssetBrowser.tsx").then((module) => ({
  default: module.AgentAssetBrowser,
})));
const AgentCanvasChatPanel = lazy(() => import("./chat/AgentCanvasChatPanel.tsx").then((module) => ({
  default: module.AgentCanvasChatPanel,
})));
const AgentCanvasEditingPanel = lazy(() => import("./editing/AgentCanvasEditingPanel.tsx").then((module) => ({
  default: module.AgentCanvasEditingPanel,
})));
const AgentCanvasInlineWorkbench = lazy(() => import("./workbench/AgentCanvasInlineWorkbench.tsx").then((module) => ({
  default: module.AgentCanvasInlineWorkbench,
})));
const AgentCanvasVideoPreviewDialog = lazy(() => import("./canvas/AgentCanvasVideoPreviewDialog.tsx").then((module) => ({
  default: module.AgentCanvasVideoPreviewDialog,
})));
const GlobalTimelinePanel = lazy(() => import("./timeline/GlobalTimelinePanel.tsx").then((module) => ({
  default: module.GlobalTimelinePanel,
})));

function reducedMotionPreference(): boolean {
  return typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

type CanvasInteractionReason = "viewport" | "node-drag";

/**
 * Read character ids declared by a node's embedded scene script.
 * The script may live in structured_content or metadata, as an object or a
 * JSON string; this is a deliberately tolerant local read used to populate
 * voice-clip speaker options. Returns [] when nothing usable is found.
 */
function readSceneCharacterIds(node: unknown): string[] {
  const holder = (node ?? {}) as {
    structured_content?: Record<string, unknown> | null;
    metadata?: Record<string, unknown> | null;
  };
  const raw = holder.structured_content?.scene_script ?? holder.metadata?.scene_script;
  if (!raw) return [];
  let parsed: unknown = raw;
  if (typeof raw === "string") {
    try {
      parsed = JSON.parse(raw);
    } catch {
      return [];
    }
  }
  const characters = (parsed as { characters?: unknown } | null)?.characters;
  if (!Array.isArray(characters)) return [];
  return characters
    .map((entry) =>
      typeof entry === "object" && entry !== null
        ? (entry as { id?: unknown }).id
        : undefined,
    )
    .filter((id): id is string => typeof id === "string");
}

/** A node's placement box for snapping (its rendered size, from the same
 * geometry the auto-layout uses). */
function canvasSnapBoxFor(
  flowNode: AgentCanvasFlowNode,
  assets: readonly ProjectAssetSummaryV2[],
): SnapBox {
  const node = flowNode.data.node;
  const asset = node.output_asset_id
    ? assets.find((candidate) => candidate.asset_id === node.output_asset_id) ?? null
    : null;
  const size = agentCanvasNodePlacementSize(
    node.node_type,
    asset ? { width: asset.width, height: asset.height } : null,
  );
  return { id: node.node_id, position: flowNode.position, size };
}

/**
 * Snap every node that was just dragged against the nodes that were not.
 * Returns the adjusted flow nodes plus the position overrides to persist
 * (only the snapped ones); unsnapped drags come back untouched.
 */
function applyCanvasDragSnap(
  flowNodes: readonly AgentCanvasFlowNode[],
  draggedIds: ReadonlySet<string>,
  assets: readonly ProjectAssetSummaryV2[],
): {
  nodes: AgentCanvasFlowNode[];
  positionOverrides: Record<string, { x: number; y: number }>;
} {
  const still = flowNodes.filter((flowNode) => !draggedIds.has(flowNode.data.node.node_id));
  const siblings = still.map((flowNode) => canvasSnapBoxFor(flowNode, assets));
  const overrides: Record<string, { x: number; y: number }> = {};
  const nodes = flowNodes.map((flowNode) => {
    if (!draggedIds.has(flowNode.data.node.node_id)) return flowNode;
    const dragged = canvasSnapBoxFor(flowNode, assets);
    const result = snapDraggedNode(dragged, siblings);
    if (!result.snap) return flowNode;
    overrides[dragged.id] = result.position;
    return { ...flowNode, position: result.position };
  });
  return { nodes, positionOverrides: overrides };
}

export function AgentCanvasPage() {
  const { refreshProjects } = useApp();
  const session = useAgentCanvasSession();
  const pointerSpotlight = useCanvasPointerSpotlight<HTMLDivElement>();
  const {
    resume: resumePointerSpotlight,
    suspend: suspendPointerSpotlight,
  } = pointerSpotlight;
  const workflow = session.state.workflow;
  const hasRunnableDraft = workflow ? hasPromptReadyDraft(workflow.nodes) : false;
  const {
    applyWorkflow,
    clearAuthoringError,
    createBinding,
    createConnectedNode,
    createNode: createCanvasNode,
    deleteBinding,
    deleteNode,
    importEditingExport,
    mergeNode,
    mergePublishedAsset,
    patchNode,
    patchBinding,
    persistLayoutPreviewPositions,
    placeActionReceiptNodes,
    setSelectedNodeId,
    rollbackNodePositions,
    updateNodePositions,
  } = session.actions;
  const runtimeCallbacks = useMemo(() => ({
    applyWorkflow,
    mergePublishedAsset,
    mergeNode,
  }), [
    applyWorkflow,
    mergeNode,
    mergePublishedAsset,
  ]);
  const live = useAgentCanvasRuntime(workflow, runtimeCallbacks, patchNode);
  const providerModels = useAgentCanvasProviderModels(workflow, session.state.selectedNode);
  const {
    cancelRun,
    clearAutoRunNotice,
    refreshRuntime,
    refreshAssets,
    refreshWorkflow,
    runAll,
    retryAllFailed,
    runNode,
  } = live.actions;
  const [nodes, setNodes] = useNodesState<AgentCanvasFlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [assetsOpen, setAssetsOpen] = useState(false);
  const [addMenuOpen, setAddMenuOpen] = useState(false);
  const [chatCollapsed, setChatCollapsed] = useState(false);
  const [canvasInteracting, setCanvasInteracting] = useState(false);
  const [dragEdgeProjection, setDragEdgeProjection] = useState<{
    liveEdgeIds: ReadonlySet<string>;
    frozenSnapshots: readonly FrozenCanvasEdgeSnapshot[];
  } | null>(null);
  const [editingNodeId, setEditingNodeId] = useState<string | null>(null);
  const [videoPreview, setVideoPreview] = useState<{
    asset: ProjectAssetSummaryV2;
    title: string;
  } | null>(null);
  const [contextMenu, setContextMenu] = useState<(
    | {
      kind: "canvas";
      menuPosition: CanvasPositionV2;
      canvasPosition: CanvasPositionV2;
    }
    | {
      kind: "node";
      menuPosition: CanvasPositionV2;
      nodeId: string;
    }
  ) | null>(null);
  const [surfaceError, setSurfaceError] = useState<string | null>(null);
  // C-mode handoff (ADR 0005): lines recovered from whichever voice-cast bed
  // was last aligned. Lives at the surface because the alignment panel and
  // the lip-sync editor render in DIFFERENT node workbenches, selected one
  // at a time — the state must survive the selection switch.
  const [alignedSpeechLines, setAlignedSpeechLines] = useState<AlignedLine[] | null>(null);
  const { displayEdges, submit: submitOptimisticConnection, cancelForNodes: cancelPendingNodeConnections, nextOrder: nextConnectionOrder } = useOptimisticCanvasConnections({
    workflow,
    edges,
    createBinding,
    onError: (error) => setSurfaceError(canvasAuthoringErrorMessage(error)),
  });
  const [connectionPolicy, setConnectionPolicy] = useState<CanvasConnectionPolicyV2 | null>(null);
  const [connectedNodeMenu, setConnectedNodeMenu] = useState<{
    anchorNodeId: string;
    direction: "upstream" | "downstream";
    point: { x: number; y: number };
  } | null>(null);
  const flowRef = useRef<ReactFlowInstance<AgentCanvasFlowNode, Edge> | null>(null);
  const edgeZoomControllerRef = useRef<CanvasEdgeZoomController | null>(null);
  const previewPrefetchRef = useRef<CanvasPreviewPrefetchHandle | null>(null);
  const activeWorkflowIdRef = useRef(workflow?.workflow_id ?? "no-workflow");
  const [serverProgress, setServerProgress] = useState<WorkflowProgressResponse | null>(null);
  const [diagnosticOpen, setDiagnosticOpen] = useState(false);
  const [creationFlowOpen, setCreationFlowOpen] = useState(false);
  const [creationFlowAssessment, setCreationFlowAssessment] = useState<CreationFlowAssessmentResponse | null>(null);
  // CreationFlowGuidance re-fetches whenever this callback identity changes, so it must stay stable.
  const handleCreationFlowAssessment = useCallback((assessment: CreationFlowAssessmentResponse) => {
    setCreationFlowAssessment(assessment);
  }, []);
  const workflowNodesRef = useRef(workflow?.nodes ?? []);
  const canonicalNodesRef = useRef<readonly AgentCanvasFlowNode[]>([]);
  const visibleCanonicalNodesRef = useRef<readonly AgentCanvasFlowNode[]>([]);
  const visibleCanonicalNodeIdsRef = useRef<readonly string[]>([]);
  const presentedNodesRef = useRef<readonly AgentCanvasFlowNode[]>([]);
  const canonicalEdgesRef = useRef<readonly Edge[]>([]);
  const presentedEdgesRef = useRef<readonly Edge[]>([]);
  const canonicalProjectionInputsRef = useRef<{
    workflowId: string;
    nodes: readonly CanvasNodeV2[];
    assets: readonly ProjectAssetSummaryV2[];
    callbacks: AgentCanvasNodeCallbacks;
    activeWorkbenchNodeId: string | null;
    runtime: typeof live.state.runtime;
  } | null>(null);
  const initialLayoutRepairWorkflowIdsRef = useRef(new Set<string>());
  const installedViewportWorkflowIdRef = useRef<string | null>(null);
  const viewportInstallFrameRef = useRef<number | null>(null);
  const layoutButtonRef = useRef<HTMLButtonElement>(null);
  const activeDraggedNodeIdsRef = useRef(new Set<string>());
  const canvasInteractionReasonsRef = useRef(new Set<CanvasInteractionReason>());
  const dragCancellationPendingRef = useRef(false);

  if (edgeZoomControllerRef.current === null) {
    edgeZoomControllerRef.current = createCanvasEdgeZoomController({
      getElement: () => pointerSpotlight.hostRef.current,
    });
  }

  useEffect(() => () => {
    edgeZoomControllerRef.current?.dispose();
  }, []);
  const latestPresentedNodesRef = useRef<readonly AgentCanvasFlowNode[]>([]);
  const pendingPresentedNodesRef = useRef<readonly AgentCanvasFlowNode[] | null>(null);
  const flowNodesRef = useRef<readonly AgentCanvasFlowNode[]>(nodes);
  const pendingDragNodeChangesRef = useRef(new Map<string, NodeChange<AgentCanvasFlowNode>>());
  const pendingDragNodeFrameRef = useRef<number | null>(null);
  const referenceUploadInputRef = useRef<HTMLInputElement>(null);
  activeWorkflowIdRef.current = workflow?.workflow_id ?? "no-workflow";

  // Poll server progress when nodes are working or failed
  useEffect(() => {
    if (!workflow?.workflow_id) return;
    const hasActiveNodes = workflow.nodes.some((n) => n.status === "working" || n.status === "failed");
    if (!hasActiveNodes) {
      setServerProgress(null);
      return;
    }
    let cancelled = false;
    const fetchProgress = async () => {
      try {
        const progress = await agentCanvasApi.getWorkflowProgress(workflow.workflow_id);
        if (!cancelled) setServerProgress(progress);
      } catch {
        // Silent fail - fall back to local computation
      }
    };
    void fetchProgress();
    const interval = setInterval(() => void fetchProgress(), 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [workflow?.workflow_id, workflow?.nodes.some((n) => n.status === "working" || n.status === "failed")]);
  workflowNodesRef.current = workflow?.nodes ?? [];
  useEffect(() => {
    flowNodesRef.current = nodes;
  }, [nodes]);
  const visibleFrozenSnapshots = useMemo(() => {
    const visibleIds = new Set(displayEdges.map((edge) => edge.id));
    return dragEdgeProjection?.frozenSnapshots.filter((snapshot) => visibleIds.has(snapshot.id)) ?? [];
  }, [dragEdgeProjection, displayEdges]);
  const renderedEdges = useMemo(() => {
    if (!visibleFrozenSnapshots.length) return displayEdges;
    const frozenIds = new Set(visibleFrozenSnapshots.map((snapshot) => snapshot.id));
    return displayEdges.filter((edge) => !frozenIds.has(edge.id));
  }, [visibleFrozenSnapshots, displayEdges]);
  const setCanvasInteractionReason = useCallback((
    reason: CanvasInteractionReason,
    active: boolean,
  ) => {
    const reasons = canvasInteractionReasonsRef.current;
    const wasInteracting = reasons.size > 0;
    if (active) reasons.add(reason);
    else reasons.delete(reason);
    const nextInteracting = reasons.size > 0;
    if (nextInteracting && !wasInteracting) suspendPointerSpotlight();
    if (!nextInteracting && wasInteracting) resumePointerSpotlight();
    setCanvasInteracting((current) => current === nextInteracting ? current : nextInteracting);
  }, [resumePointerSpotlight, suspendPointerSpotlight]);
  const beginCanvasInteraction = useCallback((reason: CanvasInteractionReason) => {
    setCanvasInteractionReason(reason, true);
  }, [setCanvasInteractionReason]);
  const endCanvasInteraction = useCallback((reason: CanvasInteractionReason) => {
    setCanvasInteractionReason(reason, false);
  }, [setCanvasInteractionReason]);
  const clearCanvasInteractions = useCallback(() => {
    if (canvasInteractionReasonsRef.current.size) resumePointerSpotlight();
    canvasInteractionReasonsRef.current.clear();
    previewPrefetchRef.current?.setPaused(false);
    setCanvasInteracting(false);
  }, [resumePointerSpotlight]);
  const scheduleLayoutButtonFocus = useCallback(() => {
    window.requestAnimationFrame(() => layoutButtonRef.current?.focus());
  }, []);
  const restoreLayoutViewport = useCallback((viewport: Viewport, previewWorkflowId: string) => {
    if (activeWorkflowIdRef.current !== previewWorkflowId) return;
    return flowRef.current?.setViewport(viewport);
  }, []);
  const layoutPreview = useAgentCanvasLayoutPreview({
    workflowId: workflow?.workflow_id ?? "no-workflow",
    persistPositions: persistLayoutPreviewPositions,
    restoreViewport: restoreLayoutViewport,
    rollbackPositions: rollbackNodePositions,
    // The hook invokes this only for explicit Undo/Keep, so project navigation keeps its focus target.
    onUserResolution: scheduleLayoutButtonFocus,
  });
  const {
    active: layoutPreviewActive,
    begin: beginLayoutPreview,
    cancel: cancelLayoutPreview,
    keep: persistLayoutPreview,
    overlay: overlayLayoutPreview,
  } = layoutPreview;
  const undoLayoutPreview = useCallback(() => cancelLayoutPreview("explicit"), [cancelLayoutPreview]);
  const dismissLayoutPreview = useCallback(() => cancelLayoutPreview("implicit"), [cancelLayoutPreview]);
  const keepLayoutPreview = useCallback(() => {
    void persistLayoutPreview();
  }, [persistLayoutPreview]);
  const {
    focusedNodeId,
    highlightedNodeIds,
    focusNode: focusCanvasNode,
    revealNodes: revealCanvasNodes,
    exitFocus: exitCanvasNodeFocus,
    scheduleExitForNodeSelection,
  } = useAgentCanvasNodeFocus({
    flowRef,
    scopeKey: workflow?.workflow_id ?? "no-workflow",
  });
  const focusNode = useCallback((nodeId: string) => {
    setSelectedNodeId(nodeId);
    void flowRef.current?.fitView({
      nodes: [{ id: nodeId }],
      padding: 0.55,
      duration: reducedMotionPreference() ? 0 : 420,
      maxZoom: 1.15,
    });
  }, [setSelectedNodeId]);
  const revealQueue = useAgentCanvasNodeRevealQueue({
    workflowId: workflow?.workflow_id ?? null,
    flowRef,
    onFocusNode: focusNode,
    reducedMotion: reducedMotionPreference(),
  });
  const {
    activeNodeId: progressiveActiveNodeId,
    enqueue: enqueueReveal,
    interrupt: interruptReveal,
    releaseNodeIds: releaseRevealNodeIds,
    reserveNodeIds: reserveRevealNodeIds,
    syncCanonicalNodeIds: syncRevealCanonicalNodeIds,
    visibleNodeIds: visibleRevealNodeIds,
  } = revealQueue;
  const revealAvailableCanvasNodes = useCallback((nodeIds: string[]) => {
    const visibleNodeIds = new Set(flowNodesRef.current.map((node) => node.id));
    revealCanvasNodes(nodeIds.filter((nodeId) => visibleNodeIds.has(nodeId)));
  }, [revealCanvasNodes]);

  // Register receipt-owned nodes before the Workflow refresh triggered by the
  // same event can make them visible. Edges remain hidden because they are
  // derived exclusively from visible node ids.
  useEffect(() => {
    live.state.chatEvents.forEach((event) => {
      if (event.event_type !== "action_receipt_created") return;
      const createdNodeIds = event.payload?.created_node_ids;
      if (!Array.isArray(createdNodeIds)) return;
      const ids = createdNodeIds.filter((id): id is string => typeof id === "string");
      if (ids.length) reserveRevealNodeIds(ids);
    });
  }, [live.state.chatEvents, reserveRevealNodeIds]);

  // Live timeline refresh signal: node_output_published drives the server-side
  // auto-clip creator (create or in-place update). Chat and document streams
  // may both carry the same event; max seq keeps the nonce duplicate-safe.
  const timelineRefreshSignal = useMemo(
    () =>
      timelineRefreshNonce(
        [...live.state.chatEvents, ...live.state.documentEvents],
        workflow?.workflow_id ?? "",
      ),
    [
      live.state.chatEvents,
      live.state.documentEvents,
      workflow?.workflow_id,
    ],
  );
  // Client-side timeline mutations (subtitle publish, ...) emit no SSE event:
  // fold in their signal so an open panel resyncs immediately. The sum of two
  // non-decreasing counters strictly grows whenever either source moves.
  const timelineMutationSignal = useSyncExternalStore(
    timelineMutationRefreshStore.subscribe,
    timelineMutationRefreshStore.getSnapshot,
  );
  const timelineExternalRefreshSignal = timelineRefreshSignal + timelineMutationSignal;
  const workflowNodeIdSet = useMemo(
    () => new Set((workflow?.nodes ?? []).map((node) => node.node_id)),
    [workflow?.nodes],
  );
  // Characters declared across scene-3d nodes; offered as voice-clip speakers.
  const availableTimelineCharacters = useMemo(() => {
    const seen = new Set<string>();
    const characters: { id: string; label?: string }[] = [];
    for (const node of workflow?.nodes ?? []) {
      for (const id of readSceneCharacterIds(node)) {
        if (seen.has(id)) continue;
        seen.add(id);
        characters.push({ id });
      }
    }
    return characters;
  }, [workflow?.nodes]);
  useEffect(() => {
    let active = true;
    void agentCanvasApi.agentCanvasConnectionPolicy()
      .then((policy) => {
        if (active) setConnectionPolicy(policy);
      })
      .catch((error) => {
        if (active) setSurfaceError(canvasAuthoringErrorMessage(error));
      });
    return () => {
      active = false;
    };
  }, []);

  const runNodeById = useCallback((nodeId: string, retryFailed = false) => {
    const node = workflow?.nodes.find((candidate) => candidate.node_id === nodeId);
    if (node) void runNode(node, { retryFailed }).catch((error) => {
      if (error instanceof NodeRunBlockedError) {
        const hint = error.suggestedNext ? ` —${error.suggestedNext}` : "";
        setSurfaceError(`Cannot run this node: ${error.message}${hint}`);
      } else {
        // D4: 运行期失败（如 scene3d_blender_unavailable / mcp_unavailable）
        // 走共享翻译层——用户看到可行动的说明，而不是后端原始 message。
        setSurfaceError(canvasAuthoringErrorMessage(error));
      }
    });
  }, [runNode, workflow?.nodes]);

  const openEditing = useCallback((nodeId: string) => {
    setEditingNodeId(nodeId);
    setSelectedNodeId(nodeId);
  }, [setSelectedNodeId]);

  const addEditingExportToCanvas = useCallback(async (exportId: string) => {
    if (!workflow || !editingNodeId) {
      throw new Error("Select an Editing node before importing an export.");
    }
    const editingNode = workflow.nodes.find((candidate) => (
      candidate.node_id === editingNodeId && candidate.node_type === "editing"
    ));
    if (!editingNode) throw new Error("The Editing node is no longer available.");
    const editingAsset = editingNode.output_asset_id
      ? workflow.assets.find((asset) => asset.asset_id === editingNode.output_asset_id) ?? null
      : null;
    const sourceSize = agentCanvasNodePlacementSize(
      editingNode.node_type,
      editingAsset ? { width: editingAsset.width, height: editingAsset.height } : null,
    );
    const videoSize = agentCanvasNodePlacementSize("video");
    const position = findAvailableCanvasPosition(
      workflow.nodes,
      {
        x: editingNode.position.x + sourceSize.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP,
        y: editingNode.position.y,
      },
      {
        assets: workflow.assets,
        candidateNodeType: "video",
        candidateDimensions: videoSize,
      },
    );
    setSurfaceError(null);
    try {
      await importEditingExport(editingNode.node_id, {
        export_id: exportId,
        title: "Exported video",
        position,
      });
      setEditingNodeId(null);
    } catch (error) {
      setSurfaceError(error instanceof Error ? error.message : "The exported video could not be added to canvas.");
      throw error;
    }
  }, [editingNodeId, importEditingExport, workflow]);

  const closeVideoPreview = useCallback(() => {
    setVideoPreview(null);
  }, []);

  const uploadSelectedNodeReferences = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.currentTarget.files ?? []);
    event.currentTarget.value = "";
    const targetNode = session.state.selectedNode;
    if (!workflow || !targetNode || !files.length) return;
    if (targetNode.node_type === "editing") {
      setSurfaceError("Use connected Video and Audio nodes as Editing inputs.");
      return;
    }
    const imageFiles = files.filter((file) => file.type.startsWith("image/"));
    if (imageFiles.length !== files.length) {
      setSurfaceError("Only image files can be attached as prompt references.");
      return;
    }
    setSurfaceError(null);
    try {
      const startOrder = workflow.bindings.filter((binding) => (
        binding.target_node_id === targetNode.node_id
      )).length;
      for (const [index, file] of imageFiles.entries()) {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("metadata", JSON.stringify({
          media_type: "image",
          title: file.name.replace(/\.[^.]+$/, "") || file.name,
          semantic_role: null,
          metadata: {},
        }));
        const uploaded = await agentCanvasApi.uploadAgentCanvasAsset(
          workflow.workflow_id,
          formData,
          createOperationKey("node-reference-upload"),
        );
        if (!uploaded.asset.version_id) {
          throw new Error(`Uploaded image ${uploaded.asset.display_name} has no immutable AssetVersion.`);
        }
        await createBinding({
          source: {
            kind: "image_asset",
            source_asset_id: uploaded.asset.asset_id,
            source_asset_version_id: uploaded.asset.version_id,
          },
          target_node_id: targetNode.node_id,
          input_role: "image_reference",
          enabled: true,
          order: startOrder + index,
        });
      }
      await refreshWorkflow();
    } catch (error) {
      setSurfaceError(error instanceof Error ? error.message : "Reference upload failed.");
    }
  }, [createBinding, refreshWorkflow, session.state.selectedNode, workflow]);

  const saveImageToLibrary = useCallback(async (
    assetId: string,
    request: SaveAgentCanvasImageToLibraryRequestV2,
  ) => {
    await agentCanvasApi.saveAgentCanvasImageToLibrary(
      assetId,
      request,
      createOperationKey("save-image-to-library"),
    );
  }, []);

  const renderWorkbench = useCallback((node: CanvasNodeV2, runtime: NodeRuntimeV2 | null) => {
    if (!workflow || session.state.selectedNodeId !== node.node_id) return null;
    return (
      <Suspense fallback={null}>
        <AgentCanvasInlineWorkbench
          workflow={workflow}
          node={node}
          runtime={runtime}
          patchNode={patchNode}
          patchBinding={patchBinding}
          deleteBinding={deleteBinding}
          connectionPolicy={connectionPolicy}
          providerModels={providerModels.models}
          providerDefaultModelRef={providerModels.defaultModelRef}
          providerModelsLoading={providerModels.loading}
          providerModelsError={providerModels.error}
          inputManifest={live.state.inputManifestsByNodeId[node.node_id]}
          modelResolution={live.state.modelResolutionsByNodeId[node.node_id]}
          inputReadinessIssue={live.state.inputReadinessIssue}
          onRun={runNode}
          onSaveImageToLibrary={saveImageToLibrary}
          onDelete={deleteNode}
          onOpenEditing={() => openEditing(node.node_id)}
          onWorkflowRefresh={refreshWorkflow}
          onOpenAssets={() => setAssetsOpen(true)}
          onUploadReferences={() => referenceUploadInputRef.current?.click()}
          onClose={() => setSelectedNodeId(null)}
          alignedSpeechLines={alignedSpeechLines}
          onSpeechLinesAligned={setAlignedSpeechLines}
        />
      </Suspense>
    );
  }, [connectionPolicy, deleteBinding, deleteNode, live.state.inputManifestsByNodeId, live.state.inputReadinessIssue, live.state.modelResolutionsByNodeId, openEditing, patchBinding, patchNode, providerModels.defaultModelRef, providerModels.error, providerModels.loading, providerModels.models, refreshWorkflow, runNode, saveImageToLibrary, session.state.selectedNodeId, setSelectedNodeId, workflow, alignedSpeechLines]);

  const openNodeVideoPreview = useCallback((nodeId: string, asset: ProjectAssetSummaryV2) => {
    const node = workflowNodesRef.current.find((candidate) => candidate.node_id === nodeId);
    setVideoPreview({
      asset,
      title: asset.display_name || node?.title || "Video preview",
    });
  }, []);

  /**
   * V0.2 §2.2: 卡片内部 = 素材归属. An image asset dropped on a card becomes
   * that node's reference input — the same binding the reference strip adds,
   * reached by a gesture instead of a menu. The asset is resolved against the
   * workflow so the binding carries a real immutable version (the same
   * requirement the reference strip has); an asset the workflow doesn't know
   * is reported, not silently dropped.
   */
  const dropAssetAsReference = useCallback(
    async (nodeId: string, assetId: string, displayName: string) => {
      if (!workflow) return;
      const target = workflow.nodes.find((candidate) => candidate.node_id === nodeId);
      if (!target) return;
      const asset = workflow.assets.find((candidate) => candidate.asset_id === assetId);
      if (!asset) {
        setSurfaceError(`资产「${displayName}」不在当前工作流中，无法作为参考。`);
        return;
      }
      // V0.2 §2.1: 人物 → 拖到镜头：成为该镜头的角色. A character asset
      // landing on the previs card joins the scene's cast (bound to that
      // asset) instead of becoming one more image reference.
      const intent = canvasCardDropIntent(
        asset.media_type,
        target.node_type,
        asset.semantic_type,
      );
      if (intent === "add_character") {
        const existing = extractSceneScriptFromNode(target);
        if (!existing) {
          setSurfaceError(
            `场景「${target.title}」还没有 SceneScript：先运行节点或从图片生成，再拖入角色。`,
          );
          return;
        }
        try {
          await patchNode(nodeId, {
            // Merge: the narration and every other key survive.
            structured_content: {
              ...target.structured_content,
              [SCENE_SCRIPT_CONTENT_KEY]: addCharacterFromAsset(existing, {
                assetId,
                displayName,
              }),
            },
          });
          setSurfaceError(null);
        } catch (error) {
          setSurfaceError(
            error instanceof Error ? error.message : "拖入角色失败，请重试。",
          );
        }
        return;
      }
      const selection: AgentAssetReferenceSelection = {
        source: "project",
        assetId,
        entityId: null,
        versionId: asset.version_id ?? null,
        mediaType: "image",
        displayName,
      };
      if (!selection.versionId) {
        setSurfaceError(`资产「${displayName}」没有可用的版本，无法作为参考。`);
        return;
      }
      try {
        await createBinding({
          source: toImageBindingSource(selection),
          target_node_id: target.node_id,
          input_role: "image_reference",
          enabled: true,
          order: workflow.bindings.filter(
            (binding) => binding.target_node_id === target.node_id,
          ).length,
        });
        setSurfaceError(null);
      } catch (error) {
        setSurfaceError(
          error instanceof Error ? error.message : "拖入参考失败，请重试。",
        );
      }
    },
    [createBinding, patchNode, setSurfaceError, workflow],
  );

  const nodeCallbacks = useMemo<AgentCanvasNodeCallbacks>(() => ({
    onRun: (nodeId) => runNodeById(nodeId, false),
    onRetry: (nodeId) => runNodeById(nodeId, true),
    onExport: openEditing,
    onOpenEditing: openEditing,
    onOpenVideoPreview: openNodeVideoPreview,
    renderWorkbench,
    onOpenConnectedNodeMenu: (nodeId, direction, point) => {
      setSelectedNodeId(nodeId);
      setConnectedNodeMenu({ anchorNodeId: nodeId, direction, point });
    },
    onAssetDroppedAsReference: (nodeId, assetId, displayName) => {
      void dropAssetAsReference(nodeId, assetId, displayName);
    },
  }), [dropAssetAsReference, openEditing, openNodeVideoPreview, renderWorkbench, runNodeById, setSelectedNodeId]);

  const canonicalNodes = useMemo(() => {
    if (!workflow) {
      canonicalProjectionInputsRef.current = null;
      canonicalNodesRef.current = [];
      return [];
    }
    const activeWorkbenchNodeId = session.state.selectedNodeId;
    const previousInputs = canonicalProjectionInputsRef.current;
    const structureUnchanged = previousInputs?.workflowId === workflow.workflow_id
      && previousInputs.nodes === workflow.nodes
      && previousInputs.assets === workflow.assets
      && previousInputs.callbacks === nodeCallbacks
      && previousInputs.activeWorkbenchNodeId === activeWorkbenchNodeId;
    let nextNodes: AgentCanvasFlowNode[];
    if (structureUnchanged && previousInputs?.runtime === live.state.runtime) {
      nextNodes = canonicalNodesRef.current as AgentCanvasFlowNode[];
    } else if (structureUnchanged) {
      const changedNodeIds = runtimeChangedCanvasNodeIds(canonicalNodesRef.current, live.state.runtime);
      nextNodes = patchAgentCanvasFlowNodes(
        workflow,
        live.state.runtime,
        nodeCallbacks,
        canonicalNodesRef.current,
        changedNodeIds,
        { activeWorkbenchNodeId },
      );
    } else {
      nextNodes = toAgentCanvasFlowNodes(workflow, live.state.runtime, nodeCallbacks, {
        previousNodes: canonicalNodesRef.current,
        activeWorkbenchNodeId,
      });
    }
    const stableNodes = reuseCanvasArray(canonicalNodesRef.current, nextNodes);
    canonicalNodesRef.current = stableNodes;
    canonicalProjectionInputsRef.current = {
      workflowId: workflow.workflow_id,
      nodes: workflow.nodes,
      assets: workflow.assets,
      callbacks: nodeCallbacks,
      activeWorkbenchNodeId,
      runtime: live.state.runtime,
    };
    return stableNodes;
  }, [live.state.runtime, nodeCallbacks, session.state.selectedNodeId, workflow]);
  useLayoutEffect(() => {
    syncRevealCanonicalNodeIds(canonicalNodes.map((node) => node.id));
  }, [canonicalNodes, syncRevealCanonicalNodeIds]);
  const visibleCanonicalNodes = useMemo(() => {
    const nextNodes = canonicalNodes.filter((node) => visibleRevealNodeIds.has(node.id));
    const stableNodes = reuseCanvasArray(visibleCanonicalNodesRef.current, nextNodes);
    visibleCanonicalNodesRef.current = stableNodes;
    return stableNodes;
  }, [canonicalNodes, visibleRevealNodeIds]);
  const visibleCanonicalNodeIds = useMemo(() => {
    const nextNodeIds = visibleCanonicalNodes.map((node) => node.id);
    const stableNodeIds = reuseCanvasArray(visibleCanonicalNodeIdsRef.current, nextNodeIds);
    visibleCanonicalNodeIdsRef.current = stableNodeIds;
    return stableNodeIds;
  }, [visibleCanonicalNodes]);
  const presentedNodes = useMemo<AgentCanvasFlowNode[]>(() => {
    const highlighted = new Set(highlightedNodeIds);
    const nextNodes = (overlayLayoutPreview(visibleCanonicalNodes) as AgentCanvasFlowNode[]).map((node) => {
      const classNames = (node.className ?? "")
        .split(/\s+/)
        .filter((className) => className && className !== "is-conversation-highlighted");
      if (highlighted.has(node.id)) classNames.push("is-conversation-highlighted");
      if (progressiveActiveNodeId === node.id) classNames.push("is-progressive-reveal");
      return classNames.join(" ") === (node.className ?? "")
        ? node
        : { ...node, className: classNames.join(" ") };
    });
    const stableNodes = reuseCanvasArray(presentedNodesRef.current, nextNodes);
    presentedNodesRef.current = stableNodes;
    return stableNodes;
  }, [highlightedNodeIds, overlayLayoutPreview, progressiveActiveNodeId, visibleCanonicalNodes]);
  const canonicalEdges = useMemo(
    () => {
      const nextEdges = workflow?.bindings
        ? toAgentCanvasFlowEdgesForNodeIds(
          workflow.bindings,
          visibleCanonicalNodeIds,
          canonicalEdgesRef.current,
        )
        : [];
      const stableEdges = reuseCanvasArray(canonicalEdgesRef.current, nextEdges);
      canonicalEdgesRef.current = stableEdges;
      return stableEdges;
    },
    [visibleCanonicalNodeIds, workflow?.bindings],
  );
  const presentedEdges = useMemo(
    () => {
      const nextEdges = highlightNodeRelatedCanvasEdges(
        canonicalEdges,
        session.state.selectedNodeId,
        presentedEdgesRef.current,
      );
      const stableEdges = reuseCanvasArray(presentedEdgesRef.current, nextEdges);
      presentedEdgesRef.current = stableEdges;
      return stableEdges;
    },
    [canonicalEdges, session.state.selectedNodeId],
  );

  useEffect(() => {
    if (!workflow || !needsInitialCanvasLayout(visibleCanonicalNodes.map((node) => node.data.node))) return;
    const workflowId = workflow.workflow_id;
    const repairAttempts = initialLayoutRepairWorkflowIdsRef.current;
    if (repairAttempts.has(workflowId)) return;
    repairAttempts.add(workflowId);

    const visibleNodeIds = new Set(visibleCanonicalNodes.map((node) => node.id));
    let layoutResult: ReturnType<typeof computeAgentCanvasAutoLayout>;
    try {
      layoutResult = computeAgentCanvasAutoLayout(
        visibleCanonicalNodes.map(agentCanvasLayoutNodeFromFlowNode),
        enabledNodeLayoutEdges(workflow.bindings, visibleNodeIds),
        {
          isolatedRowWidth: Math.max(
            960,
            (pointerSpotlight.hostRef.current?.clientWidth ?? 960)
              / (flowRef.current?.getViewport().zoom ?? 1),
          ),
        },
      );
    } catch (error) {
      setSurfaceError(error instanceof Error ? error.message : "Canvas layout could not be calculated.");
      return;
    }

    if (!layoutResult.positions.length) return;
    if (activeWorkflowIdRef.current !== workflowId) return;
    void updateNodePositions(layoutResult.positions)
      .then(() => {
        if (
          activeWorkflowIdRef.current !== workflowId
          || readAgentCanvasViewport(workflowId)
          || !flowRef.current
        ) return;
        const reducedMotion = typeof window.matchMedia === "function"
          && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        window.requestAnimationFrame(() => {
          if (activeWorkflowIdRef.current !== workflowId) return;
          void flowRef.current?.fitView({
            nodes: layoutResult.positions.map(({ node_id }) => ({ id: node_id })),
            padding: 0.22,
            maxZoom: 1,
            duration: reducedMotion ? 0 : 350,
          });
        });
      })
      .catch((error) => {
        if (activeWorkflowIdRef.current === workflowId) {
          setSurfaceError(error instanceof Error ? error.message : "Canvas layout could not be saved.");
        }
      });
  }, [pointerSpotlight.hostRef, updateNodePositions, visibleCanonicalNodes, workflow]);

  useEffect(() => {
    latestPresentedNodesRef.current = presentedNodes;
    const deferred = deferNodeSnapshotDuringDrag(
      presentedNodes,
      flowNodesRef.current,
      activeDraggedNodeIdsRef.current,
    );
    pendingPresentedNodesRef.current = deferred.pendingNodes;
    if (!deferred.nodes) return;
    const nextSnapshot = reconcileCanvasFlowSnapshot(flowNodesRef.current, deferred.nodes);
    if (nextSnapshot === flowNodesRef.current) return;
    flowNodesRef.current = nextSnapshot;
    setNodes(nextSnapshot);
  }, [presentedNodes, setNodes]);

  const cancelActiveNodeDrag = useCallback(() => {
    endCanvasInteraction("node-drag");
    setDragEdgeProjection(null);
    if (pendingDragNodeFrameRef.current !== null) {
      window.cancelAnimationFrame(pendingDragNodeFrameRef.current);
      pendingDragNodeFrameRef.current = null;
    }
    pendingDragNodeChangesRef.current.clear();
    if (!activeDraggedNodeIdsRef.current.size) return;
    dragCancellationPendingRef.current = true;
    const nextNodes = cancelNodeDrag(
      pendingPresentedNodesRef.current ?? latestPresentedNodesRef.current,
      flowNodesRef.current,
      activeDraggedNodeIdsRef.current,
    );
    pendingPresentedNodesRef.current = null;
    flowNodesRef.current = nextNodes;
    setNodes(nextNodes);
  }, [endCanvasInteraction, setNodes]);

  useEffect(() => {
    const activeDraggedNodeIds = activeDraggedNodeIdsRef.current;
    const pendingDragNodeChanges = pendingDragNodeChangesRef.current;
    const handleWindowBlur = () => {
      clearCanvasInteractions();
      cancelActiveNodeDrag();
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState !== "visible") handleWindowBlur();
    };
    window.addEventListener("blur", handleWindowBlur);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      window.removeEventListener("blur", handleWindowBlur);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      activeDraggedNodeIds.clear();
      pendingPresentedNodesRef.current = null;
      if (pendingDragNodeFrameRef.current !== null) {
        window.cancelAnimationFrame(pendingDragNodeFrameRef.current);
        pendingDragNodeFrameRef.current = null;
      }
      pendingDragNodeChanges.clear();
    };
  }, [cancelActiveNodeDrag, clearCanvasInteractions]);

  useEffect(() => {
    setEdges((current) => reconcileCanvasFlowSnapshot(
      current,
      reconcileSelectableCanvasEdges(presentedEdges, current),
    ));
  }, [presentedEdges, setEdges]);

  const clearEdgeSelection = useCallback(() => {
    setEdges((current) => {
      if (!current.some((edge) => edge.selected)) return current;
      return current.map((edge) => edge.selected ? { ...edge, selected: false } : edge);
    });
  }, [setEdges]);

  useEffect(() => {
    if (
      session.state.selectedNodeId
      && !canonicalNodes.some((node) => node.id === session.state.selectedNodeId)
    ) {
      setSelectedNodeId(null);
    }
  }, [canonicalNodes, session.state.selectedNodeId, setSelectedNodeId]);

  useEffect(() => {
    if (focusedNodeId && !canonicalNodes.some((node) => node.id === focusedNodeId)) {
      exitCanvasNodeFocus();
    }
  }, [canonicalNodes, exitCanvasNodeFocus, focusedNodeId]);

  const applyCanvasNodeChanges = useCallback((changes: NodeChange<AgentCanvasFlowNode>[]) => {
    if (!changes.length) return;
    const next = applyNodeChanges(changes, [...flowNodesRef.current]);
    flowNodesRef.current = next;
    setNodes(next);
  }, [setNodes]);

  const flushPendingDragNodeChanges = useCallback(() => {
    if (pendingDragNodeFrameRef.current !== null) {
      window.cancelAnimationFrame(pendingDragNodeFrameRef.current);
      pendingDragNodeFrameRef.current = null;
    }
    const changes = [...pendingDragNodeChangesRef.current.values()];
    pendingDragNodeChangesRef.current.clear();
    applyCanvasNodeChanges(changes);
  }, [applyCanvasNodeChanges]);

  const handleNodeChanges = useCallback((changes: NodeChange<AgentCanvasFlowNode>[]) => {
    const isDraggingPositionChange = (
      change: NodeChange<AgentCanvasFlowNode>,
    ): change is Extract<NodeChange<AgentCanvasFlowNode>, { type: "position" }> => (
      change.type === "position" && change.dragging === true
    );
    const deferred = changes.filter(isDraggingPositionChange);
    const immediate = changes.filter((change) => !isDraggingPositionChange(change));
    applyCanvasNodeChanges(immediate);
    if (!deferred.length) return;

    for (const change of deferred) {
      pendingDragNodeChangesRef.current.set(change.id, change);
    }
    if (pendingDragNodeFrameRef.current !== null) return;
    pendingDragNodeFrameRef.current = window.requestAnimationFrame(() => {
      pendingDragNodeFrameRef.current = null;
      const queued = [...pendingDragNodeChangesRef.current.values()];
      pendingDragNodeChangesRef.current.clear();
      applyCanvasNodeChanges(queued);
    });
  }, [applyCanvasNodeChanges]);

  const connect = useCallback(async (connection: Connection) => {
    if (!workflow || !connectionPolicy || !connection.source || !connection.target || connection.source === connection.target) {
      if (!connectionPolicy) setSurfaceError("Connection policy is still loading.");
      return;
    }
    const source = workflow.nodes.find((node) => node.node_id === connection.source);
    const target = workflow.nodes.find((node) => node.node_id === connection.target);
    if (!source || !target) return;
    const rule = connectionRuleForPair(connectionPolicy, source.node_type, target.node_type);
    if (!rule) {
      setSurfaceError(`Node ${source.title ?? source.node_id} cannot be connected to Node ${target.title ?? target.node_id}. Check that the output type matches the input type.`);
      return;
    }
    setSurfaceError(null);
    try {
      await submitOptimisticConnection({
        source: { kind: "node_output", source_node_id: source.node_id },
        target_node_id: connection.target,
        input_role: rule.default_role,
        enabled: true,
        order: nextConnectionOrder(connection.target),
      });
    } catch (error) {
      setSurfaceError(canvasAuthoringErrorMessage(error));
    }
  }, [connectionPolicy, nextConnectionOrder, submitOptimisticConnection, workflow]);

  const isValidCanvasConnection = useCallback((connection: Connection | Edge) => {
    if (!workflow || !connectionPolicy || !connection.source || !connection.target) return false;
    if (connection.source === connection.target) return false;
    const source = workflow.nodes.find((node) => node.node_id === connection.source);
    const target = workflow.nodes.find((node) => node.node_id === connection.target);
    if (!source || !target) return false;
    return Boolean(connectionRuleForPair(connectionPolicy, source.node_type, target.node_type));
  }, [connectionPolicy, workflow]);

  const recoverDeletedCanvasState = useCallback(async () => {
    setNodes(presentedNodes);
    setEdges((current) => reconcileSelectableCanvasEdges(presentedEdges, current));
    await refreshWorkflow();
  }, [presentedEdges, presentedNodes, refreshWorkflow, setEdges, setNodes]);

  const deleteEdges = useCallback((deleted: Edge[]) => {
    void deleteCanvasEntities(
      deleted.filter((edge) => !edge.data?.optimistic).map((edge) => edge.id),
      deleteBinding,
      recoverDeletedCanvasState,
    )
      .catch((error) => setSurfaceError(error instanceof Error ? error.message : "The connection could not be removed."));
  }, [deleteBinding, recoverDeletedCanvasState]);

  const deleteNodes = useCallback((deleted: AgentCanvasFlowNode[]) => {
    cancelPendingNodeConnections(deleted.map((node) => node.id));
    void deleteCanvasEntities(
      deleted.map((node) => node.id),
      deleteNode,
      recoverDeletedCanvasState,
    )
      .catch((error) => setSurfaceError(error instanceof Error ? error.message : "The node could not be deleted."));
  }, [cancelPendingNodeConnections, deleteNode, recoverDeletedCanvasState]);

  const deleteContextNode = useCallback((nodeId: string) => {
    const node = flowNodesRef.current.find((candidate) => candidate.id === nodeId);
    setContextMenu(null);
    if (node) deleteNodes([node]);
  }, [deleteNodes]);

  const openNodeContextMenu = useCallback((
    event: ReactMouseEvent,
    node: AgentCanvasFlowNode,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    clearEdgeSelection();
    setSelectedNodeId(node.id);
    setAddMenuOpen(false);
    setConnectedNodeMenu(null);
    setContextMenu({
      kind: "node",
      menuPosition: { x: event.clientX, y: event.clientY },
      nodeId: node.id,
    });
  }, [clearEdgeSelection, setSelectedNodeId]);

  const cancelCurrentRun = useCallback(async () => {
    setSurfaceError(null);
    try {
      await cancelRun();
    } catch (error) {
      setSurfaceError(error instanceof Error ? error.message : "The run could not be cancelled.");
    }
  }, [cancelRun]);

  const createNode = useCallback(async (
    nodeType: AgentCanvasVisibleNodeTypeV2,
    preferredPosition?: CanvasPositionV2,
  ) => {
    if (!workflow) return;
    const instance = flowRef.current;
    const defaultPosition = instance
      ? instance.screenToFlowPosition({ x: window.innerWidth * 0.48, y: window.innerHeight * 0.46 })
      : { x: 120, y: 120 };
    const position = findAvailableCanvasPosition(
      workflow.nodes,
      preferredPosition ?? defaultPosition,
      {
        assets: workflow.assets,
        candidateNodeType: nodeType,
      },
    );
    setSurfaceError(null);
    setAddMenuOpen(false);
    setContextMenu(null);
    try {
      await createCanvasNode(createDefaultCanvasNodeRequest(nodeType, position));
    } catch (error) {
      setSurfaceError(error instanceof Error ? error.message : "The node could not be created.");
    }
  }, [createCanvasNode, workflow]);

  // Timeline 2.1: promote a manual/orphan video clip by creating a video
  // node; the panel links the clip to the returned node id afterwards.
  const createVideoNodeForClip = useCallback(
    async (clip: TimelineClipV1): Promise<string> => {
      if (!workflow) throw new Error("No active workflow.");
      const instance = flowRef.current;
      const preferredPosition = instance
        ? instance.screenToFlowPosition({
            x: window.innerWidth * 0.48,
            y: window.innerHeight * 0.46,
          })
        : { x: 120, y: 120 };
      const position = findAvailableCanvasPosition(
        workflow.nodes,
        preferredPosition,
        { assets: workflow.assets, candidateNodeType: "video" },
      );
      const request = createDefaultCanvasNodeRequest("video", position);
      const node = await createCanvasNode(
        clip.label
          ? { ...request, title: `Video · ${clip.label}`.slice(0, 120) }
          : request,
      );
      if (!node) throw new Error("The video node could not be created.");
      return node.node_id;
    },
    [createCanvasNode, workflow],
  );

  const addReferences = useCallback(async (selections: AgentAssetReferenceSelection[]) => {
    if (!workflow || !session.state.selectedNode) {
      throw new Error("Select a target node before adding image references.");
    }
    if (session.state.selectedNode.node_type === "editing") {
      throw new Error("Editing nodes accept connected Video nodes and one BGM node, not image references.");
    }
    const targetNodeId = session.state.selectedNode.node_id;
    const startOrder = workflow.bindings.filter((binding) => binding.target_node_id === targetNodeId).length;
    for (const [index, selection] of selections.entries()) {
      await createBinding({
        source: toImageBindingSource(selection),
        target_node_id: targetNodeId,
        input_role: "image_reference",
        enabled: true,
        order: startOrder + index,
      });
    }
  }, [createBinding, session.state.selectedNode, workflow]);



  /**
   * V0.2 §2.1's retained feature #1: 素材 → 拖到画布 → 创建镜头. The asset
   * browser emits the canvas payload on drag; the pane turns a drop into the
   * same asset-backed create the connected-node menu uses (the backend
   * requires node type == asset media type).
   */
  const handleCanvasDragOver = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer.types.includes(CANVAS_DROP_MIME)) return;
    // Prevent the default so the drop is accepted; the browser otherwise
    // treats the pane as a non-target and swallows the gesture.
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }, []);

  const handleCanvasDrop = useCallback(
    async (event: React.DragEvent<HTMLDivElement>) => {
      if (!workflow) return;
      const raw = event.dataTransfer.getData(CANVAS_DROP_MIME);
      if (!raw) return;
      event.preventDefault();
      const payload = parseCanvasDropPayload(raw);
      if (!payload) {
        // A malformed payload degrades to "nothing happens" — never a thrown
        // error inside React's event loop.
        return;
      }
      const instance = flowRef.current;
      const preferred = instance
        ? instance.screenToFlowPosition({ x: event.clientX, y: event.clientY })
        : { x: 120, y: 120 };
      const nodeType = canvasNodeTypeForMedia(payload.media_type);
      if (!nodeType) return;
      const droppedAsset = workflow.assets.find(
        (candidate) => candidate.asset_id === payload.asset_id,
      );
      // Semantic landing first (V0.2 §2.2: 两个镜头之间 = 新镜头插入): the
      // drop point is treated as the would-be card, so releasing an asset
      // between two cards inserts it in that row at the canonical gap. Only
      // a fruitless snap falls back to "first free spot".
      const siblings = flowNodesRef.current.map((flowNode) =>
        canvasSnapBoxFor(flowNode, workflow.assets),
      );
      const snapped = snapCanvasDropPosition(
        preferred,
        siblings,
        agentCanvasNodePlacementSize(
          nodeType,
          droppedAsset
            ? { width: droppedAsset.width, height: droppedAsset.height }
            : null,
        ),
      );
      const dropSize = agentCanvasNodePlacementSize(
        nodeType,
        droppedAsset
          ? { width: droppedAsset.width, height: droppedAsset.height }
          : null,
      );
      // No semantic snap? Then a real INSERT: the release sits in a row gap
      // too narrow for the card, so the neighbours make room (V0.2 §2.2).
      // The plain snap is tried first — a gap with room never reflows.
      const insertPlan = snapped.snap
        ? null
        : planRowGapInsert(preferred, siblings, dropSize);
      const position = snapped.snap
        ? snapped.position
        : insertPlan
          ? insertPlan.insertAt
          : findAvailableCanvasPosition(workflow.nodes, preferred, {
              assets: workflow.assets,
              candidateNodeType: nodeType,
              candidateDimensions: droppedAsset
                ? { width: droppedAsset.width, height: droppedAsset.height }
                : null,
            });
      const request = canvasDropCreateRequest(payload, position);
      if (!request) return;
      try {
        await createCanvasNode(request);
        if (insertPlan && insertPlan.shifts.length > 0) {
          // The neighbours the insert pushed over: persisted so the reflow
          // survives a reload (a layout that silently springs back would
          // read as the insert having failed).
          await updateNodePositions(
            insertPlan.shifts.map((shift) => ({
              node_id: shift.id,
              x: shift.x,
              y: shift.y,
            })),
          );
        }
      } catch (error) {
        // Surfaced on the same banner every other authoring failure uses.
        setSurfaceError(
          error instanceof Error ? error.message : "拖入画布失败，请重试。",
        );
      }
    },
    [createCanvasNode, setSurfaceError, updateNodePositions, workflow],
  );

  const createReadySourceNode = useCallback(async (selection: AgentAssetSourceNodeSelection) => {
    if (!workflow) return;
    const instance = flowRef.current;
    const preferredPosition = instance
      ? instance.screenToFlowPosition({ x: window.innerWidth * 0.5, y: window.innerHeight * 0.5 })
      : { x: 180, y: 160 };
    const position = findAvailableCanvasPosition(workflow.nodes, preferredPosition, {
      assets: workflow.assets,
      candidateNodeType: selection.mediaType,
      candidateDimensions: { width: selection.width, height: selection.height },
    });
    await createCanvasNode({
      node_type: selection.mediaType,
      creative_role: selection.mediaType === "image"
        ? "general_image"
        : selection.mediaType === "video"
          ? "general_video"
          : "general_audio",
      role_contract_version: AGENT_CANVAS_ROLE_CONTRACT_VERSION,
      title: selection.displayName,
      structured_content: sourceAssetStructuredContent(
        selection.mediaType,
        selection.displayName,
        selection.durationSeconds,
      ),
      position,
      source_asset_id: selection.assetId,
    });
  }, [createCanvasNode, workflow]);

  const createConnectedNodeFromMenu = useCallback(async (
    nodeType: AgentCanvasVisibleNodeTypeV2,
    inputRole: CanvasBindingInputRoleV2,
  ) => {
    if (!workflow || !connectedNodeMenu) return;
    const anchor = workflow.nodes.find((node) => node.node_id === connectedNodeMenu.anchorNodeId);
    if (!anchor) return;
    const anchorAsset = anchor.output_asset_id
      ? workflow.assets.find((asset) => asset.asset_id === anchor.output_asset_id) ?? null
      : null;
    const anchorSize = agentCanvasNodePlacementSize(
      anchor.node_type,
      anchorAsset ? { width: anchorAsset.width, height: anchorAsset.height } : null,
    );
    const candidateSize = agentCanvasNodePlacementSize(nodeType);
    const preferred = {
      x: connectedNodeMenu.direction === "downstream"
        ? anchor.position.x + anchorSize.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP
        : anchor.position.x - candidateSize.width - AGENT_CANVAS_NODE_HORIZONTAL_GAP,
      y: anchor.position.y,
    };
    const position = findAvailableCanvasPosition(workflow.nodes, preferred, {
      assets: workflow.assets,
      candidateNodeType: nodeType,
    });
    const targetNodeId = connectedNodeMenu.direction === "downstream"
      ? null
      : anchor.node_id;
    const order = targetNodeId
      ? workflow.bindings.filter((binding) => binding.target_node_id === targetNodeId).length
      : 0;
    setConnectedNodeMenu(null);
    setSurfaceError(null);
    try {
      await createConnectedNode({
        anchor_node_id: anchor.node_id,
        direction: connectedNodeMenu.direction,
        node: createDefaultCanvasNodeRequest(nodeType, position),
        binding: {
          input_role: inputRole,
          order,
        },
      });
    } catch (error) {
      setSurfaceError(canvasAuthoringErrorMessage(error));
    }
  }, [connectedNodeMenu, createConnectedNode, workflow]);

  const placeReceiptNodes = useCallback((receipt: Parameters<typeof placeActionReceiptNodes>[0]) => {
    reserveRevealNodeIds(receipt.created_node_ids);
    void placeActionReceiptNodes(receipt)
      .then((plan) => {
        if (!plan) {
          releaseRevealNodeIds(receipt.created_node_ids);
          return;
        }
        const planned = new Set(plan.orderedNodeIds);
        releaseRevealNodeIds(
          receipt.created_node_ids.filter((nodeId) => !planned.has(nodeId)),
        );
        enqueueReveal(plan);
      })
      .catch((error) => {
        setSurfaceError(error instanceof Error ? error.message : "New canvas nodes could not be positioned.");
      });
  }, [enqueueReveal, placeActionReceiptNodes, releaseRevealNodeIds, reserveRevealNodeIds]);

  const organizeCanvas = useCallback(() => {
    const instance = flowRef.current;
    if (!workflow || !instance || layoutPreviewActive) return;

    const flowNodes = instance.getNodes();
    if (!flowNodes.length) return;
    const viewport = instance.getViewport();
    const isolatedRowWidth = Math.max(
      960,
      (pointerSpotlight.hostRef.current?.clientWidth ?? 960) / viewport.zoom,
    );
    let result: ReturnType<typeof computeAgentCanvasAutoLayout>;
    try {
      const visibleNodeIds = new Set(flowNodes.map((node) => node.id));
      result = computeAgentCanvasAutoLayout(
        flowNodes.map(agentCanvasLayoutNodeFromFlowNode),
        enabledNodeLayoutEdges(workflow.bindings, visibleNodeIds),
        { isolatedRowWidth },
      );
    } catch (error) {
      setSurfaceError(error instanceof Error ? error.message : "Canvas layout could not be calculated.");
      return;
    }

    setSurfaceError(null);
    beginLayoutPreview({
      workflowId: workflow.workflow_id,
      workflow,
      nodes: flowNodes,
      targetPositions: result.positions,
      viewport,
    });
    const reducedMotion = typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.requestAnimationFrame(() => {
      void instance.fitView({
        nodes: result.positions.map(({ node_id }) => ({ id: node_id })),
        padding: 0.2,
        maxZoom: 1,
        duration: reducedMotion ? 0 : 420,
      });
    });
  }, [beginLayoutPreview, layoutPreviewActive, pointerSpotlight.hostRef, workflow]);

  const scheduleWorkflowViewportInstall = useCallback((
    instance: ReactFlowInstance<AgentCanvasFlowNode, Edge>,
    nextWorkflow: AgentCanvasWorkflowV2,
  ) => {
    if (installedViewportWorkflowIdRef.current === nextWorkflow.workflow_id) return;
    if (viewportInstallFrameRef.current !== null) {
      window.cancelAnimationFrame(viewportInstallFrameRef.current);
    }
    installedViewportWorkflowIdRef.current = nextWorkflow.workflow_id;
    const workflowId = nextWorkflow.workflow_id;
    const nodeIds = nextWorkflow.nodes.map((node) => node.node_id);
    viewportInstallFrameRef.current = window.requestAnimationFrame(() => {
      viewportInstallFrameRef.current = null;
      if (activeWorkflowIdRef.current !== workflowId) return;
      const reducedMotion = typeof window.matchMedia === "function"
        && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      void installAgentCanvasWorkflowViewport({
        instance: {
          setViewport: (viewport, options) => instance.setViewport(viewport, options),
          fitView: (options) => instance.fitView(options),
        },
        workflowId,
        nodeIds,
        reducedMotion,
      }).catch(() => undefined);
    });
  }, []);

  const initializeFlow = useCallback((instance: ReactFlowInstance<AgentCanvasFlowNode, Edge>) => {
    flowRef.current = instance;
    edgeZoomControllerRef.current?.setZoom(instance.getViewport().zoom);
    previewPrefetchRef.current?.setViewport(instance.getViewport());
    if (workflow) scheduleWorkflowViewportInstall(instance, workflow);
  }, [scheduleWorkflowViewportInstall, workflow]);

  useEffect(() => {
    if (!workflow) {
      installedViewportWorkflowIdRef.current = null;
      return;
    }
    const instance = flowRef.current;
    if (instance) scheduleWorkflowViewportInstall(instance, workflow);
  }, [scheduleWorkflowViewportInstall, workflow]);

  useEffect(() => () => {
    if (viewportInstallFrameRef.current !== null) {
      window.cancelAnimationFrame(viewportInstallFrameRef.current);
    }
  }, []);

  const openCanvasContextMenu = useCallback((menuPosition: CanvasPositionV2) => {
    const canvasPosition = flowRef.current?.screenToFlowPosition(menuPosition) ?? { x: 120, y: 120 };
    clearEdgeSelection();
    setSelectedNodeId(null);
    setAddMenuOpen(false);
    setConnectedNodeMenu(null);
    setContextMenu({ kind: "canvas", menuPosition, canvasPosition });
  }, [clearEdgeSelection, setSelectedNodeId]);

  if (!session.state.workspaceHydrated) {
    return <div className="agent-canvas-state">Opening project...</div>;
  }
  if (!workflow) {
    return (
      <div className="agent-canvas-state agent-canvas-state--error">
        <strong>Project canvas unavailable</strong>
        <span>{session.state.workspaceRestoreError || "Open a project or create a new one."}</span>
      </div>
    );
  }

  const editingNode = editingNodeId
    ? workflow.nodes.find((node) => node.node_id === editingNodeId && node.node_type === "editing") ?? null
    : null;
  const editingPreparation = editingNode
    ? live.state.editingPreparationByNodeId[editingNode.node_id]
    : undefined;
  const connectedMenuAnchor = connectedNodeMenu
    ? workflow.nodes.find((node) => node.node_id === connectedNodeMenu.anchorNodeId) ?? null
    : null;
  const running = Boolean(live.state.runtime?.active_execution_id);
  return (
    <div className={`agent-canvas-page${chatCollapsed ? " is-chat-collapsed" : ""}`}>
      <PlayheadSyncProvider>
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- React Flow owns canvas keyboard and pointer semantics; this listener only distinguishes pane double-clicks. */}
      <div
        ref={pointerSpotlight.hostRef}
        className={`agent-canvas-board${layoutPreview.active ? " is-layout-previewing" : ""}${canvasInteracting ? " is-interacting" : ""}`}
        style={{ display: "flex", flexDirection: "column" }}
        onContextMenu={(event) => event.preventDefault()}
        onPointerMove={pointerSpotlight.onPointerMove}
        onPointerLeave={pointerSpotlight.onPointerLeave}
        onPointerCancel={(event) => {
          pointerSpotlight.onPointerCancel(event);
          clearCanvasInteractions();
          cancelActiveNodeDrag();
        }}
        onDoubleClick={(event) => {
          const target = event.target;
          if (target instanceof Element && target.classList.contains("react-flow__pane")) {
            exitCanvasNodeFocus();
          }
        }}
      >
        <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
        <ReactFlow<AgentCanvasFlowNode, Edge>
          nodes={nodes}
          edges={renderedEdges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          connectionLineComponent={AgentCanvasConnectionLine}
          connectionRadius={AGENT_CANVAS_CONNECTION_RADIUS}
          isValidConnection={isValidCanvasConnection}
          minZoom={0.05}
          maxZoom={focusedNodeId ? AGENT_CANVAS_FOCUS_MAX_ZOOM : 2}
          deleteKeyCode={["Backspace", "Delete"]}
          multiSelectionKeyCode={["Meta", "Control"]}
          selectionKeyCode="Shift"
          panOnScroll
          zoomOnDoubleClick={false}
          selectionOnDrag
          onlyRenderVisibleElements={true}
          nodesDraggable={!layoutPreview.active}
          onInit={initializeFlow}
          onDragOver={handleCanvasDragOver}
          onDrop={(event) => void handleCanvasDrop(event)}
          onMove={(_event, viewport) => {
            edgeZoomControllerRef.current?.setZoom(viewport.zoom);
            previewPrefetchRef.current?.setViewport(viewport);
          }}
          onEdgesChange={onEdgesChange}
          onNodesChange={handleNodeChanges}
          onNodeClick={(_event, node) => {
            clearEdgeSelection();
            setSelectedNodeId(node.id);
            scheduleExitForNodeSelection(node.id);
          }}
          onNodeDoubleClick={(event, node) => {
            event.preventDefault();
            event.stopPropagation();
            clearEdgeSelection();
            setSelectedNodeId(node.id);
            focusCanvasNode(node.id);
          }}
          onNodeContextMenu={(event, node) => {
            openNodeContextMenu(event, node);
          }}
          onNodeDragStart={(_event, node, draggedNodes) => {
            interruptReveal();
            beginCanvasInteraction("node-drag");
            previewPrefetchRef.current?.setPaused(true);
            dragCancellationPendingRef.current = false;
            const draggedNodeIds = new Set([
              node.id,
              ...draggedNodes.map((item) => item.id),
            ]);
            beginNodeDrag(
              activeDraggedNodeIdsRef.current,
              node.id,
              draggedNodes.map((item) => item.id),
            );
            const projection = partitionCanvasEdges(displayEdges, draggedNodeIds);
            const frozenSnapshots = captureFrozenCanvasEdges(
              new Set(projection.frozenEdges.map((edge) => edge.id)),
              pointerSpotlight.hostRef.current,
            );
            if (frozenSnapshots.length === projection.frozenEdges.length) {
              setDragEdgeProjection({
                liveEdgeIds: new Set(projection.liveEdges.map((edge) => edge.id)),
                frozenSnapshots,
              });
            } else {
              setDragEdgeProjection(null);
            }
          }}
          onNodeDragStop={(_event, node, draggedNodes) => {
            endCanvasInteraction("node-drag");
            previewPrefetchRef.current?.setPaused(false);
            setDragEdgeProjection(null);
            flushPendingDragNodeChanges();
            if (dragCancellationPendingRef.current) {
              dragCancellationPendingRef.current = false;
              return;
            }
            const changed = draggedNodes.length ? draggedNodes : [node];
            const dragResult = finishNodeDrag(
              pendingPresentedNodesRef.current ?? latestPresentedNodesRef.current,
              flowNodesRef.current,
              activeDraggedNodeIdsRef.current,
              changed,
            );
            pendingPresentedNodesRef.current = null;
            // Semantic snap (V0.2 §2.2): a released node lands on the MEANING
            // of where it was dropped — the sibling's row (same stage), the
            // canonical gap beside it (next/previous in the sequence), or the
            // sibling's column (parallel/alternative). A snap is refused when
            // it would overlap, so alignment can never stack cards.
            const snapped = applyCanvasDragSnap(
              dragResult.nodes,
              activeDraggedNodeIdsRef.current,
              workflow.assets,
            );
            flowNodesRef.current = snapped.nodes;
            setNodes(snapped.nodes);
            const positions = dragResult.positions.map((item) =>
              item.node_id in snapped.positionOverrides
                ? { ...item, ...snapped.positionOverrides[item.node_id] }
                : item,
            );
            if (positions.length) {
              void updateNodePositions(positions).catch(() => {
                void refreshWorkflow().catch(() => {});
              });
            }
          }}
          onNodesDelete={deleteNodes}
          onConnect={(connection) => void connect(connection)}
          onEdgesDelete={deleteEdges}
          onPaneContextMenu={(event) => {
            event.preventDefault();
            openCanvasContextMenu({ x: event.clientX, y: event.clientY });
          }}
          onPaneClick={() => {
            clearEdgeSelection();
            setSelectedNodeId(null);
            setAddMenuOpen(false);
            setConnectedNodeMenu(null);
            setContextMenu(null);
          }}
          onMoveStart={() => {
            interruptReveal();
            beginCanvasInteraction("viewport");
            previewPrefetchRef.current?.setPaused(true);
          }}
          onMoveEnd={(_event, viewport) => {
            endCanvasInteraction("viewport");
            edgeZoomControllerRef.current?.setZoom(viewport.zoom);
            previewPrefetchRef.current?.setViewport(viewport);
            previewPrefetchRef.current?.setPaused(false);
            if (shouldPersistAgentCanvasViewport({ focusedNodeId, layoutPreviewActive })) {
              writeAgentCanvasViewport(workflow.workflow_id, viewport);
            }
          }}
          fitView={false}
          colorMode="system"
          proOptions={{ hideAttribution: true }}
        >
          <AgentCanvasPointerBackgrounds />
          {dragEdgeProjection ? (
            <FrozenCanvasEdgesOverlay snapshots={visibleFrozenSnapshots} />
          ) : null}
          <Controls position="bottom-left" showInteractive={false} />
        </ReactFlow>

        <div className="agent-canvas-creation-flow-dock">
          <button
            type="button"
            className={`agent-canvas-creation-flow-toggle${creationFlowOpen ? " is-open" : ""}`}
            aria-expanded={creationFlowOpen}
            aria-controls="agent-canvas-creation-flow-panel"
            title={creationFlowOpen ? "Hide creation flow" : "Show creation flow"}
            onClick={() => setCreationFlowOpen((current) => !current)}
          >
            <span aria-hidden="true">🎬</span>
            Creation flow
            {creationFlowAssessment
              ? ` · ${Math.round(creationFlowAssessment.progress_percent)}%`
              : ""}
            {creationFlowAssessment?.blockers.length
              ? ` · ${creationFlowAssessment.blockers.length} blocked`
              : ""}
            <span className="agent-canvas-creation-flow-toggle-chevron" aria-hidden="true">
              {creationFlowOpen ? "▲" : "▼"}
            </span>
          </button>
          {creationFlowOpen ? (
            <div id="agent-canvas-creation-flow-panel" className="agent-canvas-creation-flow-panel">
              <CreationFlowGuidance
                workflowId={workflow.workflow_id}
                pollInterval={5000}
                showDetails
                onAssessment={handleCreationFlowAssessment}
              />
            </div>
          ) : null}
        </div>

        <CanvasPreviewPrefetcher
          ref={previewPrefetchRef}
          nodes={canonicalNodes}
          boardRef={pointerSpotlight.hostRef}
        />

        <div className="agent-canvas-toolbar" aria-label="Canvas controls">
          <div className="agent-canvas-toolbar__add">
            <button
              type="button"
              className={addMenuOpen ? "is-active" : ""}
              aria-label="Add node"
              title="Add node"
              onClick={() => setAddMenuOpen((current) => !current)}
            >
              <PlusIcon />
            </button>
            {addMenuOpen ? (
              <AgentCanvasNodePicker
                className="agent-canvas-node-picker agent-canvas-add-menu"
                menuLabel="Add node types"
                onSelect={(nodeType) => void createNode(nodeType)}
              />
            ) : null}
          </div>
          <div className="agent-canvas-toolbar__layout">
            <button
              ref={layoutButtonRef}
              type="button"
              aria-label="Organize canvas"
              title="Organize canvas"
              disabled={!nodes.length || layoutPreview.active}
              onClick={organizeCanvas}
            >
              <LayoutIcon />
            </button>
            {layoutPreview.active ? (
              <AgentCanvasLayoutConfirmation
                status={layoutPreview.status === "idle" ? "previewing" : layoutPreview.status}
                error={layoutPreview.error}
                onUndo={undoLayoutPreview}
                onDismiss={dismissLayoutPreview}
                onKeep={() => void keepLayoutPreview()}
                dismissExemptRef={pointerSpotlight.hostRef}
              />
            ) : null}
          </div>
          <button
            type="button"
            className={assetsOpen ? "is-active" : ""}
            aria-label="Open assets"
            title="Assets"
            onClick={() => setAssetsOpen(true)}
          >
            <AssetsIcon />
          </button>
          {running ? (
            <button
              type="button"
              aria-label="Cancel run"
              title="Cancel run"
              onClick={() => void cancelCurrentRun()}
            >
              <PauseIcon />
            </button>
          ) : (
            <button
              type="button"
              className="agent-canvas-toolbar__run"
              aria-label="Run all draft nodes"
              title={hasRunnableDraft ? "Run all" : "No prompt-ready drafts"}
              disabled={live.state.runPending || !hasRunnableDraft}
              onClick={() => void runAll().catch((error) => {
                setSurfaceError(error instanceof Error ? error.message : "Run could not start.");
              })}
            >
              <PlayIcon />
            </button>
          )}
          {workflow.nodes.some((n) => n.status === "failed") ? (
            <button
              type="button"
              className="agent-canvas-toolbar__retry-all"
              aria-label="Retry all failed nodes"
              title={`Retry ${workflow.nodes.filter((n) => n.status === "failed").length} failed node(s)`}
              disabled={live.state.runPending}
              onClick={() => void retryAllFailed().catch((error) => {
                setSurfaceError(error instanceof Error ? error.message : "Batch retry failed.");
              })}
            >
              <span className="agent-canvas-toolbar__retry-all-icon" aria-hidden="true">↻</span>
              Retry all
            </button>
          ) : null}
          {workflow.nodes.length > 0 ? (() => {
            const totalNodes = serverProgress?.total_nodes ?? workflow.nodes.length;
            const workingNodes = serverProgress?.working_count ?? workflow.nodes.filter((n) => n.status === "working").length;
            const readyNodes = serverProgress?.ready_count ?? workflow.nodes.filter((n) => n.status === "ready").length;
            const failedNodes = serverProgress?.failed_count ?? workflow.nodes.filter((n) => n.status === "failed").length;
            const draftNodes = serverProgress?.draft_count ?? workflow.nodes.filter((n) => n.status === "draft").length;
            const progressPercent = serverProgress?.progress_percent ?? (totalNodes > 0 ? Math.round((readyNodes / totalNodes) * 100) : 0);
            const workingLabel = serverProgress?.working_nodes?.length
              ? serverProgress.working_nodes.map((n) => NODE_TYPE_LABELS[n.node_type as keyof typeof NODE_TYPE_LABELS] ?? n.node_type).join(", ")
              : workflow.nodes.filter((n) => n.status === "working").map((n) => NODE_TYPE_LABELS[n.node_type] ?? n.node_type).join(", ");
            const blockedHint = serverProgress?.blocked_nodes?.length
              ? serverProgress.blocked_nodes.map((n) => `${n.title}: ${n.next_action ?? "retry"}`).join("; ")
              : null;
            return (
              <>
              <div className="agent-canvas-toolbar__progress" aria-label="Generation progress">
                {workingNodes > 0 ? (
                  <span className="agent-canvas-toolbar__progress-label is-working">
                    <span className="agent-canvas-toolbar__progress-dot" aria-hidden="true" />
                    Generating: {workingLabel || "in progress"} ({workingNodes}/{totalNodes})
                  </span>
                ) : failedNodes > 0 ? (
                  <span
                    className="agent-canvas-toolbar__progress-label is-failed"
                    title={blockedHint ?? undefined}
                    style={{ cursor: "pointer" }}
                    role="button"
                    tabIndex={0}
                    onClick={() => setDiagnosticOpen((v) => !v)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setDiagnosticOpen((v) => !v);
                      }
                    }}
                  >
                    {failedNodes} failed · {readyNodes}/{totalNodes} complete{blockedHint ? ` · ${blockedHint}` : ""}
                    <span style={{ marginLeft: 6, fontSize: 10 }}>{diagnosticOpen ? "▲" : "▼"}</span>
                  </span>
                ) : draftNodes > 0 ? (
                  <span className="agent-canvas-toolbar__progress-label is-draft">
                    {draftNodes} ready to run · {readyNodes}/{totalNodes} complete
                  </span>
                ) : (
                  <span className="agent-canvas-toolbar__progress-label is-complete">
                    All {totalNodes} nodes complete ✓
                  </span>
                )}
                <div className="agent-canvas-toolbar__progress-bar" role="progressbar" aria-valuenow={progressPercent} aria-valuemin={0} aria-valuemax={100}>
                  <div className="agent-canvas-toolbar__progress-fill" style={{ width: `${progressPercent}%` }} />
                </div>
              </div>
              {diagnosticOpen && failedNodes > 0 ? (
                <div className="agent-canvas-diagnostic-panel" role="region" aria-label="Node diagnostic">
                  <div className="agent-canvas-diagnostic-panel__header">
                    <strong>Diagnostic —{failedNodes} failed node(s)</strong>
                    <button type="button" onClick={() => setDiagnosticOpen(false)} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 14 }}>✕</button>
                  </div>
                  <div className="agent-canvas-diagnostic-panel__stats">
                    <span className="agent-canvas-diagnostic-panel__stat">
                      <strong>{totalNodes}</strong> total
                    </span>
                    <span className="agent-canvas-diagnostic-panel__stat is-ready">
                      <strong>{readyNodes}</strong> ready
                    </span>
                    <span className="agent-canvas-diagnostic-panel__stat is-working">
                      <strong>{workingNodes}</strong> working
                    </span>
                    <span className="agent-canvas-diagnostic-panel__stat is-failed">
                      <strong>{failedNodes}</strong> failed
                    </span>
                    <span className="agent-canvas-diagnostic-panel__stat is-draft">
                      <strong>{draftNodes}</strong> draft
                    </span>
                    <span className="agent-canvas-diagnostic-panel__stat is-progress">
                      <strong>{progressPercent}%</strong> complete
                    </span>
                  </div>
                  <div className="agent-canvas-diagnostic-panel__body">
                    {(serverProgress?.blocked_nodes ?? workflow.nodes.filter((n) => n.status === "failed")).map((node) => (
                      <div key={node.node_id ?? (node as CanvasNodeV2).node_id} className="agent-canvas-diagnostic-panel__item">
                        <span className="agent-canvas-diagnostic-panel__node-title">
                          {node.title ?? (node as CanvasNodeV2).title}
                        </span>
                        <span className="agent-canvas-diagnostic-panel__node-type">
                          ({NODE_TYPE_LABELS[(node.node_type ?? (node as CanvasNodeV2).node_type) as keyof typeof NODE_TYPE_LABELS] ?? (node.node_type ?? (node as CanvasNodeV2).node_type)})
                        </span>
                        {(node as { next_action?: string }).next_action ? (
                          <span className="agent-canvas-diagnostic-panel__next-action">
                            鈫?{(node as { next_action?: string }).next_action}
                          </span>
                        ) : null}
                        <button
                          type="button"
                          className="agent-canvas-diagnostic-panel__retry-btn"
                          onClick={() => {
                            runNodeById((node.node_id ?? (node as CanvasNodeV2).node_id)!, true);
                          }}
                        >
                          Retry
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
              </>
            );
          })() : null}
          <span className={`agent-canvas-toolbar__connection is-${live.state.connectionState}`} title={live.state.runtimeError ?? undefined}>
            <i aria-hidden="true" />
            {live.state.connectionState}
          </span>
        </div>

        {workflow.nodes.length === 0 ? (
          <div className="agent-canvas-empty agent-canvas-empty--guided">
            <strong>Two ways to start —use either or both</strong>
            <div className="agent-canvas-empty__modes">
              <div className="agent-canvas-empty__mode">
                <span className="agent-canvas-empty__mode-icon">💬</span>
                <div>
                  <b>Chat-guided</b>
                  <p>Describe your idea in the chat panel and AI builds the full workflow automatically.</p>
                </div>
              </div>
              <div className="agent-canvas-empty__mode">
                <span className="agent-canvas-empty__mode-icon">✦</span>
                <div>
                  <b>Free-form</b>
                  <p>Use the + button on the left to add nodes manually, arrange them your way.</p>
                </div>
              </div>
            </div>
            <p className="agent-canvas-empty-hint">You can switch between them anytime —they don't limit each other.</p>
          </div>
        ) : null}

        {(surfaceError || session.state.authoringError || live.state.runtimeError) ? (
          <div className="agent-canvas-notice agent-canvas-notice--with-action" role="alert">
            <span>{surfaceError || session.state.authoringError || live.state.runtimeError}</span>
            {(() => {
              const errorText = surfaceError || session.state.authoringError || live.state.runtimeError || "";
              const isModelError = /model|provider|credential|config/i.test(errorText);
              return isModelError ? (
                <Link to="/api-space" className="agent-canvas-notice__action">
                  Configure provider
                </Link>
              ) : null;
            })()}
            <button
              type="button"
              className="agent-canvas-notice__dismiss"
              aria-label="Dismiss notice"
              onClick={() => {
                setSurfaceError(null);
                clearAuthoringError();
              }}
            >
              ×
            </button>
          </div>
        ) : null}

        {live.state.autoRunNotice ? (
          <button
            type="button"
            className="agent-canvas-notice agent-canvas-notice--info"
            aria-label="Dismiss automatic run notice"
            onClick={clearAutoRunNotice}
          >
            {live.state.autoRunNotice}
          </button>
        ) : null}

        {assetsOpen ? (
          <div className="agent-canvas-overlay agent-canvas-overlay--assets" role="dialog" aria-modal="true" aria-label="Project assets">
            <Suspense fallback={null}>
              <AgentAssetBrowser
                workflowId={workflow.workflow_id}
                onClose={() => setAssetsOpen(false)}
                onAddReferences={addReferences}
                onCreateReadySourceNode={createReadySourceNode}
                onUploadComplete={refreshWorkflow}
              />
            </Suspense>
          </div>
        ) : null}

        {editingNode ? (
          <Suspense fallback={null}>
            <AgentCanvasEditingPanel
              workflow={workflow}
              node={editingNode}
              omittedNodeIds={editingPreparation?.omittedNodeIds ?? []}
              patchNode={patchNode}
              onClose={() => setEditingNodeId(null)}
              onRevisionConflict={refreshWorkflow}
              onAddExportToCanvas={addEditingExportToCanvas}
            />
          </Suspense>
        ) : null}

        {videoPreview ? (
          <Suspense fallback={null}>
            <AgentCanvasVideoPreviewDialog
              asset={videoPreview.asset}
              title={videoPreview.title}
              onClose={closeVideoPreview}
            />
          </Suspense>
        ) : null}

        <input
          ref={referenceUploadInputRef}
          className="agent-canvas-reference-upload-input"
          type="file"
          accept="image/*"
          multiple
          tabIndex={-1}
          aria-hidden="true"
          onChange={(event) => void uploadSelectedNodeReferences(event)}
        />

        {contextMenu ? (
          contextMenu.kind === "node" ? (
            <AgentCanvasContextMenu
              menuPosition={contextMenu.menuPosition}
              onDeleteNode={() => deleteContextNode(contextMenu.nodeId)}
              onClose={() => setContextMenu(null)}
              onRelocate={openCanvasContextMenu}
            />
          ) : (
            <AgentCanvasContextMenu
              menuPosition={contextMenu.menuPosition}
              canvasPosition={contextMenu.canvasPosition}
              onCreateNode={(nodeType, position) => void createNode(nodeType, position)}
              onClose={() => setContextMenu(null)}
              onRelocate={openCanvasContextMenu}
            />
          )
        ) : null}

        {connectedNodeMenu && connectedMenuAnchor && connectionPolicy ? (
          <AgentCanvasConnectedNodeMenu
            anchorNode={connectedMenuAnchor}
            direction={connectedNodeMenu.direction}
            point={connectedNodeMenu.point}
            policy={connectionPolicy}
            onSelect={(nodeType, inputRole) => void createConnectedNodeFromMenu(nodeType, inputRole)}
            onClose={() => setConnectedNodeMenu(null)}
          />
        ) : null}

        </div>

        {/* Global Timeline Panel (ADR 0007) */}
        <div style={{ flexShrink: 0, borderTop: "1px solid #353535" }}>
          <Suspense fallback={null}>
            <GlobalTimelinePanel
              workflowId={workflow?.workflow_id}
              externalRefreshNonce={timelineExternalRefreshSignal}
              workflowNodeIds={workflowNodeIdSet}
              availableCharacters={availableTimelineCharacters}
              highlightedSourceNodeId={session.state.selectedNodeId}
              onClipClick={(clip) => {
                if (
                  clip.source_node_id
                  && workflowNodeIdSet.has(clip.source_node_id)
                ) {
                  focusNode(clip.source_node_id);
                }
              }}
              onCreateVideoNode={createVideoNodeForClip}
            />
          </Suspense>
        </div>
      </div>
      </PlayheadSyncProvider>

      <Suspense fallback={null}>
        <AgentCanvasChatPanel
          workflow={workflow}
          runtime={live.state.runtime}
          chatRevision={live.state.chatRevision}
          chatEvents={live.state.chatEvents}
          settingsRevision={live.state.settingsRevision}
          documentEvents={live.state.documentEvents}
          onFocusNode={focusNode}
          onActionReceipt={placeReceiptNodes}
          onWorkflowRefresh={refreshWorkflow}
          onRuntimeRefresh={() => {
            void refreshRuntime();
          }}
          onAssetsRefresh={refreshAssets}
          onProjectsRefresh={refreshProjects}
          collapsed={chatCollapsed}
          onCollapsedChange={setChatCollapsed}
          onViewNodes={revealAvailableCanvasNodes}
        />
      </Suspense>
    </div>
  );
}
