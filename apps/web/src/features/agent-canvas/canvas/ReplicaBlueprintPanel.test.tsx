/**
 * ReplicaBlueprintPanel tests — the 拉片复刻 workbench (the "复刻" half UI).
 *
 * Locks: the empty-blueprint hint, slot editing, anchor keep/remove,
 * the save flow (patch + canvas sync), and the instantiate flow
 * (patch → POST /api/v1/replica/instantiate → workflow refetch → script
 * surface), plus the error surface.
 *
 * The App context boundary is mocked (useApp) so the panel can be tested
 * without the workspace provider.
 */

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CanvasNodeV2, ReplicaBlueprintContentV2 } from "../../../types-v2.ts";
import { ReplicaBlueprintPanel } from "./ReplicaBlueprintPanel.tsx";

const BLUEPRINT: ReplicaBlueprintContentV2 = {
  blueprint_version: "replica-blueprint-v1",
  source_video_asset_id: "asset-1",
  duration_seconds: 12,
  aspect: "9:16",
  replica_goal: "换商品",
  whole_piece_reading: "前3秒钩子，中段证明，结尾CTA。",
  format_name: "product-comparison",
  slots: [
    { kind: "character", label: "人物", source_value: "原片女主播", replace_with: "", applied: false },
    { kind: "product", label: "商品", source_value: "原片洗面奶", replace_with: "", applied: false },
    { kind: "script", label: "台词", source_value: "保留结构", replace_with: "", applied: false },
    { kind: "style", label: "风格", source_value: "", replace_with: "", applied: false },
    { kind: "voice", label: "声音", source_value: "", replace_with: "", applied: false },
  ],
  beats: [
    {
      beat_id: "b1",
      role: "hook",
      description: "错误示范抓注意力",
      start_seconds: 0,
      end_seconds: 3,
      anchor_event_ids: ["b1_caption", "b1_shot1_cap"],
    },
  ],
  anchor_events: [
    { event_id: "b1_caption", trigger: "hook 段落", beat_id: "b1", kind: "caption", hint: "此处挂字幕", keep: true },
    { event_id: "b1_shot1_cap", trigger: "别再这样洗脸", beat_id: "b1", kind: "caption", hint: "屏上文字系统", keep: true },
  ],
  shots: [
    { index: 1, start_seconds: 0, end_seconds: 2.1, shot_size: "closeup", camera_motion: "static", subject_action: "唇部特写", on_screen_text: "别再这样洗脸", transition_to_next: "cut", recreate_hint: "同机位换商品" },
  ],
  rhythm_avg_shot_seconds: 2.1,
  rhythm_cut_points_seconds: [0],
  rhythm_energy_curve: "前快后缓",
  systems_captions: "底部关键词高亮",
  systems_music: "轻快电子",
  systems_graphics: ["价格贴"],
  systems_sfx: [],
  constraints: ["推断值"],
  instantiated_script_node_id: null,
};

function replicaNode(): CanvasNodeV2 {
  return {
    node_id: "node_replica",
    workflow_id: "wf-1",
    node_type: "replica",
    creative_role: "replica_blueprint",
    title: "复刻蓝图",
    status: "draft",
    structured_content: BLUEPRINT as unknown as Record<string, unknown>,
    position: { x: 0, y: 0 },
  } as unknown as CanvasNodeV2;
}

const setAgentCanvasWorkflow = vi.fn();

vi.mock("../../../AppContextValue.ts", () => ({
  useApp: () => ({ setAgentCanvasWorkflow }),
}));

const patchNode = vi.fn(async () => ({ value: { workflow: { id: "wf-1" } } }));
const createNode = vi.fn();
const workflowWithEtag = vi.fn(async () => ({ value: { workflow_id: "wf-1" } }));

vi.mock("../../../api/agentCanvasApi.ts", () => ({
  agentCanvasApi: {
    patchAgentCanvasNode: (...args: unknown[]) => patchNode(...(args as [])),
    createAgentCanvasNode: (...args: unknown[]) => createNode(...(args as [])),
    agentCanvasWorkflowWithEtag: (...args: unknown[]) => workflowWithEtag(...(args as [])),
  },
}));

beforeEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  patchNode.mockClear();
  createNode.mockClear();
  workflowWithEtag.mockClear();
  setAgentCanvasWorkflow.mockClear();
  patchNode.mockResolvedValue({ value: { workflow: { id: "wf-1" } } });
  workflowWithEtag.mockResolvedValue({ value: { workflow_id: "wf-1" } });
});

