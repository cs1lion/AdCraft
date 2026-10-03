import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { V2ApiError } from "../../../api/v2Client.ts";
import { useNodePromptAutosave } from "./useNodePromptAutosave.ts";
import { useNodeWorkbenchDraft } from "./useNodeWorkbenchDraft.ts";
import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../../types-v2.ts";

function draftNode(prompt: string | null): CanvasNodeV2 {
  return {
    node_id: "node-1", workflow_id: "workflow-1", node_type: "image",
    creative_role: "general_image", title: "Image", status: "draft",
    generation_prompt: prompt, structured_content: {}, parameters: {},
    model_ref: null, model_selection_mode: "default",
  } as CanvasNodeV2;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("workbench authoritative prompt reconciliation", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function renderDraft(initialPrompt: string | null, patchNode = vi.fn().mockResolvedValue(undefined)) {
    const hook = renderHook(({ node }) => useNodeWorkbenchDraft({
      workflow: { workflow_id: "workflow-1" } as AgentCanvasWorkflowV2,
      node, patchNode, onRun: vi.fn(), onSaveImageToLibrary: vi.fn(),
    }), { initialProps: { node: draftNode(initialPrompt) } });
    return { ...hook, patchNode };
  }

  it("adopts null-to-prepared and subsequent clean server prompts without PATCHing them", async () => {
    const { result, rerender, patchNode, unmount } = renderDraft(null);
    rerender({ node: draftNode("Prepared by server") });
    expect(result.current.prompt).toBe("Prepared by server");
    rerender({ node: draftNode("Updated by server") });
    expect(result.current.prompt).toBe("Updated by server");
    await act(async () => { expect(await result.current.flushPrompt()).toBe(true); });
    unmount();
    expect(patchNode).not.toHaveBeenCalled();
  });

  it("preserves dirty and saving text, guards stale PATCH echoes, then adopts clean server replacements", async () => {
    const pending = deferred<void>();
    const patchNode = vi.fn().mockReturnValue(pending.promise);
    const { result, rerender } = renderDraft("Original", patchNode);
    act(() => result.current.setPrompt("Local"));
    rerender({ node: draftNode("External while dirty") });
    expect(result.current.prompt).toBe("Local");
    let flush!: Promise<boolean>;
    act(() => { flush = result.current.flushPrompt(); });
    rerender({ node: draftNode("Original") });
    expect(result.current.prompt).toBe("Local");
    await act(async () => { pending.resolve(); await flush; });
    rerender({ node: { ...draftNode("Original"), revision: 2 } });
    expect(result.current.prompt).toBe("Local");
    rerender({ node: draftNode("Local") });
    rerender({ node: draftNode("New clean server value") });
    expect(result.current.prompt).toBe("New clean server value");
    act(() => result.current.setPrompt("Unsent local"));
    rerender({ node: draftNode("Another server value") });
    expect(result.current.prompt).toBe("Unsent local");
  });

  it("keeps conflict text across authoritative refresh", async () => {
    const patchNode = vi.fn().mockRejectedValue(new V2ApiError({
      status: 412, code: "workflow_state_conflict", message: "Conflict",
      details: {}, violations: [], suggestedActions: [], payload: null,
    }));
    const { result, rerender } = renderDraft("Original", patchNode);
    act(() => result.current.setPrompt("Local conflict"));
    await act(async () => { await result.current.flushPrompt(); });
    rerender({ node: draftNode("Server conflict") });
    expect(result.current.prompt).toBe("Local conflict");
    expect(result.current.promptSaveStatus).toBe("conflict");
  });
});

describe("useNodePromptAutosave", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("debounces each node and coalesces the latest prompt", async () => {
    const patchNode = vi.fn().mockResolvedValue(undefined);
    const { result, rerender } = renderHook(({ value }) => useNodePromptAutosave({
      nodeId: "node-1",
      value,
      enabled: true,
      patchNode,
    }), { initialProps: { value: "first" } });

    act(() => result.current.schedule("second"));
    rerender({ value: "second" });
    act(() => result.current.schedule("latest"));
    rerender({ value: "latest" });
    await act(async () => { vi.advanceTimersByTime(499); });
    expect(patchNode).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(1); });
    await act(async () => { await Promise.resolve(); });

    expect(patchNode).toHaveBeenCalledTimes(1);
    expect(patchNode).toHaveBeenCalledWith("node-1", { generation_prompt: "latest" }, { coalesce: true });
  });

  it("flushes immediately and preserves local text on a revision conflict", async () => {
    const patchNode = vi.fn().mockRejectedValue(new V2ApiError({
      status: 412,
      code: "workflow_state_conflict",
      message: "Workflow changed elsewhere.",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }));
    const onConflict = vi.fn();
    const { result, rerender } = renderHook(({ value }) => useNodePromptAutosave({
      nodeId: "node-1",
      value,
      enabled: true,
      patchNode,
      onConflict,
    }), { initialProps: { value: "local text" } });
    act(() => result.current.schedule("unsaved local text"));
    rerender({ value: "unsaved local text" });
    const flushed = await act(async () => result.current.flush());

    expect(flushed).toBe(false);
    expect(result.current.status).toBe("conflict");
    expect(onConflict).toHaveBeenCalledTimes(1);
    expect(patchNode).toHaveBeenCalledWith("node-1", { generation_prompt: "unsaved local text" }, { coalesce: true });
  });

  it("flushes pending text when the editor owner unmounts", async () => {
    const patchNode = vi.fn().mockResolvedValue(undefined);
    const { result, rerender, unmount } = renderHook(({ value }) => useNodePromptAutosave({
      nodeId: "node-1",
      value,
      enabled: true,
      patchNode,
    }), { initialProps: { value: "before" } });
    act(() => result.current.schedule("on close"));
    rerender({ value: "on close" });
    unmount();
    await act(async () => { await Promise.resolve(); });

    expect(patchNode).toHaveBeenCalledWith("node-1", { generation_prompt: "on close" }, { coalesce: true });
  });

  it("flushes the previous node's latest prompt when switching nodes", async () => {
    const patchNode = vi.fn().mockResolvedValue(undefined);
    const { result, rerender } = renderHook(
      ({ nodeId, value }) => useNodePromptAutosave({
        nodeId,
        value,
        enabled: true,
        patchNode,
      }),
      { initialProps: { nodeId: "node-a", value: "A original" } },
    );

    act(() => result.current.schedule("A latest"));
    rerender({ nodeId: "node-a", value: "A latest" });
    rerender({ nodeId: "node-b", value: "B original" });
    await act(async () => { await Promise.resolve(); });

    expect(patchNode).toHaveBeenCalledWith(
      "node-a",
      { generation_prompt: "A latest" },
      { coalesce: true },
    );
    expect(patchNode).not.toHaveBeenCalledWith(
      "node-a",
      { generation_prompt: "B original" },
      { coalesce: true },
    );
  });
});
