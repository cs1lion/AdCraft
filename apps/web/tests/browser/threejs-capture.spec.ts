import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

const OUT = "spike-frames";

// First attempt captured with canvas.toBlob() outside the render callback and
// produced 12 identical BLACK pngs: without preserveDrawingBuffer the drawing
// buffer is cleared after compositing, so a read from JS sees nothing. The
// element screenshot reads the composited surface instead, which is the same
// surface the author looks at.

test("three.js can drive and capture the real scene frame by frame", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/tests/browser/threejs-capture.html");

  type Spike = {
    totalFrames: () => number;
    frameRate: () => number;
    step: (frame: number) => Promise<void>;
  };
  const dims = await page.evaluate(() => {
    const api = (window as unknown as { spike: Spike }).spike;
    return { totalFrames: api.totalFrames(), frameRate: api.frameRate() };
  });
  expect(dims.totalFrames).toBe(720);
  expect(dims.frameRate).toBe(30);

  const canvas = page.locator("canvas").first();
  await expect.poll(async () => (await canvas.boundingBox())?.width ?? 0).toBeGreaterThan(50);

  mkdirSync(OUT, { recursive: true });
  const wanted = [0, 60, 120, 180, 240, 300, 360, 420, 480, 540, 600, 719];
  const timings: number[] = [];
  const bytes: number[] = [];

  for (const frame of wanted) {
    const started = Date.now();
    await page.evaluate(async (f) => {
      await (window as unknown as { spike: Spike }).spike.step(f);
    }, frame);
    const shot = await canvas.screenshot({ path: join(OUT, `f_${String(frame).padStart(4, "0")}.png`) });
    const buffer = Buffer.from(shot);
    bytes.push(buffer.length);
    timings.push(Date.now() - started);
    writeFileSync(join(OUT, `f_${String(frame).padStart(4, "0")}.png`), buffer);
    expect(buffer.length).toBeGreaterThan(2000);
  }

  console.log(
    JSON.stringify(
      {
        frames: wanted.length,
        step_capture_ms_mean: Math.round(timings.reduce((a, b) => a + b, 0) / timings.length),
        step_capture_ms_max: Math.round(Math.max(...timings)),
        png_bytes_min: Math.min(...bytes),
        png_bytes_max: Math.max(...bytes),
        // A flat black frame compresses to a couple of hundred bytes; anything
        // with a scene in it is far larger. This is the anti-false-pass guard.
        implies_720_frames_seconds: +(
          ((timings.reduce((a, b) => a + b, 0) / timings.length) * 720) /
          1000
        ).toFixed(2),
      },
      null,
      2,
    ),
  );
  expect(errors).toEqual([]);
  expect(Math.min(...bytes)).toBeGreaterThan(5000);
});
