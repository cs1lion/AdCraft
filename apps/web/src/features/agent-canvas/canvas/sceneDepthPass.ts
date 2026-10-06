/**
 * sceneDepthPass — the DEPTH geometric control pass, rendered by three.js.
 *
 * WHY THIS EXISTS
 * `apps/api/app/services/scene3d/control_passes.py` collects a per-shot depth /
 * normal / flow bundle from a render directory. Blender used to write the depth
 * half of that bundle (`blender_converter._control_pass_lines`); the three.js
 * renderer replacement (`docs/plans/threejs-renderer-replacement.md` §4.5)
 * writes the SAME bundle from the same scene the author edits, so the collector
 * keeps working unchanged. The contract that must not move:
 *
 *   - directory ``control_depth`` as a SIBLING of the colour ``frame_*.png``
 *     output (``collect_control_passes`` builds ``base / "control_depth"``),
 *   - file name ``depth_<N>.png`` where N is the 0-based SceneScript frame
 *     (``_PASS_NAME_RE`` = ``^(\w+)_(\d+)(?:\.png)?$``) — NOT Blender's
 *     1-indexed colour-pass numbering,
 *   - one file per shot keyframe frame: 0/25/50/75/100% of the shot, with
 *     ``end_frame`` EXCLUSIVE, which is what `keyframes._shot_keyframe_frames`
 *     computes and what the collector re-derives from the SceneScript.
 *
 * WHAT IS IN HERE
 * Everything that can be pure is pure: frame selection, the directory/file
 * layout, and the normalization maths. The GL work sits behind one narrow seam
 * (`DepthPassCapture` + `DepthPassRenderer`) so the pass can be unit-tested
 * with a stubbed renderer and no GPU.
 *
 * ROUTE CHOICE (render target, not the default framebuffer)
 * The pass renders the scene a SECOND time into a `WebGLRenderTarget` that
 * owns a `DepthTexture`, with `MeshDepthMaterial` overriding every material,
 * and reads the pixels back with `renderer.readRenderTargetPixels`. That route
 * does not care whether the drawing buffer survived compositing, so it is
 * immune to the bug that produced 12 identical black PNGs the first time
 * somebody tried to read pixels (`preserveDrawingBuffer` is only needed to
 * read the CANVAS — the colour pass — outside the render callback).
 */

import * as THREE from "three";

// ---------------------------------------------------------------------------
// Layout: the files `control_passes.collect_control_passes` looks for
// ---------------------------------------------------------------------------

/**
 * Sibling directory of the colour frames holding the depth pass. Hardcoded to
 * the collector's expectation: `collect_control_passes` does
 * ``Path(frames_dir) / "control_depth"`` with no configuration.
 */
export const DEPTH_PASS_DIRECTORY_NAME = "control_depth";

/**
 * ``depth_<N>.png`` — N is the 0-based SceneScript frame.
 *
 * The collector matches ``^(\w+)_(\d+)(?:\.png)?$`` and compares
 * ``int(group(2))`` against the 0-indexed frame, so the extension is optional
 * but the zero-based number is not: the colour pass is 1-indexed because
 * Blender numbers animation frames from 1, and this pass must NOT be.
 */
export function depthPassFileName(frame: number): string {
  return `depth_${frame}.png`;
}

/**
 * ``<frames_dir>/control_depth`` in POSIX form, which is what the collector
 * reports (`src.as_posix()`), so a client and a server round-trip produce the
 * same string regardless of the host's path separator.
 */
export function depthPassDirectoryPath(framesDir: string): string {
  return `${framesDir.replace(/[/\\]+$/, "")}/${DEPTH_PASS_DIRECTORY_NAME}`;
}

/** ``<frames_dir>/control_depth/depth_<N>.png``. */
export function depthPassFilePath(framesDir: string, frame: number): string {
  return `${depthPassDirectoryPath(framesDir)}/${depthPassFileName(frame)}`;
}

export interface DepthPassFilePlanEntry {
  frame: number;
  fileName: string;
  path: string;
}

/**
 * The files one render job writes, in frame order.
 *
 * Purely derived so the frame NAMES a client produces are provably the ones
 * `collect_control_passes` later looks up (see `sceneDepthPass.test.ts`, which
 * asserts this against the collector's layout rather than a restatement).
 */
