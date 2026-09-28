/**
 * 零模型费直出渲染的可恢复句柄（handoff D7）。
 *
 * direct-execute 渲染是 detached 的：拿到 render_id 后轮询 v2 渲染状态端点；
 * 刷新页面会丢 render_id，结果再也查不回任务。把 render_id 按节点落 localStorage，
 * 刷新即重新挂上轮询。沿用 `agentCanvasViewport.ts` 的命名空间 / 可注入 storage /
 * 一次性写入（永不阻断渲染流）。
 */
export type ReplicaRenderPhase = "polling";

export interface ReplicaRenderSnapshot {
  renderId: string;
  renderPhase: ReplicaRenderPhase;
}

export function replicaRenderStorageKey(workflowId: string, nodeId: string): string {
  return `adcraft:agent-canvas:replica-render:${workflowId}:${nodeId}`;
}

export function readReplicaRender(
  workflowId: string,
  nodeId: string,
  storage: Pick<Storage, "getItem"> = window.localStorage,
): ReplicaRenderSnapshot | null {
  try {
    const value = storage.getItem(replicaRenderStorageKey(workflowId, nodeId));
    if (!value) return null;
    const parsed = JSON.parse(value) as Partial<ReplicaRenderSnapshot>;
    if (typeof parsed.renderId === "string" && parsed.renderId && parsed.renderPhase === "polling") {
      return { renderId: parsed.renderId, renderPhase: "polling" };
    }
    return null;
  } catch {
    return null;
  }
}

export function writeReplicaRender(
  workflowId: string,
  nodeId: string,
  snapshot: ReplicaRenderSnapshot,
  storage: Pick<Storage, "setItem"> = window.localStorage,
): void {
  try {
    storage.setItem(replicaRenderStorageKey(workflowId, nodeId), JSON.stringify(snapshot));
  } catch {
    // Render-handle persistence is disposable and must never block the render flow.
  }
}

export function clearReplicaRender(
  workflowId: string,
  nodeId: string,
  storage: Pick<Storage, "removeItem"> = window.localStorage,
): void {
  try {
    storage.removeItem(replicaRenderStorageKey(workflowId, nodeId));
  } catch {
    // ignore — a stale handle the next load simply never attaches.
  }
}