// D7/D2 的 localStorage 渲染句柄（replica-render）是跨用例存活的全局状态：
// 不清理时，下一用例挂载面板即"重挂轮询"，直出按钮变成"⏳ 渲染中…"，与
// 用例的点击赛跑——偶发失败且难复现（-t 过滤跑必现行）。每个用例后清空。
afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("ReplicaBlueprintPanel", () => {
  it("shows the empty hint for a blank blueprint", () => {
    const node = replicaNode();
    node.structured_content = {};
    render(<ReplicaBlueprintPanel node={node} />);
    expect(screen.getByText(/空复刻蓝图/)).toBeTruthy();
  });

  it("shows the beat word stream (whisperX time spine) when words exist", () => {
    const node = replicaNode();
    const content = node.structured_content as unknown as ReplicaBlueprintContentV2;
    content.beats = content.beats.map((beat) =>
      beat.beat_id === "b1"
        ? {
            ...beat,
            words: [
              { text: "别再", start_seconds: 0.2, end_seconds: 0.5 },
              { text: "这样", start_seconds: 0.5, end_seconds: 0.9 },
            ],
          }
        : beat,
    );
    render(<ReplicaBlueprintPanel node={node} />);
    fireEvent.click(screen.getByText(/锚点事件\(2\)/));
    expect(screen.getByText(/词流 2 词/)).toBeTruthy();
    // 时间戳 chip 是词流独有（锚点触发文本里也有"别再"，不断言它）
    expect(screen.getByText(/0\.2–0\.5s/)).toBeTruthy();
    expect(screen.getByText(/0\.5–0\.9s/)).toBeTruthy();
  });

  it("renders slots, anchors and shots tabs", () => {
    render(<ReplicaBlueprintPanel node={replicaNode()} />);
    // slots tab (default)
    expect(screen.getByText("【商品】")).toBeTruthy();
    expect(screen.getByText(/原片洗面奶/)).toBeTruthy();
    // anchors tab
    fireEvent.click(screen.getByText(/锚点事件\(2\)/));
    expect(screen.getByText(/别再这样洗脸/)).toBeTruthy();
    // shots tab
    fireEvent.click(screen.getByText(/镜头表\(1\)/));
    expect(screen.getByText(/同机位换商品/)).toBeTruthy();
  });

  it("saves the blueprint through the canvas patch API", async () => {
    render(<ReplicaBlueprintPanel node={replicaNode()} />);
    const input = screen.getByPlaceholderText("商品资产 ID 或描述") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "洗面奶A" } });
    // dirty 态下保存按钮带 ● 标记，用正则匹配
    fireEvent.click(screen.getByText(/💾 保存蓝图/));

    await waitFor(() => expect(screen.getByText("✓ 蓝图已保存")).toBeTruthy());
    expect(patchNode).toHaveBeenCalledTimes(1);
    const [workflowId, nodeId, patch] = patchNode.mock.calls[0] as unknown as [
      string,
      string,
      { structured_content: Record<string, unknown> },
    ];
    expect(workflowId).toBe("wf-1");
    expect(nodeId).toBe("node_replica");
    const slots = patch.structured_content.slots as Array<{ kind: string; replace_with: string; applied: boolean }>;
    const product = slots.find((s) => s.kind === "product");
    expect(product?.replace_with).toBe("洗面奶A");
    expect(product?.applied).toBe(true);
    expect(setAgentCanvasWorkflow).toHaveBeenCalled();
  });

  it("instantiates: patch → replica/instantiate → workflow refetch → script surface", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 200,
        json: async () => ({
          success: true,
          script_node_id: "node_script_1",
          script_text: "# 复刻脚本\n替换为「洗面奶A」",
          workflow_revision: 8,
        }),
      }),
    );

    render(<ReplicaBlueprintPanel node={replicaNode()} />);
    const input = screen.getByPlaceholderText("商品资产 ID 或描述") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "洗面奶A" } });
    fireEvent.click(screen.getByText("⚡ 一键生成复刻工作流"));

    await waitFor(() =>
      expect(screen.getAllByText(/node_script_1/).length).toBeGreaterThan(0),
    );
    // slot update carried to the instantiate call（按 URL 查找：源码 tab 的
    // 配方库拉取会先于交互式 POST 发生，索引断言会把观测绑死在顺序上）
    const instantiateCall = (fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls.find(
      (call) => String(call[0]).includes("/replica/instantiate"),
    );
    expect(instantiateCall).toBeTruthy();
    const [, init] = instantiateCall as unknown as [string, RequestInit];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.workflow_id).toBe("wf-1");
    expect(body.replica_node_id).toBe("node_replica");
    expect(body.slot_updates.product).toBe("洗面奶A");
    // script surfaced + canvas refreshed
    expect(screen.getByText(/# 复刻脚本/)).toBeTruthy();
    expect(workflowWithEtag).toHaveBeenCalledWith("wf-1");
    expect(setAgentCanvasWorkflow).toHaveBeenCalled();
  });

  it("surfaces the instantiate error detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 400,
        json: async () => ({ detail: { error: "Node node_x is script, not a replica blueprint" } }),
      }),
    );

    render(<ReplicaBlueprintPanel node={replicaNode()} />);
    fireEvent.click(screen.getByText("⚡ 一键生成复刻工作流"));
    await waitFor(() => expect(screen.getByText(/not a replica blueprint/)).toBeTruthy());
  });
});

