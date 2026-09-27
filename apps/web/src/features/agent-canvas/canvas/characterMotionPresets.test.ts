import { describe, expect, it } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script.ts";
import {
  APPROACH_DEFAULT_STOP_DISTANCE,
  CHARACTER_MOTION_PRESETS,
  UnknownCharacterPresetError,
  applyCharacterMotionPreset,
  countSpeakingFramesInWindow,
  isSpeakingAtFrame,
  yawFacing,
} from "./characterMotionPresets.ts";

function scene(): SceneScriptRoot {
  return {
    scene: { name: "lab", environment: "indoor", lighting: "cool", duration: 8, frame_rate: 30 },
    characters: [
      {
        id: "lin",
        type: "lowpoly_human",
        appearance: { color: "#E74C3C" },
        keyframes: [
          { frame: 0, position: [0, 0, 0], rotation_y: 0, action: "stand" },
          { frame: 200, position: [0, 0, 0], rotation_y: 0, action: "stand" },
        ],
      },
      {
        id: "su",
        type: "lowpoly_human",
        appearance: { color: "#3498DB" },
        keyframes: [{ frame: 0, position: [-3, 4, 0], rotation_y: 180, action: "stand" }],
      },
    ],
    props: [],
    environment: [],
    cameras: [{ id: "cam1", shot_type: "wide", keyframes: [{ frame: 0, position: [5, -6, 2.6], look_at: [0, 0, 1] }] }],
    shots: [{ id: "shot1", camera: "cam1", start_frame: 0, end_frame: 239, description: "wide" }],
    speech_bindings: [],
  };
}

function keysOf(script: SceneScriptRoot, characterId = "lin") {
  return script.characters.find((character) => character.id === characterId)!.keyframes;
}

describe("yawFacing", () => {
  it("faces +Y at yaw 0 and +X at yaw 90 (Blender Z-up)", () => {
    expect(yawFacing([0, 0, 0], [0, 5, 0])).toBeCloseTo(0, 6);
    expect(yawFacing([0, 0, 0], [5, 0, 0])).toBeCloseTo(90, 6);
    expect(yawFacing([0, 0, 0], [0, -5, 0])).toBeCloseTo(180, 6);
    expect(yawFacing([0, 0, 0], [-5, 0, 0])).toBeCloseTo(270, 6);
  });

  it("is independent of the character's height", () => {
    expect(yawFacing([0, 0, 1.7], [3, 4, 0])).toBeCloseTo(yawFacing([0, 0, 0], [3, 4, 0]), 9);
  });
});

