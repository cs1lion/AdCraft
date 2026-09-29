import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const sourceRoot = resolve(process.cwd(), "src");
const agentCanvasRoot = resolve(sourceRoot, "features/agent-canvas");

const retiredRoutePatterns = [
  /plan-from-(?:prompt|chat)/,
  /\/items\//,
  /\/slots\//,
  /working-version/,
  /selected-version/,
  /chat-target/,
  /chat-actions/,
  /free-nodes?/,
  // 只匹配**路由段**（前后带斜杠）："/final-composition/renders/…" 是路由引用；
  // "final-composition 面板/时间线" 是产品文案术语（域词汇），不是路由。
  // 原无斜杠模式把文案也判违规——误报比没检查更糟（可达性工具的同样教训）。
  /\/final-composition\//,
  /\/provider-tasks\//,
  /continue_planning/,
];

const retiredClientMethods = [
  "planFromPrompt",
  "planFromChat",
  "generateSlot",
  "regenerateSlot",
  "selectSlotVersion",
  "discardWorkingVersion",
  "resolveChatTarget",
  "applyChatAction",
  "createFreeNode",
  "renderFinalComposition",
  "pollProviderTask",
];

const retiredGuidancePatterns = [
  /creative_session/,
  /AdaptiveProduction/,
  /production_recipe_/,
  /planning_topic_updated/,
  /specialist_activity_/,
  /creative_proposal_/,
  /available_actions/,
  /generation_action/,
  /add_another_topic_node/,
  /skip_topic/,
];

function sourceFiles(directory: string): string[] {
  return readdirSync(directory)
    .flatMap((entry) => {
      const path = resolve(directory, entry);
      if (statSync(path).isDirectory()) return sourceFiles(path);
      return /\.[cm]?[jt]sx?$/.test(entry) && !entry.includes(".test.")
        ? [path]
        : [];
    });
}

describe("Agent Canvas production route boundary", () => {
  it("cannot import the broad legacy V2 client or reference retired routes", () => {
    const violations = sourceFiles(agentCanvasRoot).flatMap((path) => {
      const source = readFileSync(path, "utf8");
      const relativePath = path.slice(sourceRoot.length + 1);
      const reasons = [
        ...(source.includes("/api/v2Client") || source.includes("../../api/v2Client")
          ? ["imports v2Client directly"]
          : []),
        ...retiredRoutePatterns
          .filter((pattern) => pattern.test(source))
          .map((pattern) => `contains ${pattern.source}`),
        ...retiredClientMethods
          .filter((method) => source.includes(method))
          .map((method) => `uses ${method}`),
        ...retiredGuidancePatterns
          .filter((pattern) => pattern.test(source))
          .map((pattern) => `contains retired guidance contract ${pattern.source}`),
      ];
      return reasons.map((reason) => `${relativePath}: ${reason}`);
    });

    expect(violations).toEqual([]);
  });

  it("keeps the workflow route on the Agent Canvas page", () => {
    const workflowPage = readFileSync(resolve(sourceRoot, "pages/WorkflowPage.tsx"), "utf8");
    expect(workflowPage).toContain('features/agent-canvas/AgentCanvasPage.tsx');
    expect(workflowPage).not.toContain("features/workflow/");
  });

  it("keeps retired capabilities out of the narrow Agent Canvas API facade", () => {
    const facade = readFileSync(resolve(sourceRoot, "api/agentCanvasApi.ts"), "utf8");
    const violations = [
      ...retiredRoutePatterns
        .filter((pattern) => pattern.test(facade))
        .map((pattern) => `contains ${pattern.source}`),
      ...retiredClientMethods
        .filter((method) => facade.includes(method))
        .map((method) => `exposes ${method}`),
    ];
    expect(violations).toEqual([]);
  });

  // 46ec7e14 把 final-composition 路由字面量从 agent-canvas 移进了
  // `api/finalRenderPaths.ts`——那在本闸的扫描树之外，路由引用一夜之间失去
  // 管辖：若哪天这两个 builder 被指向别的退役路由族，没有任何灯会红。
  // 这里把该文件纳入管辖：全文件只允许一个 final-composition state 路由族
  // 字面量（cancel 路径由它派生），多一个退役字面量都不行。
  it("keeps finalRenderPaths.ts the single sanctioned home for final-composition routes", () => {
    const finalRenderPaths = readFileSync(resolve(sourceRoot, "api/finalRenderPaths.ts"), "utf8");

    // 全文件唯一允许的路由字面量（cancel 路径由它派生，自身不生成新字面量）
    const sanctionedRouteLiteral =
      "/api/v2/workflows/${encodeURIComponent(workflowId)}/final-composition/renders/${encodeURIComponent(renderId)}";
    const routeLiterals = [
      ...finalRenderPaths.matchAll(/[`"']([^`"']*\/api\/[^`"']*)[`"']/g),
    ].map((match) => match[1]);

    const violations = [
      ...routeLiterals
        .filter((literal) => literal !== sanctionedRouteLiteral)
        .map((literal) => `contains route literal ${literal}`),
      ...(finalRenderPaths.includes("v2Client") ? ["imports the broad v2 client"] : []),
      ...retiredClientMethods
        .filter((method) => finalRenderPaths.includes(method))
        .map((method) => `uses retired client method ${method}`),
      // 剥掉唯一合法字面量后再跑退役路由模式：白名单之外的任何形态都算违规
      ...retiredRoutePatterns.filter((pattern) =>
        pattern.test(routeLiterals.reduce((text, literal) => text.replaceAll(literal, ""), finalRenderPaths)),
      ).map((pattern) => `contains ${pattern.source}`),
      // 消费方（ReplicaBlueprintPanel 等）依赖这两个导出
      ...(finalRenderPaths.includes("export function finalRenderStatePath") ? [] : ["missing finalRenderStatePath export"]),
      ...(finalRenderPaths.includes("export function finalRenderCancelPath") ? [] : ["missing finalRenderCancelPath export"]),
    ];

    expect(violations).toEqual([]);
  });
});
