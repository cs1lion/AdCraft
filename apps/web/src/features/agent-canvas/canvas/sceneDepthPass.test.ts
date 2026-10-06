import { afterEach, describe, expect, it } from "vitest";
import { cleanup } from "@testing-library/react";
import * as THREE from "three";

import {
  DEPTH_PASS_DIRECTORY_NAME,
  DEFAULT_DEPTH_POLARITY,
  DepthPassCapture,
  cameraPoseAtFrame,
  depthPassDirectoryPath,
  depthPassFilePlan,
  depthPassFileName,
  depthPassFilePath,
  depthPassFramePlan,
  depthFrameStats,
  encodeDepthPng,
  flipGreyscaleRows,
  frameMaxDepth,
  normalizeDepthToGreyscale,
  shotCameraPoseAtFrame,
  shotKeyframeFrames,
  unpackDepthReadback,
  type DepthPassRenderer,
} from "./sceneDepthPass";

// The repo runs vitest under jsdom; nothing here renders, but the harness
// contract is the same one every canvas test in this tree follows.
afterEach(cleanup);

// ---------------------------------------------------------------------------
// Parity tables produced by the BACKEND implementation, not restated by hand.
//
//   D:\project\myAdCraft\apps\api\.venv\Scripts\python.exe -c "
//     import sys; sys.path.insert(0, 'apps/api')
//     from app.services.scene3d.keyframes import _shot_keyframe_frames
//     ..."
//
// `keyframes._shot_keyframe_frames` is the function
// `control_passes.collect_control_passes` calls to decide which frames a
// shot's depth files must cover, so this table IS the contract. The jinghai
// rows are the shot ranges of test-materials/jinghai_scenescript.json.
const PYTHON_SHOT_KEYFRAMES: Record<string, [number, number]> = {
  "shot_moon_wide 0..239": [0, 239],
  "shot_airlock_run 240..419": [240, 419],
  "shot_firefight 420..599": [420, 599],
  "shot_dropship 600..719": [600, 719],
  // Edge cases: 1-frame, 2-frame, and the durations where Python's
  // round-half-to-even disagrees with Math.round (0.25*duration or
  // 0.75*duration landing on .5 with an odd floor).
  "0..1 single frame": [0, 1],
  "0..2": [0, 2],
  "0..3": [0, 3],
  "0..4": [0, 4],
  "0..5": [0, 5],
  "0..7 duration 6": [0, 7],
  "0..11 duration 10": [0, 11],
  "0..12 duration 11": [0, 12],
  "5..17 offset start": [5, 17],
  "0..21": [0, 21],
  "0..31": [0, 31],
  "0..41": [0, 41],
  "3..8": [3, 8],
  "100..131": [100, 131],
  "0..101": [0, 101],
  "0..361": [0, 361],
};

const PYTHON_KEYFRAME_OUTPUT: Record<string, number[]> = {
  "shot_moon_wide 0..239": [0, 60, 119, 178, 238],
  "shot_airlock_run 240..419": [240, 284, 329, 374, 418],
  "shot_firefight 420..599": [420, 464, 509, 554, 598],
  "shot_dropship 600..719": [600, 630, 659, 688, 718],
  "0..1 single frame": [0],
  "0..2": [0, 1],
  "0..3": [0, 1, 2],
  "0..4": [0, 1, 2, 3],
  "0..5": [0, 1, 2, 3, 4],
  "0..7 duration 6": [0, 2, 3, 4, 6],
  "0..11 duration 10": [0, 2, 5, 8, 10],
  "0..12 duration 11": [0, 3, 6, 8, 11],
  "5..17 offset start": [5, 8, 10, 13, 16],
  "0..21": [0, 5, 10, 15, 20],
  "0..31": [0, 8, 15, 22, 30],
  "0..41": [0, 10, 20, 30, 40],
  "3..8": [3, 4, 5, 6, 7],
  "100..131": [100, 108, 115, 122, 130],
  "0..101": [0, 25, 50, 75, 100],
  "0..361": [0, 90, 180, 270, 360],
};

