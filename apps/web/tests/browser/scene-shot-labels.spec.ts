import { expect, test } from "@playwright/test";

// Real-WebGL coverage for the shot-label layer: the camera gizmo in the 3D
// viewport must carry a human-readable name, because a camera you cannot name is
// a camera you cannot ask an agent to move (docs/plans/scene3d-shot-preview-
// bridge.md). The unit tests cover the pure derivation; this proves the label
// actually reaches the DOM through the Html overlay.
test.beforeEach(async ({ page }) => {
  await page.goto("/tests/browser/lean-scene-canvas-mock.html?production=1");
  // Wait for the real preview to be up: the speech overlay is the signal that
  // the scene tree (and therefore the camera gizmo) has rendered.
  await expect(page.getByTestId("speech-overlay-actor")).toBeVisible();
});

test("the camera gizmo carries its shot label", async ({ page }) => {
  const label = page.locator('[data-camera-label="camera"]');
  await expect(label).toHaveText("机位01 | 双人全景");
  // An Html overlay that projects behind the camera, or whose host clipped it,
  // would still be in the DOM while being invisible.
  await expect(label).toBeVisible();
});

test("the active camera's label is marked so the author knows what a drag edits", async ({ page }) => {
  // The production scene has one shot covering every frame, so its camera is
  // the active one for the whole timeline.
  await expect(page.locator('[data-camera-label="camera"]')).toHaveAttribute(
    "data-active",
    "true",
  );
});

test("the label keeps tracking the camera as the playhead moves", async ({ page }) => {
  // The gizmo interpolates between keyframes and the Html overlay re-projects
  // every frame. Asserting on the computed transform (rather than a pixel
  // position) is the honest check: this fixture's move is a pure dolly, which
  // leaves the projected Y almost unchanged even though the camera did move.
  const label = page.locator('[data-camera-label="camera"]');
  // The span carries the name; its parent is the Html wrapper that owns the
  // projected transform, so that is what "the label tracks the camera" means.
  const transformOf = () =>
    label.evaluate((element) => element.parentElement?.style.transform ?? "");
  // The overlay projects in a layout effect, and "visible" only means it has a
  // box — poll until the projection has actually run before reading it.
  await expect.poll(transformOf).toContain("translate3d");
  const transformBefore = await transformOf();
  await page.getByRole("slider", { name: "场景预览时间轴" }).fill("59");
  await expect(page.getByRole("slider", { name: "场景预览时间轴" })).toHaveValue("59");
  await expect.poll(transformOf).not.toBe(transformBefore);
  // The label must survive the move: an overlay whose host re-mounted would
  // drop out of the DOM entirely.
  await expect(label).toBeVisible();
});
