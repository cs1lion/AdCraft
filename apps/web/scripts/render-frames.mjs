/**
 * render-frames.mjs — drive the headless previs renderer.
 *
 * Spawned by `apps/api/app/services/scene3d/threejs_renderer.py` as a single
 * subprocess, exactly the way the Blender renderer spawns `blender.exe`. It
 *
 *   1. serves `dist/` over a throwaway static server (no dev server, no vite
 *      daemon, nothing left running),
 *   2. opens `render.html` in headless Chrome with the SceneScript in the
 *      fragment,
 *   3. seeks frame by frame and writes `frame_<NNNN>.png` into the output
 *      directory — the SAME layout the Blender renderer produced, so the
 *      encoder, keyframe extraction and clip publisher are untouched.
 *
 * Arguments (argv): --script <path-to-scene-json> --out <dir>
 *                   [--start N] [--end N] [--width W] [--height H]
 *
 * Chromium's DEFAULT GL config is the one that measured 24ms/frame here
 * (ANGLE over D3D11 on the host's AMD GPU). Forcing OpenGL measured 141ms —
 * 5.8x slower — so this script deliberately passes no GL flags and says why.
 */

import { createServer } from "node:http";
import { readFile, writeFile, stat } from "node:fs/promises";
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

function fail(code, message) {
  process.stderr.write(`${code}: ${message}\n`);
  process.exit(2);
}

if (!existsSync(DIST)) fail("render_dist_missing", `no dist at ${DIST} — run npm run build`);
if (!existsSync(SCRIPT)) fail("render_script_missing", `no scene script at ${SCRIPT}`);

const scene = JSON.parse(await readFile(SCRIPT, "utf8"));

// --- static server ---------------------------------------------------------
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
const port = server.address().port;
const base = `http://127.0.0.1:${port}`;

const browser = await chromium.launch({ channel: "chrome" });
const rendered = [];
try {
  const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT } });
  // The script rides in the fragment: it can be tens of kilobytes and must not
  // show up in any server log.
  await page.goto(`${base}/render.html#${encodeURIComponent(JSON.stringify(scene))}`, {
    waitUntil: "load",
  });
  await page.waitForFunction("() => !!window.__previsRender", null, { timeout: 60_000 });
  await page.waitForFunction(
    "() => window.__previsRender && !!window.__previsSeek",
    null,
    { timeout: 60_000 },
  );

  const meta = await page.evaluate(() => window.__previsRender.meta());
  const end = Number.isFinite(Number(arg("end", String(meta.frames - 1))))
    ? Number(arg("end", String(meta.frames - 1)))
    : meta.frames - 1;

  for (let frame = START; frame <= end; frame += 1) {
    await page.evaluate((f) => window.__previsRender.seek(f), frame);
    const base64 = await page.evaluate(() => window.__previsRender.capture());
    const buffer = Buffer.from(base64, "base64");
    // A flat black PNG is a few hundred bytes. Rather than write it and let the
    // caller discover the problem, fail now with the frame number.
    if (buffer.length < 2000) {
      fail("render_frame_black", `frame ${frame} produced ${buffer.length} bytes (black?)`);
    }
    await writeFile(join(OUT, `frame_${String(frame + 1).padStart(4, "0")}.png`), buffer);
    rendered.push(frame);
  }
} finally {
  await browser.close();
  server.close();
}

// Blender's contract: the caller counts frame_*.png. Report progress on stdout
// the same shape so a timeout diagnosis is identical either way.
process.stdout.write(
  JSON.stringify({ frames: rendered.length, first: rendered[0], last: rendered.at(-1) }) + "\n",
);
