import type { CanvasNodeV2 } from "../../../types-v2.ts";

/** A node is runnable only when its prompt is actually prepared, not just draft. */
export function canvasProgressModel(nodes: readonly CanvasNodeV2[]) {
  const total = nodes.length;
  const ready = nodes.filter((node) => node.status === "ready").length;
  const working = nodes.filter((node) => node.status === "working").length;
  const failed = nodes.filter((node) => node.status === "failed").length;
  const draft = nodes.filter((node) => node.status === "draft").length;
  return {
    total, ready, working, failed, draft,
    complete: total > 0 && ready === total,
    waiting: Math.max(0, total - ready - working - failed),
    percent: total > 0 ? Math.round((ready / total) * 100) : 0,
  };
}
