/** 语言搭建映射器测试（2026-09-29 简约好用分支）。 */

import { describe, expect, it } from "vitest";

import { defaultPosition, parseSceneLanguage } from "./sceneLanguageOps";

describe("parseSceneLanguage", () => {
  it("maps 中文关键词 to props", () => {
    const op = parseSceneLanguage("加一张方桌");
    expect(op).toMatchObject({ kind: "prop", type: "rect_table" });
    expect(parseSceneLanguage("加一把椅子")).toMatchObject({ kind: "prop", type: "chair" });
    expect(parseSceneLanguage("来一个花瓶")).toMatchObject({ kind: "prop", type: "vase" });
  });

  it("maps 环境/建筑 keywords", () => {
    expect(parseSceneLanguage("加一面墙")).toMatchObject({ kind: "environment", type: "wall" });
    expect(parseSceneLanguage("种一棵树")).toMatchObject({ kind: "environment", type: "tree" });
    expect(parseSceneLanguage("开一扇窗")).toMatchObject({ kind: "environment", type: "window" });
  });

  it("maps people and honours position hints", () => {
    const left = parseSceneLanguage("加一个人物在左边");
    expect(left).toMatchObject({ kind: "character" });
    expect(left?.position[0]).toBeLessThan(0);
    const right = parseSceneLanguage("加一个人物在右边");
    expect(right?.position[0]).toBeGreaterThan(0);
  });

  it("staggers default positions instead of stacking", () => {
    const first = parseSceneLanguage("加一张桌子", 0);
    const second = parseSceneLanguage("加一张桌子", 1);
    expect(first?.position[0]).not.toBe(second?.position[0]);
  });

  it("returns null for unknown or empty input", () => {
    expect(parseSceneLanguage("")).toBeNull();
    expect(parseSceneLanguage("今天天气不错")).toBeNull();
  });

  it("generates unique ids", () => {
    const a = parseSceneLanguage("加一张桌子", 0);
    const b = parseSceneLanguage("加一张桌子", 0);
    expect(a?.id).not.toBe(b?.id);
  });
});

describe("defaultPosition", () => {
  it("keeps every slot distinct", () => {
    const xs = Array.from({ length: 6 }, (_, index) => defaultPosition(index)[0]);
    expect(new Set(xs).size).toBe(6);
  });
});
