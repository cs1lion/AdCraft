import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * The render camera must be where the SCRIPT says it is — in the right place,
 * pointing the right way.
 *
 * This spec exists because three separate attempts to fix the same defect passed
 * every check that was written for them, and the third passed its own new spec
 * too. What actually went wrong, in order:
 *
 *   1. `LeanSceneCanvas` reads its `camera` prop ONCE, in a mount-only effect,
 *      to construct the `PerspectiveCamera`. A prop that changes with the
 *      playhead therefore does nothing, and every frame after the first rendered
 *      from the seed position. Checked by comparing FRAME PIXELS — which change
 *      anyway when a character walks, so a frozen camera passed them all.
 *   2. Writing the prop into the live camera fixed (1) and left two layers: the
 *      pose was passed in SceneScript coordinates (Z-up) straight to a three.js
 *      camera (Y-up), and `look_at` was never applied at all — the canvas camera
 *      is constructed aimed at the world origin. Shot 1 of this very scene then
 *      rendered 18 m underground, which looks identical to having no fix: an
 *      empty green screen with floating labels.
 *   3. The spec written for (2) could not see either layer, because every one of
 *      its assertions was RELATIVE — "the camera moved", "it is not the seed",
 *      "more than three distinct positions", "it relocated across the cut". A
 *      mirrored, unaimed camera satisfies all four.
 *
 * So every assertion here is ABSOLUTE, against literals derived by hand from
 * `jinghai-scene.json`, and includes the facing direction. Relative assertions
 * are kept only as a second line of defence, never as the primary one.
 *
 * The page under test is the REAL render entry (`render.html`), not a mock,
 * because the defect lived in the wiring between the preview and that entry.
 *
 * The scene is a copy under tests/browser rather than ../../test-materials: an
 * absolute repo path does not resolve reliably from every process that runs
 * these specs, and a spec that cannot load its own fixture cannot be trusted.
 */

// `__dirname` does not exist in an ES module, and process.cwd() is not reliably
// the web root in a Playwright worker. Resolve from this file instead.
const SCENE = readFileSync(new URL("jinghai-scene.json", import.meta.url), "utf8");
// Not named `URL`: that would shadow the global the fixture read above needs.
const PAGE = `/render.html#${encodeURIComponent(SCENE)}`;

/**
 * SceneScript [x, y, z] = [right, forward, up] -> three.js [x, z, y] = [right, up,
 * back]. The same swap `SceneScript3DPreview` applies; a spec that asserted raw
 * keyframe numbers would pass against a mirrored camera, which is the bug.
 */
const toThree = ([x, y, z]: number[]): [number, number, number] => [x, z, y];

const distance = (a: number[], b: number[]) =>
  Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

/** The unit vector from `position` towards `lookAt`, in three.js space. */
const forwardTowards = (position: number[], lookAt: number[]) => {
  const target = toThree(lookAt);
  const direction = [
    target[0] - position[0],
    target[1] - position[1],
    target[2] - position[2],
  ];
  const length = Math.hypot(...direction);
  return direction.map((value) => value / length);
};

/**
 * What the camera must be at three frames, one per interesting shot, computed by
 * hand from the fixture:
 *
 *   frame   0  shot_moon_wide / cam_wide    scene [20,-18,6] look_at [0,0,2]
 *           -> three [20, 6,-18], forward towards [0,2,0]
 *   frame 240  shot_airlock_run / cam_airlock scene [6,2,1.6] look_at [0,5,1.2]
 *           -> three [6, 1.6, 2], forward towards [0,1.2,5]
 *   frame 600  shot_dropship / cam_sky      scene [2,-14,1.0] look_at [6,-4,6]
 *           -> three [2, 1.0, -14], forward towards [6,6,-4]
 *
 * Frame 0 is the one that separates a correct camera from an axis-swapped one:
 * the two candidate placements are 18 m apart vertically, so no tolerance hides
 * it. Frame 240 is the interesting near-miss — the swapped and correct positions
 * are only 0.4 m apart, so its value is in the FORWARD vector, where aiming at
 * the origin instead of `look_at` is off by ~90 degrees.
 */
const EXPECTED: { frame: number; position: number[]; forward: number[]; note: string }[] = [
  { frame: 0, position: toThree([20, -18, 6]), forward: forwardTowards(toThree([20, -18, 6]), [0, 0, 2]), note: "shot 1 keyframe 0" },
  { frame: 240, position: toThree([6, 2, 1.6]), forward: forwardTowards(toThree([6, 2, 1.6]), [0, 5, 1.2]), note: "shot 2 first frame" },
  { frame: 600, position: toThree([2, -14, 1.0]), forward: forwardTowards(toThree([2, -14, 1.0]), [6, -4, 6]), note: "shot 4 first frame" },
];

