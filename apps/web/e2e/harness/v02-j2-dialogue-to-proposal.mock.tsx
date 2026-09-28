/**
 * J2 acceptance harness — dialogue-to-proposal (V0.2 §14.3/§14.5/§15).
 *
 * Mounts the REAL scene-3d workbench (LocalEngineWorkbench), which is where
 * the whole journey lives in the product:
 *  - DialogueLipSyncPanel: type lines → 应用唇形 → the shot advisories
 *    (规则版顾问, from the dialogue-lipsync run) appear under
 *    「分镜提示（不自动修改）」;
 *  - the advisory's 「🎬 看看怎么接」 button is the product's own wire
 *    (onOpenTransitions → focusShotId): the editor moves the playhead into
 *    the boundary shot and the TransitionProposalsPanel auto-fetches the
 *    readings for THAT pair, priced against the speech segments the applied
 *    lip-sync run measured;
 *  - applying 声音桥 (a zero-operation reading) records the shot's
 *    transition_intent, and the ShotStrip shows the relation on the boundary
 *    (a label, not a connector line — V0.2 §13 第 5 问).
 *
 * Only HTTP is mocked (by the spec, via page.route): both LLM layers stay OFF
 * by default, so the run is local logic end to end.
 */

import { useMemo } from "react";
import { createRoot } from "react-dom/client";

import type { AgentCanvasWorkflowV2 } from "../../src/types-v2.ts";
import { SceneWorkbenchRegion } from "./v02-scene-workbench.tsx";
import { j2Workflow } from "./v02-journeys.fixtures.ts";
import "../../src/styles/base.css";
import "../../src/styles/theme.css";

function AcceptanceHarness() {
  const workflow = useMemo<AgentCanvasWorkflowV2>(() => j2Workflow(), []);
  return (
    <main className="v02-j2-harness">
      <SceneWorkbenchRegion workflow={workflow} />
    </main>
  );
}

const style = document.createElement("style");
style.textContent = `
  html, body, #root { min-height: 100%; margin: 0; background: #0a0a0a; color: #f5f5f5; }
  .v02-j2-harness { padding: 16px; font-family: Inter, sans-serif; }
`;
document.head.append(style);

createRoot(document.getElementById("root")!).render(<AcceptanceHarness />);
