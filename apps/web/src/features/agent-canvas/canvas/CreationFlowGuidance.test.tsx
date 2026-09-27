import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CreationFlowGuidance } from "./CreationFlowGuidance.tsx";

/**
 * Creation-flow guidance tests.
 *
 * Locks the warning surface: the guidance is backend-assessed, so the
 * component's only real contract is that it renders what the API said —
 * including the honest "+N more" truncation indicator.
 */

const agentCanvasApi = vi.hoisted(() => ({
  getCreationFlowAssessment: vi.fn(),
}));

vi.mock("../../../api/agentCanvasApi.ts", () => ({
  agentCanvasApi,
}));

function assessment(overrides: Record<string, unknown> = {}) {
  return {
    current_stage: "scene_3d",
    current_stage_index: 3,
    completed_stages: ["world_setting", "script", "storyboard"],
    stage_statuses: [],
    progress_percent: 50,
    next_action: "Run 3D Previs node",
    next_action_detail: "The 3D previs node exists but needs to run.",
    blockers: [],
    warnings: [],
    is_complete: false,
    ...overrides,
  };
}

beforeEach(() => {
  agentCanvasApi.getCreationFlowAssessment.mockReset();
  agentCanvasApi.getCreationFlowAssessment.mockResolvedValue(assessment());
});

afterEach(cleanup);

describe("CreationFlowGuidance", () => {
  it("renders the current stage and next action", async () => {
    render(<CreationFlowGuidance workflowId="wf-1" pollInterval={0} />);

    await waitFor(() => {
      expect(screen.getByText("Run 3D Previs node")).toBeTruthy();
    });
  });

  it("shows speaker-mismatch warnings with the valid character ids", async () => {
    agentCanvasApi.getCreationFlowAssessment.mockResolvedValue(
      assessment({
        warnings: [
          "Audio-bed speaker(s) 旁白 do not match any scene-3d character id. "
            + "Available character ids: lin, su. Lip-sync will refuse unknown speakers "
            + "(it never drops dialogue silently) — rename the bed speakers or rename "
            + "the scene characters to match.",
        ],
      }),
    );
    render(<CreationFlowGuidance workflowId="wf-1" pollInterval={0} />);

    await waitFor(() => {
      expect(screen.getByText(/do not match any scene-3d character id/)).toBeTruthy();
    });
    expect(screen.getByText(/Available character ids: lin, su/)).toBeTruthy();
  });

  it("counts the warnings it does not show (no silent truncation)", async () => {
    agentCanvasApi.getCreationFlowAssessment.mockResolvedValue(
      assessment({
        warnings: ["one", "two", "three", "four", "five"],
      }),
    );
    render(<CreationFlowGuidance workflowId="wf-1" pollInterval={0} />);

    await waitFor(() => {
      expect(screen.getByText("还有 2 条提示")).toBeTruthy();
    });
    expect(screen.getByText(/one/)).toBeTruthy();
    expect(screen.queryByText(/four/)).toBeNull();
  });
});
