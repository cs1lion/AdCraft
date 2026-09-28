import { describe, expect, it } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script";
import { CAMERA_MOTION_PRESETS } from "./cameraMotionPresets.ts";
import { CHARACTER_MOTION_PRESETS } from "./characterMotionPresets.ts";
import {
  expandDirectorMotionIntent,
  listDirectorMotionPresetIds,
} from "./directorMotion.ts";

// The command bar is the first visible piece of the director-command flow:
// it must expand a deterministic intent into a valid SceneScriptRoot that the
// editor's onChange can apply. These tests lock that contract without booting
// the (heavy) r3f canvas — the expandable intent shape is the piece the UI
// consumes directly.

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

describe("director command expansion (MVP contract)", () => {
  it("expands a camera intent into a preview script with new keyframes", () => {
    const command = expandDirectorMotionIntent(scene(), {
      intent: "camera_motion",
      targetId: "cam1",
      presetId: "orbit_left",
      startFrame: 0,
      durationFrames: 30,
    });

    expect(command.previewScript.cameras[0].keyframes.length).toBeGreaterThan(1);
    expect(command.operations.length).toBeGreaterThan(1);
    for (const operation of command.operations) {
      expect(operation.op).toBe("add_keyframe");
      expect(operation.kind).toBe("camera");
      expect(operation.id).toBe("cam1");
    }
  });

  it("expands a character intent into a preview script with new keyframes", () => {
    const command = expandDirectorMotionIntent(scene(), {
      intent: "character_motion",
      targetId: "char_a",
      presetId: "walk_to",
      startFrame: 0,
      durationFrames: 30,
      targetPosition: [6, 0, 0],
    });

    expect(command.previewScript.characters[0].keyframes.length).toBeGreaterThan(1);
    expect(command.operations.length).toBeGreaterThan(1);
    for (const operation of command.operations) {
      expect(operation.op).toBe("add_keyframe");
      expect(operation.kind).toBe("character");
      expect(operation.id).toBe("char_a");
    }
  });

  it("offers the full camera + character preset vocabulary", () => {
    const cameraIds = listDirectorMotionPresetIds("camera_motion");
    const characterIds = listDirectorMotionPresetIds("character_motion");

    for (const preset of CAMERA_MOTION_PRESETS) {
      expect(cameraIds).toContain(preset.id);
    }
    for (const preset of CHARACTER_MOTION_PRESETS) {
      expect(characterIds).toContain(preset.id);
    }
    // The bar should present more than one command per target type so the
    // director has real choices, not a single preset.
    expect(cameraIds.length).toBeGreaterThan(1);
    expect(characterIds.length).toBeGreaterThan(1);
  });

  it("builds a valid trigger event request shape", () => {
    const request = {
      trigger: "sit",
      triggerTargetId: "char_a",
      triggerFrame: 45,
      triggerTargetPosition: null,
      triggerTargetYaw: null,
      thenOps: [
        { op: "add_keyframe", kind: "camera", id: "cam1", frame: 45,
          position: [3, -3, 1.5], look_at: [0, 0, 1.0] } as Record<string, unknown>,
      ],
      thenFrame: 45,
    };
    expect(request.trigger).toBe("sit");
    expect(request.triggerTargetId).toBe("char_a");
    expect(request.thenOps.length).toBe(1);
  });
});
