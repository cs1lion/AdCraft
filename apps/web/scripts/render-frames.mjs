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
import { existsSync } from "node:fs";
import { extname, join, normalize, resolve } from "node:path";
import { chromium } from "playwright";

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

const WEB_ROOT = resolve(arg("root", "D:/project/myAdCraft/apps/web"));
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

function fail(code, message) {
  process.stderr.write(`${code}: ${message}\n`);
  process.exit(2);
}

if (!existsSync(DIST)) fail("render_dist_missing", `no dist at ${DIST} — run npm run build`);
if (!existsSync(SCRIPT)) fail("render_script_missing", `no scene script at ${SCRIPT}`);

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
const startedAt = Date.now();
try {
  const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT } });
  await page.goto(`${base}/render.html#${encodeURIComponent(JSON.stringify(scene))}`, {
    waitUntil: "load",
  });
  await page.waitForFunction("() => !!window.__previsRender", null, { timeout: 60_000 });
  await page.waitForFunction("() => !!window.__previsSeek", null, { timeout: 60_000 });

  const meta = await page.evaluate(() => window.__previsRender.meta());
  const end = Number.isFinite(Number(arg("end", "")))
    ? Number(arg("end"))
    : meta.frames - 1;

  const canvas = page.locator("canvas").first();
  await canvas.waitFor({ state: "visible", timeout: 60_000 });

  for (let frame = START; frame <= end; frame += 1) {
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
    seconds: Math.round(seconds * 10) / 10,
    ms_per_frame: rendered.length ? Math.round((seconds * 1000) / rendered.length) : null,
  }) + "\n",
);
