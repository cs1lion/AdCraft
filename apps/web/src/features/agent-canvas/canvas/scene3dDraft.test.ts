import { describe, expect, it } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script";
import {
  clearScene3dDraft,
  readScene3dDraft,
  scene3dDraftStorageKey,
  writeScene3dDraft,
} from "./scene3dDraft.ts";

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

function script(name: string): SceneScriptRoot {
  return {
    scene: { name, environment: "indoor", lighting: "cool", duration: 6, frame_rate: 30 },
    characters: [],
    props: [],
    environment: [],
    cameras: [
      {
        id: "cam1",
        shot_type: "wide",
        keyframes: [{ frame: 0, position: [1, 1, 1], look_at: [0, 0, 0] }],
      },
    ],
    shots: [{ id: "shot1", camera: "cam1", start_frame: 0, end_frame: 179, description: "wide" }],
    speech_bindings: [],
  };
}

describe("scene3dDraft (D6)", () => {
  it("round-trips a draft under a per-node namespaced key", () => {
    const storage = fakeStorage();
    expect(readScene3dDraft("wf1", "n1", storage)).toBeNull();

    writeScene3dDraft("wf1", "n1", script("draft"), storage);
    expect(storage.getItem(scene3dDraftStorageKey("wf1", "n1"))).toBeTruthy();
    expect(readScene3dDraft("wf1", "n1", storage)?.scene.name).toBe("draft");
    // Different node → different slot (no cross-node bleed).
    expect(readScene3dDraft("wf1", "n2", storage)).toBeNull();
  });

  it("returns null (never throws) on corrupt or foreign content", () => {
    const storage = fakeStorage();
    storage.setItem(scene3dDraftStorageKey("wf1", "n1"), "not json{");
    expect(readScene3dDraft("wf1", "n1", storage)).toBeNull();
    storage.setItem(scene3dDraftStorageKey("wf1", "n1"), JSON.stringify({ foo: 1 }));
    expect(readScene3dDraft("wf1", "n1", storage)).toBeNull();
  });

  it("clears the draft slot", () => {
    const storage = fakeStorage();
    writeScene3dDraft("wf1", "n1", script("draft"), storage);
    clearScene3dDraft("wf1", "n1", storage);
    expect(readScene3dDraft("wf1", "n1", storage)).toBeNull();
  });

  it("write/clear are disposable — a throwing storage never propagates", () => {
    const storage = {
      setItem: () => {
        throw new Error("quota");
      },
      removeItem: () => {
        throw new Error("nope");
      },
    };
    expect(() => writeScene3dDraft("wf1", "n1", script("d"), storage)).not.toThrow();
    expect(() => clearScene3dDraft("wf1", "n1", storage)).not.toThrow();
  });
});
