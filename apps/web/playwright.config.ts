import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "line",
  outputDir: "/tmp/adcraft-playwright-results",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5197",
    channel: process.env.PLAYWRIGHT_CHANNEL as "chrome" | "msedge" | undefined,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    ...devices["Desktop Chrome"],
  },
  // A worktree cannot bind 5197 while the main checkout holds it, so the port is
  // overridable. When PLAYWRIGHT_BASE_URL is set the server is assumed already
  // running (started by the operator), which is how a worktree runs these specs.
  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: "npm run dev -- --port " + (process.env.PLAYWRIGHT_PORT ?? 5197),
        url: "http://127.0.0.1:" + (process.env.PLAYWRIGHT_PORT ?? 5197)
          + "/tests/browser/agent-canvas-editing-mock.html",
        reuseExistingServer: false,
        timeout: 120_000,
      },
});
