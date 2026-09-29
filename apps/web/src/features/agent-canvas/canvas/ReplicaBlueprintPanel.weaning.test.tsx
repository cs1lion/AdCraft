/**
 * 概念断奶（2026-09-29）：复刻面板默认只呈现"导演台 + 槽位替换"，
 * 锚点事件/镜头表/源码等高级入口收在"⚙ 高级"后面——作者不被内部词汇淹没。
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CanvasNodeV2, ReplicaBlueprintContentV2 } from "../../../types-v2.ts";
import { ReplicaBlueprintPanel } from "./ReplicaBlueprintPanel.tsx";

afterEach(cleanup);

const setAgentCanvasWorkflow = vi.fn();

vi.mock("../../../AppContextValue.ts", () => ({
  useApp: () => ({ setAgentCanvasWorkflow }),
}));

function node(): CanvasNodeV2 {
  const blueprint: ReplicaBlueprintContentV2 = {
    blueprint_version: "replica-blueprint-v1",
    source_video_asset_id: "asset-1",
    duration_seconds: 12,
    aspect: "9:16",
    replica_goal: "换商品",
    whole_piece_reading: "前3秒钩子。",
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
        description: "抓注意力",
        start_seconds: 0,
        end_seconds: 3,
        anchor_event_ids: ["b1_caption"],
      },
    ],
    anchor_events: [
      { event_id: "b1_caption", trigger: "hook 段落", beat_id: "b1", kind: "caption", hint: "挂字幕", keep: true },
    ],
    shots: [
      { index: 1, start_seconds: 0, end_seconds: 2.1, shot_size: "closeup", camera_motion: "static", subject_action: "唇部特写", on_screen_text: "别再这样洗脸", transition_to_next: "cut", recreate_hint: "同机位" },
    ],
    rhythm_avg_shot_seconds: 2.1,
    rhythm_cut_points_seconds: [0],
    rhythm_energy_curve: "前快后缓",
    systems_captions: "底部高亮",
    systems_music: "轻快电子",
    systems_graphics: [],
    systems_sfx: [],
    constraints: [],
    instantiated_script_node_id: null,
  };
  return {
    node_id: "node_replica_1",
    workflow_id: "wf_1",
    node_type: "replica",
    creative_role: "replica_blueprint",
    title: "复刻蓝图",
    status: "draft",
    structured_content: blueprint as unknown as Record<string, unknown>,
    position: { x: 0, y: 0 },
    revision: 1,
  } as unknown as CanvasNodeV2;
}

describe("ReplicaBlueprintPanel 概念断奶", () => {
  it("默认只呈现主路径：导演台 + 槽位替换", () => {
    render(<ReplicaBlueprintPanel node={node()} />);
    expect(screen.getByText("🎬 导演台")).toBeTruthy();
    expect(screen.getByText("槽位替换")).toBeTruthy();
    // 一键成片是主路径上唯一按钮
    expect(screen.getByRole("button", { name: /🎬 生成复刻成片/ })).toBeTruthy();
    // 高级入口默认不可见
    expect(screen.queryByText(/锚点事件\(/)).toBeNull();
    expect(screen.queryByText(/镜头表\(/)).toBeNull();
    expect(screen.queryByText("源码 .adreplica")).toBeNull();
    // 高级开关在
    expect(screen.getByText("⚙ 高级")).toBeTruthy();
  });

  it("⚙ 高级 展开后才出现高级入口，收起后回主路径", () => {
    render(<ReplicaBlueprintPanel node={node()} />);
    fireEvent.click(screen.getByText("⚙ 高级"));
    expect(screen.getByText(/锚点事件\(/)).toBeTruthy();
    expect(screen.getByText(/镜头表\(/)).toBeTruthy();
    expect(screen.getByText("源码 .adreplica")).toBeTruthy();

    fireEvent.click(screen.getByText("源码 .adreplica"));
    expect(screen.getByText(/💾 保存蓝图/)).toBeTruthy();

    fireEvent.click(screen.getByText("⚙ 收起高级"));
    expect(screen.queryByText(/锚点事件\(/)).toBeNull();
    expect(screen.queryByText("源码 .adreplica")).toBeNull();
    // 收起时落回主路径 tab
    expect(screen.getByText(/槽位 = 复刻时要替换的成分/)).toBeTruthy();
  });
});
