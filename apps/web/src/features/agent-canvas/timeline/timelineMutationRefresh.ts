/**
 * Imperative timeline-refresh signal for client-side mutations.
 *
 * The SSE-derived nonce (timelineRefresh.ts) covers server-side mutations
 * that emit node_output_published. Mutations made straight through the
 * timeline API from another surface — e.g. publishing subtitle cues from
 * the scene-3d workbench — emit nothing, so an open timeline panel would
 * keep showing stale content until the next node run.
 *
 * A tiny external store (not React state on purpose: the mutation happens
 * outside the panel's tree, and the panel only needs "something changed").
 */

let nonce = 0;
const listeners = new Set<() => void>();

/** Signal every subscriber that timeline content changed client-side. */
export function bumpTimelineMutationRefresh(): void {
  nonce += 1;
  for (const listener of listeners) listener();
}

function getSnapshot(): number {
  return nonce;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export const timelineMutationRefreshStore = {
  getSnapshot,
  subscribe,
};