describe("ReplicaBlueprintPanel direct-execute render bridge (零模型费直出)", () => {
  function openSourceTab() {
    render(<ReplicaBlueprintPanel node={replicaNode()} />);
    fireEvent.click(screen.getByText("源码 .adreplica"));
  }

  function stubBridgeAndRender(
    bridge: Record<string, unknown>,
    renderState: Record<string, unknown>,
  ) {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).includes("/final-composition/renders/")) {
        return { status: 200, json: async () => renderState };
      }
      return { status: 200, json: async () => bridge };
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("saves edits first, starts the bridge render, polls to a previewable video", async () => {
    const fetchMock = stubBridgeAndRender(
      {
        success: true,
        feasible: true,
        render_id: "render_bridge01",
        status: "queued",
        timeline_id: "replica-direct-execute-1",
        timeline_version: 4,
        previous_timeline_version: 3,
        subtitle_cue_count: 1,
        needs_placeholder_video: true,
        dropped_unresolved_clip_ids: ["bgm_system", "sfx_system"],
        unresolved_assets: [
          {
            clip_id: "bgm_system",
            track_id: "bgm",
            intent: "轻快电子",
            library_hint: "轻快电子",
            duration_seconds: 12,
          },
          {
            clip_id: "sfx_system",
            track_id: "sfx",
            intent: "叮咚; 翻页",
            library_hint: ["叮咚", "翻页"],
            duration_seconds: 12,
          },
        ],
      },
      {
        status: "completed",
        progress_percent: 100,
        output_url: "https://cdn.example/final-replica.mp4",
      },
    );

    openSourceTab();
    fireEvent.click(screen.getByText("⚡ 零模型费直出"));

    // 1) 发车前先落盘（节点是真相源，不含未保存编辑）
    await waitFor(() => expect(patchNode).toHaveBeenCalledWith("wf-1", "node_replica", expect.anything()));
    // 2) 桥端点：workflow_id + 生效蓝图（按 URL 查找：源码 tab 打开时的
    // 配方库拉取会先于交互式 POST 发生，索引断言会把观测绑死在顺序上）
    const bridgeCall = (fetchMock as unknown as {
      mock: { calls: [string, RequestInit][] };
    }).mock.calls.find((call) => String(call[0]).includes("/direct-execute/render"));
    expect(bridgeCall).toBeTruthy();
    const [bridgeUrl, bridgeInit] = bridgeCall as unknown as [string, RequestInit];
    expect(bridgeUrl).toBe("/api/v1/replica/blueprint/direct-execute/render");
    const bridgeBody = JSON.parse(bridgeInit.body as string);
    expect(bridgeBody.workflow_id).toBe("wf-1");
    expect(bridgeBody.blueprint.shots.length).toBeGreaterThan(0);
    // 3) 轮询 v2 渲染状态端点
    await waitFor(() => {
      const urls = (fetchMock as unknown as { mock: { calls: [string][] } }).mock.calls.map((c) => c[0]);
      expect(
        urls.some((u) =>
          String(u).includes("/api/v2/workflows/wf-1/final-composition/renders/render_bridge01"),
        ),
      ).toBe(true);
    });
    // 4) 成片预览 + 诚实备注（替换了哪版时间线）
    await waitFor(() => expect(screen.getByText(/成片已产出/)).toBeTruthy());
    const video = document.querySelector("video");
    expect(video?.getAttribute("src")).toBe("https://cdn.example/final-replica.mp4");
    expect(screen.getByText(/已替换工作流此前的 final-composition 时间线（版本 3 → 4）/)).toBeTruthy();
    // D2: 未解析库素材是**逐条可行动清单**（clip/intent/时长/补齐入口），
    // 不再是一句"未计入"的灰色小字
    expect(screen.getByText(/有 2 个库素材未解析，已跳过、未计入本次直出/)).toBeTruthy();
    expect(screen.getByText(/\[bgm_system\] 意图「轻快电子」/)).toBeTruthy();
    expect(screen.getByText(/\[sfx_system\] 意图「叮咚; 翻页」/)).toBeTruthy();
    expect(screen.getByText(/提示：叮咚、翻页/)).toBeTruthy();
    expect(screen.getAllByText("选素材补齐").length).toBe(2);
  });

  it("submits the selected subtitle recipe (.adrecipe) with the direct render", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).includes("/api/v1/replica/blueprint/recipes")) {
        return {
          status: 200,
          json: async () => ({
            success: true,
            recipes: [
              {
                recipe_id: "bottom-bold",
                name: "底部大字",
                description: "经典短视频字幕形态",
                subtitle: { font_size: 42, color: "#FFFFFF", position: "bottom_center" },
              },
              {
                recipe_id: "amber-emphasis",
                name: "琥珀强调",
                description: "暖色强调字幕",
                subtitle: { font_size: 40, color: "#FFC658", position: "bottom_center" },
              },
            ],
          }),
        };
      }
      if (String(url).includes("/final-composition/renders/")) {
        return {
          status: 200,
          json: async () => ({ status: "completed", progress_percent: 100, output_url: "https://cdn/f.mp4" }),
        };
      }
      return {
        status: 200,
        json: async () => ({
          success: true,
          feasible: true,
          render_id: "render_recipe01",
          status: "queued",
          timeline_version: 2,
          previous_timeline_version: 1,
        }),
      };
    });
    vi.stubGlobal("fetch", fetchMock);

    openSourceTab();
    // 配方库拉取 → 默认选中第一条 + 下拉可切
    await waitFor(() => expect(screen.getByText("🎨 字幕配方")).toBeTruthy());
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("bottom-bold");
    fireEvent.change(select, { target: { value: "amber-emphasis" } });
    expect(select.value).toBe("amber-emphasis");

    fireEvent.click(screen.getByText("⚡ 零模型费直出"));

    await waitFor(() =>
      expect(screen.getAllByText(/成片已产出/).length).toBeGreaterThan(0),
    );
    const bridgeCall = (fetchMock as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls.find(
      (call) => String(call[0]).includes("/direct-execute/render"),
    );
    expect(bridgeCall).toBeTruthy();
    const body = JSON.parse((bridgeCall as unknown as [string, RequestInit])[1].body as string);
    expect(body.recipe.recipe_id).toBe("amber-emphasis");
    expect(body.recipe.subtitle.color).toBe("#FFC658");
  });

  it("surfaces P4 pace warnings (estimated speech time vs beat window) before spending", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).includes("/api/v1/replica/blueprint/recipes")) {
        return { status: 200, json: async () => ({ success: true, recipes: [] }) };
      }
      if (String(url).includes("/final-composition/renders/")) {
        return { status: 200, json: async () => ({ status: "completed", output_url: "https://cdn/f.mp4" }) };
      }
      return {
        status: 200,
        json: async () => ({
          success: true,
          feasible: true,
          render_id: "render_pace01",
          status: "queued",
          timeline_version: 2,
          previous_timeline_version: 1,
          pace_warnings: [
            {
              beat_id: "b1",
              text: "别再这样洗脸了这款洗面奶真的超级好用",
              estimated_seconds: 5.417,
              window_seconds: 3.0,
              ratio: 1.806,
            },
          ],
        }),
      };
    });
    vi.stubGlobal("fetch", fetchMock);

    openSourceTab();
    fireEvent.click(screen.getByText("⚡ 零模型费直出"));

    await waitFor(() => expect(screen.getByText(/语速预检/)).toBeTruthy());
    expect(screen.getByText(/预估 5.417s vs 段落窗 3s/)).toBeTruthy();
    expect(screen.getByText(/1.8×/)).toBeTruthy();
    expect(screen.getByText(/删词或加窗/)).toBeTruthy();
  });

  it("surfaces the feasibility gate blockers instead of rendering", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 422,
        json: async () => ({
          detail: {
            error: "Blueprint is not direct-execute feasible.",
            error_type: "direct_execute_not_feasible",
            rejected: ["shot_2 有动作镜头，需生成", "voice 需 TTS 配音"],
          },
        }),
      }),
    );

    openSourceTab();
    fireEvent.click(screen.getByText("⚡ 零模型费直出"));

    await waitFor(() => expect(screen.getByText(/不能零模型费直出/)).toBeTruthy());
    expect(screen.getByText(/shot_2 有动作镜头，需生成/)).toBeTruthy();
    expect(screen.getByText(/voice 需 TTS 配音/)).toBeTruthy();
    expect(screen.getByText(/可改用/)).toBeTruthy();
  });

  // D2 完成判据：看到跳过了什么 → 点补齐 → 选素材 → 重新直出 → 成片真的有这段声音。
  // 回归锁：unresolved_assets 必须渲染成可行动清单，且补齐真的以
  // library_resolutions 上车（而不是只显示一句文案）。
  it("D2: 未解析素材可行动——补选素材后重新直出带 library_resolutions", async () => {
    let bridgeCalls = 0;
    const fetchMock = vi.fn(async (url: string) => {
      const target = String(url);
      if (target.includes("/api/v1/replica/blueprint/recipes")) {
        return { status: 200, json: async () => ({ success: true, recipes: [] }) };
      }
      if (target.includes("/final-composition/renders/")) {
        return {
          status: 200,
          json: async () => ({ status: "completed", progress_percent: 100, output_url: "https://cdn/f.mp4" }),
        };
      }
      if (target.includes("/api/v1/asset-library/entities/lib_ent_bgm")) {
        return {
          status: 200,
          json: async () => ({
            entity: { entity_id: "lib_ent_bgm", display_name: "轻快电子 BGM" },
            assets: [
              {
                asset_id: "lib_asset_bgm1",
                semantic_type: "bgm",
                uri: "data/assets/library/bgm.mp3",
                // 库记录带真实来源 id；version 缺失时按仓内约定 version_<asset_id> 兜底
                source: { source_type: "upload", asset_id: "asset_bgm_real" },
              },
            ],
          }),
        };
      }
      if (target.includes("/api/v1/asset-library/entities")) {
        return {
          status: 200,
          json: async () => ({
            entities: [{ entity_id: "lib_ent_bgm", display_name: "轻快电子 BGM" }],
          }),
        };
      }
      if (target.includes("/direct-execute/render")) {
        bridgeCalls += 1;
        return {
          status: 200,
          json: async () => ({
            success: true,
            feasible: true,
            render_id: `render_d2_${bridgeCalls}`,
            status: "queued",
            timeline_version: 2,
            previous_timeline_version: 1,
            // 第一次还有未解析；补齐后再直出即无未解析
            unresolved_assets:
              bridgeCalls === 1
                ? [
                    {
                      clip_id: "bgm_system",
                      track_id: "bgm",
                      intent: "轻快电子",
                      library_hint: "轻快电子",
                      duration_seconds: 12,
                    },
                  ]
                : [],
          }),
        };
      }
      return { status: 200, json: async () => ({ success: true }) };
    });
    vi.stubGlobal("fetch", fetchMock);

    openSourceTab();
    fireEvent.click(screen.getByText("⚡ 零模型费直出"));

    // 1) 未解析清单可见：意图 + 时长 + 补齐入口（不是一句 note）
    await waitFor(() => expect(screen.getByText(/有 1 个库素材未解析/)).toBeTruthy());
    expect(screen.getByText(/\[bgm_system\] 意图「轻快电子」/)).toBeTruthy();
    expect(screen.getByText(/12\.0s/)).toBeTruthy();

    // 2) 行内补选：候选实体 → 实体资产（version 约定兜底）
    fireEvent.click(screen.getByText("选素材补齐"));
    await waitFor(() => expect(screen.getByText("📁 轻快电子 BGM")).toBeTruthy());
    fireEvent.click(screen.getByText("📁 轻快电子 BGM"));
    await waitFor(() =>
      expect(screen.getByText(/asset_bgm_real · version_asset_bgm_real/)).toBeTruthy(),
    );
    fireEvent.click(screen.getByText(/asset_bgm_real · version_asset_bgm_real/));

    // 3) 补齐态可见（用户知道自己选了什么 id）
    await waitFor(() =>
      expect(screen.getByText(/✓ 已选素材 asset_bgm_real（version_asset_bgm_real）/)).toBeTruthy(),
    );

    // 4) 带补齐重新直出：library_resolutions 真的上车
    fireEvent.click(screen.getByText(/↻ 带 1 个补齐重新直出/));
    await waitFor(() => expect(bridgeCalls).toBe(2));
    const renderCalls = (fetchMock as unknown as {
      mock: { calls: [string, RequestInit][] };
    }).mock.calls.filter((call) => String(call[0]).includes("/direct-execute/render"));
    const secondBody = JSON.parse(renderCalls[1][1].body as string);
    expect(secondBody.library_resolutions).toEqual([
      { clip_id: "bgm_system", asset_id: "asset_bgm_real", version_id: "version_asset_bgm_real" },
    ]);

    // 5) 无未解析残留 → 清单消失（补齐被采纳，不拿旧清单烦人）
    await waitFor(() => expect(screen.queryByText(/个库素材未解析/)).toBeNull());
  });

  it("D2: 补选器拉素材库失败必须可见（不静默空列表）", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      const target = String(url);
      if (target.includes("/api/v1/replica/blueprint/recipes")) {
        return { status: 200, json: async () => ({ success: true, recipes: [] }) };
      }
      if (target.includes("/api/v1/asset-library/entities")) {
        return { status: 503, json: async () => ({ detail: "library offline" }) };
      }
      return {
        status: 200,
        json: async () => ({
          success: true,
          feasible: true,
          render_id: "render_d2b",
          status: "queued",
          timeline_version: 2,
          previous_timeline_version: 1,
          unresolved_assets: [
            {
              clip_id: "bgm_system",
              track_id: "bgm",
              intent: "轻快电子",
              library_hint: "轻快电子",
              duration_seconds: 12,
            },
          ],
        }),
      };
    });
    vi.stubGlobal("fetch", fetchMock);

    openSourceTab();
    fireEvent.click(screen.getByText("⚡ 零模型费直出"));
    await waitFor(() => expect(screen.getByText(/有 1 个库素材未解析/)).toBeTruthy());
    fireEvent.click(screen.getByText("选素材补齐"));
    await waitFor(() => expect(screen.getByText(/素材库不可用/)).toBeTruthy());
    // 重试入口存在（失败可行动，不是死局）
    expect(screen.getByText("重试")).toBeTruthy();
  });
});

