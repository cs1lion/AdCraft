/**
 * 语言搭建（2026-09-29 简约好用分支）：一句中文 → 一个 SceneScript 实体。
 *
 * 作者说"加一张桌子在左边"，后台粗略搭起来、预览实时更新。MVP 是确定性的
 * 关键词映射——不烧 LLM、不猜意图；复杂句式交给 AI 兜底（/language-fallback）。
 * 位置默认错开排布，显式方位词（左/右/中/前/后）覆盖默认。
 *
 * 相对位置（2026-10-02）：「放在桌子后面 / 在桌子旁边加一把椅子 / 桌上放一本
 * 书」引用场景里已有的实体作锚点——主语（VOCAB 命中）+ 锚点词（ANCHOR_WORDS，
 * 允许掉"子"尾）+ 锚点后紧跟的方位词。锚点实体不存在、或句子里只有锚点没有
 * 主语时返回 null（交给 AI 兜底），没有锚点短语时保持原有的绝对方位行为。
 * 多个同类锚点取第一个，确定性优先。
 */

export type SceneLanguageOp =
  | { kind: "prop"; type: string; id: string; position: [number, number, number] }
  | { kind: "environment"; type: string; id: string; position: [number, number, number] }
  | { kind: "character"; id: string; position: [number, number, number] };

/** 相对位置解析需要的场景切片（SceneScriptRoot 结构兼容）。角色定位在
 * keyframes 里，顶层 position 是语言搭建新建实体才带的便捷字段。 */
export interface SceneLanguageScript {
  props: ReadonlyArray<{ type: string; position: readonly number[]; scale?: number }>;
  environment: ReadonlyArray<{ type: string; position: readonly number[]; scale?: number }>;
  characters: ReadonlyArray<{
    position?: readonly number[];
    appearance?: { height?: number };
    keyframes?: ReadonlyArray<{ position?: readonly number[] }>;
  }>;
}

interface VocabEntry {
  pattern: RegExp;
  kind: SceneLanguageOp["kind"];
  type: string;
}