export function depthPassFilePlan(
  framesDir: string,
  frames: readonly number[],
): DepthPassFilePlanEntry[] {
  return frames.map((frame) => ({
    frame,
    fileName: depthPassFileName(frame),
    path: depthPassFilePath(framesDir, frame),
  }));
}

// ---------------------------------------------------------------------------
// Frame selection: the same 5 keyframes per shot the collector re-derives
// ---------------------------------------------------------------------------

/**
 * The shot range the frame selection needs. Structural on purpose: both the
 * frontend `SceneShot` and the backend's shot shape satisfy it, and a test can
 * build one without a whole SceneScript.
 */
export interface ShotFrameRange {
  start_frame: number;
  end_frame: number;
}

/** The camera a shot names. */
export interface ShotCameraRef {
  /** Camera id the shot names, or "" when the reference dangles. */
  camera: string;
}

/** The camera whose pose the pass renders from. */
export interface ShotCamera {
  id: string;
  keyframes: CameraPoseKeyframe[];
}

/**
 * Python's ``round()``: half-to-even, not half-up.
 *
 * This is not pedantry. `keyframes._shot_keyframe_frames` computes
 * ``int(round(start + duration * pct))`` and `Math.round` (half-up) disagrees
 * exactly when ``duration * pct`` lands on .5 with an odd floor: an 11-frame
 * shot (duration 10) gets 2 from Python at 25% and 3 from `Math.round`, so a
 * JS port that rounds the ordinary way samples a DIFFERENT frame and the two
 * implementations silently disagree about which frames exist.
 */
function roundHalfToEven(value: number): number {
  const floor = Math.floor(value);
  const fraction = value - floor;
  if (fraction > 0.5) return floor + 1;
  if (fraction < 0.5) return floor;
  return floor % 2 === 0 ? floor : floor + 1;
}

/**
 * The 5 keyframe frames of one shot, at 0/25/50/75/100% of its range.
 *
 * Mirrors `keyframes._shot_keyframe_frames` (the function
 * `collect_control_passes` calls) line for line:
 *
 *   - ``end_frame`` is EXCLUSIVE: the last real frame is ``end_frame - 1``.
 *     Sampling ``end_frame`` would ask for a file nobody writes and the shot
 *     would quietly drop to 4 keyframes.
 *   - ``duration <= 0`` (a single-frame shot) yields just ``[start]``.
 *   - results are clamped into ``[start, end_frame - 1]`` and de-duplicated in
 *     order, so a short shot contributes fewer than 5 FILES but never a
 *     duplicate one.
 */
export function shotKeyframeFrames(shot: ShotFrameRange): number[] {
  const start = shot.start_frame;
  const last = shot.end_frame - 1;
  const duration = last - start;
  if (duration <= 0) return [start];
  const frames: number[] = [];
  for (const pct of [0.0, 0.25, 0.5, 0.75, 1.0]) {
    const frame = Math.min(last, Math.max(start, roundHalfToEven(start + duration * pct)));
    if (!frames.includes(frame)) frames.push(frame);
  }
  return frames;
}

export interface ShotDepthPassFrames {
  shotId: string;
  frames: number[];
}

export interface DepthPassFramePlan {
  /** Per shot, in script order — the order `collect_control_passes` walks. */
  shots: ShotDepthPassFrames[];
  /** Ordered de-duplicated union: the frames worth actually rendering. */
  frames: number[];
  /** Which shot each planned frame belongs to, in the same order as `frames`. */
  frameShots: { frame: number; shotId: string }[];
}

/**
 * Which frames the pass renders, for every shot.
 *
 * `collect_control_passes` aligns each shot to ITS OWN keyframes and looks the
 * files up in the shared `control_depth` directory, so the union is what gets
 * written and the per-shot split is what the collector re-derives. Contiguous
 * shots never collide (a shot's 100% frame is ``end_frame - 1`` and the next
 * shot's 0% is its ``start_frame``); if a script ever did overlap them the
 * de-duplication keeps one file per frame number, exactly like Blender's
 * generated ``_shot_keyframe_frames`` did with ``if f not in frames``.
 */