describe("ReplicaBlueprintPanel source tab (.adreplica)", () => {  function openSourceTab() {
    const node = replicaNode();
    render(<ReplicaBlueprintPanel node={node} />);
    fireEvent.click(screen.getByText("源码 .adreplica"));
  }

  it("exports the effective blueprint (with unsaved edits) as a document", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 200,
        json: async () => ({
          success: true,
          adreplica: '<advideo version="1" kind="replica-blueprint">…</advideo>',
          filename: "product-comparison.adreplica",
        }),
      }),
    );
    openSourceTab();
    // 未保存编辑也应反映在导出里（导出的是"生效内容"）
    fireEvent.click(screen.getByText("槽位替换"));
    fireEvent.change(screen.getByPlaceholderText("商品资产 ID 或描述"), {
      target: { value: "洗面奶A" },
    });
    fireEvent.click(screen.getByText("源码 .adreplica"));
    fireEvent.click(screen.getByText("📄 导出当前蓝图"));

    await waitFor(() =>
      expect(screen.getByText(/product-comparison\.adreplica/)).toBeTruthy(),
    );
    const textarea = screen.getByPlaceholderText(/粘贴到这里/) as HTMLTextAreaElement;
    expect(textarea.value).toContain("<advideo");
    // 按 URL 查找（源码 tab 打开时的配方库拉取先于交互式 POST，见上）
    const exportCall = (fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls.find(
      (call) => String(call[0]).includes("/replica/blueprint/export"),
    );
    expect(exportCall).toBeTruthy();
    const [url, init] = exportCall as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/replica/blueprint/export");
    const body = JSON.parse(init.body as string);
    const product = (body.blueprint.slots as Array<{ kind: string; replace_with: string }>).find(
      (s) => s.kind === "product",
    );
    expect(product?.replace_with).toBe("洗面奶A");
  });

  it("imports pasted .adreplica and writes it back to the node", async () => {
    const imported = {
      ...BLUEPRINT,
      slots: BLUEPRINT.slots.map((s) =>
        s.kind === "product" ? { ...s, replace_with: "洗面奶B", applied: true } : s,
      ),
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 200,
        json: async () => ({
          success: true,
          blueprint: imported,
          replica_script: "# 复刻脚本",
        }),
      }),
    );
    openSourceTab();
    fireEvent.change(screen.getByPlaceholderText(/粘贴到这里/), {
      target: { value: '<advideo version="1" kind="replica-blueprint">…</advideo>' },
    });
    fireEvent.click(screen.getByText("📥 导入重编译"));

    await waitFor(() =>
      expect(screen.getByText(/已从 \.adreplica 导入并写回蓝图节点/)).toBeTruthy(),
    );
    // 回写闭环：导入蓝图 patch 回节点 + 画布刷新
    const [, nodeId, patch] = patchNode.mock.calls[0] as unknown as [
      string,
      string,
      { structured_content: Record<string, unknown> },
    ];
    expect(nodeId).toBe("node_replica");
    const product = (patch.structured_content.slots as Array<{ kind: string; replace_with: string }>).find(
      (s) => s.kind === "product",
    );
    expect(product?.replace_with).toBe("洗面奶B");
    expect(setAgentCanvasWorkflow).toHaveBeenCalled();
  });

  it("surfaces the import parse error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 422,
        json: async () => ({
          detail: { error: "Unknown slot kind 'host'", error_type: "adreplica_parse" },
        }),
      }),
    );
    openSourceTab();
    fireEvent.change(screen.getByPlaceholderText(/粘贴到这里/), {
      target: { value: '<advideo version="1"><cast><slot kind="host"/></cast></advideo>' },
    });
    fireEvent.click(screen.getByText("📥 导入重编译"));
    await waitFor(() => expect(screen.getByText(/Unknown slot kind/)).toBeTruthy());
  });
});

