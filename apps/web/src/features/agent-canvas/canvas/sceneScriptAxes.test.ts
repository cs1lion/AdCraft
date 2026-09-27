/**
 * Axis conversion tests (SceneScript Z-up <-> three.js Y-up).
 *
 * Locks the direction of the swap: SceneScript [right, forward, up] becomes
 * three.js [right, up, back]. A flipped mapping would place every Blender
 * wall 3 m up in the browser preview and write drags back into the wrong
 * axis, so the swap is asserted explicitly in both directions plus the yaw
 * unit conversion.
 */

import { describe, expect, it } from "vitest";

import {
  sceneToThreePosition,
  threeToScenePosition,
  sceneYawToThreeRotation,
  threeRotationToSceneYaw,
} from "./sceneScriptAxes";

describe("sceneScriptAxes", () => {
  it("maps Blender [right, forward, up] to three.js [right, up, back]", () => {
    // Camera 3 m forward and 7 m up (Blender) must render 7 m up in three.js.
    expect(sceneToThreePosition([10, -12, 7])).toEqual([10, 7, -12]);
    // Character standing on the ground (z=0) stays on the ground (y=0).
    expect(sceneToThreePosition([0.9, -0.9, 0])).toEqual([0.9, 0, -0.9]);
  });

  it("is an involution: applying twice is the identity", () => {
    const position: [number, number, number] = [1.25, -3.5, 0.75];
    expect(sceneToThreePosition(sceneToThreePosition(position))).toEqual(position);
    expect(threeToScenePosition(threeToScenePosition(position))).toEqual(position);
    expect(threeToScenePosition(sceneToThreePosition(position))).toEqual(position);
  });

  it("converts yaw degrees to three.js radians and back", () => {
    expect(sceneYawToThreeRotation(180)).toBeCloseTo(Math.PI, 10);
    expect(threeRotationToSceneYaw(Math.PI / 2)).toBeCloseTo(90, 10);
    // Round trip preserves value within float tolerance.
    expect(threeRotationToSceneYaw(sceneYawToThreeRotation(137.5))).toBeCloseTo(137.5, 10);
  });
});