describe("shotKeyframeFrames — parity with keyframes._shot_keyframe_frames", () => {
  for (const [label, [start, endFrame]] of Object.entries(PYTHON_SHOT_KEYFRAMES)) {
    it(`samples ${label} the way the backend does`, () => {
      expect(shotKeyframeFrames({ start_frame: start, end_frame: endFrame })).toEqual(
        PYTHON_KEYFRAME_OUTPUT[label],
      );
    });
  }

  it("treats end_frame as EXCLUSIVE — the 100% sample is end_frame - 1", () => {
    // A shot spanning 0..60 renders frames 0-59. Sampling 60 would ask for a
    // file nobody writes; the backend's docstring calls this out explicitly.
    const frames = shotKeyframeFrames({ start_frame: 0, end_frame: 60 });
    expect(frames[frames.length - 1]).toBe(59);
    expect(frames).not.toContain(60);
  });

  it("rounds half-to-even, not half-up (Math.round would sample a different frame)", () => {
    // 0.25 * 10 = 2.5 -> Python round() = 2 (even), Math.round = 3. An
    // 11-frame shot therefore samples frame 2 here; the half-up port would
    // emit depth_3.png and silently disagree with the collector, which looks
    // for depth_2.png on that shot.
    expect(Math.round(2.5)).toBe(3);
    expect(shotKeyframeFrames({ start_frame: 0, end_frame: 11 })).toEqual([0, 2, 5, 8, 10]);
  });

  it("de-duplicates without reordering when samples collide", () => {
    // 3-frame shot: 0/1/1/2/2 -> [0, 1, 2].
    expect(shotKeyframeFrames({ start_frame: 0, end_frame: 3 })).toEqual([0, 1, 2]);
    expect(shotKeyframeFrames({ start_frame: 0, end_frame: 1 })).toEqual([0]);
  });
});

describe("depthPassFramePlan — which frames the pass renders", () => {
  // test-materials/jinghai_scenescript.json: 4 shots / 720 frames @ 30fps.
  const jinghaiShots = [
    { id: "shot_moon_wide", start_frame: 0, end_frame: 239 },
    { id: "shot_airlock_run", start_frame: 240, end_frame: 419 },
    { id: "shot_firefight", start_frame: 420, end_frame: 599 },
    { id: "shot_dropship", start_frame: 600, end_frame: 719 },
  ];

  it("covers 5 keyframes per shot and one file per frame number", () => {
    const plan = depthPassFramePlan(jinghaiShots);
    expect(plan.shots.map((shot) => shot.shotId)).toEqual([
      "shot_moon_wide",
      "shot_airlock_run",
      "shot_firefight",
      "shot_dropship",
    ]);
    for (const shot of plan.shots) expect(shot.frames).toHaveLength(5);
    // 4 shots x 5 keyframes, contiguous so nothing collides.
    expect(plan.frames).toEqual([
      0, 60, 119, 178, 238,
      240, 284, 329, 374, 418,
      420, 464, 509, 554, 598,
      600, 630, 659, 688, 718,
    ]);
  });

  it("is empty for a script with no shots (no shot can align a file)", () => {
    expect(depthPassFramePlan([])).toEqual({ shots: [], frames: [], frameShots: [] });
  });

  it("records which shot each planned frame belongs to", () => {
    const plan = depthPassFramePlan(jinghaiShots);
    expect(plan.frameShots).toEqual([
      ...[0, 60, 119, 178, 238].map((frame) => ({ frame, shotId: "shot_moon_wide" })),
      ...[240, 284, 329, 374, 418].map((frame) => ({ frame, shotId: "shot_airlock_run" })),
      ...[420, 464, 509, 554, 598].map((frame) => ({ frame, shotId: "shot_firefight" })),
      ...[600, 630, 659, 688, 718].map((frame) => ({ frame, shotId: "shot_dropship" })),
    ]);
    // The first shot to sample a shared frame number owns it.
    const shared = depthPassFramePlan([
      { id: "a", start_frame: 0, end_frame: 11 },
      { id: "b", start_frame: 10, end_frame: 21 },
    ]);
    expect(shared.frameShots.find((entry) => entry.frame === 10)?.shotId).toBe("a");
  });

  it("collapses a shared frame number once, like Blender's generated script did", () => {
    // Overlapping shots: shot A's 100% sample and shot B's 0% sample both = 10.
    const plan = depthPassFramePlan([
      { id: "a", start_frame: 0, end_frame: 11 },
      { id: "b", start_frame: 10, end_frame: 21 },
    ]);
    expect(plan.shots[0].frames).toEqual([0, 2, 5, 8, 10]);
    expect(plan.shots[1].frames).toEqual([10, 12, 15, 18, 20]);
    expect(plan.frames).toEqual([0, 2, 5, 8, 10, 12, 15, 18, 20]);
  });
});

