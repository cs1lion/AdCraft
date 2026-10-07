import { describe, expect, it } from "vitest";
import { mkdtempSync, mkdirSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import {
  describeMissingFrontend,
  hasBuiltFrontend,
  resolveWebRoot,
  webRootForDriver,
} from "./render-frames-paths.mjs";

/**
 * These lock the defect that made the three.js render path a property of one
 * machine: `render-frames.mjs` resolved its web root from a hardcoded
 * `D:/project/myAdCraft/apps/web`, so every other checkout, container and CI
 * runner failed `render_dist_missing` while the Python capability probe — which
 * resolves the same directory its own way — reported `ready`.
 *
 * A test that only ran on the author's machine could not have caught it. These
 * run against synthetic paths in a temp directory, so they hold on any machine,
 * and one of them reads the driver's SOURCE to assert no absolute path is baked
 * into it at all — because a rule that merely happens to work here is the bug,
 * not the fix.
 */

const makeCheckout = (name) => {
  const root = mkdtempSync(join(tmpdir(), "render-root-"));
  const web = join(root, name, "apps", "web");
  mkdirSync(join(web, "scripts"), { recursive: true });
  writeFileSync(join(web, "package.json"), "{}");
  return { root, web };
};

describe("webRootForDriver", () => {
  it("is the parent of the driver's own scripts/ directory", () => {
    // The driver lives at <web>/scripts/render-frames.mjs, so this arithmetic
    // cannot disagree with where the file actually is.
    expect(webRootForDriver(join("/srv", "checkout", "apps", "web", "scripts", "render-frames.mjs")))
      .toBe(join("/srv", "checkout", "apps", "web"));
  });

  it("accepts a file:// URL, which is how the driver knows its own location", () => {
    // Built from a real temp path rather than a POSIX literal: `fileURLToPath`
    // returns platform separators, so a hardcoded "/srv/..." expectation would
    // only hold off Windows — the same "passes on the author's machine" trap.
    const { web } = makeCheckout("url");
    expect(webRootForDriver(pathToFileURL(join(web, "scripts", "render-frames.mjs")).href)).toBe(web);
  });

  it("moves with the checkout rather than with the machine", () => {
    // Two different checkouts, two different roots. A hardcoded path would give
    // the same answer for both, which is exactly the bug.
    const one = webRootForDriver("/home/alice/work/apps/web/scripts/render-frames.mjs");
    const two = webRootForDriver("D:/projects/other/apps/web/scripts/render-frames.mjs");
    expect(one).not.toBe(two);
  });
});

describe("resolveWebRoot", () => {
  it("prefers an explicit --root over everything else", () => {
    const { root, web } = makeCheckout("explicit");
    expect(resolveWebRoot({ explicit: web, driverUrl: join(web, "scripts", "x.mjs"), cwd: root }))
      .toBe(web);
  });

  it("resolves a relative --root against the working directory", () => {
    // This is what makes the subprocess `cwd` meaningful, which passing nothing
    // never did.
    const { root, web } = makeCheckout("relative");
    expect(resolveWebRoot({ explicit: join("relative", "apps", "web"), driverUrl: join(web, "scripts", "x.mjs"), cwd: root }))
      .toBe(web);
  });

  it("derives the root from the driver's own location when no --root is given", () => {
    const { web } = makeCheckout("derived");
    expect(resolveWebRoot({ driverUrl: join(web, "scripts", "render-frames.mjs") })).toBe(web);
  });

  it("treats a BLANK --root as absent, not as the working directory", () => {
    // `arg()` returns the string after the flag, which is "" when the flag is
    // last with no value. An empty path is not a location.
    const { root, web } = makeCheckout("blank");
    expect(resolveWebRoot({ explicit: "   ", driverUrl: join(web, "scripts", "x.mjs"), cwd: root }))
      .toBe(web);
  });

  it("falls back to the working directory when the driver sits outside a checkout", () => {
    // A driver copied to a temp dir has no package.json sibling; the cwd is then
    // the only honest guess, and it is the caller's to have set.
    const { root } = makeCheckout("elsewhere");
    expect(resolveWebRoot({ driverUrl: join(root, "loose", "render-frames.mjs"), cwd: root }))
      .toBe(root);
  });
});

describe("hasBuiltFrontend / describeMissingFrontend", () => {
  it("reports the path it actually tried, so a wrong checkout is obvious", () => {
    const { web } = makeCheckout("missing-dist");
    expect(hasBuiltFrontend(web)).toBe(false);
    expect(describeMissingFrontend(web)).toContain(join(web, "dist"));
    mkdirSync(join(web, "dist"));
    expect(hasBuiltFrontend(web)).toBe(true);
    expect(describeMissingFrontend(web)).toBeNull();
  });
});

describe("the driver itself", () => {
  // Read the driver's SOURCE rather than only exercising the shared resolver: a
  // behavioural test can prove the rule works on this machine, and the defect was
  // precisely that it worked on exactly one machine. Resolved from the working
  // directory because vitest's jsdom transform hands `import.meta.url` an http
  // URL, and the precondition below fails loudly if that assumption ever breaks —
  // it does not skip.
  const driverPath = join(process.cwd(), "scripts", "render-frames.mjs");

  const driverSource = () => readFileSync(driverPath, "utf8");

  it("has the driver where this test expects it", () => {
    expect(existsSync(driverPath)).toBe(true);
  });

  it("contains no hardcoded absolute web root", () => {
    const source = driverSource();
    // The structural half of the fix: the machine must not be in the source at
    // all. Matched as "a string literal that IS an absolute path" rather than as
    // a particular remembered path, because the previous regex
    // (`[A-Za-z]:[/\\]...apps[/\\]web`) missed `D:/project/myAdCraft/apps/web` —
    // a drive path with more than one segment before `apps` — which is exactly
    // the string that was there. A narrow pattern is a guard that does not guard.
    expect(source).not.toMatch(/["'`][A-Za-z]:[/\\]/); // D:\... or C:/...
    expect(source).not.toMatch(/["'`]\/[A-Za-z]/); // /srv/..., /home/...
  });

  it("gets its web root from the shared resolver, not from a remembered path", () => {
    // The assignment itself, not just the presence of the import: a constant
    // assigned from the resolver is fine, one assigned from a literal is the bug.
    expect(driverSource()).toMatch(/const WEB_ROOT\s*=\s*resolveWebRoot\(/);
  });

  it("creates its own output directory instead of assuming the caller's", () => {
    // The API creates the frames dir before spawning this driver, so nothing
    // noticed that the driver relied on it — until someone ran the driver by
    // hand, which is exactly what a developer debugging a render does. It died on
    // a raw ENOENT stack trace rather than a coded failure.
    expect(driverSource()).toMatch(/mkdirSync\(\s*OUT\s*,\s*\{\s*recursive:\s*true\s*\}\s*\)/);
  });
});