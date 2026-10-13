import { describe, expect, it } from "vitest";
import type { CharacterKeyframe } from "../../../types/scene-script";
import { authoredPoseAtFrame, segmentPoseAt } from "./characterPose";

type Point = Pick<CharacterKeyframe, "frame" | "pose">;

describe("authored joint tracks", () => {
  it("leaves every legacy action unchanged when no explicit pose is authored", () => {
    const frames: Point[] = [{ frame: 0 }, { frame: 300, pose: null }];
    for (const action of ["stand", "walk", "talk", "gesture", "sit"]) {
      const actionPose = segmentPoseAt(action, 0.125);
      for (const frame of [0, 90, 150, 299]) {
        expect({ ...actionPose, ...authoredPoseAtFrame(frames, frame) }).toEqual(actionPose);
      }
    }
  });

  it("keeps the preparation on its action until each joint's first explicit point", () => {
    const frames: Point[] = [
      { frame: 0 },
      { frame: 60, pose: { head_yaw: 0.6 } },
      { frame: 90, pose: { arm_l: 1.2 } },
    ];
    expect(authoredPoseAtFrame(frames, 59.5)).toEqual({});
    expect(authoredPoseAtFrame(frames, 89.5)).toEqual({ headYaw: 0.6 });
    expect(authoredPoseAtFrame(frames, 90)).toEqual({ headYaw: 0.6, armL: 1.2 });
  });

  it("reaches a hand's authored midpoint across unrelated sparse keyframes", () => {
    // The head key at 120 must not interrupt the hand reaching 0.9 radians at
    // logical frame 105, one quarter of the 90→150 reach, including subframes.
    const frames: Point[] = [
      { frame: 150, pose: { arm_r: 1.8 } },
      { frame: 90, pose: { arm_r: 0.6 } },
      { frame: 120, pose: { head: 0.2, arm_r: null } },
    ];
    expect(authoredPoseAtFrame(frames, 105).armR).toBeCloseTo(0.9, 12);
    expect(authoredPoseAtFrame(frames, 120).armR).toBeCloseTo(1.2, 12);
    expect(authoredPoseAtFrame(frames, 120.5).armR).toBeCloseTo(1.21, 12);
    expect(authoredPoseAtFrame(frames, 119).head).toBeUndefined();
    expect(frames.map((key) => key.frame)).toEqual([150, 90, 120]);
  });

  it("retains zero resets and holds them until another explicit point", () => {
    const frames: Point[] = [
      { frame: 0, pose: { arm_l_side: -0.8, knee_l: 0.4, head_yaw: 0.6 } },
      { frame: 60, pose: { arm_l_side: 0, knee_l: 0, head_yaw: 0 } },
      { frame: 90, pose: { head: 0.2 } },
    ];
    expect(authoredPoseAtFrame(frames, 30)).toEqual({ armLSide: -0.4, kneeL: 0.2, headYaw: 0.3 });
    expect(authoredPoseAtFrame(frames, 60)).toEqual({ armLSide: 0, kneeL: 0, headYaw: 0 });
    expect(authoredPoseAtFrame(frames, 299)).toEqual({ armLSide: 0, kneeL: 0, headYaw: 0, head: 0.2 });
  });

  it("restores identical joint state on backward seek and repeated playback", () => {
    const frames: Point[] = [
      { frame: 0, pose: { arm_r_side: 0, leg_l: 0, leg_r: 0, knee_r: 0 } },
      { frame: 120, pose: { arm_r_side: 0.8, leg_l: 0.4, leg_r: -0.4, knee_r: 0.6 } },
      { frame: 240, pose: { arm_r_side: 0, leg_l: 0, leg_r: 0, knee_r: 0 } },
    ];
    const forward = authoredPoseAtFrame(frames, 60);
    expect(forward).toEqual({ armRSide: 0.4, legL: 0.2, legR: -0.2, kneeR: 0.3 });
    for (const frame of [240, 299, 60, 120, 0, 60]) authoredPoseAtFrame(frames, frame);
    expect(authoredPoseAtFrame(frames, 60)).toEqual(forward);
    expect(authoredPoseAtFrame(frames, 0)).toEqual({ armRSide: 0, legL: 0, legR: 0, kneeR: 0 });
  });

  it("overrides only explicitly controlled joints while other limbs keep walking", () => {
    const walk = segmentPoseAt("walk", 0.125);
    const overrides = authoredPoseAtFrame([{ frame: 0, pose: { arm_l: 0, head: 0 } }], 45);
    const combined = { ...walk, ...overrides };
    expect(combined.armL).toBe(0);
    expect(combined.head).toBe(0);
    expect(combined.armR).toBe(walk.armR);
    expect(combined.legL).toBe(walk.legL);
    expect(combined.kneeR).toBe(walk.kneeR);
    expect(combined.bob).toBe(walk.bob);
  });

  it("interpolates authored height compensation and returns to a written zero", () => {
    const frames: Point[] = [
      { frame: 0, pose: { bob: 0 } },
      { frame: 60, pose: { bob: 0.1 } },
      { frame: 120, pose: { bob: 0 } },
    ];
    expect(authoredPoseAtFrame(frames, 30).bob).toBeCloseTo(0.05, 12);
    expect(authoredPoseAtFrame(frames, 90).bob).toBeCloseTo(0.05, 12);
    expect(authoredPoseAtFrame(frames, 299).bob).toBe(0);
  });
});
