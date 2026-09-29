/**
 * 语言搭建（2026-09-29 简约好用分支）：一句中文 → 一个 SceneScript 实体。
 *
 * 作者说"加一张桌子在左边"，后台粗略搭起来、预览实时更新。MVP 是确定性的
 * 关键词映射——不烧 LLM、不猜意图；复杂句式留给后续的 agent 白模模式。
 * 位置默认错开排布，显式方位词（左/右/中/前/后）覆盖默认。
 */

export type SceneLanguageOp =
  | { kind: "prop"; type: string; id: string; position: [number, number, number] }
  | { kind: "environment"; type: string; id: string; position: [number, number, number] }
  | { kind: "character"; id: string; position: [number, number, number] };

const VOCAB: Array<{ pattern: RegExp; kind: SceneLanguageOp["kind"]; type: string }> = [
  { pattern: /圆桌/, kind: "prop", type: "round_table" },
  { pattern: /方桌|餐桌|桌子/, kind: "prop", type: "rect_table" },
  { pattern: /椅子|座椅/, kind: "prop", type: "chair" },
  { pattern: /凳子/, kind: "prop", type: "stool" },
  { pattern: /灯笼/, kind: "prop", type: "lantern" },
  { pattern: /木箱|箱子/, kind: "prop", type: "box" },
  { pattern: /板条箱|条箱/, kind: "prop", type: "crate" },
  { pattern: /花瓶/, kind: "prop", type: "vase" },
  { pattern: /武器|刀剑/, kind: "prop", type: "weapon" },
  { pattern: /卷轴/, kind: "prop", type: "scroll" },
  { pattern: /书本|图书|一本书/, kind: "prop", type: "book" },
  { pattern: /杯子|水杯/, kind: "prop", type: "cup" },
  { pattern: /墙壁|一面墙|墙/, kind: "environment", type: "wall" },
  { pattern: /石柱|柱子/, kind: "environment", type: "pillar" },
  { pattern: /地板|木地板/, kind: "environment", type: "floor" },
  { pattern: /坡顶|斜顶/, kind: "environment", type: "gable_roof" },
  { pattern: /平顶/, kind: "environment", type: "flat_roof" },
  { pattern: /大门|一扇门|门/, kind: "environment", type: "door" },
  { pattern: /窗户|一扇窗|窗/, kind: "environment", type: "window" },
  { pattern: /楼梯|台阶/, kind: "environment", type: "stairs" },
  { pattern: /平台|高台/, kind: "environment", type: "platform" },
  { pattern: /树木|一棵树|树/, kind: "environment", type: "tree" },
  { pattern: /岩石|石块|石头/, kind: "environment", type: "rock" },
  { pattern: /栅栏|篱笆/, kind: "environment", type: "fence" },
  { pattern: /人物|角色|一个人|人/, kind: "character", type: "lowpoly_human" },
];

const POSITION_HINTS: Array<{ pattern: RegExp; position: [number, number, number] }> = [
  { pattern: /左/, position: [-2.2, 0, 0] },
  { pattern: /右/, position: [2.2, 0, 0] },
  { pattern: /中间|中央|当中/, position: [0, 0, 0] },
  { pattern: /前/, position: [0, -2.2, 0] },
  { pattern: /后/, position: [0, 2.2, 0] },
];

/** 默认错开排布：第 n 个实体沿 x 轴散开，避免全叠在原点。 */
export function defaultPosition(count: number): [number, number, number] {
  return [((count % 6) - 2.5) * 1.4, 0, 0];
}

let seq = 0;

export function parseSceneLanguage(input: string, count = 0): SceneLanguageOp | null {
  const text = input.trim();
  if (!text) return null;
  const hit = VOCAB.find((entry) => entry.pattern.test(text));
  if (!hit) return null;
  const hint = POSITION_HINTS.find((entry) => entry.pattern.test(text));
  const position = hint ? hint.position : defaultPosition(count);
  seq += 1;
  const id = `${hit.kind}_${hit.type}_${Date.now().toString(36)}${seq.toString(36)}`;
  if (hit.kind === "character") {
    return { kind: "character", id, position };
  }
  return { kind: hit.kind, type: hit.type, id, position };
}

export const QUICK_ADDS: readonly string[] = [
  "加一张桌子",
  "加一把椅子",
  "加一棵树",
  "加一面墙",
  "加一个人物",
];