/** A keyframe 120 frames into shot 1, to separate "follows the shot" from "moves". */
const MID_SHOT: { frame: number; position: number[]; forward: number[] } = {
  frame: 120,
  position: toThree([16, -12, 5]),
  forward: forwardTowards(toThree([16, -12, 5]), [0, 0, 2]),
};

declare global {
  interface Window {
    __previsRender?: {
      seek: (f: number) => Promise<void>;
      camera: () => { position: [number, number, number]; forward: [number, number, number] } | null;
      meta: () => { frames: number; frameRate: number };
    };
  }
}

/**
 * Reads the LIVE camera off the canvas, never the pose the preview intended.
 * That distinction is the whole spec: a probe reporting the intent passes when
 * the renderer ignores it. Verified by mutation — removing the rig's camera write
 * turns these red.
 */
const liveCamera = async (page: Page, frame: number) => {
  // Each probe call is its own evaluate: crossing the boundary twice (get the
  // object, then call a method on it) hands back a dead reference.
  await page.evaluate((f) => window.__previsRender!.seek(f), frame);
  const camera = await page.evaluate(() => window.__previsRender!.camera());
  expect(camera, `no live camera published at frame ${frame}`).not.toBeNull();
  return camera!;
};

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(PAGE);
  // The render entry sets this once the preview is mounted; waiting on it rather
  // than on a timeout is what keeps a broken page from looking like a slow one.
  await page.waitForFunction(() => Boolean(window.__previsRender), null, { timeout: 60_000 });
  expect(errors).toEqual([]);
});

for (const { frame, position, forward, note } of EXPECTED) {
  test(`frame ${frame} puts the camera at the shot's position, axis-converted (${note})`, async ({ page }) => {
    const camera = await liveCamera(page, frame);
    expect(
      distance(camera.position, position),
      `camera at ${JSON.stringify(camera.position)}, expected ${JSON.stringify(position)} — `
        + "an axis-swapped placement lands here too (SceneScript is Z-up, three.js is Y-up)",
    ).toBeLessThan(0.05);
  });

  test(`frame ${frame} aims the camera at the shot's look_at (${note})`, async ({ page }) => {
    const camera = await liveCamera(page, frame);
    expect(
      distance(camera.forward, forward),
      `camera faces ${JSON.stringify(camera.forward)}, expected ${JSON.stringify(forward)} — `
        + "the canvas camera is CONSTRUCTED looking at the world origin, so aiming "
        + "has to be asserted on its own",
    ).toBeLessThan(0.02);
  });
}

test("the camera follows a move WITHIN one shot", async ({ page }) => {
  // Frame 0 and frame 120 are both shot 1, on the same camera. A rig that only
  // jumped at cuts would render these identically, which is the original defect
  // at a smaller scale.
  const atStart = await liveCamera(page, 0);
  const atMid = await liveCamera(page, MID_SHOT.frame);
  expect(distance(atMid.position, MID_SHOT.position)).toBeLessThan(0.05);
  expect(distance(atMid.forward, MID_SHOT.forward)).toBeLessThan(0.02);
  expect(distance(atStart.position, atMid.position), "the camera did not move within the shot").toBeGreaterThan(3);
});

test("each shot's own camera is used, and the positions are all distinct", async ({ page }) => {
  const seen: number[][] = [];
  for (const { frame } of EXPECTED) {
    seen.push((await liveCamera(page, frame)).position);
  }
  const distinct = new Set(seen.map((p) => p.map((v) => v.toFixed(3)).join(",")));
  expect(distinct.size, `only ${distinct.size} distinct camera positions across three shots`).toBe(3);
});

test("the camera is never left at the canvas seed", async ({ page }) => {
  // Kept as a cheap canary even though the absolute assertions above already
  // cover it: it names the specific historical value, so a regression reads as
  // "back to the seed" rather than as an unexplained number.
  const seed = toThree([8, -12, 6]);
  for (const { frame } of EXPECTED) {
    const camera = await liveCamera(page, frame);
    expect(distance(camera.position, seed), `frame ${frame} is back on the [8,-12,6] seed`).toBeGreaterThan(1);
  }
});