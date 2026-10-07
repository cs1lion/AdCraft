/**
 * render-frames.mjs — drive the headless previs renderer.
 *
 * Spawned by the API's three.js renderer as a single subprocess, exactly the way
 * the Blender renderer spawns `blender.exe`. It
 *
 *   1. serves `dist/` over a throwaway static server (no dev server, no vite
 *      daemon, nothing left running),
 *   2. opens `render.html` in headless Chrome with the SceneScript in the
 *      fragment,
 *   3. seeks frame by frame and writes `frame_<NNNN>.png` into the output
 *      directory — the SAME layout the Blender renderer produced, so the
 *      encoder, keyframe extraction and clip publisher are untouched.
 *
 * `--control-depth` additionally renders the DEPTH control pass (ADR 0005 §4):
 * for every shot's 5 keyframe frames it writes `<out>/control_depth/depth_<N>.png`,
 * N the 0-based SceneScript frame — the layout
 * `control_passes.collect_control_passes` collects beside the colour frames,
 * and the same one the Blender renderer produced before the three.js swap. A
 * depth frame the page reports as having no geometry is a failure, not a black
 * PNG on disk: that is the trap that let 12 identical black frames "pass".
 *
 * CAPTURE PATH — read this before "optimising" it.
 * The first implementation captured in-page with `canvas.toDataURL()` and
 * produced 481 byte-identical PNGs while the playhead advanced correctly. The
 * context really did have `preserveDrawingBuffer: true` (verified at runtime
 * through `getContextAttributes()`), the canvas really was being redrawn (a
 * Playwright element screenshot of the same canvas differed on every frame), and
 * yet `toDataURL` kept returning the first frame. So the in-page read is not
 * trustworthy here and this driver captures with an element screenshot instead,
 * which reads the composited surface.
 *
 * Two guards that exist because this exact class of bug shipped twice:
 *   - a frame under 2000 bytes is treated as black and fails the render;
 *   - every captured frame is hashed, and a hash equal to the PREVIOUS frame's
 *     fails the render. A frozen canvas must not be able to produce a "passing"
 *     run. Both are deliberate: they make the driver slower and louder.
 *
 * Chromium's DEFAULT GL config is what measured fast here (ANGLE over D3D11 on
 * the host's AMD GPU). Forcing OpenGL with --use-angle=gl measured ~5.8x SLOWER,
 * so this script passes no GL flags and this comment is why.
 */

import { createServer } from "node:http";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { existsSync, mkdirSync } from "node:fs";
import {
  extname,
  join,
  normalize,
  resolve,
} from "node:path";
import { chromium } from "playwright";

import { describeMissingFrontend, resolveWebRoot } from "./render-frames-paths.mjs";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".webp": "image/webp",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".map": "application/json",
};

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i === -1 ? fallback : process.argv[i + 1];
}

// The frontend root this driver renders. Resolved from the DRIVER'S OWN
// LOCATION, never a hardcoded path: a literal here means an operator on another
// machine renders a different checkout's frontend and never knows. The API
// passes `--root` explicitly; this is the fallback for a manual run. The rule
// and its tests live in `render-frames-paths.mjs` — and that test asserts this
// file contains no absolute path literal, so do not paste one back in, not even
// into a comment.
const WEB_ROOT = resolveWebRoot({ explicit: arg("root"), driverUrl: import.meta.url });
const DIST = join(WEB_ROOT, "dist");
const SCRIPT = resolve(arg("script"));
const OUT = resolve(arg("out"));
const START = Number(arg("start", "0"));
const WIDTH = Number(arg("width", "1280"));
const HEIGHT = Number(arg("height", "540"));
/** Consecutive frames allowed to hash identically before the render fails.
 *  0 means "any repeat is a bug". Real scenes do hold still for a frame or two
 *  at a cut, so the default tolerates a short hold but not a frozen canvas. */
const MAX_REPEAT = Number(arg("max-repeat", "3"));
/** Depth control pass: write `<out>/control_depth/depth_<N>.png` per shot
 *  keyframe, the layout `control_passes.collect_control_passes` collects. */
const CONTROL_DEPTH = process.argv.includes("--control-depth");

function fail(code, message) {
  process.stderr.write(`${code}: ${message}\n`);
  process.exit(2);
}

const missingFrontend = describeMissingFrontend(WEB_ROOT);
if (missingFrontend) fail("render_dist_missing", missingFrontend);
if (!existsSync(SCRIPT)) fail("render_script_missing", `no scene script at ${SCRIPT}`);
// The output directory is created here rather than assumed. The API side
// `os.makedirs`'d it, so the only way to notice that the driver relied on the
// caller is to run the driver — which is the manual path a developer debugging a
// render takes, and it died on a raw ENOENT stack trace instead of a coded
// failure. Nothing reads the frames before this point, so creating it early
// costs nothing and makes the driver self-sufficient.
mkdirSync(OUT, { recursive: true });

const scene = JSON.parse(await readFile(SCRIPT, "utf8"));

