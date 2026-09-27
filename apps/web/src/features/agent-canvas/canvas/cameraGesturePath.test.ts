import { describe, expect, it } from "vitest";

import { GESTURE_LOOK_AHEAD_METERS, keyframesFromGesturePath } from "./cameraGesturePath";

const OPTIONS = {
  startFrame: 0,
  durationFrames: 30,
  anchorHeight: 2.6,
  frameRate: 30,
};

function positionsOf(keyframes: { position: [number, number, number] }[]) {
  return keyframes.map((keyframe) => keyframe.position);
}

describe("keyframesFromGesturePath", () => {
  it("turns a drawn line into constant-speed keyframes at a fixed step", () => {
    // A 4m line drawn over 30 frames: samples every 15 frames plus the end.
    const result = keyframesFromGesturePath(
      [
        [0, 0, 0],
        [4, 0, 0],
      ],
      OPTIONS,
    );

    expect(result.lengthMeters).toBeCloseTo(4, 6);
    const positions = positionsOf(result.keyframes);
    expect(positions).toEqual([
      [0, 0, 2.6],
      [2, 0, 2.6],
      [4, 0, 2.6],
    ]);
    // Equal arc length between samples => constant speed.
    const gaps = positions.slice(1).map((point, index) => point[0] - positions[index][0]);
    expect(new Set(gaps).size).toBe(1);
  });

  it("looks ahead along the path so the rig faces where it is going", () => {
    const result = keyframesFromGesturePath(
      [
        [0, 0, 0],
        [10, 0, 0],
      ],
      { ...OPTIONS, durationFrames: 15 },
    );

    for (const keyframe of result.keyframes) {
      // Moving along +X: the gaze sits further along +X than the camera.
      expect(keyframe.look_at![0]).toBeGreaterThan(keyframe.position[0]);
      // And the gaze dips toward the ground (never the horizon).
      expect(keyframe.look_at![2]).toBeLessThan(keyframe.position[2]);
    }
    expect(result.keyframes[0].look_at![0] - result.keyframes[0].position[0]).toBeCloseTo(
      GESTURE_LOOK_AHEAD_METERS,
      6,
    );
  });

  it("resamples a hand-drawn polyline by arc length (no stutter, no race)", () => {
    // Dense samples near the start (a hesitant hand) then a long straight
    // run: the keyframes must still be evenly spaced along the path.
    const result = keyframesFromGesturePath(
      [
        [0, 0, 0],
        [0.2, 0, 0],
        [0.4, 0, 0],
        [0.6, 0, 0],
        [3, 0, 0],
      ],
      { ...OPTIONS, durationFrames: 30 },
    );

    const xs = positionsOf(result.keyframes).map((point) => point[0]);
    const gaps = xs.slice(1).map((x, index) => x - xs[index]);
    for (const gap of gaps) {
      expect(gap).toBeCloseTo(1.5, 6);
    }
    expect(result.lengthMeters).toBeCloseTo(3, 6);
  });

  it("treats a click (no travel) as no move at all", () => {
    const click = keyframesFromGesturePath(
      [
        [1, 1, 0],
        [1, 1, 0],
      ],
      OPTIONS,
    );
    const empty = keyframesFromGesturePath([], OPTIONS);

    expect(click.keyframes).toEqual([]);
    expect(empty.keyframes).toEqual([]);
  });

  it("preserves the authored camera height through the gesture", () => {
    const result = keyframesFromGesturePath(
      [
        [0, 0, 0],
        [2, 2, 0],
      ],
      { ...OPTIONS, anchorHeight: 5 },
    );

    expect(result.keyframes.every((keyframe) => keyframe.position[2] === 5)).toBe(true);
  });

  it("turns a corner by facing each segment as it is travelled", () => {
    const result = keyframesFromGesturePath(
      [
        [0, 0, 0],
        [4, 0, 0],
        [4, 4, 0],
      ],
      { ...OPTIONS, durationFrames: 30 },
    );

    const first = result.keyframes[0];
    const last = result.keyframes[result.keyframes.length - 1];
    // Along the first segment the gaze points +X …
    expect(first.look_at![0]).toBeGreaterThan(first.position[0]);
    expect(first.look_at![1]).toBeCloseTo(first.position[1], 6);
    // … and along the last segment it points +Y.
    expect(last.look_at![1]).toBeGreaterThan(last.position[1]);
  });

  it("always lands exactly on the final frame", () => {
    const result = keyframesFromGesturePath(
      [
        [0, 0, 0],
        [5, 5, 0],
      ],
      { ...OPTIONS, durationFrames: 32 },
    );

    const frames = result.keyframes.map((keyframe) => keyframe.frame);
    expect(frames[frames.length - 1]).toBe(32);
    expect(result.keyframes[result.keyframes.length - 1].position).toEqual([5, 5, 2.6]);
  });
});
