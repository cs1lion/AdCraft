#!/usr/bin/env node
/**
 * Backend endpoint reachability check.
 *
 * Why this exists
 * ---------------
 * AdCraft ships backend endpoints faster than the UI can consume them. A 2026-09-28
 * audit found 7 of 16 replica endpoints and 17 of 31 scene-3d endpoints had no
 * production caller at all — complete, tested, documented backend features that a
 * user could not reach. `check-agent-canvas-backend-contract.mjs` cannot catch this:
 * it compares *schema shapes* for five whitelisted models, not *who calls what*.
 *
 * This check answers one question per route: does a real consumer reference it?
 *
 * Consumers are scanned separately so the report can distinguish
 * "dead" (nothing calls it) from "internal" (only the agent runtime calls it):
 *
 *   web        apps/web/src        minus *.test.*  -> the shipping UI
 *   web-test   apps/web/src        *.test.* only   -> locked by tests, no UI
 *   agent      apps/api/agent      the v2 client runtime
 *   e2e        apps/web/e2e        Playwright journeys
 *   scripts    apps/api/scripts    operator/verification tooling
 *
 * A route with no consumer in ANY of those is reported DEAD. A route that only
 * web-test references is reported UI-MISSING: it is proven to work, has no user.
 *
 * Usage
 * -----
 *   node scripts/check-backend-endpoint-reachability.mjs            # report, exit 0
 *   node scripts/check-backend-endpoint-reachability.mjs --check     # CI gate, exit 1 on drift
 *   node scripts/check-backend-endpoint-reachability.mjs --module replica
 *   node scripts/check-backend-endpoint-reachability.mjs --baseline file.json
 *
 * The --check mode compares against the committed baseline so that *new* dead
 * endpoints fail the build, while the existing backlog stays visible instead of
 * being hidden behind a permanent --no-verify escape hatch.
 */

import { readdir, readFile, stat, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..", "..");
const API_ROOT = path.join(REPO_ROOT, "apps", "api");
const WEB_ROOT = path.join(REPO_ROOT, "apps", "web");

const BASELINE_PATH = path.join(HERE, "endpoint-reachability-baseline.json");
const EXEMPTIONS_PATH = path.join(HERE, "endpoint-reachability-exemptions.json");

/** Mount prefixes, mirrored from apps/api/app/main.py. */
const MOUNT_PREFIX = { v1: "/api/v1", v2: "/api/v2", internal: "" };

const CONSUMERS = [
  { id: "web", label: "web (prod)", root: path.join(WEB_ROOT, "src"), tests: false },
  { id: "web-test", label: "web (tests only)", root: path.join(WEB_ROOT, "src"), tests: true },
  { id: "agent", label: "agent runtime", root: path.join(API_ROOT, "agent") },
  { id: "e2e", label: "playwright e2e", root: path.join(WEB_ROOT, "e2e") },
  { id: "scripts", label: "api scripts", root: path.join(API_ROOT, "scripts") },
];

// ---------------------------------------------------------------------------
// Backend route collection
// ---------------------------------------------------------------------------

const ROUTE_DECORATOR = /@(?:[A-Za-z_][\w]*_?router|router)\s*\.\s*(get|post|put|patch|delete)\s*\(\s*(?:[rl]?)?"([^"]+)"/g;
const PREFIX_DECL = /(?:APIRouter|APIRouter\()\s*(?:prefix\s*=\s*)?"([^"]+)"/;
/** Mount-time prefixes: `api_router.include_router(creation.router, prefix="/creation")`.
 * Most endpoint modules declare their prefix on the in-file APIRouter; creation.py
 * is mounted with one instead, and missing it reported every creation route dead. */
const ROUTER_MOUNT = /include_router\(\s*(\w+)\.router\s*(?:,\s*prefix\s*=\s*"([^"]+)")?\s*\)/g;

async function collectRouterMounts(version) {
  const routerFile = path.join(API_ROOT, "app", "api", version, "router.py");
  if (!existsSync(routerFile)) return {};
  const source = await readFile(routerFile, "utf8");
  const mounts = {};
  for (const match of source.matchAll(ROUTER_MOUNT)) {
    const [, moduleName, prefix] = match;
    mounts[moduleName] = prefix ?? "";
  }
  return mounts;
}