describe("ReplicaBlueprintPanel local-state sync", () => {
  it("follows external node content updates (import recompile / collab)", async () => {
    const { rerender } = render(<ReplicaBlueprintPanel node={replicaNode()} />);
    const input = () => screen.getByPlaceholderText("商品资产 ID 或描述") as HTMLInputElement;
    expect(input().value).toBe("");

    const updated = replicaNode();
    updated.structured_content = {
      ...BLUEPRINT,
      slots: BLUEPRINT.slots.map((s) =>
        s.kind === "product" ? { ...s, replace_with: "洗面奶B", applied: true } : s,
      ),
    } as unknown as Record<string, unknown>;
    rerender(<ReplicaBlueprintPanel node={updated} />);

    await waitFor(() => expect(input().value).toBe("洗面奶B"));
  });

  it("keeps in-progress typing across unrelated rerenders", () => {
    const { rerender } = render(<ReplicaBlueprintPanel node={replicaNode()} />);
    const input = () => screen.getByPlaceholderText("商品资产 ID 或描述") as HTMLInputElement;
    fireEvent.change(input(), { target: { value: "洗面奶C" } });

    // 内容未变的重渲染（父组件 re-render）不得清掉输入
    rerender(<ReplicaBlueprintPanel node={replicaNode()} />);
    expect(input().value).toBe("洗面奶C");
  });
});