describe("applyCharacterMotionPreset", () => {
  it("walk_to samples the straight path and lands on stand", () => {
    const next = applyCharacterMotionPreset(scene(), "lin", "walk_to", {
      startFrame: 30,
      durationFrames: 60,
      target: [6, 0, 0],
    });
    const keys = keysOf(next).filter((key) => key.frame >= 30 && key.frame <= 90);

    expect(keys.map((key) => key.frame)).toEqual([30, 45, 60, 75, 90]);
    expect(keys[0].position).toEqual([0, 0, 0]);
    expect(keys[keys.length - 1].position).toEqual([6, 0, 0]);
    // Walking the whole way, standing at the door.
    expect(keys.slice(0, -1).every((key) => key.action === "walk")).toBe(true);
    expect(keys[keys.length - 1].action).toBe("stand");
    // Facing rides along: +X is the direction of travel.
    expect(keys[keys.length - 1].rotation_y).toBeCloseTo(90, 1);
    // Height is preserved (a walk is a floor move).
    expect(keys.every((key) => key.position[2] === 0)).toBe(true);
  });

  it("turn_to takes the short arc and keeps the action", () => {
    const script = scene();
    script.characters[0].keyframes = [
      { frame: 0, position: [1, 1, 0], rotation_y: 350, action: "talk" },
    ];
    const next = applyCharacterMotionPreset(script, "lin", "turn_to", {
      startFrame: 0,
      durationFrames: 30,
      target: [1, 2, 0], // due north: yaw 0
    });
    const keys = keysOf(next);

    // 350 -> 0 is a +10° turn, not a -350° sweep: every key stays in the
    // 345..360 band (wrapping to 0/360), never dipping into the long way.
    expect(keys[0].rotation_y).toBeCloseTo(350, 6);
    expect(keys[keys.length - 1].rotation_y).toBeCloseTo(0, 6);
    for (const key of keys) {
      const yaw = key.rotation_y;
      const onShortArc = yaw > 345 || yaw < 1;
      expect(onShortArc, `yaw ${yaw} left the short arc`).toBe(true);
    }
    // And consecutive keys never jump more than one sample's worth (15°).
    for (let index = 1; index < keys.length; index += 1) {
      const delta = Math.abs(
        ((keys[index].rotation_y - keys[index - 1].rotation_y + 540) % 360) - 180,
      );
      expect(delta).toBeLessThanOrEqual(5); // 10° across 2 steps
    }
    // A turn never clobbers a talk mark.
    expect(keys.every((key) => key.action === "talk")).toBe(true);
  });

  it("approach stops at the stand-off distance and faces the target", () => {
    const next = applyCharacterMotionPreset(scene(), "su", "approach", {
      startFrame: 0,
      durationFrames: 60,
      target: [0, 0, 0],
      stopDistance: APPROACH_DEFAULT_STOP_DISTANCE,
    });
    const keys = keysOf(next, "su");
    const landing = keys[keys.length - 1].position;
    const gap = Math.hypot(landing[0] - 0, landing[1] - 0);

    expect(gap).toBeCloseTo(APPROACH_DEFAULT_STOP_DISTANCE, 3);
    const facingLandingYaw = yawFacing(landing, [0, 0, 0]);
    expect(keys[keys.length - 1].rotation_y).toBeCloseTo(facingLandingYaw, 0);
  });

  it("approach is a no-op move when already inside the stand-off distance", () => {
    const next = applyCharacterMotionPreset(scene(), "lin", "approach", {
      startFrame: 0,
      durationFrames: 30,
      target: [0.5, 0, 0],
      stopDistance: 1.2,
    });
    const keys = keysOf(next).filter((key) => key.frame <= 30);

    expect(keys.every((key) => key.position[0] === 0 && key.position[1] === 0)).toBe(true);
  });

  it("mark_talk marks the frame and clears the window it owns", () => {
    const script = scene();
    script.characters[0].keyframes = [
      { frame: 0, position: [0, 0, 0], rotation_y: 0, action: "stand" },
      { frame: 40, position: [1, 0, 0], rotation_y: 0, action: "walk" },
    ];
    const next = applyCharacterMotionPreset(script, "lin", "mark_talk", {
      startFrame: 0,
      durationFrames: 0,
      target: [0, 0, 0],
    });
    const keys = keysOf(next);

    // The marked frame plus the authored frame-40 key OUTSIDE the window.
    expect(keys).toHaveLength(2);
    expect(keys[0]).toEqual({ frame: 0, position: [0, 0, 0], rotation_y: 0, action: "talk" });
    expect(keys[1].frame).toBe(40);
  });

  it("replaces only its own window (re-apply extends, never stacks)", () => {
    const short = applyCharacterMotionPreset(scene(), "lin", "walk_to", {
      startFrame: 30,
      durationFrames: 30,
      target: [4, 0, 0],
    });
    const longer = applyCharacterMotionPreset(short, "lin", "walk_to", {
      startFrame: 30,
      durationFrames: 90,
      target: [8, 0, 0],
    });

    const keys = keysOf(longer).filter((key) => key.frame >= 30 && key.frame <= 120);
    expect(keys[keys.length - 1].frame).toBe(120);
    expect(keys[keys.length - 1].position).toEqual([8, 0, 0]);
    const frames = keysOf(longer).map((key) => key.frame);
    expect(new Set(frames).size).toBe(frames.length);
  });

  it("leaves authored keys outside the window untouched", () => {
    const withLateKey = scene();
    withLateKey.characters[0].keyframes.push({
      frame: 150,
      position: [9, 9, 9],
      rotation_y: 45,
      action: "sit",
    });

    const next = applyCharacterMotionPreset(withLateKey, "lin", "walk_to", {
      startFrame: 0,
      durationFrames: 60,
      target: [4, 0, 0],
    });

    expect(keysOf(next).find((key) => key.frame === 150)).toEqual({
      frame: 150,
      position: [9, 9, 9],
      rotation_y: 45,
      action: "sit",
    });
  });

  it("leaves other characters alone", () => {
    const next = applyCharacterMotionPreset(scene(), "lin", "walk_to", {
      startFrame: 0,
      durationFrames: 30,
      target: [4, 0, 0],
    });
    expect(keysOf(next, "su")).toEqual(keysOf(scene(), "su"));
  });

  it("fails loud on an unknown preset and a missing character", () => {
    expect(() =>
      applyCharacterMotionPreset(scene(), "lin", "moonwalk" as never, {
        startFrame: 0,
        durationFrames: 30,
        target: [0, 0, 0],
      }),
    ).toThrow(UnknownCharacterPresetError);
    expect(() =>
      applyCharacterMotionPreset(scene(), "ghost", "walk_to", {
        startFrame: 0,
        durationFrames: 30,
        target: [0, 0, 0],
      }),
    ).toThrow(/Character not found/);
  });

  it("ships a labelled preset catalogue for the picker", () => {
    expect(CHARACTER_MOTION_PRESETS.length).toBeGreaterThanOrEqual(4);
    for (const preset of CHARACTER_MOTION_PRESETS) {
      expect(preset.label.length).toBeGreaterThan(0);
      expect(preset.description.length).toBeGreaterThan(0);
      expect(typeof preset.needsTarget).toBe("boolean");
    }
  });

  it("pins the id set the backend LLM-proposal validator accepts", () => {
    // Parity contract with transition_narratives.CHARACTER_MOTION_PRESET_IDS:
    // the LLM may only speak these ids, so this catalogue IS the vocabulary.
    expect(CHARACTER_MOTION_PRESETS.map((preset) => preset.id).sort()).toEqual([
      "approach",
      "mark_talk",
      "turn_to",
      "walk_to",
    ]);
  });
});

