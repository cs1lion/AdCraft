import { describe, expect, it } from "vitest";

import {
  clearReplicaRender,
  readReplicaRender,
  replicaRenderStorageKey,
  writeReplicaRender,
} from "./replicaRenderStore.ts";

function fakeStorage() {
  const map = new Map<string, string>();
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => {
      map.set(key, value);
    },
    removeItem: (key: string) => {
      map.delete(key);
    },
  };
}

describe("replicaRenderStore (D7)", () => {
  it("round-trips the in-flight render handle under a per-node key", () => {
    const storage = fakeStorage();
    expect(readReplicaRender("wf1", "replica-1", storage)).toBeNull();
    writeReplicaRender("wf1", "replica-1", { renderId: "rnd_123", renderPhase: "polling" }, storage);
    expect(readReplicaRender("wf1", "replica-1", storage)?.renderId).toBe("rnd_123");
    expect(readReplicaRender("wf1", "other", storage)).toBeNull();
  });

  it("ignores non-polling / corrupt entries (never throws)", () => {
    const storage = fakeStorage();
    storage.setItem(
      replicaRenderStorageKey("wf1", "n1"),
      JSON.stringify({ renderId: "r", renderPhase: "completed" }),
    );
    expect(readReplicaRender("wf1", "n1", storage)).toBeNull();
    storage.setItem(replicaRenderStorageKey("wf1", "n1"), "not json{");
    expect(readReplicaRender("wf1", "n1", storage)).toBeNull();
  });

  it("clears and is disposable on a throwing storage", () => {
    const storage = fakeStorage();
    writeReplicaRender("wf1", "n1", { renderId: "r", renderPhase: "polling" }, storage);
    clearReplicaRender("wf1", "n1", storage);
    expect(readReplicaRender("wf1", "n1", storage)).toBeNull();
    const broken = {
      setItem: () => {
        throw new Error("x");
      },
      removeItem: () => {
        throw new Error("y");
      },
    };
    expect(() =>
      writeReplicaRender("wf1", "n1", { renderId: "r", renderPhase: "polling" }, broken),
    ).not.toThrow();
    expect(() => clearReplicaRender("wf1", "n1", broken)).not.toThrow();
  });
});
