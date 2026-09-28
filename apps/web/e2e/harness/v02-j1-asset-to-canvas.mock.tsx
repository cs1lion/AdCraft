/**
 * J1 acceptance harness — asset-to-canvas (V0.2 §2.1/§2.2).
 *
 * Mounts the REAL surfaces the journey touches:
 *  - the real AgentAssetBrowser (the drag source; its list is served by the
 *    spec's page.routes);
 *  - a real ReactFlow pane with the real AgentCanvasNodeRenderer cards, so a
 *    created node is exactly the card the product renders;
 *  - the real SceneWorkbenchRegion (LocalEngineWorkbench + SceneScript3DEditor),
 *    where the reference-input line for a bound asset appears.
 *
 * The pane's drop adapter mirrors AgentCanvasPageSurface.handleCanvasDrop:
 * it reads the SAME custom MIME, parses it with the SAME tolerant parser,
 * decides placement with the SAME pure snap/insert functions, builds the
 * create request with the SAME ``canvasDropCreateRequest`` (whose media→node
 * mapping mirrors the backend's ``validate_asset_backed_node``) and persists
 * through the SAME ``agentCanvasApi.createAgentCanvasNode`` / ``createAgentCanvasBinding``
 * clients the product uses. The card drop itself is the card's own handler.
 *
 * Only HTTP is mocked (by the spec, via page.route) — all gesture, parsing,
 * placement and rendering logic is the product's own code.
 */

import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type DragEvent as ReactDragEvent,
} from "react";
import { createRoot } from "react-dom/client";
import { ReactFlow, type ReactFlowInstance } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { agentCanvasApi } from "../../src/api/agentCanvasApi.ts";
import { AgentAssetBrowser } from "../../src/features/agent-canvas/assets/AgentAssetBrowser.tsx";
import {
  AgentCanvasNodeRenderer,
  type AgentCanvasFlowNode,
  type AgentCanvasNodeCallbacks,
} from "../../src/features/agent-canvas/canvas/AgentCanvasNode.tsx";
import {
  findAvailableCanvasPosition,
  toAgentCanvasFlowNodes,
} from "../../src/features/agent-canvas/canvas/canvasGraphModel.ts";
import {
  CANVAS_DROP_MIME,
  canvasDropCreateRequest,
  canvasNodeTypeForMedia,
  parseCanvasDropPayload,
} from "../../src/features/agent-canvas/canvas/canvasDrop.ts";
import {
  planRowGapInsert,
  snapCanvasDropPosition,
  type SnapBox,
} from "../../src/features/agent-canvas/canvas/canvasSnap.ts";
import { agentCanvasNodePlacementSize } from "../../src/features/agent-canvas/canvas/nodeGeometry.ts";
import type { AgentCanvasWorkflowV2 } from "../../src/types-v2.ts";
import { SceneWorkbenchRegion } from "./v02-scene-workbench.tsx";
import { j1Workflow } from "./v02-journeys.fixtures.ts";
import "../../src/styles/base.css";
import "../../src/styles/theme.css";
import "../../src/features/agent-canvas/agent-canvas-page.css";

// Registered once at module scope: a fresh object every render would remount
// every card on each state change.
const nodeTypes = { agentCanvas: AgentCanvasNodeRenderer };