export function depthPassFramePlan(
  shots: readonly ({ id: string } & ShotFrameRange)[],
): DepthPassFramePlan {
  const perShot = shots.map((shot) => ({
    shotId: shot.id,
    frames: shotKeyframeFrames(shot),
  }));
  const frames: number[] = [];
  const frameShots: { frame: number; shotId: string }[] = [];
  for (const shot of perShot) {
    for (const frame of shot.frames) {
      if (frames.includes(frame)) continue;
      frames.push(frame);
      frameShots.push({ frame, shotId: shot.shotId });
    }
  }
  return { shots: perShot, frames, frameShots };
}

// ---------------------------------------------------------------------------
// The camera the pass renders FROM: the shot's camera, not the editor's.
//
// Blender keyframed `scene.camera` per shot, so its depth pass was the geometry
// of that shot's own viewpoint — which is what a video model needs as guidance
// for that shot. The preview's canvas is an ORBIT camera (the author's
// viewpoint, dragged by OrbitControls), so the pass has to borrow the shot
// camera's pose for the duration of a capture rather than render whatever
// corner of the scene the author happens to be looking at. `shotCameraPoseAt
// Frame` below is the pure half of that.
// ---------------------------------------------------------------------------

/** The camera fields a pose needs. Structural, so the backend's shape fits too. */
export interface CameraPoseKeyframe {
  frame: number;
  position: [number, number, number];
  look_at: [number, number, number];
}

export interface CameraPose {
  position: [number, number, number];
  lookAt: [number, number, number];
}

/**
 * Interpolate a camera's keyframes at `frame` (SceneScript coordinates).
 *
 * Clamped outside the keyframe range: before the first keyframe the first pose
 * governs, after the last the last does. This mirrors
 * `SceneScript3DPreview`'s `interpolateCameraKeyframes`, which drives the
 * on-screen gizmo — the gizmo and the pass must agree on where the camera is,
 * so the two stay deliberately identical.
 */
export function cameraPoseAtFrame(
  keyframes: readonly CameraPoseKeyframe[],
  frame: number,
): CameraPose | null {
  if (keyframes.length === 0) return null;
  if (keyframes.length === 1 || frame <= keyframes[0].frame) {
    return { position: keyframes[0].position, lookAt: keyframes[0].look_at };
  }
  const last = keyframes[keyframes.length - 1];
  if (frame >= last.frame) {
    return { position: last.position, lookAt: last.look_at };
  }
  for (let index = 0; index < keyframes.length - 1; index += 1) {
    const a = keyframes[index];
    const b = keyframes[index + 1];
    if (frame >= a.frame && frame <= b.frame) {
      const t = (frame - a.frame) / (b.frame - a.frame || 1);
      return {
        position: [
          a.position[0] + (b.position[0] - a.position[0]) * t,
          a.position[1] + (b.position[1] - a.position[1]) * t,
          a.position[2] + (b.position[2] - a.position[2]) * t,
        ],
        lookAt: [
          a.look_at[0] + (b.look_at[0] - a.look_at[0]) * t,
          a.look_at[1] + (b.look_at[1] - a.look_at[1]) * t,
          a.look_at[2] + (b.look_at[2] - a.look_at[2]) * t,
        ],
      };
    }
  }
  return null;
}

/**
 * The pose the pass renders `frame` from: the camera of the shot that samples
 * it, interpolated to that frame. Returns null when the shot's camera is
 * missing, dangling or unkeyframed — the caller then falls back to whatever
 * camera it already has rather than inventing a viewpoint.
 */
export function shotCameraPoseAtFrame(
  cameras: readonly ShotCamera[],
  shot: ShotCameraRef | null,
  frame: number,
): (CameraPose & { cameraId: string }) | null {
  if (!shot || !shot.camera) return null;
  const camera = cameras.find((candidate) => candidate.id === shot.camera);
  if (!camera) return null;
  const pose = cameraPoseAtFrame(camera.keyframes, frame);
  if (!pose) return null;
  return { cameraId: camera.id, ...pose };
}

// ---------------------------------------------------------------------------
// Normalization: Blender's max_d, with a stated greyscale polarity
// ---------------------------------------------------------------------------

