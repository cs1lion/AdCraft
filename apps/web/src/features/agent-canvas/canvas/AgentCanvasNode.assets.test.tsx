import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CanvasNodeV2 } from "../../../types-v2.ts";
import { AgentCanvasNodeCard, AgentCanvasNodeRenderer, type AgentCanvasNodeData } from "./AgentCanvasNode.tsx";
import { areAgentCanvasNodePropsEqual } from "./agentCanvasNodeRenderModel.ts";

vi.mock("./ReplicaBlueprintPanel.tsx", () => ({
  ReplicaBlueprintPanel: ({ onOpenAssets }: { onOpenAssets?: () => void }) => (
    <button type="button" onClick={onOpenAssets}>选择或上传声音素材</button>
  ),
}));
vi.mock("@xyflow/react", async () => ({
  ...await vi.importActual<typeof import("@xyflow/react")>("@xyflow/react"),
  useUpdateNodeInternals: () => vi.fn(),
}));

const node = {
  node_id: "replica-1", workflow_id: "wf-1", node_type: "replica",
  creative_role: "replica_blueprint", status: "draft", metadata: {}, parameters: {},
  structured_content: {}, position: { x: 0, y: 0 }, revision: 1,
} as CanvasNodeV2;

function rendererProps(data: AgentCanvasNodeData): Parameters<typeof areAgentCanvasNodePropsEqual>[0] {
  return {
    id: node.node_id, data, type: "agentCanvas", selected: false, dragging: false,
    draggable: true, selectable: true, deletable: true, isConnectable: true,
    zIndex: 0, positionAbsoluteX: 0, positionAbsoluteY: 0,
  };
}

afterEach(cleanup);

describe("replica node asset-browser callback", () => {
  it("passes the optional card callback through NodeSurface to the panel", () => {
    const onOpenAssets = vi.fn();
    render(<AgentCanvasNodeCard node={node} onOpenAssets={onOpenAssets} />);
    fireEvent.click(screen.getByRole("button", { name: "选择或上传声音素材" }));
    expect(onOpenAssets).toHaveBeenCalledOnce();
  });

  it("passes renderer data to the card and updates changed callbacks", () => {
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = render(<ReactFlowProvider><AgentCanvasNodeRenderer {...rendererProps({ node, onOpenAssets: first })} /></ReactFlowProvider>);
    fireEvent.click(screen.getByRole("button", { name: "选择或上传声音素材" }));
    expect(first).toHaveBeenCalledOnce();
    rerender(<ReactFlowProvider><AgentCanvasNodeRenderer {...rendererProps({ node, onOpenAssets: second })} /></ReactFlowProvider>);
    fireEvent.click(screen.getByRole("button", { name: "选择或上传声音素材" }));
    expect(second).toHaveBeenCalledOnce();
    expect(first).toHaveBeenCalledOnce();
  });

  it("keeps callback-free callers compatible and includes callback identity in memo equality", () => {
    render(<AgentCanvasNodeCard node={node} />);
    fireEvent.click(screen.getByRole("button", { name: "选择或上传声音素材" }));
    const first = rendererProps({ node });
    expect(areAgentCanvasNodePropsEqual(first, rendererProps({ node }))).toBe(true);
    expect(areAgentCanvasNodePropsEqual(first, rendererProps({ node, onOpenAssets: vi.fn() }))).toBe(false);
  });
});
