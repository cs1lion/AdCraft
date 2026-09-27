import { describe, expect, it } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script.ts";
import {
  CAMERA_MOTION_PRESETS,
  CAMERA_MOTION_SAMPLE_STEP_FRAMES,
  UnknownCameraPresetError,
  applyCameraMotionPreset,
} from "./cameraMotionPresets.ts";

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
        // 5m right, 6m back, 2.6m up, looking at the subject's chest.
        keyframes: [{ frame: 0, position: [5, -6, 2.6], look_at: [0, 0, 1.2] }],
      },
      { id: "cam2", shot_type: "close", keyframes: [{ frame: 0, position: [0, 0, 2], look_at: [0, 0, 1] }] },
    ],
    shots: [{ id: "shot1", camera: "cam1", start_frame: 0, end_frame: 179, description: "wide" }],
    speech_bindings: [],
  };
}

function cameraOf(script: SceneScriptRoot, cameraId = "cam1") {
  return script.cameras.find((camera) => camera.id === cameraId)!;
}

describe("applyCameraMotionPreset", () => {
  it("push_in closes the distance to the look-at point", () => {
    const before = cameraOf(scene());
    const beforeRadius = Math.hypot(
      before.keyframes[0].position[0] - before.keyframes[0].look_at![0],
      before.keyframes[0].position[1] - before.keyframes[0].look_at![1],
      before.keyframes[0].position[2] - before.keyframes[0].look_at![2],
    );

    const next = applyCameraMotionPreset(scene(), "cam1", "push_in", {
      startFrame: 0,
      durationFrames: 30,
    });
    const keys = cameraOf(next).keyframes;
    const last = keys[keys.length - 1];
    const afterRadius = Math.hypot(
      last.position[0] - last.look_at![0],
      last.position[1] - last.look_at![1],
      last.position[2] - last.look_at![2],
    );

    expect(afterRadius).toBeCloseTo(beforeRadius * 0.5, 5);
    // The look-at point is the anchor of a push: the subject stays framed.
    expect(last.look_at).toEqual([0, 0, 1.2]);
  });

  it("orbit samples the arc (chords would cut the circle)", () => {
    const next = applyCameraMotionPreset(scene(), "cam1", "orbit_left", {
      startFrame: 0,
      durationFrames: 90,
    });
    const keys = cameraOf(next).keyframes;

    // 90 frames at a 15-frame step = 7 samples including both ends.
    expect(keys.length).toBe(7);
    // Every sample sits on the sphere around the look-at point: the orbit
    // turns the horizontal plane but keeps the camera's height, so the 3D
    // radius (including the 1.4m height offset) is the invariant.
    const radii = keys.map((key) =>
      Math.hypot(
        key.position[0] - 0,
        key.position[1] - 0,
        key.position[2] - 1.2,
      ),
    );
    for (const radius of radii) {
      expect(radius).toBeCloseTo(Math.hypot(5, 6, 2.6 - 1.2), 4);
    }
    // And the samples actually rotate (not a degenerate stop-motion).
    const first = keys[0].position;
    const middle = keys[3].position;
    expect(Math.hypot(first[0] - middle[0], first[1] - middle[1])).toBeGreaterThan(1);
  });

  it("pan moves the gaze and keeps the camera still", () => {
    const next = applyCameraMotionPreset(scene(), "cam1", "pan_left", {
      startFrame: 10,
      durationFrames: 30,
    });
    const keys = cameraOf(next).keyframes;
    const start = keys.find((key) => key.frame === 10)!;
    const end = keys[keys.length - 1];

    expect(start.position).toEqual([5, -6, 2.6]);
    expect(end.position).toEqual([5, -6, 2.6]);
    expect(end.look_at).not.toEqual(start.look_at);
  });

  it("crane raises the camera and tilts the gaze by half", () => {
    const next = applyCameraMotionPreset(scene(), "cam1", "crane_up", {
      startFrame: 0,
      durationFrames: 30,
    });
    const keys = cameraOf(next).keyframes;
    const end = keys[keys.length - 1];

    expect(end.position[2]).toBeCloseTo(2.6 + 1.2, 5);
    expect(end.look_at![2]).toBeCloseTo(1.2 + 0.6, 5);
  });

  it("replaces only its own window (re-apply extends, never stacks)", () => {
    const short = applyCameraMotionPreset(scene(), "cam1", "orbit_right", {
      startFrame: 0,
      durationFrames: 30,
    });
    const longer = applyCameraMotionPreset(short, "cam1", "orbit_right", {
      startFrame: 0,
      durationFrames: 90,
    });

    const keys = cameraOf(longer).keyframes;
    expect(keys[keys.length - 1].frame).toBe(90);
    // No duplicated frames (a stacked preset would collide at 30).
    const frames = keys.map((key) => key.frame);
    expect(new Set(frames).size).toBe(frames.length);
  });

  it("leaves keyframes outside the window untouched", () => {
    const withLateKey = scene();
    withLateKey.cameras[0].keyframes.push({ frame: 150, position: [1, 1, 3], look_at: [0, 0, 1] });

    const next = applyCameraMotionPreset(withLateKey, "cam1", "push_in", {
      startFrame: 0,
      durationFrames: 30,
    });
    const keys = cameraOf(next).keyframes;

    expect(keys.find((key) => key.frame === 150)).toEqual({
      frame: 150,
      position: [1, 1, 3],
      look_at: [0, 0, 1],
    });
  });

  it("leaves the other cameras alone", () => {
    const next = applyCameraMotionPreset(scene(), "cam1", "push_in", {
      startFrame: 0,
      durationFrames: 30,
    });
    expect(cameraOf(next, "cam2").keyframes).toEqual(cameraOf(scene(), "cam2").keyframes);
  });

  it("fails loud on an unknown preset and a missing camera", () => {
    expect(() =>
      applyCameraMotionPreset(scene(), "cam1", "dolly_zoom" as never, {
        startFrame: 0,
        durationFrames: 30,
      }),
    ).toThrow(UnknownCameraPresetError);
    expect(() =>
      applyCameraMotionPreset(scene(), "cam_missing", "push_in", {
        startFrame: 0,
        durationFrames: 30,
      }),
    ).toThrow(/Camera not found/);
  });

  it("ships a labelled preset catalogue for the picker", () => {
    expect(CAMERA_MOTION_PRESETS.length).toBeGreaterThanOrEqual(8);
    for (const preset of CAMERA_MOTION_PRESETS) {
      expect(preset.label.length).toBeGreaterThan(0);
      expect(preset.description.length).toBeGreaterThan(0);
    }
    expect(CAMERA_MOTION_SAMPLE_STEP_FRAMES).toBeGreaterThan(0);
  });

  it("pins the id set the backend LLM-proposal validator accepts", () => {
    // Parity contract with transition_narratives.CAMERA_MOTION_PRESET_IDS:
    // the LLM may only speak these ids, so this catalogue IS the vocabulary.
    // Adding a preset here without the backend set makes this fail.
    expect(CAMERA_MOTION_PRESETS.map((preset) => preset.id).sort()).toEqual([
      "crane_down",
      "crane_up",
      "orbit_left",
      "orbit_right",
      "pan_left",
      "pan_right",
      "pull_out",
      "push_in",
    ]);
  });
});
