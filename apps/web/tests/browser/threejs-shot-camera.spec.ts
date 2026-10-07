import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * The viewport camera must FOLLOW THE SHOT CAMERA.
 *
 * This is the assertion the renderer was missing. Every earlier "the previs
 * works" check compared PIXELS between frames, and pixels change when
 * characters move too - so a camera frozen on its seed position passed all of
 * them. The camera prop was read once at canvas creation, so every frame after
 * the first rendered from the same vantage while the playhead advanced
 * normally: 720 PNGs, none of them from the shot's camera.
 *
 * So this spec reads the CAMERA'S OWN POSITION across frames. Scene content
 * cannot fake that.
 *
 * The page under test is the REAL render entry (`src/render/PrevisRenderEntry`),
 * not a mock, because the bug lived in the wiring between the preview and that
 * entry. The scene rides in the URL fragment exactly as a render job supplies it.
 *
 * The scene is read from inside this repo (a copy under tests/browser) rather
 * than from ../../test-materials: the absolute repo path does not resolve
 * reliably from every process that runs these specs, and a spec that cannot load
 * its own fixture is a spec that cannot be trusted.
 */

// `__dirname` does not exist in an ES module, and process.cwd() is not reliably
// the web root in a Playwright worker. Resolve from this file instead.
const SCENE = readFileSync(
  new URL("jinghai-scene.json", import.meta.url),
  "utf8",
);
// Not named `URL`: that shadows the global the fixture read above needs.
const PAGE = `/render.html#${encodeURIComponent(SCENE)}`;

// Each probe call is its own evaluate: crossing the boundary twice (get the
// object, then call a method on it) hands back a dead reference.
const seek = (page: Page, frame: number) =>
  page.evaluate((f) => window.__previsRender!.seek(f), frame);
const meta = (page: Page) =>
  page.evaluate(() => window.__previsRender!.meta());

declare global {
  interface Window {
    __previsRender?: {
      seek: (f: number) => Promise<void>;
      cameraPosition: () => [number, number, number] | null;
      meta: () => { frames: number; frameRate: number };
    };
    __previsCameraPosition?: () => [number, number, number] | null;
    /** The LIVE camera, published by the canvas rather than by the caller. */
    __previsLiveCameraPosition?: () => [number, number, number];
  }
}

/**
 * Reads the LIVE camera, never the prop.
 *
 * The distinction is the whole spec. `__previsCameraPosition` reports the pose
 * the preview handed to the canvas; `__previsLiveCameraPosition` reports where
 * the canvas's camera actually is. A spec against the former passes even when
 * the canvas ignores the prop — which is exactly how this renderer shipped a
 * frozen camera while 720 frames "rendered successfully". Verified by mutation:
 * delete the position write in LeanSceneCanvas and this spec goes red.
 */
const liveCamera = (page: Page) =>
  page.evaluate(() => window.__previsLiveCameraPosition?.() ?? null);

test.beforeEach(async ({ page }) => {
  await page.goto(PAGE);
  await page.waitForFunction(
    () => Boolean((window as unknown as { __previsCameraPosition?: unknown }).__previsCameraPosition),
    null,
    { timeout: 60_000 },
  );
});

test("the viewport camera follows the shot camera, frame by frame", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  const info = await meta(page);
  expect(info.frames).toBeGreaterThan(1);

  const positions: [number, number, number][] = [];
  for (let frame = 0; frame < Math.min(info.frames, 60); frame += 6) {
    await seek(page, frame);
    const at = await liveCamera(page);
    expect(at, `live camera position at frame ${frame}`).not.toBeNull();
    positions.push(at as [number, number, number]);
  }

  const moved = positions.some(
    (p, i) => i > 0 && p.some((v, axis) => Math.abs(v - positions[i - 1][axis]) > 1e-6),
  );
  expect(moved, `camera never moved: ${JSON.stringify(positions)}`).toBe(true);

  const seeded = positions.every(
    (p) => Math.abs(p[0] - 8) < 1e-6 && Math.abs(p[1] + 12) < 1e-6,
  );
  expect(seeded, "camera is still the hardcoded [8,-12,6] seed").toBe(false);

  const distinct = new Set(positions.map((p) => p.map((v) => v.toFixed(4)).join(",")));
  expect(distinct.size, `only ${distinct.size} distinct camera positions`).toBeGreaterThan(3);

  expect(errors).toEqual([]);
});

test("a shot cut relocates the camera to the other shot's camera", async ({ page }) => {
  const info = await meta(page);
  const boundary = 240;
  test.skip(boundary >= info.frames, "scene has no second shot to cut to");

  await seek(page, boundary - 1);
  const before = await liveCamera(page);
  await seek(page, boundary);
  const after = await liveCamera(page);

  const distance = Math.hypot(
    (after?.[0] ?? 0) - (before?.[0] ?? 0),
    (after?.[1] ?? 0) - (before?.[1] ?? 0),
    (after?.[2] ?? 0) - (before?.[2] ?? 0),
  );
  expect(distance, `camera did not relocate across the cut d=${distance}`).toBeGreaterThan(0.5);
});
