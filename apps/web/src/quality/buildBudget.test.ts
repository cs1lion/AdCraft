import { spawnSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, test } from "vitest";
import { transform } from "lightningcss";

const budgetScriptPath = join(process.cwd(), "scripts/perf/check-build-budget.mjs");
const temporaryDirectories: string[] = [];

function writeAsset(assetsDirectory: string, name: string, size = 1) {
  writeFileSync(join(assetsDirectory, name), Buffer.alloc(size));
}

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { force: true, recursive: true });
  }
});

describe("build budget", () => {
  test("keeps standard backdrop-filter after equivalent prefixed fallbacks across route styles", () => {
    const visit = (directory: string): string[] => readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
      const path = join(directory, entry.name);
      return entry.isDirectory() ? visit(path) : entry.name.endsWith(".css") ? [path] : [];
    });
    for (const path of visit(join(process.cwd(), "src"))) {
      const css = readFileSync(path, "utf8");
      expect(css, path).not.toMatch(/(?<!-)backdrop-filter:\s*([^;]+);\s*-webkit-backdrop-filter:\s*\1;/);
    }
  });
  test("preserves the standard Discover backdrop filter in production CSS", () => {
    const source = readFileSync(join(process.cwd(), "src/pages/home.css"), "utf8").replace(/\r\n/g, "\n");
    const match = source.match(/\.orbit__card\s*\{([^}]*)\}/);
    expect(match).not.toBeNull();
    const rule = `.orbit__card {${match![1]}}`;
    const compress = (css: string) => transform({
      filename: "home.css", code: Buffer.from(css), minify: true,
      targets: { chrome: 107 << 16, edge: 107 << 16, firefox: 104 << 16, safari: 16 << 16 },
    }).code.toString();
    // With Lightning CSS 1.33.0, the prefix must precede the standard property:
    // the reversed order drops the standard declaration and breaks Chromium.
    expect(compress(rule)).toMatch(/(?:^|[;{])backdrop-filter:blur\(16px\)saturate\(1\.08\)/);
    const mutated = rule.replace(
      "-webkit-backdrop-filter: blur(16px) saturate(1.08);\n  backdrop-filter: blur(16px) saturate(1.08);",
      "backdrop-filter: blur(16px) saturate(1.08);\n  -webkit-backdrop-filter: blur(16px) saturate(1.08);",
    );
    expect(mutated).not.toBe(rule);
    expect(compress(mutated)).not.toMatch(/(?:^|[;{])backdrop-filter:/);
  });
  test("counts lazy 3D chunks toward core JS instead of hiding growth behind code splitting", () => {
    const distDirectory = mkdtempSync(join(tmpdir(), "adcraft-build-budget-"));
    temporaryDirectories.push(distDirectory);
    const assetsDirectory = join(distDirectory, "assets");
    const manifestDirectory = join(distDirectory, ".vite");
    mkdirSync(assetsDirectory);
    mkdirSync(manifestDirectory);
    writeAsset(assetsDirectory, "index-fixture.js", 1);
    for (const name of ["WorkflowPage-fixture.js", "WorkflowPage-fixture.css", "vendor-react-flow-fixture.js", "vendor-react-flow-fixture.css", "AgentCanvasChatPanel-fixture.js", "CanonicalAssetViewer-fixture.js", "home-fixture.css"]) {
      writeAsset(assetsDirectory, name);
    }
    writeAsset(assetsDirectory, "SceneScript3DPreview-fixture.js", 1281 * 1024);
    writeFileSync(join(manifestDirectory, "manifest.json"), JSON.stringify({
      "index.html": {
        file: "assets/index-fixture.js",
        dynamicImports: ["src/features/agent-canvas/canvas/SceneScript3DPreview.tsx"],
      },
      "src/features/agent-canvas/canvas/SceneScript3DPreview.tsx": {
        file: "assets/SceneScript3DPreview-fixture.js",
      },
      "src/pages/HomePage.tsx": {
        file: "assets/index-fixture.js", css: ["assets/home-fixture.css"],
      },
      "src/pages/WorkflowPage.tsx": {
        name: "WorkflowPage", file: "assets/WorkflowPage-fixture.js", imports: ["_vendor-react-flow.js"],
      },
      "_vendor-react-flow.js": { file: "assets/vendor-react-flow-fixture.js" },
    }));
    const run = () => spawnSync(process.execPath, [budgetScriptPath, "--dist", distDirectory], { encoding: "utf8" });
    const oversized = run();
    expect(oversized.status).toBe(1);
    expect(oversized.stderr).toContain("core JS is");
    // Mutate only payload size: a genuinely smaller lazy chunk passes without
    // changing the budget, its classification, or its loading strategy.
    writeAsset(assetsDirectory, "SceneScript3DPreview-fixture.js", 1281 * 1024 - 1);
    const withinBudget = run();
    expect(withinBudget.status).toBe(0);
    expect(withinBudget.stderr).not.toContain("core JS is");
  });
  test("selects the JavaScript Workflow route entry when CSS has the same chunk name", () => {
    const distDirectory = mkdtempSync(join(tmpdir(), "adcraft-build-budget-"));
    temporaryDirectories.push(distDirectory);
    const assetsDirectory = join(distDirectory, "assets");
    const manifestDirectory = join(distDirectory, ".vite");
    mkdirSync(assetsDirectory);
    mkdirSync(manifestDirectory);

    for (const asset of [
      "index-fixture.js",
      "WorkflowPage-fixture.js",
      "WorkflowPage-fixture.css",
      "vendor-react-flow-fixture.js",
      "vendor-react-flow-fixture.css",
      "AgentCanvasChatPanel-fixture.js",
      "CanonicalAssetViewer-fixture.js",
      "global-fixture.css",
      "home-fixture.js",
      "home-fixture.css",
    ]) {
      writeAsset(assetsDirectory, asset);
    }

    writeFileSync(join(manifestDirectory, "manifest.json"), JSON.stringify({
      "index.html": {
        file: "assets/index-fixture.js",
        css: ["assets/global-fixture.css"],
      },
      "src/pages/HomePage.tsx": {
        file: "assets/home-fixture.js",
        css: ["assets/home-fixture.css"],
      },
      "_WorkflowPage-fixture.css": {
        file: "assets/WorkflowPage-fixture.css",
        src: "_WorkflowPage-fixture.css",
      },
      "src/pages/WorkflowPage.tsx": {
        name: "WorkflowPage",
        file: "assets/WorkflowPage-fixture.js",
        imports: ["_vendor-react-flow.js"],
        css: ["assets/WorkflowPage-fixture.css"],
      },
      "_vendor-react-flow.js": {
        name: "vendor-react-flow",
        file: "assets/vendor-react-flow-fixture.js",
        css: ["assets/vendor-react-flow-fixture.css"],
      },
    }));

    const result = spawnSync(process.execPath, [
      budgetScriptPath,
      "--dist",
      distDirectory,
    ], { encoding: "utf8" });

    expect(result.status).toBe(0);
    expect(result.stderr).not.toContain("Agent Canvas Workflow route chunk is missing");
    expect(result.stderr).not.toContain("Agent Canvas Workflow route does not own the React Flow vendor chunk");
  });

  test("keeps Agent Canvas and React Flow out of the initial application chunk", () => {
    const appSource = readFileSync(
      join(process.cwd(), "src/App.tsx"),
      "utf8",
    );
    const workflowPageSource = readFileSync(
      join(process.cwd(), "src/pages/WorkflowPage.tsx"),
      "utf8",
    );
    const viteSource = readFileSync(
      join(process.cwd(), "vite.config.ts"),
      "utf8",
    );
    const budgetSource = readFileSync(budgetScriptPath, "utf8");

    expect(appSource).toContain('lazy(() => import("./pages/WorkflowPage")');
    expect(workflowPageSource).toContain(
      'import { AgentCanvasPage } from "../features/agent-canvas/AgentCanvasPage.tsx"',
    );
    expect(viteSource).toContain('return "vendor-react-flow"');
    expect(budgetSource).toContain("MAX_AGENT_CANVAS_ROUTE_JS_BYTES");
    expect(budgetSource).toContain("MAX_VENDOR_REACT_FLOW_JS_BYTES");
    expect(budgetSource).toContain('asset.name.startsWith("WorkflowPage-")');
    expect(budgetSource).toContain('asset.name.startsWith("vendor-react-flow-")');
  });

  test("does not retain the removed Home WebGL renderer budget", () => {
    const viteSource = readFileSync(
      join(process.cwd(), "vite.config.ts"),
      "utf8",
    );
    const budgetSource = readFileSync(budgetScriptPath, "utf8");

    expect(viteSource).not.toContain('return "vendor-three"');
    expect(budgetSource).not.toContain("MAX_HOME_COSMIC_RENDERER_JS_BYTES");
    expect(budgetSource).not.toContain('asset.name.startsWith("homeCosmicRenderer-")');
    expect(budgetSource).not.toContain('asset.name.startsWith("vendor-three-")');
  });

  test("counts deduplicated CSS across Home's full static import graph", () => {
    const distDirectory = mkdtempSync(join(tmpdir(), "adcraft-build-budget-"));
    temporaryDirectories.push(distDirectory);
    const assetsDirectory = join(distDirectory, "assets");
    const manifestDirectory = join(distDirectory, ".vite");
    mkdirSync(assetsDirectory);
    mkdirSync(manifestDirectory);

    for (const asset of [
      "index-fixture.js",
      "home-fixture.js",
      "shared-a-fixture.js",
      "shared-b-fixture.js",
      "screenplay-editor-fixture.js",
      "V2FinalCompositionEditor-fixture.js",
      "V2ShotTimeline-fixture.js",
      "timeline-editor-fixture.js",
      "timeline-editor-fixture.css",
    ]) {
      writeAsset(assetsDirectory, asset);
    }
    writeAsset(assetsDirectory, "home-fixture.css", 2 * 1024);
    writeAsset(assetsDirectory, "shared-fixture.css", 15 * 1024);
    writeAsset(assetsDirectory, "global-fixture.css", 12 * 1024);

    writeFileSync(join(manifestDirectory, "manifest.json"), JSON.stringify({
      "index.html": {
        file: "assets/index-fixture.js",
        css: ["assets/global-fixture.css"],
      },
      "src/pages/HomePage.tsx": {
        file: "assets/home-fixture.js",
        css: ["assets/home-fixture.css"],
        imports: ["_shared-a.js", "_shared-b.js", "index.html"],
      },
      "_shared-a.js": {
        file: "assets/shared-a-fixture.js",
        css: ["assets/shared-fixture.css"],
        imports: ["_shared-b.js"],
      },
      "_shared-b.js": {
        file: "assets/shared-b-fixture.js",
        css: ["assets/shared-fixture.css"],
      },
      "src/features/agent-canvas/editing/AgentCanvasEditing.tsx": {
        file: "assets/V2FinalCompositionEditor-fixture.js",
        dynamicImports: [
          "src/features/agent-canvas/editing/AgentCanvasTimeline.tsx",
        ],
      },
      "src/features/agent-canvas/editing/AgentCanvasTimeline.tsx": {
        file: "assets/V2ShotTimeline-fixture.js",
        imports: ["_timeline-editor.js"],
      },
      "_timeline-editor.js": {
        file: "assets/timeline-editor-fixture.js",
      },
    }));

    const result = spawnSync(process.execPath, [
      budgetScriptPath,
      "--dist",
      distDirectory,
    ], { encoding: "utf8" });

    expect(result.status).toBe(1);
    expect(result.stdout).toContain("Home route CSS total: 17 KiB");
    expect(result.stderr).toContain("Home route CSS is 17 KiB, expected <= 16 KiB");
  });

  test("rejects a production-shaped Agent Canvas route without the React Flow vendor import", () => {
    const distDirectory = mkdtempSync(join(tmpdir(), "adcraft-build-budget-"));
    temporaryDirectories.push(distDirectory);
    const assetsDirectory = join(distDirectory, "assets");
    const manifestDirectory = join(distDirectory, ".vite");
    mkdirSync(assetsDirectory);
    mkdirSync(manifestDirectory);

    for (const asset of [
      "index-fixture.js",
      "home-fixture.js",
      "WorkflowPage-fixture.js",
      "vendor-react-flow-fixture.js",
      "global-fixture.css",
      "home-fixture.css",
      "WorkflowPage-fixture.css",
      "vendor-react-flow-fixture.css",
    ]) {
      writeAsset(assetsDirectory, asset);
    }

    writeFileSync(join(manifestDirectory, "manifest.json"), JSON.stringify({
      "index.html": {
        file: "assets/index-fixture.js",
        css: ["assets/global-fixture.css"],
      },
      "src/pages/HomePage.tsx": {
        file: "assets/home-fixture.js",
        css: ["assets/home-fixture.css"],
      },
      "src/pages/WorkflowPage.tsx": {
        name: "WorkflowPage",
        file: "assets/WorkflowPage-fixture.js",
        css: ["assets/WorkflowPage-fixture.css"],
      },
      "_vendor-react-flow.js": {
        name: "vendor-react-flow",
        file: "assets/vendor-react-flow-fixture.js",
        css: ["assets/vendor-react-flow-fixture.css"],
      },
    }));

    const result = spawnSync(process.execPath, [
      budgetScriptPath,
      "--dist",
      distDirectory,
    ], { encoding: "utf8" });

    expect(result.status).toBe(1);
    expect(result.stderr).toContain(
      "Agent Canvas Workflow route does not own the React Flow vendor chunk",
    );
  });
});
