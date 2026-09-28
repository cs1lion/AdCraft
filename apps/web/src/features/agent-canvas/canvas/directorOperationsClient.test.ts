import { afterEach, describe, expect, it, vi } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script";
import { applyDirectorMotion } from "./directorOperationsClient.ts";

function scene(): SceneScriptRoot {
  return {
    scene: { name: "lab", environment: "indoor", lighting: "cool", duration: 6, frame_rate: 30 },
    characters: [
      {
        id: "char_a",
        type: "lowpoly_human",
        appearance: { color: "#E74C3C" },
        keyframes: [{ frame: 0, position: [0, 0, 0], rotation_y: 0, action: "stand" }],
      },
    ],
    props: [],
    environment: [],
    cameras: [
      {
        id: "cam1",
        shot_type: "wide",
        keyframes: [{ frame: 0, position: [5, -6, 2.6], look_at: [0, 0, 1.2] }],
      },
    ],
    shots: [{ id: "shot1", camera: "cam1", start_frame: 0, end_frame: 179, description: "wide" }],
    speech_bindings: [],
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});


describe("director motion gate client", () => {
  it("POSTs the intent and adopts the applied scene script", async () => {
    const appliedScript = { ...scene(), scene: { ...scene().scene, name: "lab-gated" } };
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      expect(url).toBe("/api/v1/scene-3d/director-motion");
      expect(init?.method).toBe("POST");
      const body = JSON.parse(String(init?.body)) as { intent: string; target_id: string; preset_id: string };
      expect(body.intent).toBe("camera_motion");
      expect(body.target_id).toBe("cam1");
      expect(body.preset_id).toBe("push_in");
      return new Response(
        JSON.stringify({ success: true, applied_scene_script: appliedScript, operations: [{ op: "add_keyframe" }] }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await applyDirectorMotion(scene(), {
      intent: "camera_motion",
      target_id: "cam1",
      preset_id: "push_in",
      start_frame: 0,
      duration_frames: 30,
    });

    expect(result.ok).toBe(true);
    expect(result.appliedSceneScript?.scene.name).toBe("lab-gated");
    expect(result.operations?.length).toBe(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("surfaces the gate's rejection when the preset is unknown", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          detail: { error: "unknown camera preset xyz", error_code: "director_motion_preset_unknown" },
        }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await applyDirectorMotion(scene(), {
      intent: "camera_motion",
      target_id: "cam1",
      preset_id: "xyz",
      start_frame: 0,
      duration_frames: 15,
    });

    expect(result.ok).toBe(false);
    expect(result.errorCode).toBe("director_motion_preset_unknown");
  });
});
