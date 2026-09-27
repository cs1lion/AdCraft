import { describe, expect, it } from "vitest";

import { blockingPathLength, cameraPathPoints, characterPathPoints } from "./blockingPath";

describe("blockingPath", () => {
  it("draws a point at every position change in frame order", () => {
    const points = characterPathPoints([
      { frame: 0, position: [0, 0, 0], rotation_y: 0, action: "stand" },
      { frame: 30, position: [2, 0, 0], rotation_y: 90, action: "walk" },
      { frame: 60, position: [4, 0, 0], rotation_y: 90, action: "stand" },
    ]);

    expect(points.map((point) => point.frame)).toEqual([0, 30, 60]);
    expect(points[1].scenePosition).toEqual([2, 0, 0]);
    // The conversion to three.js space happens once, here.
    expect(points[1].threePosition).toEqual([2, 0, 0]);
  });

  it("collapses a turn-in-place into one point (no zero-length flicker)", () => {
    const points = characterPathPoints([
      { frame: 0, position: [1, 1, 0], rotation_y: 0, action: "stand" },
      { frame: 15, position: [1, 1, 0], rotation_y: 90, action: "stand" },
      { frame: 30, position: [1, 1, 0], rotation_y: 180, action: "talk" },
    ]);

    expect(points).toHaveLength(1);
    expect(points[0].frame).toBe(0);
  });

  it("preserves height along the path (a lift is not flattened)", () => {
    const points = characterPathPoints([
      { frame: 0, position: [0, 0, 0], rotation_y: 0, action: "stand" },
      { frame: 30, position: [1, 1, 2.5], rotation_y: 0, action: "walk" },
    ]);

    expect(points[1].scenePosition[2]).toBe(2.5);
    // three.js z-up -> y-up conversion keeps the height on the y axis.
    expect(points[1].threePosition[1]).toBe(2.5);
  });

  it("accepts unsorted keyframes and empty lists", () => {
    expect(
      characterPathPoints([
        { frame: 60, position: [4, 0, 0], rotation_y: 0 },
        { frame: 0, position: [0, 0, 0], rotation_y: 0 },
      ]).map((point) => point.frame),
    ).toEqual([0, 60]);
    expect(characterPathPoints([])).toEqual([]);
    expect(cameraPathPoints([])).toEqual([]);
  });

  it("measures the path length the way the viewport draws it", () => {
    const points = characterPathPoints([
      { frame: 0, position: [0, 0, 0], rotation_y: 0 },
      { frame: 15, position: [3, 0, 0], rotation_y: 0 },
      { frame: 30, position: [3, 4, 0], rotation_y: 0 },
    ]);

    expect(blockingPathLength(points)).toBeCloseTo(7, 6); // 3 right + 4 up-forward
    expect(blockingPathLength([])).toBe(0);
  });

  it("serves camera keyframes with the same contract", () => {
    const points = cameraPathPoints([
      { frame: 0, position: [5, -6, 2.6], look_at: [0, 0, 1.2] },
      { frame: 30, position: [6, -6, 2.6], look_at: [0, 0, 1.2] },
      { frame: 60, position: [6, -6, 2.6], look_at: [1, 0, 1.2] },
    ]);

    // The look_at change alone does not add a point: a pan is a gaze change.
    expect(points).toHaveLength(2);
    expect(points[1].frame).toBe(30);
  });
});
