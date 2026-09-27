import { describe, expect, it } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script";
import {
  applyTransitionOperations,
  type TransitionProposalPayload,
} from "./transitionProposals";

function script(): SceneScriptRoot {
  return {
    scene: { name: "lab", environment: "indoor", lighting: "cool", duration: 8, frame_rate: 30 },
    characters: [
      {
        id: "lin",
        type: "lowpoly_human",
        appearance: { color: "#E74C3C" },
        keyframes: [{ frame: 0, position: [0, 0, 0], rotation_y: 0, action: "stand" }],
      },
    ],
    props: [],
    environment: [],
    cameras: [
      { id: "cam1", shot_type: "wide", keyframes: [{ frame: 0, position: [5, -6, 2.6], look_at: [0, 0, 1.2] }] },
    ],
    shots: [
      { id: "s1", camera: "cam1", start_frame: 0, end_frame: 89, description: "" },
      { id: "s2", camera: "cam1", start_frame: 90, end_frame: 179, description: "" },
    ],
    speech_bindings: [],
  };
}

const continuousMotion: TransitionProposalPayload = {
  id: "continuous_motion",
  label: "连续运动",
  narrative: "人物穿过空间，摄影机跟随。",
  feasible: true,
  operations: [
    {
      kind: "character_preset",
      rationale: "走向下一镜主体",
      preset_id: "walk_to",
      character_id: "lin",
      start_frame: 0,
      duration_frames: 45,
    },
    {
      kind: "camera_preset",
      rationale: "环绕跟拍",
      preset_id: "orbit_right",
      camera_id: "cam1",
      start_frame: 0,
      duration_frames: 45,
    },
  ],
};

describe("applyTransitionOperations", () => {
  it("replays presets through the SAME libraries the inspector uses", () => {
    const result = applyTransitionOperations(script(), continuousMotion, 30);

    expect(result.applied).toBe(2);
    expect(result.errors).toEqual([]);
    expect(result.deferred).toEqual([]);
    // The character walked: keyframes at 0/15/30/45 with walk then stand.
    const keys = result.sceneScript.characters[0].keyframes;
    expect(keys[keys.length - 1].action).toBe("stand");
    // The camera orbited: sampled keyframes exist around the look-at axis.
    expect(result.sceneScript.cameras[0].keyframes.length).toBeGreaterThan(1);
  });

  it("moves a shot boundary for the cut operation", () => {
    const proposal: TransitionProposalPayload = {
      id: "time_jump",
      label: "时间/空间跳跃",
      narrative: "切在停顿里。",
      feasible: true,
      operations: [
        { kind: "cut", rationale: "移到停顿", at_seconds: 3, shot_id: "s2" },
      ],
    };

    const result = applyTransitionOperations(script(), proposal, 30);

    expect(result.applied).toBe(1);
    expect(result.sceneScript.shots[1].start_frame).toBe(90); // 3s * 30fps
  });

  it("refuses a cut that would swallow the neighbouring shot", () => {
    const proposal: TransitionProposalPayload = {
      id: "time_jump",
      label: "时间/空间跳跃",
      narrative: "切在停顿里。",
      feasible: true,
      operations: [
        // 6s would land past shot 3 (there is none) but past shot 2's range:
        // the boundary must stay inside the (s1, s2) span.
        { kind: "cut", rationale: "越界", at_seconds: 6.5, shot_id: "s2" },
      ],
    };

    const result = applyTransitionOperations(script(), proposal, 30);

    expect(result.applied).toBe(0);
    // The refusal is reported, not silent, and nothing was applied.
    expect(result.errors).toEqual(["剪切点会吃掉该镜头自身"]);
    expect(result.deferred).toEqual([]);
  });

  it("defers viewport placement instead of inventing a camera pose", () => {
    const proposal: TransitionProposalPayload = {
      id: "angle_switch",
      label: "视角切换",
      narrative: "新机位。",
      feasible: true,
      operations: [
        { kind: "camera_place", rationale: "放置新机位", camera_id: "cam1", start_frame: 90 },
      ],
    };

    const result = applyTransitionOperations(script(), proposal, 30);

    expect(result.applied).toBe(0);
    expect(result.deferred).toHaveLength(1);
    expect(result.deferred[0].reason).toContain("两次点击");
  });

  it("reports a failing op and still applies the rest (partial, never silent)", () => {
    const proposal: TransitionProposalPayload = {
      id: "mixed",
      label: "混合",
      narrative: "一步坏，一步好。",
      feasible: true,
      operations: [
        // No preset_id: cannot execute.
        { kind: "camera_preset", rationale: "坏", camera_id: "cam1" },
        ...continuousMotion.operations,
      ],
    };

    const result = applyTransitionOperations(script(), proposal, 30);

    expect(result.applied).toBe(2); // the two good ones still landed
    expect(result.deferred).toHaveLength(1); // the bad one is accounted for
  });
});
