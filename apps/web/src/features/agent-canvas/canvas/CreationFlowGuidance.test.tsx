import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CreationFlowGuidance } from "./CreationFlowGuidance.tsx";

/**
 * Creation-flow guidance tests.
 *
 * Locks workflow/request ownership, serial polling, observable refresh failures,
 * and progressive access to every backend-assessed blocker and warning.
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

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

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

  it("makes all warnings accessible through progressive details", async () => {
    agentCanvasApi.getCreationFlowAssessment.mockResolvedValue(
      assessment({
        warnings: ["one", "two", "three", "four", "five"],
      }),
    );
    render(<CreationFlowGuidance workflowId="wf-1" pollInterval={0} />);

    await waitFor(() => {
      expect(screen.getByText("Show 2 more warnings")).toBeTruthy();
    });
    const details = screen.getByText("Show 2 more warnings").closest("details")!;
    expect(details.open).toBe(false);
    fireEvent.click(screen.getByText("Show 2 more warnings"));
    expect(details.open).toBe(true);
    expect(screen.getByText(/four/)).toBeTruthy();
    expect(screen.getByText(/five/)).toBeTruthy();
  });

  it("makes all blockers accessible through progressive details", async () => {
    agentCanvasApi.getCreationFlowAssessment.mockResolvedValue(assessment({
      blockers: ["First blocker", "Second blocker", "Third blocker", "Fourth blocker", "Fifth blocker"],
    }));
    render(<CreationFlowGuidance workflowId="wf-1" pollInterval={0} />);
    await screen.findByText("Show 2 more blockers");
    const details = screen.getByText("Show 2 more blockers").closest("details")!;
    expect(details.open).toBe(false);
    fireEvent.click(screen.getByText("Show 2 more blockers"));
    expect(details.open).toBe(true);
    expect(screen.getByText("Fourth blocker")).toBeTruthy();
    expect(screen.getByText("Fifth blocker")).toBeTruthy();
  });

  it("ignores late workflow A results in both the DOM and parent callback", async () => {
    const a = deferred<ReturnType<typeof assessment>>();
    const b = deferred<ReturnType<typeof assessment>>();
    const onAssessment = vi.fn();
    agentCanvasApi.getCreationFlowAssessment.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    const { rerender } = render(<CreationFlowGuidance workflowId="A" pollInterval={0} onAssessment={onAssessment} />);
    rerender(<CreationFlowGuidance workflowId="B" pollInterval={0} onAssessment={onAssessment} />);
    const resultB = assessment({ next_action: "B action" });
    await act(async () => { b.resolve(resultB); });
    await act(async () => { a.resolve(assessment({ next_action: "A action" })); });
    expect(screen.getByText("B action")).toBeTruthy();
    expect(screen.queryByText("A action")).toBeNull();
    expect(onAssessment).toHaveBeenCalledExactlyOnceWith(resultB);
  });

  it("clears the prior workflow assessment and expanded stage while the next workflow loads", async () => {
    const b = deferred<ReturnType<typeof assessment>>();
    agentCanvasApi.getCreationFlowAssessment.mockResolvedValueOnce(assessment({
      stage_statuses: [{ stage: "scene_3d", display_name: "3D Previs", completed: false, ready_nodes: 0, total_nodes: 1, description: "Stage detail", blockers: [] }],
    })).mockReturnValueOnce(b.promise);
    const { rerender } = render(<CreationFlowGuidance workflowId="A" pollInterval={0} />);
    await screen.findByText("Run 3D Previs node");
    fireEvent.click(screen.getByRole("button", { name: /3D Previs/ }));
    expect(screen.getByText("Stage detail")).toBeTruthy();
    rerender(<CreationFlowGuidance workflowId="B" pollInterval={0} />);
    expect(screen.queryByText("Run 3D Previs node")).toBeNull();
    expect(screen.queryByText("Stage detail")).toBeNull();
    expect(screen.getByText("Loading creation flow...")).toBeTruthy();
  });

  it("retains useful data after refresh rejection, exposes stale/retrying state and recovers by manual retry", async () => {
    vi.useFakeTimers();
    const refresh = deferred<ReturnType<typeof assessment>>();
    const retry = deferred<ReturnType<typeof assessment>>();
    agentCanvasApi.getCreationFlowAssessment.mockResolvedValueOnce(assessment())
      .mockReturnValueOnce(refresh.promise).mockReturnValueOnce(retry.promise);
    render(<CreationFlowGuidance workflowId="A" pollInterval={100} />);
    await act(async () => {});
    await act(async () => { vi.advanceTimersByTime(100); });
    await act(async () => { refresh.reject(new Error("Internal request trace secret")); });
    expect(screen.getByText("Run 3D Previs node")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("may be out of date");
    expect(screen.queryByText(/Internal request trace/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(screen.getByRole("status").textContent).toContain("Retrying");
    await act(async () => { retry.resolve(assessment({ next_action: "Updated action" })); });
    expect(screen.getByText("Updated action")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("shows a friendly initial failure and allows manual retry without technical noise", async () => {
    agentCanvasApi.getCreationFlowAssessment.mockRejectedValueOnce(new Error("GET /internal trace"))
      .mockResolvedValueOnce(assessment());
    render(<CreationFlowGuidance workflowId="A" pollInterval={0} />);
    await screen.findByText("Unable to refresh creation flow. Please try again.");
    expect(screen.queryByText(/internal trace/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText("Run 3D Previs node");
    expect(agentCanvasApi.getCreationFlowAssessment).toHaveBeenCalledTimes(2);
  });

  it("serializes polling and uses the latest callback without restarting requests", async () => {
    vi.useFakeTimers();
    const first = deferred<ReturnType<typeof assessment>>();
    const second = deferred<ReturnType<typeof assessment>>();
    agentCanvasApi.getCreationFlowAssessment.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const oldCallback = vi.fn();
    const newCallback = vi.fn();
    const { rerender } = render(<CreationFlowGuidance workflowId="A" pollInterval={100} onAssessment={oldCallback} />);
    rerender(<CreationFlowGuidance workflowId="A" pollInterval={100} onAssessment={newCallback} />);
    await act(async () => { vi.advanceTimersByTime(1000); });
    expect(agentCanvasApi.getCreationFlowAssessment).toHaveBeenCalledTimes(1);
    await act(async () => { first.resolve(assessment()); });
    expect(oldCallback).not.toHaveBeenCalled();
    expect(newCallback).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(99); });
    expect(agentCanvasApi.getCreationFlowAssessment).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(agentCanvasApi.getCreationFlowAssessment).toHaveBeenCalledTimes(2);
    await act(async () => { vi.advanceTimersByTime(1000); });
    expect(agentCanvasApi.getCreationFlowAssessment).toHaveBeenCalledTimes(2);
  });

  it("ignores a pending assessment after unmount and never schedules another poll", async () => {
    vi.useFakeTimers();
    const pending = deferred<ReturnType<typeof assessment>>();
    const onAssessment = vi.fn();
    agentCanvasApi.getCreationFlowAssessment.mockReturnValueOnce(pending.promise);
    const { unmount } = render(<CreationFlowGuidance workflowId="A" pollInterval={100} onAssessment={onAssessment} />);
    unmount();
    await act(async () => { pending.resolve(assessment()); });
    await act(async () => { vi.advanceTimersByTime(1000); });
    expect(onAssessment).not.toHaveBeenCalled();
    expect(agentCanvasApi.getCreationFlowAssessment).toHaveBeenCalledTimes(1);
  });
});
