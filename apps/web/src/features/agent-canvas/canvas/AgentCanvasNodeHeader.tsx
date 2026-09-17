import type {
  CanvasNodeStatusV2,
  CanvasNodeV2,
  NodeRuntimePhaseV2,
  NodeRuntimeV2,
} from "../../../types-v2.ts";
import { AgentCanvasNodeIcon } from "./AgentCanvasNodeIcon.tsx";
import { projectCharacterNodePresentation } from "./characterNodePresentation.ts";
import { creativeRoleDisplayName } from "./creativeRoleDisplayName.ts";

const NODE_PHASE_LABELS: Record<NodeRuntimePhaseV2, string> = {
  waiting_for_input: "Waiting for input",
  blocked_by_upstream: "Blocked",
  queued: "Queued",
  running: "Running",
  waiting_provider: "Waiting for AI",
  recovering: "Recovering",
  publishing: "Publishing",
};

interface AgentCanvasNodeHeaderProps {
  node: CanvasNodeV2;
  status: CanvasNodeStatusV2;
  runtime?: NodeRuntimeV2 | null;
  dimensions?: { width: number; height: number } | null;
  onOpenConnectedNodeMenu?: (
    nodeId: string,
    direction: "upstream" | "downstream",
    point: { x: number; y: number },
  ) => void;
}

export function AgentCanvasNodeHeader({
  node,
  status,
  runtime,
  dimensions,
  onOpenConnectedNodeMenu,
}: AgentCanvasNodeHeaderProps) {
  const roleName = creativeRoleDisplayName(node.creative_role);
  const characterPresentation = projectCharacterNodePresentation(node);
  const name = characterPresentation?.phaseLabel ?? roleName;
  const showDimensions = node.node_type === "image" || node.node_type === "video";
  const phaseLabel = runtime?.phase ? NODE_PHASE_LABELS[runtime.phase] : null;

  return (
    <div className={`agent-canvas-node__header agent-canvas-node__header--${status}`}>
      <span
        className="agent-canvas-node__header-icon"
        role="img"
        aria-label={`${name} node type`}
      >
        <AgentCanvasNodeIcon nodeType={node.node_type} />
      </span>
      <span className="agent-canvas-node__header-name">{name}</span>
      {phaseLabel && status === "working" ? (
        <span className={`agent-canvas-node__header-phase agent-canvas-node__header-phase--${runtime?.phase}`}>
          {phaseLabel}
        </span>
      ) : null}
      {showDimensions && dimensions ? (
        <span className="agent-canvas-node__header-dimensions">
          {dimensions.width} × {dimensions.height}
        </span>
      ) : null}
      {onOpenConnectedNodeMenu ? (
        <span className="agent-canvas-node__header-connect-actions">
          <button
            type="button"
            className="agent-canvas-node__header-connect-btn"
            title="添加输入节点"
            onClick={(e) => {
              e.stopPropagation();
              const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
              onOpenConnectedNodeMenu(node.node_id, "upstream", { x: rect.left, y: rect.bottom });
            }}
          >
            +入
          </button>
          <button
            type="button"
            className="agent-canvas-node__header-connect-btn"
            title="添加输出节点"
            onClick={(e) => {
              e.stopPropagation();
              const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
              onOpenConnectedNodeMenu(node.node_id, "downstream", { x: rect.left, y: rect.bottom });
            }}
          >
            +出
          </button>
        </span>
      ) : null}
    </div>
  );
}