describe("ReplicaBlueprintPanel style variants (Jev 式风格导演)", () => {
  const VARIANTS = {
    success: true,
    variants: [
      {
        variant_id: "variant_a",
        skill_ids: ["gentle-everyday-vlog"],
        names: ["温柔日常Vlog影像"],
        score: 1.62,
        rationale: "匹配关键词：日常、手持",
        mixable_applied: true,
        recipe_id: "bottom-bold",
        recipe_name: "底部大字",
      },
      {
        variant_id: "variant_b",
        skill_ids: ["lived-in-epic-cinema", "jewelry-editorial-film"],
        names: ["生活质感史诗影像", "珠宝微距编辑片"],
        score: 0.8,
        rationale: "组合候选",
        mixable_applied: false,
        recipe_id: "amber-emphasis",
        recipe_name: "琥珀强调",
      },
    ],
  };

  const RECIPES = {
    success: true,
    recipes: [
      {
        recipe_id: "bottom-bold",
        name: "底部大字",
        description: "经典短视频字幕形态",
        subtitle: { font_size: 42, color: "#FFFFFF", position: "bottom_center" },
      },
      {
        recipe_id: "amber-emphasis",
        name: "琥珀强调",
        description: "暖色强调字幕",
        subtitle: { font_size: 28, color: "#FFC658", position: "top_center" },
      },
    ],
  };

  function stubVariants(overrides: { variants?: unknown; recipes?: unknown } = {}) {
    return vi.fn(async (url: string) => {
      const target = String(url);
      if (target.includes("/style-variants")) {
        return { status: 200, json: async () => overrides.variants ?? VARIANTS };
      }
      if (target.includes("/recipes")) {
        return { status: 200, json: async () => overrides.recipes ?? RECIPES };
      }
      if (target.includes("/final-composition/renders/")) {
        return {
          status: 200,
          json: async () => ({ status: "completed", progress_percent: 100, output_url: "https://cdn/f.mp4" }),
        };
      }
      if (target.includes("/direct-execute/render")) {
        return {
          status: 200,
          json: async () => ({
            success: true,
            feasible: true,
            render_id: "render_e1",
            status: "queued",
            timeline_version: 2,
            previous_timeline_version: 1,
          }),
        };
      }
      return { status: 200, json: async () => ({ success: true }) };
    });
  }

  it("recommends variants and applies a single skill into the style slot", async () => {
    const fetchMock = stubVariants();
    vi.stubGlobal("fetch", fetchMock);

    render(<ReplicaBlueprintPanel node={replicaNode()} />);
    fireEvent.click(screen.getByText("🎲 风格推荐"));
    await waitFor(() => expect(screen.getByText(/温柔日常Vlog影像/)).toBeTruthy());

    // 组合候选不可应用（多风格激活未支持）
    const buttons = screen.getAllByText("应用");
    expect((buttons[0] as HTMLButtonElement).disabled).toBe(false);
    expect((buttons[1] as HTMLButtonElement).disabled).toBe(true);

    // 应用单风格 → 填进风格槽位
    fireEvent.click(buttons[0]);
    const styleInput = screen.getByPlaceholderText(
      "风格 skill_id（如 gentle-everyday-vlog）",
    ) as HTMLInputElement;
    expect(styleInput.value).toBe("gentle-everyday-vlog");
  });

  // E1（G5 兑付点）：变体差异必须肉眼可辨——配方名 + 迷你字幕预览卡并排，
  // 且应用变体时把它的配方选为直出配方（此前 recipe 在 UI 层断裂）。
  it("shows each variant's recipe and a side-by-side caption preview (E1)", async () => {
    vi.stubGlobal("fetch", stubVariants());

    render(<ReplicaBlueprintPanel node={replicaNode()} />);
    fireEvent.click(screen.getByText("🎲 风格推荐"));
    await waitFor(() => expect(screen.getByText(/🎨 底部大字/)).toBeTruthy());
    expect(screen.getByText(/🎨 琥珀强调/)).toBeTruthy();

    // 预览卡按配方参数渲染：白色底部大字 vs 琥珀色顶部小字（肉眼可辨）
    const chips = screen.getAllByText("别再这样洗脸");
    expect(chips.length).toBe(2);
    const colors = chips.map((chip) => (chip as HTMLElement).style.color);
    expect(colors).toContain("rgb(255, 255, 255)");
    expect(colors).toContain("rgb(255, 198, 88)");
    // 顶部/居中/底部由字号与标题提示体现（position 在 title 里可查）
    expect((chips[0] as HTMLElement).closest("div")?.getAttribute("title")).toContain("position=");
  });

  it("applies a variant together with its recipe for the direct render (E1)", async () => {
    const fetchMock = stubVariants();
    vi.stubGlobal("fetch", fetchMock);

    render(<ReplicaBlueprintPanel node={replicaNode()} />);
    fireEvent.click(screen.getByText("🎲 风格推荐"));
    await waitFor(() => expect(screen.getByText(/🎨 底部大字/)).toBeTruthy());

    fireEvent.click(screen.getAllByText("应用")[0]);

    // 配方已选为直出配方：到源码 tab 的直出提交里带着它
    fireEvent.click(screen.getByText("源码 .adreplica"));
    await waitFor(() => expect(screen.getByText("🎨 字幕配方")).toBeTruthy());
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("bottom-bold");
    fireEvent.click(screen.getByText("⚡ 零模型费直出"));
    await waitFor(() =>
      expect(screen.getAllByText(/成片已产出/).length).toBeGreaterThan(0),
    );
    const bridgeCall = (fetchMock as unknown as {
      mock: { calls: [string, RequestInit][] };
    }).mock.calls.find((call) => String(call[0]).includes("/direct-execute/render"));
    const body = JSON.parse((bridgeCall as unknown as [string, RequestInit])[1].body as string);
    expect(body.recipe.recipe_id).toBe("bottom-bold");
    expect(body.recipe.subtitle.color).toBe("#FFFFFF");
  });

  it("surfaces the recommendation error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).includes("/recipes")) {
          return { status: 200, json: async () => ({ success: true, recipes: [] }) };
        }
        return {
          status: 422,
          json: async () => ({ detail: { error: "n out of range [1, 12]: 99" } }),
        };
      }),
    );
    render(<ReplicaBlueprintPanel node={replicaNode()} />);
    fireEvent.click(screen.getByText("🎲 风格推荐"));
    await waitFor(() => expect(screen.getByText(/n out of range/)).toBeTruthy());
  });
});

