/**
 * render-frames-paths.mjs — where the render driver finds the built frontend.
 *
 * WHY THIS IS A SEPARATE MODULE
 * The first version of `render-frames.mjs` resolved its web root with a
 * hardcoded absolute path (`D:/project/myAdCraft/apps/web`). It worked on the
 * machine that wrote it and nowhere else. The Python side did not help: it set
 * the subprocess `cwd` but never passed `--root`, and `path.resolve()` ignores
 * `cwd` when handed an absolute path — so the `cwd` looked like a fix and was
 * not one. On any other checkout, container or CI machine the driver fails
 * `render_dist_missing`, while the capability probe (which resolves the same
 * directory correctly, in Python) still reports `ready`. An operator then gets
 * "renderer unavailable" from a machine that has the renderer.
 *
 * That is the same shape as the two parent-counting bugs already recorded in
 * `threejs_renderer.py`: a path resolved one way by the checker and another way
 * by the thing being checked. So the rule is now derived from the DRIVER'S OWN
 * LOCATION, which cannot be wrong about which checkout it belongs to:
 *
 *   1. `--root`, when the caller passes one (the Python side always does).
 *   2. otherwise the parent of this script's own directory — the driver lives at
 *      `<web>/scripts/render-frames.mjs`, so that parent IS the web root, found
 *      by arithmetic on `import.meta.url` rather than by a remembered path.
 *   3. otherwise the working directory, for a driver copied out of the repo.
 *
 * Pure and dependency-free so it can be unit-tested: `render-frames-paths.test.mjs`
 * asserts the resolution against synthetic paths, which is the only way to prove
 * no machine-specific path is baked in.
 */

import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * The web root a driver at `driverPath` belongs to: its `scripts/` parent's
 * parent. Accepts a filesystem path or a `file://` URL.
 */
export function webRootForDriver(driverPathOrUrl) {
  const driverPath = driverPathOrUrl.startsWith("file://")
    ? fileURLToPath(driverPathOrUrl)
    : driverPathOrUrl;
  return dirname(dirname(driverPath));
}

/**
 * The web root to serve `dist/` from.
 *
 * `explicit` is the `--root` argument (undefined when absent — note that a BLANK
 * `--root` is treated as absent, because `Number("")`/empty-string handling has
 * already burned this driver once). `driverUrl` is `import.meta.url`.
 */
export function resolveWebRoot({ explicit, driverUrl, cwd = process.cwd() } = {}) {
  if (typeof explicit === "string" && explicit.trim()) {
    return resolve(cwd, explicit.trim());
  }
  if (driverUrl) {
    const beside = webRootForDriver(driverUrl);
    // Only trust the sibling layout when it really is one: a `package.json`
    // beside the driver is what makes "the parent is the web root" true rather
    // than merely plausible.
    if (existsSync(join(beside, "package.json"))) return beside;
  }
  return resolve(cwd);
}

/** True when `<webRoot>/dist` exists — the driver serves nothing else. */
export function hasBuiltFrontend(webRoot) {
  return existsSync(join(webRoot, "dist"));
}

/**
 * A readable description of why a web root is unusable, or null when it is fine.
 * The message names the path it actually tried, so a wrong checkout is obvious
 * from the node error alone.
 */
export function describeMissingFrontend(webRoot) {
  if (hasBuiltFrontend(webRoot)) return null;
  return `no dist at ${join(webRoot, "dist")} — run npm run build in that apps/web`;
}