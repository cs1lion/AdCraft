import { defineConfig, devices } from "@playwright/test";

/**
 * Config for the V0.2 journey harness (apps/web/e2e).
 *
 * Deliberately separate from the repo-level playwright.config.ts (whose
 * testDir is ./tests/browser): this suite owns its own harness pages under
 * e2e/harness, served by the same vite dev server. Port 5198 keeps it from
 * colliding with the 5197 suite if both ever run at once.
 */
export default defineConfig({
  testDir: ".",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "line",
  outputDir: "/tmp/adcraft-e2e-v02-results",
  // The scene-3d workbench pulls in three.js and a lazy editor chunk, so the
  // first paint of a harness page is heavier than a static mock.
  timeout: 90_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5198",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    ...devices["Desktop Chrome"],
  },
  webServer: process.env.PLAYWRIGHT_BASE_URL ? undefined : {
    command: "npm run dev -- --port 5198",
    url: "http://127.0.0.1:5198/e2e/harness/v02-j1-asset-to-canvas.mock.html",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
