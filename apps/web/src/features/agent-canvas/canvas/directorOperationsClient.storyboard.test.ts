import { afterEach, describe, expect, it, vi } from "vitest";

import {
  exportStoryboard,
  fetchContinuitySuggestions,
} from "./directorOperationsClient.ts";
import type { SceneScriptRoot } from "../../../types/scene-script";

function scene(): SceneScriptRoot {
  return {
    scene: { name: "lab", environment: "indoor", duration: 4, frame_rate: 30 },
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
    shots: [{ id: "s1", camera: "cam1", start_frame: 0, end_frame: 60 }],
    speech_bindings: [],
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("exportStoryboard client", () => {
  it("POSTs to /scene-3d/storyboard and returns the shot list", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      expect(url).toBe("/api/v1/scene-3d/storyboard");
      expect(init?.method).toBe("POST");
      const body = JSON.parse(String(init?.body)) as { scene_script: SceneScriptRoot };
      expect(body.scene_script.scene.name).toBe("lab");
      return new Response(
        JSON.stringify({
          success: true,
          scene_name: "lab",
          total_shots: 1,
          shots: [
            {
              shot_id: "s1",
              camera_id: "cam1",
              shot_type: "wide",
              start_frame: 0,
              end_frame: 60,
              duration_frames: 60,
              description: "",
              transition_intent: null,
              keyframe_frames: [0, 15, 30, 45, 59],
            },
          ],
          all_keyframe_frames: [0, 15, 30, 45, 59],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await exportStoryboard(scene());
    expect(result.ok).toBe(true);
    expect(result.shots?.length).toBe(1);
    expect(result.shots?.[0].shot_id).toBe("s1");
    expect(result.allKeyframeFrames).toHaveLength(5);
  });

  it("reports a failure when the backend rejects", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ success: false, error: "camera missing", error_code: "storyboard_expansion_failed" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await exportStoryboard(scene());
    expect(result.ok).toBe(false);
    expect(result.errorCode).toBe("storyboard_expansion_failed");
  });
});

describe("fetchContinuitySuggestions client", () => {
  it("POSTs to /scene-3d/continuity-suggestions and returns suggestions", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      expect(url).toBe("/api/v1/scene-3d/continuity-suggestions");
      const body = JSON.parse(String(init?.body)) as { segments: unknown[] | null };
      expect(body.segments).toBeNull();
      return new Response(
        JSON.stringify({
          success: true,
          suggestions: [
            {
              kind: "question",
              source_code: "facing_flip",
              detail: "角色 char_a 转身反了",
              message: "转身方向跨镜反了，是故意的吗？",
              subjects: ["char_a", "s1→s2"],
              remedy: "补一个转身关键帧",
            },
          ],
          untranslated: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchContinuitySuggestions(scene(), null);
    expect(result.ok).toBe(true);
    expect(result.suggestions?.length).toBe(1);
    expect(result.suggestions?.[0].source_code).toBe("facing_flip");
    expect(result.untranslated).toHaveLength(0);
  });

  it("returns untranslated entries for unknown codes", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          success: true,
          suggestions: [],
          untranslated: [{ code: "teleport_gap", detail: "teleport" }],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchContinuitySuggestions(scene(), null);
    expect(result.ok).toBe(true);
    expect(result.untranslated?.length).toBe(1);
    expect(result.untranslated?.[0].code).toBe("teleport_gap");
  });
});
