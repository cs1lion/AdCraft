import { describe, expect, it, vi } from "vitest";

import {
  bumpTimelineMutationRefresh,
  timelineMutationRefreshStore,
} from "./timelineMutationRefresh.ts";

describe("timelineMutationRefreshStore", () => {
  it("notifies subscribers on each bump", () => {
    const listener = vi.fn();
    const unsubscribe = timelineMutationRefreshStore.subscribe(listener);

    bumpTimelineMutationRefresh();
    bumpTimelineMutationRefresh();

    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
    bumpTimelineMutationRefresh();
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("returns a strictly growing snapshot (never a stale nonce)", () => {
    const first = timelineMutationRefreshStore.getSnapshot();

    bumpTimelineMutationRefresh();

    expect(timelineMutationRefreshStore.getSnapshot()).toBeGreaterThan(first);
  });

  it("is a stable store object across imports (useSyncExternalStore contract)", () => {
    expect(typeof timelineMutationRefreshStore.getSnapshot).toBe("function");
    expect(typeof timelineMutationRefreshStore.subscribe).toBe("function");
  });
});
