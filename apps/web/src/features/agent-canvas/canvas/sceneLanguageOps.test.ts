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

describe("relative placement", () => {
  function scriptWithTable(scale = 1) {
    return {
      props: [{ id: "prop_rect_table_1", type: "rect_table", position: [2, 1, 0], scale }],
      environment: [],
      characters: [],
    };
  }

  it("places a subject behind an existing anchor", () => {
    const op = parseSceneLanguage("加一把椅子放在桌子后面", 1, scriptWithTable());
    expect(op).toMatchObject({ kind: "prop", type: "chair" });
    expect(op?.position[0]).toBeCloseTo(2);
    expect(op?.position[1]).toBeCloseTo(2.5); // 1 + 1.5
  });

  it("understands anchor-first grammar (在桌子旁边加…)", () => {
    const op = parseSceneLanguage("在桌子旁边加一把椅子", 1, scriptWithTable());
    expect(op?.type).toBe("chair");
    expect(op?.position[0]).toBeCloseTo(3.3); // 2 + 1.3
    expect(op?.position[1]).toBeCloseTo(1.6); // 1 + 0.6
  });

  it("stacks on the anchor top (桌上放一本书)", () => {
    const op = parseSceneLanguage("桌上放一本书", 1, scriptWithTable());
    expect(op).toMatchObject({ kind: "prop", type: "book" });
    expect(op?.position[0]).toBeCloseTo(2);
    expect(op?.position[1]).toBeCloseTo(1);
    expect(op?.position[2]).toBeCloseTo(0.8); // rect_table 顶面
  });

  it("stacking respects the anchor scale", () => {
    const op = parseSceneLanguage("桌上放一本书", 1, scriptWithTable(2));
    expect(op?.position[2]).toBeCloseTo(1.6);
  });

  it("hands a relative sentence with a missing anchor entity to the AI path", () => {
    expect(
      parseSceneLanguage("加一把椅子放在桌子后面", 1, { props: [], environment: [], characters: [] }),
    ).toBeNull();
  });

  it("hands an anchor-only sentence (放在桌子后面) to the AI path", () => {
    expect(parseSceneLanguage("放在桌子后面", 1, scriptWithTable())).toBeNull();
  });

  it("keeps absolute scene placement when no anchor phrase exists", () => {
    const op = parseSceneLanguage("加一个人物在左边");
    expect(op).toMatchObject({ kind: "character" });
    expect(op?.position[0]).toBeLessThan(0);
  });

  it("supports a character anchor (人物头上…)", () => {
    const scene = {
      props: [],
      environment: [],
      characters: [{ position: [0, 0, 0], appearance: { height: 1.8 } }],
    };
    const op = parseSceneLanguage("人物头上放一个灯笼", 1, scene);
    expect(op).toMatchObject({ kind: "prop", type: "lantern" });
    expect(op?.position[2]).toBeCloseTo(1.8);
  });
});