function AcceptanceHarness() {
  const [workflow, setWorkflow] = useState<AgentCanvasWorkflowV2>(() => j1Workflow());
  const [surfaceError, setSurfaceError] = useState<string | null>(null);
  const workflowRef = useRef(workflow);
  workflowRef.current = workflow;

  /**
   * V0.2 §2.2 card drop (卡片内部 = 素材归属): an image dropped on the
   * scene-3d card becomes its reference input — the same
   * ``createBinding(input_role: "image_reference")`` write the connected-node
   * menu uses, so the edge is claimable and the executor can publish it.
   */
  const dropAssetAsReference = useCallback(
    async (nodeId: string, assetId: string, displayName: string) => {
      const current = workflowRef.current;
      const target = current.nodes.find((candidate) => candidate.node_id === nodeId) ?? null;
      const asset = current.assets.find((candidate) => candidate.asset_id === assetId) ?? null;
      if (!target || !asset) {
        setSurfaceError(`资产「${displayName}」不在当前工作流中，无法作为参考。`);
        return;
      }
      if (!asset.version_id) {
        setSurfaceError(`资产「${displayName}」没有可用的版本，无法作为参考。`);
        return;
      }
      try {
        const response = await agentCanvasApi.createAgentCanvasBinding(current.workflow_id, {
          source: {
            kind: "image_asset",
            source_asset_id: asset.asset_id,
            source_asset_version_id: asset.version_id,
          },
          target_node_id: target.node_id,
          input_role: "image_reference",
          enabled: true,
          order: current.bindings.filter((binding) => binding.target_node_id === target.node_id).length,
        });
        setWorkflow(response.value.workflow);
        setSurfaceError(null);
      } catch (error) {
        setSurfaceError(
          error instanceof Error ? error.message : "拖入参考失败，请重试。",
        );
      }
    },
    [],
  );

  const nodeCallbacks = useMemo<AgentCanvasNodeCallbacks>(
    () => ({
      onAssetDroppedAsReference: (nodeId, assetId, displayName) => {
        void dropAssetAsReference(nodeId, assetId, displayName);
      },
    }),
    [dropAssetAsReference],
  );

  const flowNodes = useMemo(
    () => toAgentCanvasFlowNodes(workflow, null, nodeCallbacks),
    [workflow, nodeCallbacks],
  );
  const flowNodesRef = useRef<AgentCanvasFlowNode[]>(flowNodes);
  flowNodesRef.current = flowNodes;
  // The instance arrives through onInit (the ref slot is the wrapper div),
  // exactly as the product surface captures it.
  const flowRef = useRef<ReactFlowInstance<AgentCanvasFlowNode> | null>(null);

  /** A node's placement box for snapping (same geometry as the surface). */
  const snapBoxFor = useCallback((flowNode: AgentCanvasFlowNode): SnapBox => {
    const node = flowNode.data.node;
    const asset = node.output_asset_id
      ? workflowRef.current.assets.find((candidate) => candidate.asset_id === node.output_asset_id) ?? null
      : null;
    const size = agentCanvasNodePlacementSize(
      node.node_type,
      asset ? { width: asset.width, height: asset.height } : null,
    );
    return { id: node.node_id, position: flowNode.position, size };
  }, []);

  // Pane drop (V0.2 §2.1: 素材 → 拖到画布 → 创建镜头). Mirrors
  // AgentCanvasPageSurface.handleCanvasDrop; the pure decision functions and
  // the API client are imported, not re-implemented.
  const handlePaneDragOver = useCallback((event: ReactDragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer.types.includes(CANVAS_DROP_MIME)) return;
    // Accept the drop: the browser otherwise treats the pane as a non-target
    // and swallows the gesture.
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }, []);

  const handlePaneDrop = useCallback(
    async (event: ReactDragEvent<HTMLDivElement>) => {
      const raw = event.dataTransfer.getData(CANVAS_DROP_MIME);
      if (!raw) return;
      event.preventDefault();
      const payload = parseCanvasDropPayload(raw);
      // A malformed payload degrades to "nothing happens" — never a throw
      // inside React's event loop.
      if (!payload) return;
      const nodeType = canvasNodeTypeForMedia(payload.media_type);
      if (!nodeType) return;
      const instance = flowRef.current;
      const preferred = instance
        ? instance.screenToFlowPosition({ x: event.clientX, y: event.clientY })
        : { x: 120, y: 120 };
      const current = workflowRef.current;
      const droppedAsset =
        current.assets.find((candidate) => candidate.asset_id === payload.asset_id) ?? null;
      const dropSize = agentCanvasNodePlacementSize(
        nodeType,
        droppedAsset ? { width: droppedAsset.width, height: droppedAsset.height } : null,
      );
      const siblings = flowNodesRef.current.map((flowNode) => snapBoxFor(flowNode));
      const snapped = snapCanvasDropPosition(preferred, siblings, dropSize);
      const insertPlan = snapped.snap ? null : planRowGapInsert(preferred, siblings, dropSize);
      const position = snapped.snap
        ? snapped.position
        : insertPlan
          ? insertPlan.insertAt
          : findAvailableCanvasPosition(current.nodes, preferred, {
              assets: current.assets,
              candidateNodeType: nodeType,
              candidateDimensions: droppedAsset
                ? { width: droppedAsset.width, height: droppedAsset.height }
                : null,
            });
      const request = canvasDropCreateRequest(payload, position);
      if (!request) return;
      try {
        const response = await agentCanvasApi.createAgentCanvasNode(current.workflow_id, request);
        setWorkflow(response.value.workflow);
        setSurfaceError(null);
      } catch (error) {
        setSurfaceError(
          error instanceof Error ? error.message : "拖拽创建节点失败，请重试。",
        );
      }
    },
    [snapBoxFor],
  );

  return (
    <main className="v02-j1-harness">
      <aside className="v02-j1-harness__browser">
        <header className="v02-j1-harness__title">素材 · 资产浏览器</header>
        <AgentAssetBrowser
          workflowId={workflow.workflow_id}
          onAddReferences={async () => {}}
          onCreateReadySourceNode={async () => {}}
        />
      </aside>
      <section className="v02-j1-harness__stage">
        <header className="v02-j1-harness__title">画布 · 拖入创建，拖上卡片绑定</header>
        <div
          className="agent-canvas-board v02-j1-harness__board"
          data-testid="canvas-pane"
          onDragOver={handlePaneDragOver}
          onDrop={(event) => void handlePaneDrop(event)}
        >
          <ReactFlow<AgentCanvasFlowNode>
            nodes={flowNodes}
            nodeTypes={nodeTypes}
            proOptions={{ hideAttribution: true }}
            fitView={false}
            minZoom={0.2}
            onInit={(instance) => {
              flowRef.current = instance;
            }}
          />
        </div>
        {surfaceError ? (
          <p className="v02-j1-harness__error" data-testid="j1-surface-error">
            {surfaceError}
          </p>
        ) : null}
        <SceneWorkbenchRegion workflow={workflow} />
      </section>
    </main>
  );
}

const style = document.createElement("style");
style.textContent = `
  html, body, #root { min-height: 100%; margin: 0; background: #0a0a0a; color: #f5f5f5; }
  .v02-j1-harness { display: grid; grid-template-columns: 340px 1fr; gap: 16px; padding: 16px; font-family: Inter, sans-serif; }
  .v02-j1-harness__title { font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: #9a9a9a; margin-bottom: 8px; }
  .v02-j1-harness__stage { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
  .v02-j1-harness__board { height: 60vh; border: 1px solid #2c2c2c; border-radius: 8px; overflow: hidden; }
  .v02-j1-harness__error { color: #ff9b9b; font-size: 13px; }
`;
document.head.append(style);

createRoot(document.getElementById("root")!).render(<AcceptanceHarness />);
