import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { builtinModules } from "node:module";

import { describe, expect, it } from "vitest";

/**
 * 被 vi.mock 的模块，其依赖不得从 package.json 删除。
 *
 * 2026-09-29 实测盲区（P5 治理误删 three 链的成因）：`SceneScript3DPreview.tsx`
 * 一直在 import `three`/`@react-three/*`，但两个测试文件都 `vi.mock` 掉了这个
 * 组件——测试套件从未真正加载过 three。于是把这三个依赖从 package.json 删掉
 * 之后，tsc/vitest 本地全绿（`--package-lock-only` 不剪枝 node_modules），只有
 * 干净安装（npm ci）才断链。孤立地看每个测试都绿，合起来却把断链放过了。
 *
 * 本闸堵住这个模式：对每个测试里的 `vi.mock("<相对路径>")`，解析到本地模块，
 * 沿本地 import 闭包（含再导出链）收集所有裸包名，逐一断言 package.json 的
 * dependencies / devDependencies 仍然声明它们。被 mock 的本地模块在测试中
 * 从不加载，它的依赖缺席没有任何现有红灯能发现——只有这第五条能。
 */

const sourceRoot = resolve(process.cwd(), "src");

// import/export ... from "x" / import "x" / import("x") / require("x")
const IMPORT_PATTERN = /(?:\bfrom\s*|\bimport\s*\(|\bimport\s+|\brequire\(\s*)["']([^"']+)["']/g;

const RESOLVE_EXTENSIONS = [".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"];
const INDEX_CANDIDATES = ["index.ts", "index.tsx", "index.js"];

// 单个 vi.mock 目标的 import 闭包审计上限（防病态大图；触顶必须报警而不是静默截断）
const CLOSURE_LIMIT = 500;

type PackageJson = {
  dependencies?: Record<string, string>;
  devDependencies?: Record<string, string>;
};

function declaredPackages(json: PackageJson): Set<string> {
  return new Set([
    ...Object.keys(json.dependencies ?? {}),
    ...Object.keys(json.devDependencies ?? {}),
  ]);
}

function testFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = resolve(directory, entry);
    if (statSync(path).isDirectory()) return testFiles(path);
    return /\.test\.tsx?$/.test(entry) ? [path] : [];
  });
}

function mockedSpecifiers(source: string): string[] {
  return [...source.matchAll(/\bvi\.(?:do)?mock\(\s*["']([^"']+)["']/g)].map((match) => match[1]);
}

function isFile(path: string): boolean {
  return existsSync(path) && statSync(path).isFile();
}

function resolveLocalModule(specifier: string, fromDir: string): string | null {
  const base = resolve(fromDir, specifier);
  if (isFile(base)) return base;
  for (const extension of RESOLVE_EXTENSIONS) {
    if (isFile(base + extension)) return base + extension;
  }
  if (existsSync(base) && statSync(base).isDirectory()) {
    for (const index of INDEX_CANDIDATES) {
      const candidate = resolve(base, index);
      if (isFile(candidate)) return candidate;
    }
  }
  return null;
}

// 剥掉注释再扫 import：源码注释里的英文散文（from "faithful" …）不是 import。
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/[^\n]*/g, "$1");
}

function packageNameOf(specifier: string): string | null {
  if (specifier.startsWith(".") || specifier.startsWith("/")) return null;
  if (specifier.startsWith("node:") || builtinModules.includes(specifier.split("/")[0])) {
    return null;
  }
  // 侧-effect 的资源导入不是包依赖
  if (/\.(css|scss|sass|less|svg|png|jpe?g|gif|webp|mp4|mp3|wav|json|woff2?)$/.test(specifier)) {
    return null;
  }
  const segments = specifier.split("/");
  return specifier.startsWith("@") ? segments.slice(0, 2).join("/") : segments[0];
}

/**
 * 从入口本地模块出发走 import 闭包：返回闭包内引用到的、未在 package.json
 * 声明的裸包名；以及审计是否触顶（触顶 = 结果不可信，必须报警）。
 */
function undeclaredPackagesInClosure(entry: string, declared: Set<string>): {
  missing: Set<string>;
  truncated: boolean;
} {
  const queue = [entry];
  const seen = new Set<string>();
  const missing = new Set<string>();
  while (queue.length > 0) {
    if (seen.size >= CLOSURE_LIMIT) {
      return { missing, truncated: true };
    }
    const file = queue.pop();
    if (file === undefined || seen.has(file) || !isFile(file)) continue;
    seen.add(file);
    const moduleSource = stripComments(readFileSync(file, "utf8"));
    for (const specifier of [...moduleSource.matchAll(IMPORT_PATTERN)].map(
      (match) => match[1],
    )) {
      const packageName = packageNameOf(specifier);
      if (packageName) {
        if (!declared.has(packageName)) missing.add(packageName);
        continue;
      }
      if (specifier.startsWith(".")) {
        const nested = resolveLocalModule(specifier, dirname(file));
        if (nested) queue.push(nested);
      }
    }
  }
  return { missing, truncated: false };
}

describe("mocked modules keep their dependencies declared", () => {
  const packageJson = JSON.parse(
    readFileSync(resolve(process.cwd(), "package.json"), "utf8"),
  ) as PackageJson;
  const declared = declaredPackages(packageJson);

  it("keeps every dependency of a vi.mock'ed local module present in package.json", () => {
    const violations = testFiles(sourceRoot).flatMap((testFile) => {
      const source = readFileSync(testFile, "utf8");
      return mockedSpecifiers(source).flatMap((specifier) => {
        // 只闸本地模块：包级 mock（如 "@xyflow/react"）mock 的即包本身，没有
        // 本地源码可查它的依赖；包的缺席由 tsc/干净安装兜。
        if (!specifier.startsWith(".")) return [];
        const entry = resolveLocalModule(specifier, dirname(testFile));
        const testRelative = relative(process.cwd(), testFile);
        if (!entry) {
          return [`${testRelative}: vi.mock("${specifier}") cannot be resolved to a local module`];
        }
        const { missing, truncated } = undeclaredPackagesInClosure(entry, declared);
        return [
          ...(truncated
            ? [`${testRelative}: closure audit of ${relative(process.cwd(), entry)} exceeded ${CLOSURE_LIMIT} modules — audit truncated, result not trustworthy`]
            : []),
          ...[...missing].map(
            (packageName) =>
              `${testRelative}: vi.mock's ${relative(process.cwd(), entry)} imports "${packageName}", which package.json does not declare (mocked modules never load in tests — nothing else would catch this)`,
          ),
        ];
      });
    });

    expect(violations).toEqual([]);
  });
});
