import { describe, expect, it } from "vitest";
import { Matrix4, PerspectiveCamera, Vector3 } from "three";
import blenderFixture from "./sceneCameraOutput.blender-fixture.json";
import { sceneToThreePosition, type SceneVec3 } from "./sceneScriptAxes";
import {
  applySceneOutputCamera, sceneCameraOutputCanvasStyle, sceneCameraOutputPosition,
  SCENE_OUTPUT_ASPECT, SCENE_OUTPUT_VERTICAL_FOV, SCENE_OUTPUT_WORLD_SCALE,
} from "./sceneCameraOutput";

function projectSource(camera: PerspectiveCamera, point: SceneVec3): Vector3 {
  return new Vector3(...sceneToThreePosition(point))
    .multiply(new Vector3(...SCENE_OUTPUT_WORLD_SCALE)).project(camera);
}

describe("Blender camera output space", () => {
  it.each(blenderFixture.samples)("matches real Blender camera UV and depth: $name", (sample) => {
    const camera = new PerspectiveCamera();
    applySceneOutputCamera(camera, {
      position: sample.pose.position as SceneVec3, lookAt: sample.pose.lookAt as SceneVec3,
    }, new Vector3());
    for (const [actor, point] of Object.entries(sample.points)) {
      const outputPoint = new Vector3(...sceneToThreePosition(point as SceneVec3))
        .multiply(new Vector3(...SCENE_OUTPUT_WORLD_SCALE));
      const ndc = outputPoint.clone().project(camera);
      const depth = -outputPoint.clone().applyMatrix4(camera.matrixWorldInverse).z;
      const expected = sample.expectedUVDepth[actor as keyof typeof sample.expectedUVDepth];
      expect((ndc.x + 1) / 2).toBeCloseTo(expected[0], 6);
      expect((ndc.y + 1) / 2).toBeCloseTo(expected[1], 6);
      expect(depth).toBeCloseTo(expected[2], 5);
    }
  });

  it("keeps source left/right and up with the actual 50 mm / 16:9 lens", () => {
    const camera = new PerspectiveCamera(50, 270 / 288, .1, 1000);
    applySceneOutputCamera(camera, { position: [0, -5, 1], lookAt: [0, 0, 1] }, new Vector3());
    expect(projectSource(camera, [-1, 0, 1]).x).toBeCloseTo(-5 / 9, 10);
    expect(projectSource(camera, [1, 0, 1]).x).toBeCloseTo(5 / 9, 10);
    expect(projectSource(camera, [0, 0, 2]).y).toBeCloseTo(80 / 81, 10);
    expect(camera.aspect).toBe(SCENE_OUTPUT_ASPECT);
    expect(camera.fov).toBe(SCENE_OUTPUT_VERTICAL_FOV);
    // Actual Blender 5.2.1 calc_matrix_camera output, captured independently at
    // camera-native-projection-v5: this is the final render lens, not angle_y.
    expect(camera.projectionMatrix.elements[0]).toBeCloseTo(2.777777671813965, 6);
    expect(camera.projectionMatrix.elements[5]).toBeCloseTo(4.938271522521973, 6);
  });

  it("preserves an oblique camera's projection independently of the editor axis swap", () => {
    const pose = { position: [4, -6, 3] as SceneVec3, lookAt: [0, 0, 1] as SceneVec3 };
    const camera = new PerspectiveCamera();
    applySceneOutputCamera(camera, pose, new Vector3());
    const eye = new Vector3(...pose.position);
    const forward = new Vector3(...pose.lookAt).sub(eye).normalize();
    const right = forward.clone().cross(new Vector3(0, 0, 1)).normalize();
    const up = right.clone().cross(forward).normalize();
    for (const point of [[-1.2, .1, 1.3], [1.2, .1, 1.3], [0, .75, 1.7]] as SceneVec3[]) {
      const relative = new Vector3(...point).sub(eye);
      const distance = relative.dot(forward);
      const actual = projectSource(camera, point);
      expect(actual.x).toBeCloseTo(relative.dot(right) / distance * 100 / 36, 10);
      expect(actual.y).toBeCloseTo(relative.dot(up) / distance * 100 / (36 / SCENE_OUTPUT_ASPECT), 10);
    }
  });

  it("compensates handedness at the output boundary without changing edit coordinates", () => {
    const source: SceneVec3 = [2, 3, 4];
    expect(sceneToThreePosition(source)).toEqual([2, 4, 3]);
    expect(sceneCameraOutputPosition(source)).toEqual([2, 4, -3]);
    const legacy = new Matrix4().set(1, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 1);
    const compensation = new Matrix4().makeScale(...SCENE_OUTPUT_WORLD_SCALE);
    expect(legacy.determinant()).toBe(-1);
    expect(compensation.multiply(legacy).determinant()).toBe(1);
    expect(source).toEqual([2, 3, 4]);
  });

  it("letterboxes narrow read-only cards while the Orbit editor keeps its viewport", () => {
    const output = sceneCameraOutputCanvasStyle(288, false);
    expect(output.width).toBe("min(100%, 512px)");
    expect(output.height).toBe("auto");
    expect(output.aspectRatio).toBe("16 / 9");
    expect(sceneCameraOutputCanvasStyle(288, true)).toEqual({ width: "100%", height: "100%" });
  });
});