async function walk(dir, filter = () => true) {
  const out = [];
  if (!existsSync(dir)) return out;
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === "__pycache__" || entry.name === ".git") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...(await walk(full, filter)));
    else if (filter(full)) out.push(full);
  }
  return out;
}

async function collectRoutes() {
  const routes = [];
  for (const version of ["v1", "v2", "internal"]) {
    const dir = path.join(API_ROOT, "app", "api", version, "endpoints");
    const files = await walk(dir, (f) => f.endsWith(".py"));
    const moduleMounts = await collectRouterMounts(version);
    for (const file of files) {
      const source = await readFile(file, "utf8");
      // APIRouter(prefix="...") — first declaration wins; it is the module prefix.
      const prefix = PREFIX_DECL.exec(source)?.[1] ?? "";
      const mountPrefix = moduleMounts[path.basename(file, ".py")] ?? "";
      for (const match of source.matchAll(ROUTE_DECORATOR)) {
        const [, method, routePath] = match;
        routes.push({
          module: path.relative(REPO_ROOT, file).replaceAll("\\", "/"),
          file,
          version,
          method: method.toUpperCase(),
          // Full mounted path: mount prefix + router prefix + route path.
          fullPath: `${MOUNT_PREFIX[version]}${mountPrefix}${prefix}${routePath}`.replace(/\/{2,}/g, "/"),
          // Router-relative path, for consumers that call through a helper which
          // supplies the mount prefix (apps/web/src/api/client.ts).
          routerPath: `${mountPrefix}${prefix}${routePath}`.replace(/\/{2,}/g, "/"),
          line: source.slice(0, match.index).split("\n").length,
        });
      }
    }
  }
  return routes;
}

// ---------------------------------------------------------------------------
// Consumer scanning
// ---------------------------------------------------------------------------

/**
 * Build a map of simple string constants so composed URLs resolve.
 *
 * The frontend writes `const SCENE_3D_BASE = "/api/v1/scene-3d"` and then
 * ``fetch(`${SCENE_3D_BASE}/trigger-event`)``. A naive literal scan sees only
 * the base and misses every endpoint built on top of it, which is how the first
 * run of this checker reported 18 dead scene-3d endpoints that the UI calls.
 */
function collectStringConstants(source) {
  const constants = new Map();
  const decl = /\b(?:const|let|var)\s+([A-Z][A-Z0-9_]*)\s*=\s*("(?:[^"\\]|\\.)*")\s*;/g;
  for (const match of source.matchAll(decl)) {
    constants.set(match[1], match[2].slice(1, -1));
  }
  return constants;
}

/**
 * Replace every `${...}` group in a literal with a slash-free placeholder.
 *
 * A scanner is used rather than a regex because template expressions nest:
 * `/asset-references/suggest${query ? `?${query}` : ""}`.
 *
 * The placeholder keeps the *position* of interpolated path segments, which
 * matters: truncating at `${` instead turns `/workflows/${id}/canvas/runtime`
 * into `/workflows/` and silently loses every workflow-scoped route.
 */
const PARAM_PLACEHOLDER = "~p~";
function neutraliseTemplateExpressions(text) {
  let out = "";
  for (let i = 0; i < text.length; i += 1) {
    if (text[i] === "$" && text[i + 1] === "{") {
      let depth = 1;
      i += 2;
      while (i < text.length && depth > 0) {
        if (text[i] === "{") depth += 1;
        else if (text[i] === "}") depth -= 1;
        i += 1;
      }
      out += PARAM_PLACEHOLDER;
      i -= 1;
      continue;
    }
    out += text[i];
  }
  return out;
}

/**
 * Pull URL literals out of a source file, resolving base-constant composition.
 *
 * Two shapes exist in this codebase and both must be understood:
 *
 *   absolute   "/api/v1/replica/teardown"
 *              `${SCENE_3D_BASE}/trigger-event`   (base declared in another module)
 *
 *   relative   request("/asset-library/entities") (apps/web/src/api/client.ts)
 *              the "/api/v1" prefix is applied by the request helper, so the
 *              literal carries no mount prefix
 *
 * Returning only absolutes marked 60+ live v1 endpoints dead on the first run.
 */
