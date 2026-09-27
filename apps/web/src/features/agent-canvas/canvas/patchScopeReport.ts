/**
 * Patch scope report store (ADR 0009 决策 2 / V0.2 §10).
 *
 * The backend answers the author's real question after an edit — "what did I
 * just affect?" — with a `scope_report` on every node patch. The patch path
 * used to discard it (`Promise<void>`), so the answer died in the API client:
 * an author who moved a character had no way to learn that no neighbour was
 * touched, and would read the silence as "the system didn't check".
 *
 * A tiny external store (same pattern as timelineMutationRefresh: the patch
 * happens outside any one component's tree). Subscribers read the LAST
 * report; a surface renders it for the node it cares about.
 */

import { useSyncExternalStore } from "react";

/** One entry in `affected_neighbours` as the backend reports it. */
export interface ScopeNeighbour {
  node_id?: string;
  relation?: string;
  reason?: string;
}

/** The patch response's scope_report (ADR 0009 决策 2). */
export interface NodeScopeReport {
  edited_keys?: string[];
  content_areas?: string[];
  affected_neighbours?: ScopeNeighbour[];
  dirty_reasons?: string[];
  notes?: string[];
}

export interface PatchScopeRecord {
  /** Monotonic id so a repeat patch of the same node still re-renders. */
  nonce: number;
  nodeId: string;
  report: NodeScopeReport;
}

let current: PatchScopeRecord | null = null;
const listeners = new Set<() => void>();

/** Publish the scope report of a successful node patch. */
export function publishPatchScopeReport(
  nodeId: string,
  report: NodeScopeReport | null | undefined,
): void {
  if (!report) return;
  current = {
    nonce: (current?.nonce ?? 0) + 1,
    nodeId,
    report,
  };
  for (const listener of listeners) listener();
}

/** The last published report (null before the first patch). */
export function lastPatchScopeReport(): PatchScopeRecord | null {
  return current;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): PatchScopeRecord | null {
  return current;
}

export const patchScopeReportStore = {
  getSnapshot,
  subscribe,
};

/** Subscribe to the last report (null-aware for useSyncExternalStore). */
export function useLastPatchScopeReport(): PatchScopeRecord | null {
  return useSyncExternalStore(
    subscribe,
    getSnapshot,
    () => null,
  );
}

/**
 * The one sentence the ADR demands be SAID: an edit that touches no
 * neighbour must not leave that fact to silence.
 */
export function scopeSummary(record: PatchScopeRecord): {
  headline: string;
  detail: string | null;
} {
  const neighbours = record.report.affected_neighbours ?? [];
  if (neighbours.length === 0) {
    return {
      headline: "未影响其他节点",
      detail:
        record.report.notes?.[0] ??
        "本次编辑不影响任何已绑定节点（下游只消费本节点的产物，不读取作者态）。",
    };
  }
  const named = neighbours
    .map((neighbour) => neighbour.node_id ?? "未命名节点")
    .join("、");
  return {
    headline: `影响 ${neighbours.length} 个关联节点`,
    detail: `${named}｜${record.report.notes?.[0] ?? ""}`.trim(),
  };
}
