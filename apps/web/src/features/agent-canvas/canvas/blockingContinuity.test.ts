import { describe, expect, it } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script";
import {
  FACING_FLIP_THRESHOLD_DEGREES,
  checkBlockingContinuity,
  yawDeltaDegrees,
} from "./blockingContinuity";

function script(characters: SceneScriptRoot["characters"], shots: SceneScriptRoot["shots"]): SceneScriptRoot {
  return {
    scene: { name: "lab", environment: "indoor", lighting: "cool", duration: 8, frame_rate: 30 },
    characters,
    props: [],
    environment: [],
    cameras: [{ id: "cam1", shot_type: "wide", keyframes: [{ frame: 0, position: [5, -6, 2.6], look_at: [0, 0, 1] }] }],
    shots,
    speech_bindings: [],
  };
}

const twoShots: SceneScriptRoot["shots"] = [
  { id: "s1", camera: "cam1", start_frame: 0, end_frame: 89, description: "" },
  { id: "s2", camera: "cam1", start_frame: 90, end_frame: 179, description: "" },
];

function character(keyframes: { frame: number; position: [number, number, number]; rotation_y: number }[]) {
  return {
    id: "lin",
    type: "lowpoly_human" as const,
    appearance: { color: "#E74C3C" },
    keyframes: keyframes.map((keyframe) => ({ ...keyframe, action: "stand" as const })),
  };
}

describe("yawDeltaDegrees", () => {
  it("takes the short way around the circle", () => {
    expect(yawDeltaDegrees(350, 10)).toBe(20);
    expect(yawDeltaDegrees(10, 350)).toBe(20);
    expect(yawDeltaDegrees(0, 90)).toBe(90);
    expect(yawDeltaDegrees(0, 180)).toBe(180);
    expect(yawDeltaDegrees(0, 270)).toBe(90);
  });
});

describe("checkBlockingContinuity", () => {
  it("stays silent when the pose carries across the cut", () => {
    const issues = checkBlockingContinuity(
      script(
        [character([
          { frame: 0, position: [0, 0, 0], rotation_y: 90 },
          { frame: 180, position: [0, 0, 0], rotation_y: 90 },
        ])],
        twoShots,
      ),
    );

    expect(issues).toEqual([]);
  });

  it("flags a facing flip across the boundary (V0.2's exact failure)", () => {
    // The B-side pose is authored as its own keyframe AT the cut with no turn
    // between: the 180° change happens in one frame.
    const issues = checkBlockingContinuity(
      script(
        [character([
          { frame: 0, position: [0, 0, 0], rotation_y: 0 },
          { frame: 89, position: [0, 0, 0], rotation_y: 0 },   // faces +Y through shot A
          { frame: 90, position: [0, 0, 0], rotation_y: 180 }, // faces -Y in shot B
        ])],
        twoShots,
      ),
    );

    expect(issues).toHaveLength(1);
    expect(issues[0].code).toBe("facing_flip");
    expect(issues[0].subject).toBe("lin");
    expect(issues[0].boundary).toBe("s1→s2");
    expect(issues[0].message).toContain("两个镜头之间没有转身");
    expect(issues[0].remedy).toContain("转身面向");
    expect(issues[0].severity).toBe("warning"); // advisory, never blocking
  });

  it("flags a position jump farther than the character could walk", () => {
    // The shots are contiguous (no gap), so anything beyond ~0.35m is a jump.
    const issues = checkBlockingContinuity(
      script(
        [character([
          { frame: 0, position: [0, 0, 0], rotation_y: 90 },
          { frame: 89, position: [0, 0, 0], rotation_y: 90 },
          { frame: 90, position: [6, 0, 0], rotation_y: 90 },
        ])],
        twoShots,
      ),
    );

    const jump = issues.find((issue) => issue.code === "position_jump");
    expect(jump).toBeTruthy();
    expect(jump?.message).toContain("6m");
    expect(jump?.remedy).toContain("走到");
  });

  it("accepts a walk that fits the gap between shots", () => {
    // Shot A ends at frame 89, shot B starts at frame 150: a 2s gap allows
    // ~2.4m of travel, so 1.5m is legitimate blocking.
    const issues = checkBlockingContinuity(
      script(
        [character([
          { frame: 0, position: [0, 0, 0], rotation_y: 90 },
          { frame: 150, position: [1.5, 0, 0], rotation_y: 90 },
        ])],
        [
          { id: "s1", camera: "cam1", start_frame: 0, end_frame: 89, description: "" },
          { id: "s2", camera: "cam1", start_frame: 150, end_frame: 239, description: "" },
        ],
      ),
    );

    expect(issues).toEqual([]);
  });

  it("ignores characters without keyframes and single-shot scenes", () => {
    const empty = {
      id: "ghost",
      type: "lowpoly_human" as const,
      appearance: { color: "#333" },
      keyframes: [],
    };
    expect(checkBlockingContinuity(script([empty], twoShots))).toEqual([]);
    expect(checkBlockingContinuity(script([character([{ frame: 0, position: [0, 0, 0], rotation_y: 0 }])], [twoShots[0]]))).toEqual([]);
  });

  it("exposes its threshold for the doc and the tests", () => {
    expect(FACING_FLIP_THRESHOLD_DEGREES).toBeGreaterThan(0);
  });
});