/**
 * Greyscale polarity. Both values normalize by the frame's own maximum depth
 * (Blender's ``max_d``); they differ only in which end is white:
 *
 *  - ``"near-bright"`` (DEFAULT): white = nearest. This is three.js's own
 *    MeshDepthMaterial convention ("White is nearest, black is farthest", see
 *    the material docstring and the ``1.0 - fragCoordZ`` in
 *    ShaderLib/depth.glsl.js) and the repo's depth-map convention
 *    (`depth_estimator.py`: "closer objects are brighter";
 *    `depth_reprojection.render_depth_orbit`: "Grayscale depth map
 *    (near=bright)").
 *  - ``"far-bright"``: white = farthest — what Blender 5.x actually wrote,
 *    because it stored the ray's Euclidean distance and emitted
 *    ``norm = depth / max_d`` (near geometry is a SMALL number there).
 *
 * The task that ordered this pass asks for near = bright; Blender's output was
 * the other way round. Rather than silently pick one, the polarity is a
 * parameter so `far-bright` reproduces Blender's bytes exactly.
 */
export type DepthPolarity = "near-bright" | "far-bright";

export const DEFAULT_DEPTH_POLARITY: DepthPolarity = "near-bright";

/**
 * Blender's ``max_d``: the frame's own maximum depth, or 1.0 when nothing was
 * hit.
 *
 * ``max_d = float(depth.max()) if depth.max() > 0 else 1.0`` — normalizing by
 * the frame's own maximum is the whole approach; the zero guard keeps an empty
 * frame (an all-zero depth buffer) from dividing by zero. 0 marks "no
 * geometry" everywhere in this module, so it is skipped both as a sample and
 * as a candidate maximum.
 */
export function frameMaxDepth(samples: ArrayLike<number>): number {
  let max = 0;
  for (let i = 0; i < samples.length; i += 1) {
    const sample = samples[i];
    if (sample > max) max = sample;
  }
  return max > 0 ? max : 1;
}

/**
 * Distances (camera-plane, >0) to greyscale bytes, one per pixel.
 *
 * - background (0 / non-finite) stays 0: black, the "no geometry" value,
 *   which is also what Blender wrote for a ray that hit nothing;
 * - geometry is ``distance / maxDepth`` — Blender's ``norm`` — then mapped to
 *   the requested polarity. The ``min`` is only a guard so a caller-supplied
 *   ``maxDepth`` below the true maximum cannot overflow the byte range;
 *   Blender's own maximum made it a no-op.
 */
export function normalizeDepthToGreyscale(
  samples: ArrayLike<number>,
  options: { maxDepth?: number; polarity?: DepthPolarity } = {},
): Uint8ClampedArray {
  const polarity = options.polarity ?? DEFAULT_DEPTH_POLARITY;
  const maxDepth =
    options.maxDepth !== undefined && options.maxDepth > 0
      ? options.maxDepth
      : frameMaxDepth(samples);
  const out = new Uint8ClampedArray(samples.length);
  for (let i = 0; i < samples.length; i += 1) {
    const sample = samples[i];
    if (!(sample > 0)) {
      out[i] = 0;
      continue;
    }
    const normalized = Math.min(sample, maxDepth) / maxDepth;
    const grey = polarity === "far-bright" ? normalized : 1 - normalized;
    out[i] = Math.round(grey * 255);
  }
  return out;
}

export interface DepthFrameStats {
  /** Blender's ``max_d`` for this frame. */
  maxDepth: number;
  /** Pixels that hit geometry; 0 means an empty (all-black) frame. */
  geometryPixels: number;
  /** Greyscale range actually written — a flat frame has min === max. */
  minGrey: number;
  maxGrey: number;
}

/**
 * Numbers a caller can assert on WITHOUT decoding the PNG.
 *
 * A depth PNG that is entirely background is a legitimate render of an empty
 * scene, which is indistinguishable from a broken capture if all you have is a
 * byte count. `render-frames.mjs` and the browser spec use these stats as the
 * anti-false-pass guard: `geometryPixels > 0` proves the frame is not black and
 * `maxGrey - minGrey > 0` proves it is not flat.
 */
