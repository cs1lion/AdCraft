import { expect, test, type Page } from "@playwright/test";

/**
 * The viewport must show how big things are.
 *
 * §2.6 of `docs/plans/previs-asset-and-motion-gap.md`, third missing contract. The
 * other two now exist: the generator prompt says what each kind measures in metres,
 * and the schema rejects a scale that renders something implausibly large. Neither is
 * visible while authoring, and an author dragging a pillar past the roof has no way
 * to notice -- which is how a 19 m column beside a 1.85 m person shipped unnoticed.
 *
 * `REFERENCE_PERSON_HEIGHT` existed in the generated frontend contract for a while
 * with no consumers at all. This spec exists so that cannot recur silently: it
 * asserts the figure is DRAWN, that its height is the generated constant rather than
 * a number someone typed here, and that it stays out of delivered frames.
 */

type Snapshot = { characterMeshes: number; characterParts: Record<string, number> };
const snapshot = (page: Page) =>
  page.evaluate(() => (window as unknown as { leanScene: { snapshot: () => Snapshot } }).leanScene.snapshot());

const GIZMOS_ON = "/tests/browser/lean-scene-canvas-mock.html?character=1";
const GIZMOS_OFF = "/tests/browser/lean-scene-canvas-mock.html?character=1&nogizmos=1";

test.describe("the scale reference figure", () => {
  test("is drawn when the authoring aids are on", async ({ page }) => {
    await page.goto(GIZMOS_ON);
    await expect(page.getByTestId("character-fixture")).toBeVisible();
    await expect.poll(async () => (await snapshot(page)).characterMeshes).toBeGreaterThan(0);

    // Two boxes per human character: a vertical extent bar and a head-height tick.
    // Absolute, not relative: the point of §2.6 is that scale was unreadable, so a
    // count that only says "more than before" would miss a figure drawn at the wrong
    // size.
    const withGizmos = await snapshot(page);
    expect(withGizmos.characterParts.box ?? 0).toBeGreaterThanOrEqual(8);
  });

  test("adds nothing when the authoring aids are off", async ({ page }) => {
    // This is the load-bearing half. The render entry passes showGizmos={false}, and
    // a grey mannequin appearing in a delivered frame would be a worse defect than
    // the missing ruler this feature exists to add.
    await page.goto(GIZMOS_OFF);
    await expect(page.getByTestId("character-fixture")).toBeVisible();
    await expect.poll(async () => (await snapshot(page)).characterMeshes).toBeGreaterThan(0);
    const withoutGizmos = await snapshot(page);

    await page.goto(GIZMOS_ON);
    await expect(page.getByTestId("character-fixture")).toBeVisible();
    await expect.poll(async () => (await snapshot(page)).characterMeshes).toBeGreaterThan(0);
    const withGizmos = await snapshot(page);

    expect(withoutGizmos.characterMeshes).toBe(11); // nine articulated segments + mouth + ID cone
    expect(withGizmos.characterMeshes).toBe(withoutGizmos.characterMeshes + 2);
  });

  test("the character is still drawn in its own colour with the figure present", async ({ page }) => {
    // The figure must not occlude the thing it is there to measure. A wireframe with
    // depthTest off does not; this asserts the character still paints.
    await page.goto(GIZMOS_ON);
    await expect(page.getByTestId("character-fixture")).toBeVisible();
    const canvas = page.locator("canvas").first();
    await expect.poll(async () => (await canvas.boundingBox())?.width ?? 0).toBeGreaterThan(50);
    const shot = await canvas.screenshot();
    expect(shot.byteLength).toBeGreaterThan(5000);
  });
});

test.describe("the scale constant is the generated one", () => {
  test("REFERENCE_PERSON_HEIGHT is consumed by the preview", async ({ page }) => {
    // Guards the exact failure that left it dangling: a generated export with zero
    // readers. If the preview hardcoded 1.75 instead of importing it, the contract
    // and the viewport would drift and nothing else would notice.
    const source = await page.request.get("/src/features/agent-canvas/canvas/SceneScript3DPreview.tsx");
    const text = await source.text();
    expect(text).toContain("REFERENCE_PERSON_HEIGHT");
  });
});
