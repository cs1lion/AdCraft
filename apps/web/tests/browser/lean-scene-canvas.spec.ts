import { expect, test, type Page } from "@playwright/test";

type Snapshot = { sceneRenders: number; sceneSetups: number; sceneCleanups: number; ticks: number; triangles: number; lost: boolean; meshes: number; color: string; width: number; height: number; top: number; left: number; selected: number; missed: number; drags: number; orbit: string };
const snapshot = (page: Page) => page.evaluate(() => (window as unknown as { leanScene: { snapshot: () => Snapshot } }).leanScene.snapshot());
const point = (page: Page) => page.evaluate(() => (window as unknown as { leanScene: { project: () => { x: number; y: number } } }).leanScene.project());

test.beforeEach(async ({ page }, info) => {
  if (info.title.startsWith("production")) return;
  await page.goto("/tests/browser/lean-scene-canvas-mock.html");
  await expect.poll(async () => (await snapshot(page)).triangles).toBeGreaterThan(10);
});

test("real WebGL geometry, finite catalogue, Grid/Html, context and StrictMode survival", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await expect(page.getByTestId("context-label")).toHaveText("red");
  expect((await snapshot(page)).meshes).toBeGreaterThan(25);
  // React 19 nested StrictMode replays renders, not effects, when the
  // secondary reconciler root itself isn't strict (also true of stock Canvas).
  expect((await snapshot(page)).sceneRenders).toBeGreaterThanOrEqual(2);
  expect((await snapshot(page)).sceneSetups).toBe(1);
  expect((await snapshot(page)).sceneCleanups).toBe(0);
  const pixel = await page.evaluate(() => (window as unknown as { leanScene: { pixel: () => number[] } }).leanScene.pixel());
  expect(pixel[0]).toBeGreaterThan(pixel[2]);
  const before = await snapshot(page);
  // R3F's uncancellable unmount disposal is 500ms: don't only test replay's
  // first frame. Poll until elapsed >650ms, then prove animation and GL live.
  const until = Date.now() + 650;
  await expect.poll(() => Date.now(), { timeout: 2_000 }).toBeGreaterThan(until);
  const after = await snapshot(page);
  expect(after.ticks).toBeGreaterThan(before.ticks);
  expect(after.lost).toBe(false);
  await page.getByRole("button", { name: "context", exact: true }).click();
  await expect(page.getByTestId("context-label")).toHaveText("blue");
  await expect.poll(async () => (await snapshot(page)).color).toBe("blue");
  expect(errors).toEqual([]);
});

test("selection, pointer missed, orbit and object drag stay independent", async ({ page }) => {
  let center = await point(page);
  await page.mouse.click(center.x, center.y);
  await expect.poll(async () => (await snapshot(page)).selected).toBe(1);
  const canvas = await page.locator("canvas").boundingBox();
  if (!canvas) throw new Error("No canvas");
  await page.mouse.click(canvas.x + 10, canvas.y + 10);
  await expect.poll(async () => (await snapshot(page)).missed).toBeGreaterThan(0);
  const orbit = (await snapshot(page)).orbit;
  await page.mouse.move(canvas.x + 35, canvas.y + 80);
  await page.mouse.down();
  await page.mouse.move(canvas.x + 100, canvas.y + 120, { steps: 8 });
  await page.mouse.up();
  await expect.poll(async () => (await snapshot(page)).orbit).not.toBe(orbit);
  center = await point(page);
  await page.mouse.move(center.x, center.y);
  await page.mouse.down();
  await page.mouse.move(center.x + 50, center.y, { steps: 10 });
  await page.mouse.up();
  await expect.poll(async () => (await snapshot(page)).drags).toBeGreaterThan(0);
});

test("resize, nested scroll, and rapid true remount do not lose the new context", async ({ page }) => {
  await page.getByRole("button", { name: "resize", exact: true }).click();
  await expect.poll(async () => (await snapshot(page)).width).toBe(760);
  await expect.poll(async () => (await snapshot(page)).height).toBe(400);
  const before = (await snapshot(page)).top;
  await page.getByTestId("scroll").evaluate((element) => { element.scrollTop = 40; });
  await expect.poll(async () => (await snapshot(page)).top).toBe(before - 40);
  await page.getByRole("button", { name: "remount", exact: true }).click();
  await expect(page.getByTestId("context-label")).toBeVisible();
  const until = Date.now() + 650;
  await expect.poll(() => Date.now(), { timeout: 2_000 }).toBeGreaterThan(until);
  expect((await snapshot(page)).lost).toBe(false);
  expect((await snapshot(page)).triangles).toBeGreaterThan(10);
});

test("production SceneScript preview renders every registered asset and playback context", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/tests/browser/lean-scene-canvas-mock.html?production=1");
  await expect(page.getByTestId("speech-overlay-actor")).toHaveText("real preview context");
  await expect(page.getByTestId("blocking-length-actor")).toContainText("1.0m");
  await expect(page.getByRole("slider", { name: "场景预览时间轴" })).toHaveValue("0");
  const until = Date.now() + 650;
  await expect.poll(() => Date.now(), { timeout: 2_000 }).toBeGreaterThan(until);
  await expect(page.getByTestId("speech-overlay-actor")).toBeVisible();
  await page.getByRole("slider", { name: "场景预览时间轴" }).fill("30");
  await expect(page.getByRole("slider", { name: "场景预览时间轴" })).toHaveValue("30");
  await expect(page.getByTestId("speech-overlay-actor")).toBeVisible();
  await page.getByRole("button", { name: "播放场景预览" }).click();
  await expect(page.getByRole("button", { name: "暂停场景预览" })).toBeVisible();
  await page.getByRole("button", { name: "暂停场景预览" }).click();
  expect(errors).toEqual([]);
});

test("production baseline Canvas and lean Canvas inherit matching React 19 StrictMode semantics", async ({ page }) => {
  await page.goto("/tests/browser/lean-scene-canvas-mock.html?baseline=1");
  await expect.poll(async () => (await snapshot(page)).triangles).toBeGreaterThan(10);
  const baseline = await snapshot(page);
  expect(baseline.sceneRenders).toBeGreaterThanOrEqual(2);
  expect(baseline.sceneSetups).toBe(1);
  expect(baseline.sceneCleanups).toBe(0);
  await page.goto("/tests/browser/lean-scene-canvas-mock.html");
  await expect.poll(async () => (await snapshot(page)).triangles).toBeGreaterThan(10);
  const lean = await snapshot(page);
  expect(lean.sceneRenders).toBeGreaterThanOrEqual(2);
  expect(lean.sceneSetups).toBe(baseline.sceneSetups);
  expect(lean.sceneCleanups).toBe(baseline.sceneCleanups);
});

test("real scene errors reach the DOM boundary", async ({ page }) => {
  await page.getByRole("button", { name: "error", exact: true }).click();
  await expect(page.getByTestId("error")).toHaveText("lean scene deliberate error");
});

test("real scene suspense reaches the DOM fallback and resumes", async ({ page }) => {
  await page.getByRole("button", { name: "suspend", exact: true }).click();
  await expect(page.getByTestId("loading")).toBeVisible();
  await page.evaluate(() => (window as unknown as { leanScene: { resolve: () => void } }).leanScene.resolve());
  await expect(page.getByTestId("loading")).toHaveCount(0);
  await expect.poll(async () => (await snapshot(page)).triangles).toBeGreaterThan(10);
});