export function depthFrameStats(
  samples: ArrayLike<number>,
  pixels?: ArrayLike<number>,
): DepthFrameStats {
  let geometryPixels = 0;
  let minGrey = 255;
  let maxGrey = 0;
  for (let i = 0; i < samples.length; i += 1) {
    if (samples[i] > 0) geometryPixels += 1;
    if (pixels) {
      const grey = pixels[i];
      if (grey < minGrey) minGrey = grey;
      if (grey > maxGrey) maxGrey = grey;
    }
  }
  if (!pixels) {
    minGrey = 0;
    maxGrey = 0;
  }
  return { maxDepth: frameMaxDepth(samples), geometryPixels, minGrey, maxGrey };
}

// ---------------------------------------------------------------------------
// Reading the depth render back: 24-bit packed window depth -> distance
// ---------------------------------------------------------------------------

/**
 * `MeshDepthMaterial` with `RGBADepthPacking` writes `packDepthToRGBA(
 * fragCoordZ)` (three's ShaderChunk/packing.glsl.js). The four channels are a
 * 24-bit fixed-point window depth, which is decoded with the same constants
 * the shader uses (`UnpackFactors4` = `vec4((255/256)/1, (255/256)/256,
 * (255/256)/65536, 1/16777216)`), then converted to a positive camera-plane
 * distance with `perspectiveDepthToViewZ`.
 *
 * RGBADepthPacking (24 bits) rather than BasicDepthPacking (8 bits) is
 * deliberate: the preview camera is near=0.1 / far=1000, and window depth is
 * hyperbolically distributed, so at 8 bits everything past ~10 units collapses
 * onto the same one or two byte values — a "depth map" with no depth in it.
 *
 * The factors below are `UnpackFactors4` with the byte->[0,1] division folded
 * in, so they multiply the raw bytes `readRenderTargetPixels` returns.
 *
 * A pixel of all zeroes is the cleared background (`packDepthToRGBA` maps
 * v <= 0 to (0,0,0,0)); the only false positive is geometry sitting exactly on
 * the near plane, which reads as background and is accepted as an edge case.
 */
const UNPACK_FACTORS = [1 / 256, 1 / 65536, 1 / 16777216, 1 / 4294967296];

export function unpackDepthReadback(
  rgba: ArrayLike<number>,
  near: number,
  far: number,
  out?: Float32Array,
): Float32Array {
  const count = rgba.length / 4;
  const distances = out && out.length === count ? out : new Float32Array(count);
  for (let i = 0, p = 0; i < count; i += 1, p += 4) {
    const r = rgba[p];
    const g = rgba[p + 1];
    const b = rgba[p + 2];
    const a = rgba[p + 3];
    if (r === 0 && g === 0 && b === 0 && a === 0) {
      distances[i] = 0;
      continue;
    }
    const windowDepth = r * UNPACK_FACTORS[0] + g * UNPACK_FACTORS[1] + b * UNPACK_FACTORS[2] + a * UNPACK_FACTORS[3];
    const viewZ = (near * far) / ((far - near) * windowDepth - far);
    distances[i] = viewZ < 0 ? -viewZ : 0;
  }
  return distances;
}

// ---------------------------------------------------------------------------
// The GL seam
// ---------------------------------------------------------------------------

/**
 * Flip a greyscale buffer vertically, in place of nothing: returns a new buffer.
 *
 * `readRenderTargetPixels` hands back rows in GL order — row 0 is the BOTTOM of
 * the rendered image — while every image format (and the PNG encoder below)
 * expects row 0 at the TOP. Skipping this flip does not lose information, it
 * just hands the caller an upside-down depth map, which is exactly the kind of
 * bug that survives a byte-count assertion. Pure, so it is unit-tested.
 */
export function flipGreyscaleRows(
  pixels: ArrayLike<number>,
  width: number,
  height: number,
): Uint8ClampedArray {
  const flipped = new Uint8ClampedArray(pixels.length);
  for (let row = 0; row < height; row += 1) {
    const target = row * width;
    const source = (height - 1 - row) * width;
    for (let column = 0; column < width; column += 1) {
      flipped[target + column] = pixels[source + column];
    }
  }
  return flipped;
}

/**
 * The slice of `THREE.WebGLRenderer` this pass uses. Structural so a test can
 * hand in a stub and assert the orchestration (what gets overridden, what gets
 * restored) without a GPU.
 */
