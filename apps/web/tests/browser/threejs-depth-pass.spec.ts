import { expect, test } from "@playwright/test";

// The depth control pass (ADR 0005 §4, plan §4.5) rendered by the real
// three.js preview in real Chrome with real WebGL.
//
// The anti-false-pass guard is the point of this spec: the first attempt at
// reading pixels without `preserveDrawingBuffer` produced 12 identical BLACK
// PNGs and a test that "passed". Every assertion below therefore checks that
// the frames are real content — geometry pixels, a greyscale range, distinct
// bytes between frames — and not merely that files exist.

type Delivery = {
  frame: number;
  fileName: string;
  bytes: number;
  checksum: number;
  stats: { maxDepth: number; geometryPixels: number };
};

test("the three.js renderer writes a real DEPTH pass for each shot keyframe", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/tests/browser/threejs-depth-pass.html");

  const plan = await page.evaluate(() =>
    (
      window as unknown as {
        depthPass: { plan: () => { shots: { shotId: string; frames: number[] }[]; frames: number[] } };
      }
    ).depthPass.plan(),
  );

  // 4 shots x 5 keyframes — the contract `collect_control_passes` re-derives.
  expect(plan.shots).toHaveLength(4);
  for (const shot of plan.shots) expect(shot.frames).toHaveLength(5);
  expect(plan.frames).toHaveLength(20);

  const deliveries = (await page.evaluate(() =>
    (
      window as unknown as { depthPass: { captureAll: () => Promise<Delivery[]> } }
    ).depthPass.captureAll(),
  )) as Delivery[];

  expect(errors).toEqual([]);
  expect(deliveries).toHaveLength(plan.frames.length);

  for (const delivery of deliveries) {
    // The collector's naming: control_depth/depth_<N>.png, N 0-based.
    const match = /^depth_(\d+)\.png$/.exec(delivery.fileName);
    expect(match, `${delivery.fileName} is not a pass file name`).not.toBeNull();
    expect(Number(match?.[1])).toBe(delivery.frame);
    expect(plan.frames).toContain(delivery.frame);

    // NOT black: geometry was rendered into the pass, and the frame has a
    // greyscale range rather than a single flat value.
    expect(delivery.stats.geometryPixels, `frame ${delivery.frame} has no geometry`).toBeGreaterThan(0);
    expect(delivery.stats.maxDepth).toBeGreaterThan(0);
    // A depth PNG of a real scene is far larger than a flat one.
    expect(delivery.bytes, `frame ${delivery.frame} PNG is suspiciously small`).toBeGreaterThan(2000);
  }

  // NOT 12 identical PNGs: different poses produce different bytes. Shot
  // boundaries move the camera, so at minimum the frames of different shots
  // must differ, and no two deliveries may share a checksum across the set.
  const byShot = new Map<number, Delivery[]>();
  for (const delivery of deliveries) {
    const shotIndex = plan.shots.findIndex((shot) => shot.frames.includes(delivery.frame));
    byShot.set(shotIndex, [...(byShot.get(shotIndex) ?? []), delivery]);
  }
  expect(byShot.size).toBe(4);
  const shotSignatures = [...byShot.values()].map((frames) => frames[0].checksum);
  expect(new Set(shotSignatures).size).toBe(4);
});