/** 实体关键词词表。导出仅供跨边界契约测试锁定：映射目标必须存在于 schema。 */
export const VOCAB: VocabEntry[] = [
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
  { pattern: /书本|图书|一本书|书/, kind: "prop", type: "book" },
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

/**
 * 锚点词：只用于定位"方位词跟在谁后面"，绝不创建实体。比 VOCAB 多出掉
 * "子"尾的短形（桌上/椅上/树上）。顺序即优先级，具体的排前面（板条箱先于箱子）。
 * 导出仅供跨边界契约测试锁定映射目标。
 */
export const ANCHOR_WORDS: VocabEntry[] = [
  { pattern: /圆桌/, kind: "prop", type: "round_table" },
  { pattern: /方桌|餐桌|桌子|桌/, kind: "prop", type: "rect_table" },
  { pattern: /板条箱|条箱/, kind: "prop", type: "crate" },
  { pattern: /箱子|箱/, kind: "prop", type: "box" },
  { pattern: /椅子|椅/, kind: "prop", type: "chair" },
  { pattern: /凳子|凳/, kind: "prop", type: "stool" },
  { pattern: /树木|一棵树|树/, kind: "environment", type: "tree" },
  { pattern: /墙壁|一面墙|墙/, kind: "environment", type: "wall" },
  { pattern: /石柱|柱子|柱/, kind: "environment", type: "pillar" },
  { pattern: /窗户|一扇窗|窗/, kind: "environment", type: "window" },
  { pattern: /平台|高台/, kind: "environment", type: "platform" },
  { pattern: /岩石|石块|石头/, kind: "environment", type: "rock" },
  { pattern: /人物|角色|一个人|人/, kind: "character", type: "lowpoly_human" },
];

/** 锚点后紧跟的方位词（最长优先），只认"的"和空白作连接。 */
const DIRECTION_PATTERN =
  /^[的]?\s*(后面|背后|后方|前面|前方|左边|左侧|右边|右侧|旁边|边上|附近|跟前|上面|上边|上头|顶上|头顶|头上|上)/;

/** 叠放方位（锚点顶面），其余方位是 XY 平面偏移（X 右，Y 前，Z 上）。 */
const STACK_DIRECTIONS = new Set(["上面", "上边", "上头", "顶上", "头顶", "头上", "上"]);

const RELATIVE_OFFSETS: Record<string, [number, number, number]> = {
  后面: [0, 1.5, 0],
  背后: [0, 1.5, 0],
  后方: [0, 1.5, 0],
  前面: [0, -1.5, 0],
  前方: [0, -1.5, 0],
  左边: [-1.5, 0, 0],
  左侧: [-1.5, 0, 0],
  右边: [1.5, 0, 0],
  右侧: [1.5, 0, 0],
  旁边: [1.3, 0.6, 0],
  边上: [1.3, 0.6, 0],
  附近: [1.3, 0.6, 0],
  跟前: [1.0, 0.8, 0],
};

/**
 * 叠放用的对象顶面近似高度（米），对照 sceneScriptGeometry.tsx 的原语尺寸
 * 校准——白模定位是提示性的，精确顶面以渲染器为准。
 */
const STACK_HEIGHTS: Record<string, number> = {
  round_table: 0.8,
  rect_table: 0.8,
  chair: 0.45,
  stool: 0.5,
  crate: 0.6,
  box: 0.5,
  lantern: 0.4,
  vase: 0.35,
  weapon: 0.15,
  scroll: 0.1,
  book: 0.05,
  cup: 0.1,
  platform: 1.0,
  rock: 0.8,
  fence: 1.0,
  stairs: 1.5,
  door: 2.0,
  window: 1.5,
  wall: 5.0,
  pillar: 4.0,
  tree: 3.0,
  gable_roof: 2.0,
  flat_roof: 0.5,
  floor: 0.05,
};

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

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

interface SpanHit {
  kind: VocabEntry["kind"];
  type: string;
  start: number;
  end: number;
}

function scan(text: string, entries: VocabEntry[]): SpanHit[] {
  const hits: SpanHit[] = [];
  for (const entry of entries) {
    const match = entry.pattern.exec(text);
    if (match) {
      hits.push({ kind: entry.kind, type: entry.type, start: match.index, end: match.index + match[0].length });
    }
  }
  return hits;
}

function overlaps(a: SpanHit, b: SpanHit): boolean {
  return a.start < b.end && b.start < a.end;
}

function buildOp(hit: SpanHit, position: [number, number, number]): SceneLanguageOp {
  seq += 1;
  const id = `${hit.kind}_${hit.type}_${Date.now().toString(36)}${seq.toString(36)}`;
  if (hit.kind === "character") {
    return { kind: "character", id, position };
  }
  return { kind: hit.kind, type: hit.type, id, position };
}

function resolveAnchor(
  script: SceneLanguageScript,
  hit: SpanHit,
): { position: [number, number, number]; height: number } | null {
  if (hit.kind === "character") {
    const character = script.characters[0];
    if (!character) return null;
    const position = character.position ?? character.keyframes?.[0]?.position ?? [0, 0, 0];
    return {
      position: [position[0], position[1], position[2]],
      height: character.appearance?.height ?? 1.7,
    };
  }
  const pool = hit.kind === "prop" ? script.props : script.environment;
  const entity = pool.find((candidate) => candidate.type === hit.type);
  if (!entity) return null;
  return {
    position: [entity.position[0], entity.position[1], entity.position[2]],
    height: (STACK_HEIGHTS[hit.type] ?? 0.5) * (entity.scale ?? 1),
  };
}

let seq = 0;

export function parseSceneLanguage(
  input: string,
  count = 0,
  script?: SceneLanguageScript,
): SceneLanguageOp | null {
  const text = input.trim();
  if (!text) return null;

  const subjectHits = scan(text, VOCAB);
  if (!subjectHits.length) return null;

  // 相对位置：锚点词 + 紧跟的方位词。命中即按相对意图处理——缺主语
  // （"放在桌子后面"）或缺锚点实体时返回 null 交给 AI，不按绝对方位瞎猜。
  if (script) {
    const anchored = scan(text, ANCHOR_WORDS)
      .map((hit) => {
        const match = DIRECTION_PATTERN.exec(text.slice(hit.end));
        return match ? { hit, direction: match[1] } : null;
      })
      .filter((entry): entry is { hit: SpanHit; direction: string } => entry !== null)
      .pop();
    if (anchored) {
      const subject = subjectHits.find((hit) => !overlaps(hit, anchored.hit));
      const anchor = subject ? resolveAnchor(script, anchored.hit) : null;
      if (!subject || !anchor) return null;
      const offset: [number, number, number] = STACK_DIRECTIONS.has(anchored.direction)
        ? [0, 0, anchor.height]
        : RELATIVE_OFFSETS[anchored.direction];
      return buildOp(subject, [
        clamp(anchor.position[0] + offset[0], -50, 50),
        clamp(anchor.position[1] + offset[1], -50, 50),
        clamp(anchor.position[2] + offset[2], 0, 30),
      ]);
    }
  }

  const hit = subjectHits[0];
  const hint = POSITION_HINTS.find((entry) => entry.pattern.test(text));
  const position = hint ? hint.position : defaultPosition(count);
  return buildOp(hit, position);
}

export const QUICK_ADDS: readonly string[] = [
  "加一张桌子",
  "加一把椅子",
  "加一棵树",
  "加一面墙",
  "加一个人物",
];
