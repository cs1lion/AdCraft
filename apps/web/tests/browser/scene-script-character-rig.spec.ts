import { expect, test, type Page } from "@playwright/test";

/**
 * The character silhouette IS the product.
 *
 * The plan (docs/plans/threejs-renderer-replacement.md §3.6) replaces the
 * Blender renderer with a server render of THIS preview, which makes the
 * browser rig the deliverable: the old rig drew a box with a sphere on top, so
 * "a box character" would ship. This spec mounts the preview with one
 * character and counts the meshes that character actually draws, through the
 * same `window.leanScene` count the lean-scene-canvas harness already exposes
 * (the fixture behind `?character=1` mounts nothing else, so the count is that
 * character's own).
 */

type CharacterParts = Partial<Record<"box" | "sphere" | "cylinder" | "cone" | "other", number>>;
type Snapshot = { characterMeshes: number; characterParts: CharacterParts };
const snapshot = (page: Page) =>
  page.evaluate(() => (window as unknown as { leanScene: { snapshot: () => Snapshot } }).leanScene.snapshot());

test.beforeEach(async ({ page }) => {
  await page.goto("/tests/browser/lean-scene-canvas-mock.html?character=1");
  // The speech overlay is the Html-driven proof the character is mounted (and
  // talking), so the scene tree is up before anything is counted.
  await expect(page.getByTestId("speech-overlay-lone")).toBeVisible();
  await expect.poll(async () => (await snapshot(page)).characterMeshes).toBeGreaterThan(0);
});

test("the character is the converter's seven-segment rig, not a box and a head", async ({ page }) => {
  // Blender's lowpoly_human draws torso + neck + head + LegL/LegR + ArmL/ArmR
  // (blender_converter.py _build_lowpoly_human). The preview adds the mouth and
  // the ID label cone on top: 9 meshes. The rig this replaces drew 3 — one torso
  // box, one head sphere, the mouth.
  const { characterMeshes, characterParts } = await snapshot(page);
  expect(characterMeshes).toBe(9);
  // 6 boxes where the old rig had 2 (torso + mouth): the torso plus four limbs.
  // A character whose legs are boxes with a gap between them reads as legs;
  // a character whose whole body is one box does not read as a person.
  expect(characterParts.box).toBe(6);
  expect(characterParts.sphere).toBe(1); // head
  expect(characterParts.cylinder).toBe(1); // neck: a part the old rig had no place for
  expect(characterParts.cone).toBe(1); // ID label
});

test("the canvas still draws the character, in its own colour", async ({ page }) => {
  // A mesh count is not a picture. Screenshot the composited surface — reading
  // the canvas' own drawing buffer from JS after compositing sees a cleared
  // buffer, which is how the first capture attempt produced 12 identical black
  // PNGs (threejs-capture.spec.ts). Then prove the character's APPEARANCE
  // colour is on screen: a body painted the script's colour is the other half
  // of "the preview agrees with the render".
  const canvas = page.locator("canvas").first();
  await expect.poll(async () => (await canvas.boundingBox())?.width ?? 0).toBeGreaterThan(50);
  const shot = await canvas.screenshot();
  // A flat fill compresses to a couple of hundred bytes; a scene does not.
  expect(shot.byteLength).toBeGreaterThan(5000);
  const painted = await page.evaluate(async (dataUrl) => {
    const image = new Image();
    image.src = dataUrl;
    await image.decode();
    const surface = document.createElement("canvas");
    surface.width = image.width;
    surface.height = image.height;
    const context = surface.getContext("2d");
    if (!context) return { lit: 0, body: 0 };
    context.drawImage(image, 0, 0);
    const { data } = context.getImageData(0, 0, surface.width, surface.height);
    let lit = 0;
    let body = 0;
    for (let index = 0; index < data.length; index += 4) {
      const red = data[index];
      const green = data[index + 1];
      const blue = data[index + 2];
      // Anything brighter than the #1a1a2e backdrop.
      if (red + green + blue > 40) lit += 1;
      // The fixture character's #FF4422 body colour, lit but still red.
      if (red > 120 && red > green * 1.8 && red > blue * 1.8) body += 1;
    }
    return { lit, body };
  }, `data:image/png;base64,${shot.toString("base64")}`);
  expect(painted.lit).toBeGreaterThan(2000); // grid lines + character + HUD
  expect(painted.body).toBeGreaterThan(300); // the character itself
});

test("the speech overlay and the character share the viewport", async ({ page }) => {
  // The overlay is DOM, the character is canvas: if a rig change put the two in
  // different coordinate frames the line would float off the speaker.
  await expect(page.getByTestId("speech-overlay-lone")).toHaveText("rig check");
  await expect(page.getByTestId("character-fixture")).toHaveText("lone");
  const overlay = await page.getByTestId("speech-overlay-lone").boundingBox();
  const canvas = await page.locator("canvas").first().boundingBox();
  if (!overlay || !canvas) throw new Error("missing overlay or canvas");
  expect(overlay.y + overlay.height).toBeGreaterThan(canvas.y);
  expect(overlay.y).toBeLessThan(canvas.y + canvas.height);
});
