import { expect, test, type Page } from "@playwright/test";

type Point = [number, number, number];
type Leg = {
  hip: Point; thighBottom: Point; shinTop: Point; shinBottom: Point;
  shinCenter: Point; thighPitch: number; kneePitch: number; connectedParent: boolean;
};
type Pose = { frame: number; sample: number; legs: Record<"L" | "R", Leg> };
const pose = (page: Page) => page.evaluate(() =>
  (window as unknown as { leanScene: { poseSnapshot: () => Pose | null } }).leanScene.poseSnapshot());
const distance = (a: Point, b: Point) => Math.hypot(...a.map((value, i) => value - b[i]));
const relative = (point: Point, origin: Point): Point => point.map((value, i) => value - origin[i]) as Point;
const sides = ["L", "R"] as const;

async function seek(page: Page, frame: number): Promise<Pose> {
  const previousSample = (await pose(page))?.sample ?? -1;
  const slider = page.getByRole("slider", { name: "场景预览时间轴" });
  await slider.fill(String(frame));
  await expect(slider).toHaveValue(String(frame));
  await expect.poll(async () => {
    const value = await pose(page);
    return value?.frame === frame && value.sample > previousSample;
  }).toBe(true);
  const value = await pose(page);
  if (!value) throw new Error(`No mounted rig probe at frame ${frame}`);
  for (const side of sides) {
    const leg = value.legs[side];
    expect(leg.connectedParent, `${side}: knee must be a child of the thigh pivot`).toBe(true);
    const gap = distance(leg.thighBottom, leg.shinTop);
    expect(Number.isFinite(gap), `${side}: finite world endpoints`).toBe(true);
    expect(gap, `${side}: connected knee at frame ${frame}, metres`).toBeLessThanOrEqual(0.001);
  }
  return value;
}

function expectSameShape(actual: Pose, expected: Pose) {
  for (const side of sides) {
    const a = actual.legs[side];
    const b = expected.legs[side];
    expect(a.thighPitch).toBeCloseTo(b.thighPitch, 8);
    expect(a.kneePitch).toBeCloseTo(b.kneePitch, 8);
    for (const point of ["thighBottom", "shinTop", "shinBottom", "shinCenter"] as const) {
      // Remove only whole-character translation; keep the actual world rotation.
      expect(distance(relative(a[point], a.hip), relative(b[point], b.hip)),
        `${side}: restored ${point}`).toBeLessThanOrEqual(0.001);
    }
  }
}

for (const height of [1.1, 1.85]) {
  for (const scale of [1, 1.5]) {
    test(`real mounted knee chain survives seek: height=${height}, scale=${scale}`, async ({ page }) => {
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.goto(`/tests/browser/lean-scene-canvas-mock.html?pose=1&height=${height}&scale=${scale}`);
      await expect(page.getByTestId("pose-fixture")).toHaveText(`${height}/${scale}`);
      await expect.poll(async () => (await pose(page))?.frame).toBe(0);
      const stand = await seek(page, 0);
      for (const side of sides) expect(stand.legs[side].kneePitch).toBeCloseTo(0, 8);

      // Probe several moving frames, not a walk action at zero travelled distance.
      const walk = [] as Pose[];
      for (const frame of [34, 38, 46, 54]) walk.push(await seek(page, frame));
      expect(Math.max(...walk.flatMap((value) => sides.map((side) =>
        Math.abs(value.legs[side].kneePitch))))).toBeGreaterThan(0.01);
      for (const side of sides) {
        expect(Math.max(...walk.map((value) => Math.abs(
          value.legs[side].thighPitch - stand.legs[side].thighPitch)))).toBeGreaterThan(0.01);
      }

      const sit = await seek(page, 60);
      for (const side of sides) {
        const leg = sit.legs[side];
        expect(leg.thighPitch).toBeGreaterThan(1);
        expect(leg.kneePitch).toBeLessThan(-1); // relative knee bends opposite the thigh
        expect(leg.shinBottom[1]).toBeLessThan(leg.shinTop[1]); // shin hangs down, not a kick
        expect(distance(relative(leg.shinCenter, leg.hip),
          relative(stand.legs[side].shinCenter, stand.legs[side].hip)),
          `${side}: shin follows the changed thigh, not a fixed root pivot`).toBeGreaterThan(0.05);
      }
      const restoredStand = await seek(page, 90);
      for (const side of sides) expect(restoredStand.legs[side].kneePitch).toBeCloseTo(0, 8);
      expectSameShape(restoredStand, stand);
      expectSameShape(await seek(page, 120), sit); // a second sit action, not just a backward seek
      // Seek backward to the identical sit frame: no accumulated transforms and
      // no retained stand angles. Repeat the full reset once more for stability.
      expectSameShape(await seek(page, 60), sit);
      expectSameShape(await seek(page, 90), stand);
      expectSameShape(await seek(page, 60), sit);
      expect(errors).toEqual([]);
    });
  }
}
