/**
 * The scene-3d workbench region shared by both V0.2 journey mock pages.
 *
 * This mounts the REAL ``LocalEngineWorkbench`` — the product surface that
 * hosts the dialogue lip-sync panel, the SceneScript3DEditor (shot strip +
 * transition picker) and the executor-published reports. Both journeys end
 * inside this surface: J1's reference-input line lives in the editor, and
 * all of J2 lives on its panels. Mounting the real workbench (instead of a
 * hand-wired composition of panels) means the advisory → playhead →
 * auto-fetch wire proven by J2 is the product's own wire, not a harness
 * replica.
 *
 * The draft comes from the real ``useNodeWorkbenchDraft`` hook with stub
 * collaborators: no HTTP is issued by the workbench itself (the panels'
 * fetches are what the spec routes).
 */

import { useCallback } from "react";

import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../src/types-v2.ts";
import { LocalEngineWorkbench } from "../../src/features/agent-canvas/workbench/LocalEngineWorkbench.tsx";
import { useNodeWorkbenchDraft } from "../../src/features/agent-canvas/workbench/useNodeWorkbenchDraft.ts";
import type { PatchNode } from "../../src/features/agent-canvas/workbench/workbenchTypes.ts";
import { SCENE_NODE_ID } from "./v02-journeys.fixtures.ts";

/** Finds the scene node, then mounts the real workbench on it. */
export function SceneWorkbenchRegion({
  workflow,
}: {
  workflow: AgentCanvasWorkflowV2;
}) {
  const sceneNode = workflow.nodes.find((node) => node.node_id === SCENE_NODE_ID) ?? null;
  if (!sceneNode) return null;
  return <SceneWorkbench workflow={workflow} sceneNode={sceneNode} />;
}

function SceneWorkbench({
  workflow,
  sceneNode,
}: {
  workflow: AgentCanvasWorkflowV2;
  sceneNode: CanvasNodeV2;
}) {
  // The workbench persists lines/variants through patchNode; the journeys
  // never save, and a stub keeps every write observable in the spec's routes.
  const patchNode = useCallback<PatchNode>(async () => {}, []);
  const draft = useNodeWorkbenchDraft({
    workflow,
    node: sceneNode,
    patchNode,
    onRun: async () => {},
    onSaveImageToLibrary: async () => {},
    onWorkflowRefresh: () => {},
  });

  return (
    <section className="v02-scene-workbench" data-testid="scene-workbench">
      <LocalEngineWorkbench node={sceneNode} draft={draft} patchNode={patchNode} />
    </section>
  );
}