describe("ReplicaSourceEditor (源码高亮编辑 + 锚点双向跳转)", () => {
  async function openSourceWithExportedDoc() {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 200,
        json: async () => ({
          success: true,
          adreplica:
            '<advideo version="1" kind="replica-blueprint">\n  <script>\n    <beat id="b1" role="hook" dur="0-3">抓注意力<line>@{b1_caption}别再这样洗脸了@{/b1_caption}</line></beat>\n  </script>\n  <events>\n    <caption id="b1_caption" during="b1" trigger="hook" keep="true">hint</caption>\n  </events>\n</advideo>',
          filename: "product-comparison.adreplica",
        }),
      }),
    );
    render(<ReplicaBlueprintPanel node={replicaNode()} />);
    fireEvent.click(screen.getByText("源码 .adreplica"));
    fireEvent.click(screen.getByText("📄 导出当前蓝图"));
    await waitFor(() => expect(screen.getByText(/product-comparison\.adreplica/)).toBeTruthy());
  }

  it("renders the highlight layer with colored tags and clickable anchors", async () => {
    await openSourceWithExportedDoc();
    const layer = screen.getByTestId("source-highlight-layer");
    expect(layer).toBeTruthy();
    // 行内词锚在衬层里带可定位标记
    const anchorSpan = screen.getByTestId("source-anchor-b1_caption");
    expect(anchorSpan.textContent).toBe("@{b1_caption}");
    // 标签名被着色（tag kind）
    expect(layer.innerHTML).toContain("rgb(106, 176, 243)");
    // 编辑仍然生效：输入事件穿透透明文本区
    const textarea = screen.getByPlaceholderText(/粘贴到这里/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "<advideo edited/>" } });
    expect((screen.getByTestId("source-highlight-layer") as HTMLElement).textContent).toBe(
      "<advideo edited/>",
    );
  });

  it("jumps from a source inline anchor to the highlighted anchor row", async () => {
    await openSourceWithExportedDoc();
    fireEvent.click(screen.getByTestId("source-anchor-b1_caption"));
    // 切到锚点 tab 且目标行高亮
    expect(screen.getByText(/锚点事件 = 挂在结构段落上/)).toBeTruthy();
    const row = document.getElementById("anchor-row-b1_caption");
    expect(row).toBeTruthy();
    expect(row?.getAttribute("style")).toContain("rgb(42, 58, 42)");
  });

  it("jumps from the anchor row back to the source inline anchor selection", async () => {
    await openSourceWithExportedDoc();
    fireEvent.click(screen.getByTestId("source-anchor-b1_caption"));
    const targetRow = document.getElementById("anchor-row-b1_caption");
    expect(targetRow).toBeTruthy();
    fireEvent.click(within(targetRow as HTMLElement).getByText("📍 源码定位"));
    // 回到源码 tab，文本区选中该行内锚
    expect(screen.getByTestId("source-anchor-b1_caption")).toBeTruthy();
    const textarea = screen.getByPlaceholderText(/粘贴到这里/) as HTMLTextAreaElement;
    expect(document.activeElement).toBe(textarea);
    expect(textarea.value.slice(textarea.selectionStart, textarea.selectionEnd)).toBe(
      "@{b1_caption}",
    );
  });
});