export interface DepthPassRenderer {
  getRenderTarget(): THREE.WebGLRenderTarget | null;
  setRenderTarget(target: THREE.WebGLRenderTarget | null): void;
  getClearColor(target: THREE.Color): THREE.Color;
  getClearAlpha(): number;
  setClearColor(color: THREE.ColorRepresentation, alpha?: number): void;
  setClearAlpha(alpha: number): void;
  render(scene: THREE.Scene, camera: THREE.Camera): void;
  readRenderTargetPixels(
    renderTarget: THREE.WebGLRenderTarget,
    x: number,
    y: number,
    width: number,
    height: number,
    buffer: ArrayLike<number> & { set(array: ArrayLike<number>, offset?: number): void },
  ): void;
}

export interface DepthPassFrame {
  width: number;
  height: number;
  /** One greyscale byte per pixel; 0 = no geometry (black background). */
  pixels: Uint8ClampedArray;
  /** The frame's own maximum distance (Blender's ``max_d``); 1 when empty. */
  maxDepth: number;
  /** Pixels that hit geometry. */
  geometryPixels: number;
}

/**
 * The camera the pass reads `near`/`far` from. `Camera` no longer carries them
 * in three r186, and the window-depth -> distance conversion needs them; the
 * preview's camera (and every other three camera used for rendering) has both.
 */
export type DepthPassCamera = THREE.Camera & { near: number; far: number };

export interface DepthPassSize {
  width: number;
  height: number;
}

export interface DepthPassCaptureOptions {
  polarity?: DepthPolarity;
  size?: DepthPassSize;
}

/**
 * Renders a scene's depth into a greyscale frame, one call per frame.
 *
 * Owns the render target (with its `DepthTexture`) and the override material;
 * every renderer/scene state it touches is saved and restored, and the restore
 * runs in a `finally` so a failed read cannot leave the live preview rendering
 * with a depth material.
 */
export class DepthPassCapture {
  readonly polarity: DepthPolarity;
  private readonly renderer: DepthPassRenderer;
  private readonly material: THREE.MeshDepthMaterial;
  private target: THREE.WebGLRenderTarget | null = null;
  private readback: Uint8Array | null = null;
  private distances: Float32Array | null = null;
  private size: DepthPassSize;

  constructor(renderer: DepthPassRenderer, options: DepthPassCaptureOptions = {}) {
    this.renderer = renderer;
    this.polarity = options.polarity ?? DEFAULT_DEPTH_POLARITY;
    // 24-bit packed depth: RGBADepthPacking writes (r, g, b, a) = one 24-bit
    // window depth. BasicDepthPacking would be an 8-bit greyscale of the same
    // value, which the preview's near=0.1/far=1000 camera destroys (see
    // unpackDepthReadback).
    this.material = new THREE.MeshDepthMaterial({ depthPacking: THREE.RGBADepthPacking });
    this.size = { width: 0, height: 0 };
    if (options.size) this.ensureSize(options.size.width, options.size.height);
  }

  /** The size the current render target was allocated for (0 before first capture). */
  get frameSize(): DepthPassSize {
    return { ...this.size };
  }