// ---------------------------------------------------------------------------
// The camera the pass renders from. Blender keyframed the scene camera per
// shot, so its depth pass was the shot's own viewpoint; the preview's canvas is
// the author's orbit camera, which the pass must borrow for the capture.
// ---------------------------------------------------------------------------
describe("cameraPoseAtFrame", () => {
  const keyframes = [
    { frame: 0, position: [20, -18, 6], look_at: [0, 0, 1] },
    { frame: 120, position: [16, -12, 5], look_at: [0, 0, 1] },
    { frame: 239, position: [12, -8, 4.5], look_at: [1, 0, 1] },
  ];

  it("returns the first and last pose outside the keyframe range", () => {
    expect(cameraPoseAtFrame(keyframes, -5)).toEqual({ position: [20, -18, 6], lookAt: [0, 0, 1] });
    expect(cameraPoseAtFrame(keyframes, 500)).toEqual({ position: [12, -8, 4.5], lookAt: [1, 0, 1] });
  });

  it("interpolates between keyframes", () => {
    expect(cameraPoseAtFrame(keyframes, 60)).toEqual({
      position: [18, -15, 5.5],
      lookAt: [0, 0, 1],
    });
    expect(cameraPoseAtFrame(keyframes, 0)).toEqual({ position: [20, -18, 6], lookAt: [0, 0, 1] });
  });

  it("returns null for a camera with no keyframes", () => {
    expect(cameraPoseAtFrame([], 10)).toBeNull();
  });
});

