import { existsSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("shared static cosmic background", () => {
  it("ships the black-hole wallpaper and removes retired background assets", () => {
    const path = resolve(
      process.cwd(),
      "public/assets/home-dark-black-hole.webp",
    );
    const retiredBackgroundPath = resolve(
      process.cwd(),
      "public/assets/home-dark-cosmic.webp",
    );
    const removedRingPath = resolve(
      process.cwd(),
      "public/assets/home-cosmic-ring.webp",
    );

    expect(existsSync(path)).toBe(true);
    expect(statSync(path).size).toBeLessThan(1_200_000);
    expect(existsSync(retiredBackgroundPath)).toBe(false);
    expect(existsSync(removedRingPath)).toBe(false);
  });

  // 订正（2026-09-29 晚）：P5 治理曾按本测试的"缺席"断言把 three/@react-three/*
  // 从 package.json 删除，理由"src 零 import"是误判——3D 预演的实时预览
  // SceneScript3DPreview.tsx（经 SceneScript3DEditor/SceneScriptPanel 上车）
  // 仍在 import 它们。移除 Three.js **背景**是有意的产品变更，但依赖不是
  // "忘删"：背景资产缺席由上一条测试锁，依赖在场由本测试锁。
  it("keeps the three.js dependencies required by the live 3D preview chain", () => {
    const packageJson = JSON.parse(
      readFileSync(resolve(process.cwd(), "package.json"), "utf8"),
    ) as {
      dependencies?: Record<string, string>;
      devDependencies?: Record<string, string>;
    };

    expect(packageJson.dependencies?.three).toBeDefined();
    expect(packageJson.dependencies?.["@react-three/fiber"]).toBeDefined();
    expect(packageJson.dependencies?.["@react-three/drei"]).toBeDefined();
    expect(packageJson.devDependencies?.["@types/three"]).toBeDefined();
  });
});
