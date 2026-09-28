import { describe, expect, it } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script";
import { expandDirectorMotionIntent, listDirectorMotionPresetIds } from "./directorMotion.ts";

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

describe("director motion intents", () => {
  it("expands character presets when no explicit target is given", () => {
    const result = expandDirectorMotionIntent(scene(), {
      intent: "character_motion",
      targetId: "char_a",
      presetId: "walk_to",
      startFrame: 0,
      durationFrames: 30,
    });

    expect(result.operations.length).toBeGreaterThan(1);
    for (const operation of result.operations) {
      expect(operation.op).toBe("add_keyframe");
      expect(operation.kind).toBe("character");
      expect(operation.id).toBe("char_a");
    }
    expect(result.previewScript.characters[0].keyframes.length).toBeGreaterThan(1);
  });

  it("expands camera presets into backend-compatible add_keyframe ops", () => {
    const result = expandDirectorMotionIntent(scene(), {
      intent: "camera_motion",
      targetId: "cam1",
      presetId: "push_in",
      startFrame: 0,
      durationFrames: 30,
    });

    expect(result.operations.length).toBeGreaterThan(1);
    for (const operation of result.operations) {
      expect(operation.op).toBe("add_keyframe");
      expect(operation.kind).toBe("camera");
      expect(operation.id).toBe("cam1");
    }
    expect(result.previewScript.cameras[0].keyframes.length).toBeGreaterThan(1);
  });

  it("expands character presets into backend-compatible add_keyframe ops", () => {
    const result = expandDirectorMotionIntent(scene(), {
      intent: "character_motion",
      targetId: "char_a",
      presetId: "walk_to",
      startFrame: 30,
      durationFrames: 60,
      targetPosition: [6, 0, 0],
    });

    expect(result.operations.length).toBeGreaterThan(1);
    for (const operation of result.operations) {
      expect(operation.op).toBe("add_keyframe");
      expect(operation.kind).toBe("character");
      expect(operation.id).toBe("char_a");
    }
    expect(result.previewScript.characters[0].keyframes.at(-1)?.position).toEqual([6, 0, 0]);
  });

  it("exposes the preset vocabulary for both intents", () => {
    expect(listDirectorMotionPresetIds("camera_motion")).toEqual(
      ["push_in", "pull_out", "orbit_left", "orbit_right", "pan_left", "pan_right", "crane_up", "crane_down"],
    );
    expect(listDirectorMotionPresetIds("character_motion")).toEqual([
      "walk_to",
      "turn_to",
      "approach",
      "mark_talk",
    ]);
  });
});
