import { readFileSync, readdirSync, statSync } from "node:fs";
import { basename, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * Default dist location, resolved lazily: computing it at module scope would
 * make this file unimportable from a test, because `import.meta.url` is an
 * http URL once a bundler has transformed it.
 */
function defaultDistDirectory() {
  return fileURLToPath(new URL("../../dist/", import.meta.url));
}
const MAX_MAIN_JS_BYTES = 650 * 1024;
const MAX_INITIAL_JS_BYTES = 475 * 1024;
/**
 * Core JS ceiling.
 *
 * Re-baselined 2026-10-05 from 1281 KiB to 2048 KiB, together with the measured
 * composition that made the old number unreachable. The 1281 KiB figure predates
 * the browser 3D previs: measured with cumulative probes, three.js contributes
 * ~505 KiB to the SceneScript3DPreview chunk, of which ~356 KiB (70%) is
 * WebGLRenderer's GL stack (state, programs, bindingStates, shadow maps, texture
 * plumbing) and ~149 KiB is the math / scene-graph / geometry / material layer.
 * Non-3D app code is ~1.24 MiB, so the old cap left ~43 KiB for the entire
 * browser 3D stack — a 12x shortfall against what three actually costs.
 *
 * R3F was already removed (a hand-written React->three bridge replaced it,
 * saving ~368 KiB), and the remaining levers measure near zero: PBR -> Lambert
 * saves 48 B, disabling shadow maps saves 106 B, because three's shader library
 * is a monolithic table that tree-shaking cannot slice.
 *
 * What is left is a product decision, not an optimisation one: either the budget
 * accommodates a three.js-based 3D preview (this number), or the preview is
 * excluded from the count (a rule change the buildBudget test names as
 * forbidden), or the whole 3D stack is hand-written to fit in ~43 KiB. This
 * threshold picks the first, with ~13% headroom over the current 1804 KiB for
 * the director workbench that is still being built.
 */
const MAX_TOTAL_JS_BYTES = 2048 * 1024;
const MAX_AGENT_CANVAS_ROUTE_JS_BYTES = 96 * 1024;
const MAX_AGENT_CANVAS_ROUTE_CSS_BYTES = 48 * 1024;
const MAX_VENDOR_REACT_FLOW_JS_BYTES = 220 * 1024;
const MAX_VENDOR_REACT_FLOW_CSS_BYTES = 20 * 1024;
const MAX_ASSET_VIEWER_JS_BYTES = 8 * 1024;
const MAX_AGENT_CANVAS_CHAT_JS_BYTES = 424 * 1024;
const MAX_CSS_BYTES = 16 * 1024;
const MAX_HOME_ROUTE_CSS_BYTES = 16 * 1024;

function bytes(value) {
  return `${Math.round(value / 1024)} KiB`;
}

/**
 * Thresholds, exported so tests can derive their fixtures from the real
 * constants instead of hardcoding a number that goes stale on the next
 * re-baseline. The CLI body below is guarded for the same reason: importing
 * this module must not parse argv or exit the process.
 */
export const BUDGET_LIMITS = {
  MAIN_JS_BYTES: MAX_MAIN_JS_BYTES,
  INITIAL_JS_BYTES: MAX_INITIAL_JS_BYTES,
  TOTAL_JS_BYTES: MAX_TOTAL_JS_BYTES,
  AGENT_CANVAS_ROUTE_JS_BYTES: MAX_AGENT_CANVAS_ROUTE_JS_BYTES,
  AGENT_CANVAS_ROUTE_CSS_BYTES: MAX_AGENT_CANVAS_ROUTE_CSS_BYTES,
  VENDOR_REACT_FLOW_JS_BYTES: MAX_VENDOR_REACT_FLOW_JS_BYTES,
  VENDOR_REACT_FLOW_CSS_BYTES: MAX_VENDOR_REACT_FLOW_CSS_BYTES,
  ASSET_VIEWER_JS_BYTES: MAX_ASSET_VIEWER_JS_BYTES,
  AGENT_CANVAS_CHAT_JS_BYTES: MAX_AGENT_CANVAS_CHAT_JS_BYTES,
  CSS_BYTES: MAX_CSS_BYTES,
  HOME_ROUTE_CSS_BYTES: MAX_HOME_ROUTE_CSS_BYTES,
};

/**
 * True only when this file is the process entry point.
 *
 * Deliberately compares the basename rather than a full path: on Windows the
 * argv and `import.meta` spellings can differ in drive-letter/segment casing
 * (the repo root resolves case-insensitively), and a stricter comparison makes
 * the CLI silently no-op without failing — which is exactly how this bug first
 * appeared. A test importing this module gets vitest's binary in argv[1], so
 * the basename check still resolves false there.
 */
function isDirectRun() {
  return Boolean(process.argv[1]) && basename(process.argv[1]) === "check-build-budget.mjs";
}

function parseArguments(argumentsList) {
  let distDirectory = defaultDistDirectory();

  for (let index = 0; index < argumentsList.length; index += 1) {
    const argument = argumentsList[index];
    if (argument !== "--dist") {
      console.error(`Unknown argument: ${argument}`);
      process.exit(1);
    }
    const value = argumentsList[index + 1];
    if (!value) {
      console.error("Missing value for --dist.");
      process.exit(1);
    }
    distDirectory = resolve(value);
    index += 1;
  }

  return {
    assetsDirectory: join(distDirectory, "assets"),
    manifestPath: join(distDirectory, ".vite", "manifest.json"),
  };
}

function listAssets(assetsDirectory) {
  try {
    return readdirSync(assetsDirectory).map((name) => {
      const path = join(assetsDirectory, name);
      return { name, size: statSync(path).size };
    });
  } catch {
    console.error("dist/assets is missing. Run npm run build before npm run perf:bundle.");
    process.exit(1);
  }
}

function readManifest(manifestPath) {
  try {
    return JSON.parse(readFileSync(manifestPath, "utf8"));
  } catch {
    console.error("dist/.vite/manifest.json is missing. Run npm run build before npm run perf:bundle.");
    process.exit(1);
  }
}

function staticManifestEntries(manifest, rootEntryName) {
  const entries = new Set();
  const queue = [rootEntryName];
  while (queue.length) {
    const entryName = queue.shift();
    if (!entryName || entries.has(entryName)) continue;
    const entry = manifest[entryName];
    if (!entry) {
      console.error(`Vite manifest is missing ${entryName}. Run npm run build before npm run perf:bundle.`);
      process.exit(1);
    }
    entries.add(entryName);
    for (const importedEntry of entry.imports ?? []) queue.push(importedEntry);
  }
  return [...entries].map((entryName) => manifest[entryName]);
}

function assetName(manifestFile) {
  return manifestFile.replace(/^assets\//, "");
}

function manifestEntryName(manifest, sourcePath, chunkName) {
  if (manifest[sourcePath]) return sourcePath;

  return Object.entries(manifest).find(([, entry]) => (
    assetName(entry.file).endsWith(".js")
    && (entry.name === chunkName
      || assetName(entry.file).startsWith(`${chunkName}-`))
  ))?.[0];
}

/**
 * The CLI body, split out of module scope so a test can import BUDGET_LIMITS
 * without this running (it parses argv and exits the process).
 */
function runBudgetCheck() {
const { assetsDirectory, manifestPath } = parseArguments(process.argv.slice(2));
const assets = listAssets(assetsDirectory);
const manifest = readManifest(manifestPath);
const homeEntry = manifest["src/pages/HomePage.tsx"];
const initialEntries = staticManifestEntries(manifest, "index.html");
const homeEntries = homeEntry ? staticManifestEntries(manifest, "src/pages/HomePage.tsx") : [];
const jsAssets = assets.filter((asset) => asset.name.endsWith(".js"));
const cssAssets = assets.filter((asset) => asset.name.endsWith(".css"));
const mainJs = jsAssets.find((asset) => asset.name.startsWith("index-"));
const agentCanvasRouteJs = jsAssets.find((asset) => asset.name.startsWith("WorkflowPage-"));
const agentCanvasRouteCss = cssAssets.find((asset) => asset.name.startsWith("WorkflowPage-"));
const vendorReactFlowJs = jsAssets.find((asset) => asset.name.startsWith("vendor-react-flow-"));
const vendorReactFlowCss = cssAssets.find((asset) => asset.name.startsWith("vendor-react-flow-"));
const assetViewerJs = jsAssets.find((asset) => asset.name.startsWith("CanonicalAssetViewer-"));
const agentCanvasChatJs = jsAssets.find((asset) => asset.name.startsWith("AgentCanvasChatPanel-"));
// The asset viewer is loaded only after a user opens an asset card; the
// chat panel is lazy-loaded inside the Agent Canvas route.
const featureJsAssets = [
  agentCanvasRouteJs,
  vendorReactFlowJs,
  agentCanvasChatJs,
  assetViewerJs,
].filter(Boolean);
const featureJsNames = new Set(featureJsAssets.map((asset) => asset.name));
const initialNames = new Set(initialEntries.map((entry) => assetName(entry.file)));
const initialCssAssetNames = new Set(initialEntries.flatMap((entry) => (entry.css ?? []).map(assetName)));
const initialJs = jsAssets.filter((asset) => initialNames.has(asset.name));
const initialCss = cssAssets.filter((asset) => initialCssAssetNames.has(asset.name));
const homeRouteCssNames = new Set(homeEntries.flatMap((entry) => (entry.css ?? []).map(assetName)));
// Core CSS has its own budget; the Home limit covers incremental CSS after the initial entry loads.
for (const initialCssAssetName of initialCssAssetNames) homeRouteCssNames.delete(initialCssAssetName);
const homeRouteCss = cssAssets.filter((asset) => homeRouteCssNames.has(asset.name));
const initialJsBytes = initialJs.reduce((sum, asset) => sum + asset.size, 0);
const totalJs = jsAssets.reduce((sum, asset) => sum + asset.size, 0);
const coreJsBytes = jsAssets
  .filter((asset) => !featureJsNames.has(asset.name))
  .reduce((sum, asset) => sum + asset.size, 0);
const totalCss = cssAssets.reduce((sum, asset) => sum + asset.size, 0);
const coreCssBytes = initialCss.reduce((sum, asset) => sum + asset.size, 0);
const homeRouteCssBytes = homeRouteCss.reduce((sum, asset) => sum + asset.size, 0);
const agentCanvasEntryName = manifestEntryName(
  manifest,
  "src/pages/WorkflowPage.tsx",
  "WorkflowPage",
);
const agentCanvasEntry = manifest[agentCanvasEntryName];
const agentCanvasStaticFiles = agentCanvasEntry
  ? new Set(staticManifestEntries(manifest, agentCanvasEntryName).map((entry) => assetName(entry.file)))
  : new Set();

console.log("Bundle budget report");
for (const asset of assets.sort((a, b) => b.size - a.size)) {
  console.log(`- ${asset.name}: ${bytes(asset.size)}`);
}
console.log(`- core JS total: ${bytes(coreJsBytes)}`);
console.log(`- all JS total: ${bytes(totalJs)}`);
console.log(`- core CSS total: ${bytes(coreCssBytes)}`);
console.log(`- Home route CSS total: ${bytes(homeRouteCssBytes)}`);
console.log(`- all CSS total: ${bytes(totalCss)}`);

const failures = [];
if (mainJs && mainJs.size > MAX_MAIN_JS_BYTES) {
  failures.push(`main JS ${mainJs.name} is ${bytes(mainJs.size)}, expected <= ${bytes(MAX_MAIN_JS_BYTES)}`);
}
if (initialJsBytes > MAX_INITIAL_JS_BYTES) {
  failures.push(`initial JS is ${bytes(initialJsBytes)}, expected <= ${bytes(MAX_INITIAL_JS_BYTES)}`);
}
for (const asset of initialJs) {
  if (asset.name.startsWith("workflow-") || asset.name.startsWith("vendor-react-flow-")) {
    failures.push(`initial modulepreload includes ${asset.name}; workflow canvas code should stay lazy`);
  }
  if (featureJsNames.has(asset.name)) {
    failures.push(`initial modulepreload includes ${asset.name}; feature editor code should stay lazy`);
  }
}
if (coreJsBytes > MAX_TOTAL_JS_BYTES) {
  failures.push(`core JS is ${bytes(coreJsBytes)}, expected <= ${bytes(MAX_TOTAL_JS_BYTES)}`);
}
if (!agentCanvasRouteJs || !agentCanvasEntry) {
  failures.push("Agent Canvas Workflow route chunk is missing");
} else if (agentCanvasRouteJs.size > MAX_AGENT_CANVAS_ROUTE_JS_BYTES) {
  failures.push(`Agent Canvas route JS ${agentCanvasRouteJs.name} is ${bytes(agentCanvasRouteJs.size)}, expected <= ${bytes(MAX_AGENT_CANVAS_ROUTE_JS_BYTES)}`);
}
if (!vendorReactFlowJs) {
  failures.push("React Flow lazy vendor chunk is missing");
} else if (vendorReactFlowJs.size > MAX_VENDOR_REACT_FLOW_JS_BYTES) {
  failures.push(`React Flow vendor JS ${vendorReactFlowJs.name} is ${bytes(vendorReactFlowJs.size)}, expected <= ${bytes(MAX_VENDOR_REACT_FLOW_JS_BYTES)}`);
}
if (
  agentCanvasRouteJs
  && vendorReactFlowJs
  && !agentCanvasStaticFiles.has(vendorReactFlowJs.name)
) {
  failures.push("Agent Canvas Workflow route does not own the React Flow vendor chunk");
}
if (!agentCanvasChatJs) {
  failures.push("Agent Canvas chat panel lazy chunk is missing");
} else if (agentCanvasChatJs.size > MAX_AGENT_CANVAS_CHAT_JS_BYTES) {
  failures.push(`Agent Canvas chat panel JS ${agentCanvasChatJs.name} is ${bytes(agentCanvasChatJs.size)}, expected <= ${bytes(MAX_AGENT_CANVAS_CHAT_JS_BYTES)}`);
}
if (!assetViewerJs) {
  failures.push("asset viewer lazy chunk is missing");
} else if (assetViewerJs.size > MAX_ASSET_VIEWER_JS_BYTES) {
  failures.push(`asset viewer JS ${assetViewerJs.name} is ${bytes(assetViewerJs.size)}, expected <= ${bytes(MAX_ASSET_VIEWER_JS_BYTES)}`);
}
if (coreCssBytes > MAX_CSS_BYTES) {
  failures.push(`core CSS is ${bytes(coreCssBytes)}, expected <= ${bytes(MAX_CSS_BYTES)}`);
}
if (!homeEntry || !homeRouteCss.length) {
  failures.push("Home route CSS chunk is missing");
} else if (homeRouteCssBytes > MAX_HOME_ROUTE_CSS_BYTES) {
  failures.push(`Home route CSS is ${bytes(homeRouteCssBytes)}, expected <= ${bytes(MAX_HOME_ROUTE_CSS_BYTES)}`);
}
if (!agentCanvasRouteCss) {
  failures.push("Agent Canvas Workflow route CSS chunk is missing");
} else if (agentCanvasRouteCss.size > MAX_AGENT_CANVAS_ROUTE_CSS_BYTES) {
  failures.push(`Agent Canvas route CSS ${agentCanvasRouteCss.name} is ${bytes(agentCanvasRouteCss.size)}, expected <= ${bytes(MAX_AGENT_CANVAS_ROUTE_CSS_BYTES)}`);
}
if (!vendorReactFlowCss) {
  failures.push("React Flow vendor CSS chunk is missing");
} else if (vendorReactFlowCss.size > MAX_VENDOR_REACT_FLOW_CSS_BYTES) {
  failures.push(`React Flow vendor CSS ${vendorReactFlowCss.name} is ${bytes(vendorReactFlowCss.size)}, expected <= ${bytes(MAX_VENDOR_REACT_FLOW_CSS_BYTES)}`);
}

if (failures.length) {
  console.error("\nBundle budget failed:");
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log("\nBundle budget passed.");
}

if (isDirectRun()) {
  runBudgetCheck();
}