  /**
   * Render `scene` from `camera` as a depth frame at `size`.
   *
   * `size` is the caller's drawing-buffer size (the preview passes
   * `gl.getDrawingBufferSize()`), so the pass is captured at the same
   * resolution as the colour frames it ships beside.
   */
  capture(scene: THREE.Scene, camera: DepthPassCamera, size: DepthPassSize): DepthPassFrame {
    this.ensureSize(size.width, size.height);
    const target = this.target;
    if (!target) throw new Error("DepthPassCapture: render target was not allocated");
    const { width, height } = this.size;
    const readback = this.readback;
    if (!readback) throw new Error("DepthPassCapture: readback buffer was not allocated");

    const previousTarget = this.renderer.getRenderTarget();
    const previousClearColor = this.renderer.getClearColor(new THREE.Color());
    const previousClearAlpha = this.renderer.getClearAlpha();
    const previousOverride = scene.overrideMaterial;
    const previousBackground = scene.background;

    try {
      // Clear to transparent black: unrendered pixels must read back as the
      // all-zeroes "no geometry" value, not as the scene's background colour.
      // The scene's own background is hidden because it would be drawn with
      // the override material and produce phantom depth.
      this.renderer.setClearColor(0x000000, 0);
      scene.background = null;
      scene.overrideMaterial = this.material;
      this.renderer.setRenderTarget(target);
      this.renderer.render(scene, camera);
      this.renderer.readRenderTargetPixels(target, 0, 0, width, height, readback);
    } finally {
      scene.overrideMaterial = previousOverride;
      scene.background = previousBackground;
      this.renderer.setClearColor(previousClearColor, previousClearAlpha);
      this.renderer.setRenderTarget(previousTarget);
    }

    const distances = this.distances;
    if (!distances) throw new Error("DepthPassCapture: distance buffer was not allocated");
    unpackDepthReadback(readback, camera.near, camera.far, distances);
    // One implementation of "how much of this frame has geometry" (and of
    // Blender's max_d), shared with callers that hold raw samples.
    const stats = depthFrameStats(distances);
    const normalized = normalizeDepthToGreyscale(distances, {
      maxDepth: stats.maxDepth,
      polarity: this.polarity,
    });
    return {
      width,
      height,
      // Image order (top row first), which is what the encoder and every image
      // format expect — readRenderTargetPixels is bottom-up.
      pixels: flipGreyscaleRows(normalized, width, height),
      maxDepth: stats.maxDepth,
      geometryPixels: stats.geometryPixels,
    };
  }

  dispose(): void {
    this.target?.dispose();
    this.target = null;
    this.readback = null;
    this.distances = null;
    this.material.dispose();
    this.size = { width: 0, height: 0 };
  }

  private ensureSize(width: number, height: number): void {
    const w = Math.max(1, Math.floor(width));
    const h = Math.max(1, Math.floor(height));
    if (this.target && this.size.width === w && this.size.height === h) return;
    // Recreated rather than `setSize()`-ed: a resize disposes the render target
    // and its depth texture anyway, and allocating fresh makes the lifecycle
    // obvious instead of depending on three's re-binding path.
    this.target?.dispose();
    this.target = new THREE.WebGLRenderTarget(w, h, {
      depthTexture: new THREE.DepthTexture(w, h),
    });
    this.size = { width: w, height: h };
    this.readback = new Uint8Array(w * h * 4);
    this.distances = new Float32Array(w * h);
  }
}

// ---------------------------------------------------------------------------
// PNG encoding (thin seam; the pixels are already greyscale)
// ---------------------------------------------------------------------------

/** The greyscale frame `encodeDepthPng` consumes. */
export interface DepthPngFrame {
  width: number;
  height: number;
  pixels: ArrayLike<number>;
}

export type CanvasFactory = () => HTMLCanvasElement | null;

function defaultCanvasFactory(): HTMLCanvasElement | null {
  if (typeof document === "undefined") return null;
  return document.createElement("canvas");
}

/**
 * Greyscale bytes to a PNG `Blob` (one byte per pixel, r=g=b=grey, a=255).
 *
 * Dependency-injected canvas factory so a test (or a worker without a DOM) can
 * supply its own. Browsers emit RGB PNGs rather than true greyscale
 * (colour type 0); writing a real greyscale encoder for this pipe would be
 * bytes better spent elsewhere, and every consumer decodes either form the
 * same way.
 */
export async function encodeDepthPng(
  frame: DepthPngFrame,
  createCanvas: CanvasFactory = defaultCanvasFactory,
): Promise<Blob> {
  const canvas = createCanvas();
  const context = canvas?.getContext("2d");
  if (!canvas || !context) {
    throw new Error("encodeDepthPng: no 2D canvas context available to encode the depth PNG");
  }
  canvas.width = frame.width;
  canvas.height = frame.height;
  const image = context.createImageData(frame.width, frame.height);
  const data = image.data;
  for (let i = 0, p = 0; i < frame.pixels.length; i += 1, p += 4) {
    const grey = frame.pixels[i];
    data[p] = grey;
    data[p + 1] = grey;
    data[p + 2] = grey;
    data[p + 3] = 255;
  }
  context.putImageData(image, 0, 0);
  const blob = await new Promise<Blob | null>((resolve) => {
    canvas.toBlob((result) => resolve(result), "image/png");
  });
  if (!blob) {
    throw new Error("encodeDepthPng: canvas.toBlob produced no PNG");
  }
  return blob;
}