function extractUrls(source, constants = collectStringConstants(source)) {
  const absolute = new Set();
  const relative = new Set();
  const literal = /(["'`])((?:\\.|(?!\1).)*)\1/g;
  for (const match of source.matchAll(literal)) {
    let text = match[2];
    // Resolve ${CONST} against known string constants, up to a few passes.
    for (let pass = 0; pass < 4; pass += 1) {
      const next = text.replace(/\$\{([A-Z][A-Z0-9_]*)\}/g, (whole, name) => constants.get(name) ?? whole);
      if (next === text) break;
      text = next;
    }
    text = neutraliseTemplateExpressions(text).replaceAll("//", "/");
    if (text.includes("api/")) {
      const pathPart = text.split("?")[0];
      const start = pathPart.indexOf("/api/");
      if (start !== -1) absolute.add(pathPart.slice(start).split("#")[0]);
      continue;
    }
    // A plain path-shaped literal is a relative call through a request helper.
    // Guard against module specifiers and asset paths.
    if (/^\/[A-Za-z0-9][^"'`\s]*$/.test(text) && !/^\/(src|node_modules)\//.test(text)) {
      relative.add(text);
    }
  }
  return { absolute: [...absolute], relative: [...relative] };
}

/**
 * Turn a route template into a matcher regex: {param} matches one path segment.
 *
 * The trailing lookahead matters. Without it, route `/blueprint/direct-execute`
 * matches the consumer literal `/blueprint/direct-execute/render` as a prefix
 * substring and is reported REACHABLE even though nothing calls it. Anchoring on
 * "not followed by another path segment" is what separates a route from its own
 * sub-routes.
 */
function routeMatcher(fullPath) {
  const escaped = fullPath
    .split("/")
    .map((segment) => (segment.startsWith("{") ? "[^/]+" : segment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))
    .join("/")
    // A template segment collapses the two slashes around it.
    .replaceAll("//+", "/");
  return new RegExp(`${escaped.replace(/\/\[^\/]+\//g, "/[^/]+/")}(?![/\\w-])`);
}

async function collectConsumerUrls() {
  const perConsumer = new Map(
    CONSUMERS.map((c) => [c.id, { absolute: new Set(), relative: new Set() }]),
  );
  for (const consumer of CONSUMERS) {
    if (!existsSync(consumer.root)) continue;
    const files = await walk(consumer.root, (f) => /\.(ts|tsx|mjs|js|py)$/.test(f) && !/\.d\.ts$/.test(f));
    const sources = new Map();
    // URL bases are declared in one module and consumed in another
    // (SCENE_3D_BASE lives next to the client that uses it, but v2Client.ts
    // composes its own). Collect constants across the whole consumer first so a
    // base defined anywhere can resolve everywhere.
    const constants = new Map();
    for (const file of files) {
      const source = await readFile(file, "utf8");
      sources.set(file, source);
      for (const [name, value] of collectStringConstants(source)) {
        if (!constants.has(name)) constants.set(name, value);
      }
    }
    for (const [file, source] of sources) {
      const isTest = /\.(test|spec)\.[^.]+$/.test(file) || /[/\\]tests?[/\\]/.test(file);
      if (Boolean(consumer.tests) !== isTest) continue;
      const bucket = perConsumer.get(consumer.id);
      const { absolute, relative } = extractUrls(source, constants);
      for (const url of absolute) bucket.absolute.add(url);
      for (const url of relative) bucket.relative.add(url);
    }
  }
  return perConsumer;
}

// ---------------------------------------------------------------------------
// Exemptions / baseline
// ---------------------------------------------------------------------------

async function readJson(file, fallback) {
  if (!existsSync(file)) return fallback;
  return JSON.parse(await readFile(file, "utf8"));
}

function exemptionKey(route) {
  return `${route.version}:${route.method} ${route.fullPath}`;
}

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------

function parseArgs(argv) {
  const args = { check: false, module: null, baseline: null };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--check") args.check = true;
    else if (arg === "--module") args.module = argv[++i];
    else if (arg === "--baseline") args.baseline = path.resolve(HERE, argv[++i]);
  }
  return args;
}

const args = parseArgs(process.argv.slice(2));

const routes = await collectRoutes();
const consumerUrls = await collectConsumerUrls();
const exemptions = await readJson(EXEMPTIONS_PATH, { endpoints: [] });
const exemptionMap = new Map(exemptions.endpoints.map((e) => [e.key, e]));

const analysed = routes
  .map((route) => {
    const absoluteMatcher = routeMatcher(route.fullPath);
    const relativeMatcher = routeMatcher(route.routerPath);
    const hitBy = CONSUMERS.filter((c) => {
      const urls = consumerUrls.get(c.id);
      return [...urls.absolute].some((url) => absoluteMatcher.test(url)) ||
        [...urls.relative].some((url) => relativeMatcher.test(url));
    }).map((c) => c.id);
    return { ...route, hitBy };
  })
  .filter((route) => (args.module ? route.module.includes(args.module) : true))
  .sort((a, b) => a.module.localeCompare(b.module) || a.fullPath.localeCompare(b.fullPath));

const dead = [];
const uiMissing = [];
const exempt = [];
const reachable = [];

for (const route of analysed) {
  const key = exemptionKey(route);
  if (exemptionMap.has(key)) {
    exempt.push({ ...route, reason: exemptionMap.get(key).reason });
    continue;
  }
  const prod = route.hitBy.some((id) => id === "web" || id === "agent" || id === "e2e");
  if (route.hitBy.includes("web") || prod) reachable.push(route);
  else if (route.hitBy.length) uiMissing.push(route);
  else dead.push(route);
}

const byModule = new Map();
for (const row of [...reachable, ...uiMissing, ...dead]) {
  if (!byModule.has(row.module)) byModule.set(row.module, { reachable: 0, uiMissing: 0, dead: 0 });
  const bucket = reachable.includes(row) ? "reachable" : uiMissing.includes(row) ? "uiMissing" : "dead";
  byModule.get(row.module)[bucket] += 1;
}

const lines = [];
lines.push("Backend endpoint reachability");
lines.push(`  scanned ${routes.length} backend routes; scope ${args.module ?? "all"}`);
lines.push("");
lines.push("  module                                  routes  reachable  ui-missing  dead");
for (const [module, counts] of [...byModule.entries()].sort()) {
  lines.push(
    `  ${module.padEnd(38)}${String(counts.reachable + counts.uiMissing + counts.dead).padStart(6)}` +
      `${String(counts.reachable).padStart(11)}${String(counts.uiMissing).padStart(12)}${String(counts.dead).padStart(6)}`,
  );
}

if (dead.length) {
  lines.push("");
  lines.push(`DEAD — no consumer anywhere (${dead.length}):`);
  for (const route of dead) lines.push(`  ${route.method.padEnd(6)} ${route.fullPath}   (${route.module}:${route.line})`);
}
if (uiMissing.length) {
  lines.push("");
  lines.push(`UI-MISSING — proven by tests, unreachable in the product (${uiMissing.length}):`);
  for (const route of uiMissing) lines.push(`  ${route.method.padEnd(6)} ${route.fullPath}   [${route.hitBy.join(", ")}]`);
}
if (exempt.length) {
  lines.push("");
  lines.push(`EXEMPT (${exempt.length}):`);
  for (const route of exempt) lines.push(`  ${route.method.padEnd(6)} ${route.fullPath}   — ${route.reason}`);
}

console.log(lines.join("\n"));

// ---------------------------------------------------------------------------
// Gate
// ---------------------------------------------------------------------------

const baselinePath = args.baseline ?? BASELINE_PATH;
const currentDead = dead.map((r) => exemptionKey(r)).sort();

if (args.check) {
  const baseline = await readJson(baselinePath, { deadEndpoints: [] });
  const known = new Set(baseline.deadEndpoints);
  const regressed = currentDead.filter((key) => !known.has(key));
  if (regressed.length) {
    console.error(`\nREGRESSION: ${regressed.length} new unreachable endpoint(s):`);
    for (const key of regressed) console.error(`  ${key}`);
    console.error("\nEither wire it up, or record an exemption in endpoint-reachability-exemptions.json,");
    console.error("or (only if it is genuinely dead weight) add it to the baseline in this commit.");
    process.exit(1);
  }
  console.log(`\nOK: ${dead.length} known-unreachable endpoint(s) match the committed baseline; no new dead endpoints.`);
}

if (process.argv.includes("--write-baseline")) {
  await writeFile(baselinePath, `${JSON.stringify({ deadEndpoints: currentDead }, null, 2)}\n`, "utf8");
  console.log(`\nBaseline written to ${path.relative(REPO_ROOT, baselinePath)} (${currentDead.length} entries).`);
}

// Keep the unused import honest for tooling that tree-shakes aggressively.
void stat;