describe("shotCameraPoseAtFrame", () => {
  const cameras = [
    { id: "cam_wide", keyframes: [{ frame: 0, position: [20, -18, 6], look_at: [0, 0, 1] }] },
    { id: "cam_airlock", keyframes: [{ frame: 240, position: [6, 2, 1.6], look_at: [0, 0, 1] }] },
  ];

  it("resolves the shot's own camera, interpolated to the frame", () => {
    const pose = shotCameraPoseAtFrame(cameras, { camera: "cam_airlock" }, 240);
    expect(pose).toEqual({
      cameraId: "cam_airlock",
      position: [6, 2, 1.6],
      lookAt: [0, 0, 1],
    });
  });

  it("returns null for a dangling camera reference or an unkeyframed camera", () => {
    expect(shotCameraPoseAtFrame(cameras, { camera: "cam_missing" }, 0)).toBeNull();
    expect(shotCameraPoseAtFrame(cameras, { camera: "" }, 0)).toBeNull();
    expect(
      shotCameraPoseAtFrame([{ id: "cam_wide", keyframes: [] }], { camera: "cam_wide" }, 0),
    ).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// The layout `control_passes.collect_control_passes` reads. The expectations
// below are transcribed from apps/api/app/services/scene3d/control_passes.py:
//   depth_dir = base / "control_depth"
//   _PASS_NAME_RE = re.compile(r"^(\w+)_(\d+)(?:\.png)?$")
//   ... int(match.group(2)) == frame_num  (0-based SceneScript frame)
// ---------------------------------------------------------------------------
describe("depth pass layout — the collector's contract", () => {
  it("writes into control_depth next to the colour frames", () => {
    expect(DEPTH_PASS_DIRECTORY_NAME).toBe("control_depth");
    expect(depthPassDirectoryPath("/renders/run1")).toBe("/renders/run1/control_depth");
    expect(depthPassDirectoryPath("/renders/run1/")).toBe("/renders/run1/control_depth");
    expect(depthPassDirectoryPath("C:\\renders\\run1")).toBe("C:\\renders\\run1/control_depth");
  });

  it("names files depth_<N>.png with a 0-based SceneScript frame", () => {
    expect(depthPassFileName(0)).toBe("depth_0.png");
    expect(depthPassFileName(719)).toBe("depth_719.png");
    expect(depthPassFilePath("/renders/run1", 719)).toBe(
      "/renders/run1/control_depth/depth_719.png",
    );
  });

  it("produces names the collector's regex and 0-based lookup accept", () => {
    // The collector's own pattern and comparison, copied from control_passes.py.
    const passNameRe = /^(\w+)_(\d+)(?:\.png)?$/;
    const frames = [0, 60, 179, 719];
    for (const entry of depthPassFilePlan("/renders/run1", frames)) {
      expect(entry.path).toBe(`/renders/run1/control_depth/${entry.fileName}`);
      const match = passNameRe.exec(entry.fileName);
      expect(match).not.toBeNull();
      expect(match?.[1]).toBe("depth");
      // 0-based, NOT the colour pass's 1-indexed numbering.
      expect(Number(match?.[2])).toBe(entry.frame);
    }
  });

  it("plans one file per planned frame, in frame order", () => {
    const plan = depthPassFilePlan("/out", [60, 0, 120, 0]);
    expect(plan.map((entry) => entry.path)).toEqual([
      "/out/control_depth/depth_60.png",
      "/out/control_depth/depth_0.png",
      "/out/control_depth/depth_120.png",
      "/out/control_depth/depth_0.png",
    ]);
  });
});

// ---------------------------------------------------------------------------
// Normalization: Blender's max_d, with a stated polarity.
// ---------------------------------------------------------------------------
describe("frameMaxDepth — Blender's max_d", () => {
  it("is the frame's own maximum", () => {
    expect(frameMaxDepth([1, 5, 3, 5])).toBe(5);
  });

  it("falls back to 1 when nothing was hit (all background)", () => {
    expect(frameMaxDepth([0, 0, 0])).toBe(1);
    expect(frameMaxDepth([])).toBe(1);
  });
});

describe("normalizeDepthToGreyscale", () => {
  const samples = [2, 4, 8, 0]; // last pixel: no geometry

  it("normalizes by the frame's own maximum and keeps background black", () => {
    const grey = normalizeDepthToGreyscale(samples, { polarity: "far-bright" });
    // depth / max_d, exactly Blender's `norm = depth / max_d`.
    expect(Array.from(grey)).toEqual([Math.round((2 / 8) * 255), Math.round((4 / 8) * 255), 255, 0]);
  });

  it("defaults to near = bright (three.js MeshDepthMaterial's convention)", () => {
    expect(DEFAULT_DEPTH_POLARITY).toBe("near-bright");
    // 1 - (depth / max_d) per pixel: the nearest pixel is the brightest.
    expect(Array.from(normalizeDepthToGreyscale(samples))).toEqual([
      Math.round((1 - 2 / 8) * 255),
      Math.round((1 - 4 / 8) * 255),
      0,
      0,
    ]);
    // Nearest geometry is white, farthest geometry is black, background black.
    expect(Array.from(normalizeDepthToGreyscale([0.5, 1, 0]))).toEqual([128, 0, 0]);
  });

  it("far-bright reproduces what Blender wrote byte for byte", () => {
    expect(Array.from(normalizeDepthToGreyscale([0.5, 1, 0], { polarity: "far-bright" }))).toEqual([
      128, 255, 0,
    ]);
  });

  it("guards an empty frame (max_d -> 1) and a supplied maxDepth below the true max", () => {
    expect(Array.from(normalizeDepthToGreyscale([0, 0]))).toEqual([0, 0]);
    // Clamped so a stale maxDepth cannot overflow the byte range.
    expect(Array.from(normalizeDepthToGreyscale([10], { maxDepth: 4 }))).toEqual([0]);
    // A zero maxDepth is ignored rather than dividing by zero.
    expect(Array.from(normalizeDepthToGreyscale([4], { maxDepth: 0, polarity: "far-bright" }))).toEqual([
      255,
    ]);
  });
});

describe("depthFrameStats — the anti-false-pass numbers", () => {
  it("counts geometry and the greyscale range a caller can assert on", () => {
    const samples = [2, 4, 8, 0];
    const pixels = normalizeDepthToGreyscale(samples);
    const stats = depthFrameStats(samples, pixels);
    expect(stats.maxDepth).toBe(8);
    expect(stats.geometryPixels).toBe(3);
    expect(stats.maxGrey - stats.minGrey).toBeGreaterThan(0);
  });

  it("reports an empty (all-black) frame honestly", () => {
    const stats = depthFrameStats([0, 0, 0], new Uint8ClampedArray([0, 0, 0]));
    expect(stats.geometryPixels).toBe(0);
    expect(stats.maxGrey).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// The readback maths. `packDepthToRGBA` mirrors three's ShaderChunk/packing
// (used by MeshDepthMaterial with RGBADepthPacking) so the round trip is
// tested against the same constants the GPU uses.
// ---------------------------------------------------------------------------
function packDepthToRGBA(windowDepth: number): [number, number, number, number] {
  if (windowDepth <= 0) return [0, 0, 0, 0];
  if (windowDepth >= 1) return [255, 255, 255, 255];
  let vuf = Math.floor(windowDepth * 2 ** 24);
  const af = windowDepth * 2 ** 24 - vuf;
  const bf = (vuf / 256) % 1;
  vuf = Math.floor(vuf / 256);
  const gf = (vuf / 256) % 1;
  vuf = Math.floor(vuf / 256);
  return [vuf, Math.round(gf * 256), Math.round(bf * 256), Math.round(af * 255)];
}

function viewZToWindowDepth(viewZ: number, near: number, far: number): number {
  // three's packing.glsl.js: -near maps to 0, -far maps to 1.
  return ((near + viewZ) * far) / ((far - near) * viewZ);
}

describe("unpackDepthReadback", () => {
  it("recovers camera-plane distance from packed RGBA depth", () => {
    const near = 0.1;
    const far = 1000;
    const distances = [1, 5, 12.5, 100, 400];
    const rgba = new Uint8Array(distances.length * 4);
    distances.forEach((distance, index) => {
      const packed = packDepthToRGBA(viewZToWindowDepth(-distance, near, far));
      rgba.set(packed, index * 4);
    });
    const out = unpackDepthReadback(rgba, near, far);
    out.forEach((distance, index) => {
      // 24-bit fixed point: sub-millimetre error, far tighter than the 8-bit
      // BasicDepthPacking alternative the preview camera would destroy.
      expect(Math.abs(distance - distances[index])).toBeLessThan(0.001);
    });
  });

  it("treats the cleared background (all zeroes) as no geometry", () => {
    const rgba = new Uint8Array([0, 0, 0, 0, 255, 255, 255, 255]);
    const out = unpackDepthReadback(rgba, 0.1, 1000);
    expect(out[0]).toBe(0);
    // Clamped to the far plane: 24-bit fixed point lands within a unit of it.
    expect(out[1]).toBeCloseTo(1000, -1);
  });

  it("reuses a right-sized output buffer", () => {
    const near = 0.1;
    const far = 1000;
    const rgba = new Uint8Array([0, 0, 0, 0, 0, 0, 0, 0]);
    const out = new Float32Array(2);
    expect(unpackDepthReadback(rgba, near, far, out)).toBe(out);
    expect(out[0]).toBe(0);
    expect(out[1]).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// The GL seam, driven by a stub renderer (no GPU).
// ---------------------------------------------------------------------------
class StubRenderer implements DepthPassRenderer {
  target: THREE.WebGLRenderTarget | null = null;
  clearColor = new THREE.Color(0x123456);
  clearAlpha = 1;
  overrideMaterialDuringRender: THREE.Material | null = null;
  backgroundDuringRender: THREE.Color | null | undefined;
  renderCount = 0;
  readCalls: { width: number; height: number }[] = [];
  /** What the "GPU" returns for the next read. */
  readback: Uint8Array | null = null;
  failNextRead = false;
  /** The render target the scene was last rendered into (stub bookkeeping). */
  lastRenderedTarget: THREE.WebGLRenderTarget | null = null;

  getRenderTarget(): THREE.WebGLRenderTarget | null {
    return this.target;
  }
  setRenderTarget(target: THREE.WebGLRenderTarget | null): void {
    this.target = target;
  }
  getClearColor(target: THREE.Color): THREE.Color {
    return target.copy(this.clearColor);
  }
  getClearAlpha(): number {
    return this.clearAlpha;
  }
  setClearColor(color: THREE.ColorRepresentation, alpha?: number): void {
    this.clearColor.set(color);
    if (alpha !== undefined) this.clearAlpha = alpha;
  }
  setClearAlpha(alpha: number): void {
    this.clearAlpha = alpha;
  }
  render(scene: THREE.Scene, _camera: THREE.Camera): void {
    this.overrideMaterialDuringRender = scene.overrideMaterial;
    this.backgroundDuringRender = scene.background;
    this.renderCount += 1;
    const target = this.target;
    if (!target) throw new Error("stub: rendered without a render target");
    if (this.failNextRead) throw new Error("stub: readback failed");
    // Touch the target so the stub is not accused of ignoring it.
    this.lastRenderedTarget = target;
  }
  readRenderTargetPixels(
    renderTarget: THREE.WebGLRenderTarget,
    _x: number,
    _y: number,
    width: number,
    height: number,
    buffer: { set(array: ArrayLike<number>, offset?: number): void },
  ): void {
    this.readCalls.push({ width, height });
    if (!this.readback) throw new Error("stub: no readback bytes staged");
    if (this.readback.length !== width * height * 4) {
      throw new Error(`stub: readback is ${this.readback.length} bytes, target wants ${width * height * 4}`);
    }
    buffer.set(this.readback);
    void renderTarget;
  }
}

function stagedScene(): { scene: THREE.Scene; camera: THREE.PerspectiveCamera } {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x1a1a2e);
  scene.overrideMaterial = new THREE.MeshBasicMaterial();
  scene.add(new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial()));
  const camera = new THREE.PerspectiveCamera(50, 16 / 9, 0.1, 1000);
  camera.position.set(5, 5, 5);
  camera.lookAt(0, 0, 0);
  return { scene, camera };
}

/** A full-frame readback: geometry at 4 and 8 units, then background. */
function stagedReadback(width: number, height: number): Uint8Array {
  const near = 0.1;
  const far = 1000;
  const pixels = width * height;
  const rgba = new Uint8Array(pixels * 4);
  for (let index = 0; index < pixels; index += 1) {
    const distance = index === 0 ? 4 : index === 1 ? 8 : 0;
    const packed =
      distance === 0
        ? [0, 0, 0, 0]
        : packDepthToRGBA(viewZToWindowDepth(-distance, near, far));
    rgba.set(packed, index * 4);
  }
  return rgba;
}

describe("flipGreyscaleRows — GL order is bottom-up, images are top-down", () => {
  it("turns a bottom-up buffer into image order", () => {
    // 3x2: row 0 (GL bottom) is the bright row, row 1 the dark one.
    const glOrder = new Uint8ClampedArray([9, 9, 9, 1, 1, 1]);
    expect(Array.from(flipGreyscaleRows(glOrder, 3, 2))).toEqual([1, 1, 1, 9, 9, 9]);
  });

  it("is its own inverse and a no-op for a single row", () => {
    const pixels = new Uint8ClampedArray([1, 2, 3, 4, 5, 6]);
    const once = flipGreyscaleRows(pixels, 2, 3);
    expect(Array.from(flipGreyscaleRows(once, 2, 3))).toEqual(Array.from(pixels));
    expect(Array.from(flipGreyscaleRows(pixels, 6, 1))).toEqual(Array.from(pixels));
  });
});

describe("DepthPassCapture — the GL seam", () => {
  it("renders the scene a second time with a packed depth material and restores every state it touched", () => {
    const renderer = new StubRenderer();
    renderer.readback = stagedReadback(3, 1);
    const { scene, camera } = stagedScene();
    const basicOverride = scene.overrideMaterial;
    const background = scene.background;
    const capture = new DepthPassCapture(renderer);

    const frame = capture.capture(scene, camera, { width: 3, height: 1 });

    expect(renderer.renderCount).toBe(1);
    // A MeshDepthMaterial with 24-bit packing, not the 8-bit default.
    expect(renderer.overrideMaterialDuringRender).toBeInstanceOf(THREE.MeshDepthMaterial);
    expect(
      (renderer.overrideMaterialDuringRender as THREE.MeshDepthMaterial).depthPacking,
    ).toBe(THREE.RGBADepthPacking);
    // The scene's own background is hidden: it would draw as phantom depth.
    expect(renderer.backgroundDuringRender).toBeNull();
    // ...and everything the pass touched is put back.
    expect(scene.overrideMaterial).toBe(basicOverride);
    expect(scene.background).toBe(background);
    expect(renderer.clearAlpha).toBe(1);
    expect(renderer.clearColor.getHex()).toBe(0x123456);
    expect(renderer.target).toBeNull();

    expect(renderer.readCalls).toEqual([{ width: 3, height: 1 }]);
    expect(frame.width).toBe(3);
    expect(frame.height).toBe(1);
    expect(frame.geometryPixels).toBe(2);
    expect(frame.maxDepth).toBeCloseTo(8, 3);
    // near = bright: the pixel at 4 units (half the frame's max) is mid-grey,
    // the pixel at 8 units (the max itself) is black, the background is black.
    expect(Array.from(frame.pixels)).toEqual([128, 0, 0]);

    // The render target owns a DepthTexture, which is what makes the depth
    // write real (the render-target route the plan asks for).
    capture.dispose();
  });

  it("allocates the render target with a DepthTexture and reports its size", () => {
    const renderer = new StubRenderer();
    renderer.readback = stagedReadback(4, 2);
    const { scene, camera } = stagedScene();
    const capture = new DepthPassCapture(renderer);
    expect(capture.frameSize).toEqual({ width: 0, height: 0 });

    capture.capture(scene, camera, { width: 4, height: 2 });
    expect(capture.frameSize).toEqual({ width: 4, height: 2 });
    // capture() restored the renderer; assert the size it was allocated at and
    // that a resize re-allocates (a 4x2 readback must not be fed to a 6x2).
    renderer.readback = stagedReadback(6, 2);
    capture.capture(scene, camera, { width: 6, height: 2 });
    expect(capture.frameSize).toEqual({ width: 6, height: 2 });
    expect(renderer.readCalls.map((call) => call.width)).toEqual([4, 6]);
    capture.dispose();
  });

  it("hands pixels back in IMAGE order even though GL reads bottom-up", () => {
    const renderer = new StubRenderer();
    // 3x2 with geometry at 4 and 8 units in the GL BOTTOM row (indices 0-2).
    renderer.readback = stagedReadback(3, 2);
    const { scene, camera } = stagedScene();
    const capture = new DepthPassCapture(renderer);
    const frame = capture.capture(scene, camera, { width: 3, height: 2 });
    // The bright 4-unit pixel lands on the TOP row of the image, not the GL
    // bottom row: a PNG written from these bytes is the right way up.
    expect(Array.from(frame.pixels)).toEqual([0, 0, 0, 128, 0, 0]);
    expect(frame.geometryPixels).toBe(2);
    expect(frame.maxDepth).toBeCloseTo(8, 3);
    capture.dispose();
  });

  it("puts the target's DepthTexture on the render target it renders into", () => {    const renderer = new StubRenderer();
    renderer.readback = stagedReadback(3, 1);
    const { scene, camera } = stagedScene();
    const seen: (THREE.DepthTexture | null)[] = [];
    const originalRender = renderer.render.bind(renderer);
    renderer.render = (sceneArg, cameraArg) => {
      const target = renderer.target;
      seen.push(target ? target.depthTexture : null);
      originalRender(sceneArg, cameraArg);
    };
    const capture = new DepthPassCapture(renderer);
    capture.capture(scene, camera, { width: 3, height: 1 });
    expect(seen).toHaveLength(1);
    expect(seen[0]).toBeInstanceOf(THREE.DepthTexture);
    capture.dispose();
  });

  it("restores the scene even when the GPU read fails", () => {
    const renderer = new StubRenderer();
    const { scene, camera } = stagedScene();
    const capture = new DepthPassCapture(renderer);
    const clearAlpha = renderer.clearAlpha;
    const clearHex = renderer.clearColor.getHex();
    renderer.failNextRead = true;
    expect(() => capture.capture(scene, camera, { width: 3, height: 1 })).toThrow(/readback failed/);
    // A failed pass must not leave the live preview rendering depth.
    expect(scene.overrideMaterial).toBeInstanceOf(THREE.MeshBasicMaterial);
    expect(scene.background).toBeInstanceOf(THREE.Color);
    expect(renderer.clearAlpha).toBe(clearAlpha);
    expect(renderer.clearColor.getHex()).toBe(clearHex);
    expect(renderer.target).toBeNull();
    capture.dispose();
  });
});

// ---------------------------------------------------------------------------
// PNG encoding behind the injected canvas factory.
// ---------------------------------------------------------------------------
describe("encodeDepthPng", () => {
  it("writes greyscale bytes into an RGBA PNG and encodes it", async () => {
    const blobs: Blob[] = [];
    const images: { width: number; height: number; data: Uint8ClampedArray }[] = [];
    const blob = await encodeDepthPng(
      { width: 2, height: 1, pixels: new Uint8ClampedArray([0, 255]) },
      () =>
        ({
          width: 0,
          height: 0,
          getContext: () => ({
            createImageData: (width: number, height: number) => {
              const image = {
                width,
                height,
                data: new Uint8ClampedArray(width * height * 4),
              };
              images.push(image);
              return image;
            },
            putImageData: () => undefined,
          }),
          toBlob: (resolve: (blob: Blob | null) => void) => {
            const result = new Blob(["png"]);
            blobs.push(result);
            resolve(result);
          },
        }) as unknown as HTMLCanvasElement,
    );

    expect(blobs).toHaveLength(1);
    expect(blob).toBe(blobs[0]);
    expect(images[0].data.slice(0, 8)).toEqual(
      new Uint8ClampedArray([0, 0, 0, 255, 255, 255, 255, 255]),
    );
  });

  it("fails loudly when there is no 2D context to encode with", async () => {
    await expect(
      encodeDepthPng({ width: 1, height: 1, pixels: new Uint8ClampedArray([0]) }, () => null),
    ).rejects.toThrow(/no 2D canvas context/);
    await expect(
      encodeDepthPng({ width: 1, height: 1, pixels: new Uint8ClampedArray([0]) }, () => ({
        getContext: () => null,
      }) as unknown as HTMLCanvasElement),
    ).rejects.toThrow(/no 2D canvas context/);
  });
});