// --- throwaway static server ----------------------------------------------
const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url ?? "/", "http://localhost");
    const rel = normalize(url.pathname).replace(/^(\.\.[/\\])+/, "");
    const file = join(DIST, rel === "/" ? "index.html" : rel);
    const body = await readFile(file);
    res.writeHead(200, { "Content-Type": MIME[extname(file)] ?? "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404).end("not found");
  }
});
await new Promise((done) => server.listen(0, "127.0.0.1", done));
const base = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch({ channel: "chrome" });
const rendered = [];
let previousHash = null;
let identicalRun = 0;
let wanted = [];
// Depth-pass frames, in the outer scope for the same reason as `wanted`: the
// stdout report runs after the try block, and a scoped const here would crash
// AFTER every frame (colour and depth) had been written correctly.
let depthRendered = [];
const startedAt = Date.now();
try {
  const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT } });
  await page.goto(`${base}/render.html#${encodeURIComponent(JSON.stringify(scene))}`, {
    waitUntil: "load",
  });
  await page.waitForFunction("() => !!window.__previsRender", null, { timeout: 60_000 });
  await page.waitForFunction("() => !!window.__previsSeek", null, { timeout: 60_000 });

  const meta = await page.evaluate(() => window.__previsRender.meta());
  // A discrete frame list (keyframes-only renders) or a contiguous range.
  // --frames takes precedence over --start/--end because "which instants" is
  // the whole point of a keyframes-only pass.
  const framesArg = arg("frames", "");
  const endArg = arg("end", "");
  // `wanted` lives in the outer scope because the stdout report needs it. An
  // IIFE-local const is how this once crashed AFTER every frame had been
  // written correctly — a perfect render reported as a failure.
  if (framesArg) {
    wanted = framesArg
      .split(",")
      .map((v) => Number(v.trim()))
      .filter((v) => Number.isInteger(v) && v >= 0);
  } else {
    // `Number("")` is 0 and `Number.isFinite(0)` is true, so an ABSENT --end used
    // to compute as "frame 0" rather than "not supplied" — the caller asked for
    // a full sequence and got one frame. Treat blank as unset and fall back to
    // the scene's own frame count.
    const end = endArg.trim() ? Number(endArg) : meta.frames - 1;
    if (!Number.isFinite(end)) fail("render_bad_end", `--end is not a number: ${endArg}`);
    wanted = [];
    for (let f = START; f <= end; f += 1) wanted.push(f);
  }
  if (!wanted.length) fail("render_no_frames", "no frames selected");

  const canvas = page.locator("canvas").first();
  await canvas.waitFor({ state: "visible", timeout: 60_000 });

  for (const frame of wanted) {
    await page.evaluate((f) => window.__previsRender.seek(f), frame);
    const shot = await canvas.screenshot();
    const buffer = Buffer.from(shot);

    // Guard 1: a flat black frame compresses to a few hundred bytes.
    if (buffer.length < 2000) {
      fail("render_frame_black", `frame ${frame} produced ${buffer.length} bytes (black?)`);
    }
    // Guard 2: the frozen-canvas trap. Same bytes as the last frame is not a
    // render, and a run of them is how 481 identical PNGs once "succeeded".
    const hash = createHash("sha256").update(buffer).digest("hex");
    if (hash === previousHash) {
      identicalRun += 1;
      if (identicalRun > MAX_REPEAT) {
        fail(
          "render_frames_frozen",
          `frame ${frame} is identical to the previous frame for ${identicalRun} `
            + "consecutive frames — the canvas is not being redrawn",
        );
      }
    } else {
      identicalRun = 0;
    }
    previousHash = hash;

    await writeFile(join(OUT, `frame_${String(frame + 1).padStart(4, "0")}.png`), buffer);
    rendered.push(frame);
  }

  // --- DEPTH control pass -----------------------------------------------------
  // Same 5-keyframes-per-shot sampling the collector re-derives, but the page
  // owns the plan (it must match what the preview renders) — ask it rather than
  // recompute the shot maths here.
  if (CONTROL_DEPTH) {
    const depthFrames = await page.evaluate(() => window.__previsRender.depthFrames());
    const depthDir = join(OUT, "control_depth");
    mkdirSync(depthDir, { recursive: true });
    for (const frame of depthFrames) {
      const { png, stats } = await page.evaluate((f) => window.__previsRender.captureDepth(f), frame);
      const buffer = Buffer.from(png, "base64");
      // The page reports how much of the frame actually has geometry: a depth
      // PNG with nothing in it is a broken capture, not a dark frame, and must
      // not reach the collector (which would count it as an available pass).
      if (!stats || stats.geometryPixels === 0) {
        fail("render_depth_black", `frame ${frame} depth pass has no geometry`);
      }
      if (buffer.length < 200) {
        fail("render_depth_black", `frame ${frame} depth pass is ${buffer.length} bytes`);
      }
      await writeFile(join(depthDir, `depth_${frame}.png`), buffer);
      depthRendered.push(frame);
    }
  }
} finally {
  await browser.close();
  server.close();
}

const seconds = (Date.now() - startedAt) / 1000;
// Blender's contract: the caller counts frame_*.png. Report progress the same
// shape so a timeout diagnosis reads identically either way.
process.stdout.write(
  JSON.stringify({
    frames: rendered.length,
    first: rendered[0],
    last: rendered.at(-1),
    requested: wanted.length,
    depth_frames: CONTROL_DEPTH ? depthRendered.length : null,
    seconds: Math.round(seconds * 10) / 10,
    ms_per_frame: rendered.length ? Math.round((seconds * 1000) / rendered.length) : null,
  }) + "\n",
);