// ---------------------------------------------------------------------------
// The locked speech layer (V0.2 §14.13: 锁住 Audio，只重做 Visual)
// ---------------------------------------------------------------------------

/** A character mid-line: lip-sync wrote talk 30–59 (stand resumes at 60). */
function speakingScene(): SceneScriptRoot {
  const script = scene();
  script.characters[0].keyframes = [
    { frame: 0, position: [0, 0, 0], rotation_y: 0, action: "stand" },
    { frame: 30, position: [0, 0, 0], rotation_y: 0, action: "talk" },
    { frame: 59, position: [0, 0, 0], rotation_y: 0, action: "talk" },
    { frame: 60, position: [0, 0, 0], rotation_y: 0, action: "stand" },
    { frame: 200, position: [0, 0, 0], rotation_y: 0, action: "stand" },
  ];
  return script;
}

describe("isSpeakingAtFrame", () => {
  it("reads the speech window with nearest-at-or-before semantics", () => {
    const keys = speakingScene().characters[0].keyframes;
    expect(isSpeakingAtFrame(keys, 15)).toBe(false); // before the line
    expect(isSpeakingAtFrame(keys, 30)).toBe(true);
    expect(isSpeakingAtFrame(keys, 45)).toBe(true); // between the talk keys
    expect(isSpeakingAtFrame(keys, 59)).toBe(true);
    expect(isSpeakingAtFrame(keys, 60)).toBe(false); // stand resumed
    expect(isSpeakingAtFrame(keys, 100)).toBe(false);
  });

  it("treats a character with no keys as silent", () => {
    expect(isSpeakingAtFrame([], 10)).toBe(false);
  });
});

describe("the speech layer is locked against motion redos", () => {
  it("walk_to keeps talk on speaking frames (the body moves, the mouth does not close)", () => {
    const next = applyCharacterMotionPreset(speakingScene(), "lin", "walk_to", {
      startFrame: 30,
      durationFrames: 60,
      target: [6, 0, 0],
    });
    const keys = keysOf(next).filter((key) => key.frame >= 30 && key.frame <= 90);

    // Frames 30–59 are inside the speech window: they still say "talk".
    const speaking = keys.filter((key) => key.frame <= 59);
    expect(speaking.length).toBeGreaterThan(0);
    expect(speaking.every((key) => key.action === "talk")).toBe(true);
    // The walk still HAPPENS on those frames: position follows the path.
    expect(speaking[speaking.length - 1].position[0]).toBeGreaterThan(0);
    // Past the line's end the normal vocabulary resumes.
    expect(keys.find((key) => key.frame === 75)?.action).toBe("walk");
    expect(keys[keys.length - 1].action).toBe("stand");
  });

  it("approach honors the same lock", () => {
    const next = applyCharacterMotionPreset(speakingScene(), "lin", "approach", {
      startFrame: 30,
      durationFrames: 30,
      target: [4, 0, 0],
      stopDistance: 1,
    });
    const keys = keysOf(next).filter((key) => key.frame >= 30 && key.frame <= 60);
    expect(keys.filter((key) => key.frame <= 59).every((key) => key.action === "talk")).toBe(true);
  });

  it("a silent walk is unchanged (the lock costs nothing when nobody speaks)", () => {
    const next = applyCharacterMotionPreset(scene(), "lin", "walk_to", {
      startFrame: 30,
      durationFrames: 60,
      target: [6, 0, 0],
    });
    const keys = keysOf(next).filter((key) => key.frame >= 30 && key.frame <= 90);
    expect(keys.slice(0, -1).every((key) => key.action === "walk")).toBe(true);
    expect(keys[keys.length - 1].action).toBe("stand");
  });

  it("the reported count matches the frames actually preserved", () => {
    const keys = speakingScene().characters[0].keyframes;
    expect(countSpeakingFramesInWindow(keys, 30, 60)).toBe(
      // Sampled every 15 frames: 30, 45, 60 are inside the window; 30 and 45
      // are inside the speech window (59 is the last talking frame, 60 stands).
      2,
    );
    expect(countSpeakingFramesInWindow(keys, 0, 29)).toBe(0);
  });
});
