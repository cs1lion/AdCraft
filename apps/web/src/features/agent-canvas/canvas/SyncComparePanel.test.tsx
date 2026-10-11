import { cleanup, render, screen, fireEvent, act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AgentCanvasWorkflowV2, CanvasNodeV2, ProjectAssetSummaryV2, V2AssetVersionMetadata } from "../../../types-v2.ts";
import {
  SyncComparePanel,
} from "./SyncComparePanel.tsx";
import {
  aspectMismatch,
  assetVersionContentPath,
  bestOffsetByNcc,
  clampOffsetSeconds,
  collectSyncCompareCandidates,
  expectedRightTime,
  loopBoundaryTime,
  pickPreviousVersion,
  pickSyncCompareDefaults,
  SYNC_DRIFT_TOLERANCE,
  SYNC_OFFSET_LIMIT,
  type SyncCompareCandidate,
} from "./syncCompareModel.ts";

afterEach(cleanup);

function asset(asset_id: string): ProjectAssetSummaryV2 {
  return {
    asset_id,
    version_id: `version_${asset_id}`,
    project_id: "proj_test",
    workflow_id: "adwf_v2_test",
    media_type: "video",
    source_type: "upload",
    semantic_type: null,
    display_name: asset_id,
    mime_type: "video/mp4",
    status: "ready",
    size_bytes: 1024,
    storage_key: null,
    preview_url: null,
    media_url: null,
    width: 1280,
    height: 720,
    duration_seconds: 15,
    checksum: "sha",
    source_semantic_role: null,
    source_node_id: null,
    source_execution_id: null,
    provider: null,
    model_id: null,
    prompt_provenance: {},
    actual_media_facts: {},
    generation_provenance: {},
    quality_metadata: {},
    created_at: null,
    updated_at: null,
  } as ProjectAssetSummaryV2;
}

function node(node_id: string, node_type: CanvasNodeV2["node_type"], title: string, output_asset_id: string | null): CanvasNodeV2 {
  return {
    node_id,
    workflow_id: "adwf_v2_test",
    node_type,
    creative_role: "storyboard_video",
    role_contract_version: "ad-media-role-v2",
    title,
    status: "ready",
    execution_mode: "generative",
    summary_prompt: null,
    generation_prompt: null,
    prompt_presentation: null,
    structured_content: {},
    model_selection_mode: "default",
    model_ref: null,
    model_summary: null,
    parameters: {},
    metadata: {},
    parameter_provenance: {},
    prompt_context_snapshot_id: null,
    output_asset_id,
    output_asset_version_id: output_asset_id ? `version_${output_asset_id}` : null,
    latest_attempt: null,
    position: { x: 0, y: 0 },
    revision: 1,
    error: null,
    authoring_origin: null,
    intent_hint: null,
    prompt_preparation: null,
    created_at: null,
    updated_at: null,
  } as CanvasNodeV2;
}

function workflow(nodes: CanvasNodeV2[], assets: ProjectAssetSummaryV2[]): AgentCanvasWorkflowV2 {
  return {
    workflow_id: "adwf_v2_test",
    project_id: "proj_test",
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision: 1,
    layout_revision: 1,
    nodes,
    bindings: [],
    assets,
    active_style_skill: null,
  } as AgentCanvasWorkflowV2;
}

const WM_NODE = node("node_wm", "video", "入局 · 3D 预演白模 15s（agnes 白模版）", "asset_wm");
const FIN_NODE = node("node_fin", "video", "入局 · 最终成片 15s（H3 v2）", "asset_fin");
const IMG_NODE = node("node_img", "image", "设定图", "asset_img");
const NO_OUTPUT = node("node_empty", "video", "未生成视频", null);

describe("collectSyncCompareCandidates", () => {
  it("只收有视频输出的 video/scene-3d 节点（按标题排序）", () => {
    const wf = workflow([WM_NODE, FIN_NODE, IMG_NODE, NO_OUTPUT], [asset("asset_wm"), asset("asset_fin")]);
    const candidates = collectSyncCompareCandidates(wf);
    expect(candidates.map((c) => c.node.node_id)).toEqual(["node_wm", "node_fin"]);
    expect(candidates.every((c) => c.url.includes("/api/v2/assets/"))).toBe(true);
  });
});

describe("pickSyncCompareDefaults", () => {
  const candidates: SyncCompareCandidate[] = [
    { node: FIN_NODE, asset: asset("asset_fin"), url: "/fin" },
    { node: WM_NODE, asset: asset("asset_wm"), url: "/wm" },
  ];

  it("左侧默认白模、右侧默认成片", () => {
    expect(pickSyncCompareDefaults(candidates)).toEqual({ leftId: "node_wm", rightId: "node_fin" });
  });

  it("没有白模时退回前两个", () => {
    const only = [candidates[0]];
    expect(pickSyncCompareDefaults(only)).toEqual({ leftId: "node_fin", rightId: null });
  });

  it("空候选返回空", () => {
    expect(pickSyncCompareDefaults([])).toEqual({ leftId: null, rightId: null });
  });
});

describe("expectedRightTime", () => {
  it("B 侧时间 = A 主时钟时间 + 偏移", () => {
    expect(expectedRightTime(5, 0.3, 15)).toBeCloseTo(5.3, 6);
    expect(expectedRightTime(5, -0.5, 15)).toBeCloseTo(4.5, 6);
  });

  it("负偏移不会早于 0", () => {
    expect(expectedRightTime(0.2, -0.5, 15)).toBe(0);
  });

  it("超出 B 时长时夹到 B 时长", () => {
    expect(expectedRightTime(14.9, 0.5, 15)).toBe(15);
  });

  it("B 时长未知时不夹上限", () => {
    expect(expectedRightTime(14.9, 0.5, NaN)).toBeCloseTo(15.4, 6);
  });

  it("偏移限幅常量为正且合理", () => {
    expect(SYNC_OFFSET_LIMIT).toBeGreaterThan(0);
    expect(SYNC_OFFSET_LIMIT).toBeLessThanOrEqual(5);
  });
});

describe("clampOffsetSeconds", () => {
  it("限幅 ±3 且按 0.1 精度取整", () => {
    expect(clampOffsetSeconds(0.14)).toBeCloseTo(0.1, 6);
    expect(clampOffsetSeconds(3.5)).toBe(3);
    expect(clampOffsetSeconds(-9)).toBe(-3);
    expect(clampOffsetSeconds(-0.26)).toBeCloseTo(-0.3, 6);
  });
});

describe("loopBoundaryTime", () => {
  it("越过出点回入点；未设出点不循环；未设入点回 0", () => {
    expect(loopBoundaryTime(5.2, 1, 5)).toBe(1);
    expect(loopBoundaryTime(4.9, 1, 5)).toBeNull();
    expect(loopBoundaryTime(5.2, null, 5)).toBe(0);
    expect(loopBoundaryTime(5.2, 1, null)).toBeNull();
  });
});

describe("aspectMismatch", () => {
  it("宽高比差超 1% 视为错位；缺尺寸不判错", () => {
    expect(aspectMismatch({ w: 1280, h: 720 }, { w: 1280, h: 720 })).toBe(false);
    expect(aspectMismatch({ w: 1280, h: 720 }, { w: 720, h: 720 })).toBe(true);
    expect(aspectMismatch(null, { w: 720, h: 720 })).toBe(false);
    expect(aspectMismatch({ w: 0, h: 0 }, { w: 720, h: 720 })).toBe(false);
  });
});

describe("assetVersionContentPath", () => {
  it("按版本寻址内容 URL", () => {
    expect(assetVersionContentPath("asset_wm", "ver_1")).toBe("/api/v2/assets/asset_wm/content?v=ver_1");
  });
});

describe("pickPreviousVersion", () => {
  const version = (version_id: string, version_no: number, status: "ready" | "unavailable" = "ready"): V2AssetVersionMetadata => ({
    version_id,
    asset_id: "asset_wm",
    version_no,
    storage_key: `generated/a/v${version_no}.mp4`,
    sha256: `sha-${version_no}`,
    size_bytes: 1,
    mime_type: "video/mp4",
    width: 1280,
    height: 720,
    duration_seconds: 15,
    status,
    created_at: "2026-10-11T00:00:00Z",
  });

  it("沿版本链往回走：当前 v3 → 上一版 v2 → 上一版 v1 → null", () => {
    const versions = [version("v1", 1), version("v2", 2), version("v3", 3)];
    expect(pickPreviousVersion(versions, "v3")).toEqual({ versionId: "v2", versionNo: 2 });
    expect(pickPreviousVersion(versions, "v2")).toEqual({ versionId: "v1", versionNo: 1 });
    expect(pickPreviousVersion(versions, "v1")).toBeNull();
  });

  it("当前为 null 时取最新版的上一版；unavailable 版本跳过", () => {
    const versions = [version("v1", 1), version("v2", 2, "unavailable"), version("v3", 3)];
    expect(pickPreviousVersion(versions, null)).toEqual({ versionId: "v1", versionNo: 1 });
  });

  it("当前版不在链上或链不足两版返回 null", () => {
    expect(pickPreviousVersion([version("v1", 1)], "v9")).toBeNull();
    expect(pickPreviousVersion([version("v1", 1)], null)).toBeNull();
  });
});

describe("bestOffsetByNcc", () => {  const pattern = (i: number) => Math.sin(i * 1.7) + 0.5 * Math.sin(i * 0.53);

  it("平移轨迹找到正确 lag：B 落后 3 格 → offset +1.5s、相关≈1", () => {
    const trackA = Array.from({ length: 40 }, (_, i) => pattern(i));
    const trackB = Array.from({ length: 40 }, (_, i) => pattern(i - 3));
    const result = bestOffsetByNcc(trackA, trackB, 0.5, 3);
    expect(result).not.toBeNull();
    expect(result!.offset).toBeCloseTo(1.5, 6);
    expect(result!.score).toBeGreaterThan(0.99);
  });

  it("轨迹过平（零方差）返回 null", () => {
    expect(bestOffsetByNcc(new Array(40).fill(1), new Array(40).fill(1), 0.5, 3)).toBeNull();
  });

  it("轨迹太短返回 null", () => {
    expect(bestOffsetByNcc([1, 2, 3], [1, 2, 3], 0.5, 3)).toBeNull();
  });
});

describe("SyncComparePanel", () => {
  it("打开时双播放器就位，默认选中白模与成片", () => {
    const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
    render(<SyncComparePanel workflow={wf} open onClose={() => undefined} />);
    const left = screen.getByTestId("sync-compare-video-left") as HTMLVideoElement;
    const right = screen.getByTestId("sync-compare-video-right") as HTMLVideoElement;
    expect(left.getAttribute("src")).toContain("asset_wm");
    expect(right.getAttribute("src")).toContain("asset_fin");
    expect(screen.getByTestId("sync-compare").textContent).toContain("同步对比播放");
  });

  it("关闭时不渲染", () => {
    const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
    render(<SyncComparePanel workflow={wf} open={false} onClose={() => undefined} />);
    expect(screen.queryByTestId("sync-compare")).toBeNull();
  });

  it("seek 同时设置两条视频的时间（经逐帧按钮，jsdom 无 duration）", () => {
    const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
    render(<SyncComparePanel workflow={wf} open onClose={() => undefined} />);
    const left = screen.getByTestId("sync-compare-video-left") as HTMLVideoElement;
    const right = screen.getByTestId("sync-compare-video-right") as HTMLVideoElement;
    fireEvent.click(screen.getByLabelText("下一帧"));
    expect(left.currentTime).toBeCloseTo(1 / 24, 5);
    expect(right.currentTime).toBeCloseTo(1 / 24, 5);
  });

  it("播放按钮切换播放态并同时驱动两个 video", () => {
    const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
    const playSpy = vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
    render(<SyncComparePanel workflow={wf} open onClose={() => undefined} />);
    fireEvent.click(screen.getByTestId("sync-compare-play"));
    expect(playSpy).toHaveBeenCalledTimes(2);
    playSpy.mockRestore();
  });

  it("没有可播放视频时给出空态", () => {
    const wf = workflow([IMG_NODE], []);
    render(<SyncComparePanel workflow={wf} open onClose={() => undefined} />);
    expect(screen.getByText("选择左侧视频")).toBeTruthy();
    expect(screen.getByText("选择右侧视频")).toBeTruthy();
  });

  it("漂移阈值是正数常量", () => {
    expect(SYNC_DRIFT_TOLERANCE).toBeGreaterThan(0);
  });

  it("切换视图模式不重建 video 元素（播放进度保留）", () => {
    const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
    render(<SyncComparePanel workflow={wf} open onClose={() => undefined} />);
    const before = screen.getByTestId("sync-compare-video-left");
    fireEvent.click(screen.getByLabelText("下一帧"));
    fireEvent.click(screen.getByRole("button", { name: "滑动分割" }));
    const after = screen.getByTestId("sync-compare-video-left");
    expect(after).toBe(before);
    expect(after.currentTime).toBeCloseTo(1 / 24, 5);
  });

  it("A 播完：B 一并暂停，Transport 回到播放态按钮", () => {
    const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
    const playSpy = vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
    const pauseSpy = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    render(<SyncComparePanel workflow={wf} open onClose={() => undefined} />);
    fireEvent.click(screen.getByTestId("sync-compare-play"));
    expect(screen.getByTestId("sync-compare-play").getAttribute("aria-label")).toBe("暂停");
    fireEvent(screen.getByTestId("sync-compare-video-left"), new Event("ended"));
    expect(pauseSpy).toHaveBeenCalled();
    expect(screen.getByTestId("sync-compare-play").getAttribute("aria-label")).toBe("播放");
    playSpy.mockRestore();
    pauseSpy.mockRestore();
  });

  it("音源默认 A：左侧出声 B 静音；切 B 反转；静音全灭", () => {
    const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
    render(<SyncComparePanel workflow={wf} open onClose={() => undefined} />);
    const left = screen.getByTestId("sync-compare-video-left") as HTMLVideoElement;
    const right = screen.getByTestId("sync-compare-video-right") as HTMLVideoElement;
    expect(left.muted).toBe(false);
    expect(right.muted).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "B" }));
    expect(left.muted).toBe(true);
    expect(right.muted).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "静音" }));
    expect(left.muted).toBe(true);
    expect(right.muted).toBe(true);
  });

  it("差异模式切 is-diff 且顶层无裁剪；分割模式 B 侧带 clipPath", () => {
    const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
    render(<SyncComparePanel workflow={wf} open onClose={() => undefined} />);
    const stage = screen.getByTestId("sync-compare-stage");
    const right = screen.getByTestId("sync-compare-video-right") as HTMLVideoElement;
    expect(stage.className).toContain("is-split");
    fireEvent.click(screen.getByRole("button", { name: "滑动分割" }));
    expect(stage.className).toContain("is-wipe");
    expect(right.style.clipPath).toContain("inset");
    fireEvent.click(screen.getByRole("button", { name: "差异" }));
    expect(stage.className).toContain("is-diff");
    expect(right.style.clipPath).toBe("");
  });

  it("中文逗号/句号也能逐帧步进", () => {
    const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
    render(<SyncComparePanel workflow={wf} open onClose={() => undefined} />);
    const left = screen.getByTestId("sync-compare-video-left") as HTMLVideoElement;
    fireEvent.keyDown(window, { key: "。" });
    expect(left.currentTime).toBeCloseTo(1 / 24, 5);
    fireEvent.keyDown(window, { key: "，" });
    expect(left.currentTime).toBeCloseTo(0, 5);
  });

  it("I/O 键设区间，越点自动交换，可清除", () => {
    const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
    render(<SyncComparePanel workflow={wf} open onClose={() => undefined} />);
    const left = screen.getByTestId("sync-compare-video-left") as HTMLVideoElement;
    left.currentTime = 5;
    fireEvent.keyDown(window, { key: "o" });
    left.currentTime = 7;
    fireEvent.keyDown(window, { key: "i" });
    expect(screen.getByTestId("sync-compare-region").textContent).toBe("0:05.0–0:07.0");
    fireEvent.click(screen.getByRole("button", { name: "清除区间" }));
    expect(screen.getByTestId("sync-compare-region").textContent).toBe("区间");
  });

  it("播放越过出点回跳入点（I/O 区间循环）", () => {
    vi.useFakeTimers();
    const playSpy = vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
    try {
      const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
      render(<SyncComparePanel workflow={wf} open onClose={() => undefined} />);
      const left = screen.getByTestId("sync-compare-video-left") as HTMLVideoElement;
      const right = screen.getByTestId("sync-compare-video-right") as HTMLVideoElement;
      left.currentTime = 1;
      fireEvent.keyDown(window, { key: "i" });
      left.currentTime = 5;
      fireEvent.keyDown(window, { key: "o" });
      fireEvent.click(screen.getByTestId("sync-compare-play"));
      left.currentTime = 5.3;
      right.currentTime = 5.3;
      act(() => {
        vi.advanceTimersByTime(260);
      });
      expect(left.currentTime).toBe(1);
      expect(right.currentTime).toBe(1);
    } finally {
      playSpy.mockRestore();
      vi.useRealTimers();
    }
  });

  it("B 在 seeking/缓冲中跳过漂移校正（防 seek 风暴拉扯）", () => {
    vi.useFakeTimers();
    const playSpy = vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
    try {
      const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
      render(<SyncComparePanel workflow={wf} open onClose={() => undefined} />);
      const left = screen.getByTestId("sync-compare-video-left") as HTMLVideoElement;
      const right = screen.getByTestId("sync-compare-video-right") as HTMLVideoElement;
      fireEvent.click(screen.getByTestId("sync-compare-play"));
      left.currentTime = 5;
      right.currentTime = 5.5;
      Object.defineProperty(right, "seeking", { value: true, configurable: true });
      Object.defineProperty(right, "readyState", { value: 4, configurable: true });
      act(() => {
        vi.advanceTimersByTime(260);
      });
      expect(right.currentTime).toBe(5.5);
      Object.defineProperty(right, "seeking", { value: false, configurable: true });
      right.currentTime = 5.8;
      act(() => {
        vi.advanceTimersByTime(260);
      });
      expect(right.currentTime).toBe(5);
    } finally {
      playSpy.mockRestore();
      vi.useRealTimers();
    }
  });

  it("分割线方向键 ±2% 且不触发全局 ±1s 步进", () => {
    const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
    render(<SyncComparePanel workflow={wf} open onClose={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "滑动分割" }));
    const divider = screen.getByRole("slider", { name: "分割位置" });
    const left = screen.getByTestId("sync-compare-video-left") as HTMLVideoElement;
    fireEvent.keyDown(divider, { key: "ArrowRight" });
    expect(divider.getAttribute("aria-valuenow")).toBe("52");
    expect(left.currentTime).toBe(0);
  });

  it("加载失败显示错误 pill，重试清除", () => {
    const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
    render(<SyncComparePanel workflow={wf} open onClose={() => undefined} />);
    const left = screen.getByTestId("sync-compare-video-left");
    fireEvent(left, new Event("error"));
    expect(screen.getByTestId("sync-compare-error-left").textContent).toContain("加载失败");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(screen.queryByTestId("sync-compare-error-left")).toBeNull();
  });

  it("宽高比不同时叠加视图提示错位，一致时不提示", () => {
    const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
    render(<SyncComparePanel workflow={wf} open onClose={() => undefined} />);
    const left = screen.getByTestId("sync-compare-video-left") as HTMLVideoElement;
    const right = screen.getByTestId("sync-compare-video-right") as HTMLVideoElement;
    Object.defineProperty(left, "videoWidth", { value: 1280, configurable: true });
    Object.defineProperty(left, "videoHeight", { value: 720, configurable: true });
    Object.defineProperty(right, "videoWidth", { value: 720, configurable: true });
    Object.defineProperty(right, "videoHeight", { value: 720, configurable: true });
    fireEvent(left, new Event("loadedmetadata"));
    fireEvent(right, new Event("loadedmetadata"));
    fireEvent.click(screen.getByRole("button", { name: "差异" }));
    expect(screen.getByTestId("sync-compare-aspect-warn").textContent).toContain("错位");
    Object.defineProperty(right, "videoWidth", { value: 1280, configurable: true });
    fireEvent(right, new Event("loadedmetadata"));
    expect(screen.queryByTestId("sync-compare-aspect-warn")).toBeNull();
  });

  it("打开时焦点进入面板（焦点陷阱）", () => {
    const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
    render(<SyncComparePanel workflow={wf} open onClose={() => undefined} />);
    expect(document.activeElement).toBe(screen.getByTestId("sync-compare-panel"));
  });

  it("自动对齐：采样→NCC→写 offsetB 并恢复播放位置", async () => {
    const pattern = (i: number) => Math.sin(i * 1.7) + 0.5 * Math.sin(i * 0.53);
    const sampler = vi.fn(async (video: HTMLVideoElement, times: number[]) => {
      const shift = video.getAttribute("data-testid") === "sync-compare-video-right" ? 3 : 0;
      return times.map((_, i) => pattern(i - shift));
    });
    const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
    render(<SyncComparePanel workflow={wf} open onClose={() => undefined} sampleTracks={sampler} />);
    const left = screen.getByTestId("sync-compare-video-left") as HTMLVideoElement;
    const right = screen.getByTestId("sync-compare-video-right") as HTMLVideoElement;
    Object.defineProperty(left, "duration", { value: 10, configurable: true });
    Object.defineProperty(right, "duration", { value: 10, configurable: true });
    fireEvent.click(screen.getByTestId("sync-compare-auto-align"));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(sampler).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("sync-compare-offset").textContent).toContain("+1.5");
    expect(screen.getByTestId("sync-compare-align-note").textContent).toContain("自动对齐");
    expect(left.currentTime).toBe(0);
    expect(right.currentTime).toBeCloseTo(1.5, 6);
  });

  it("小漂移用 playbackRate 微调，回阈值内复位，大漂移硬 seek", () => {
    vi.useFakeTimers();
    const playSpy = vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
    try {
      const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
      render(<SyncComparePanel workflow={wf} open onClose={() => undefined} />);
      const left = screen.getByTestId("sync-compare-video-left") as HTMLVideoElement;
      const right = screen.getByTestId("sync-compare-video-right") as HTMLVideoElement;
      Object.defineProperty(right, "readyState", { value: 4, configurable: true });
      fireEvent.click(screen.getByTestId("sync-compare-play"));
      left.currentTime = 5;
      right.currentTime = 5.3;
      act(() => {
        vi.advanceTimersByTime(260);
      });
      expect(right.playbackRate).toBeCloseTo(0.88, 5);
      right.currentTime = 5.02;
      act(() => {
        vi.advanceTimersByTime(260);
      });
      expect(right.playbackRate).toBe(1);
      right.currentTime = 5.8;
      act(() => {
        vi.advanceTimersByTime(260);
      });
      expect(right.currentTime).toBe(5);
      expect(right.playbackRate).toBe(1);
    } finally {
      playSpy.mockRestore();
      vi.useRealTimers();
    }
  });

  it("版本栈：上一版按钮把右侧切到版本链上一版，到头给出提示", async () => {
    const version = (version_id: string, version_no: number): V2AssetVersionMetadata => ({
      version_id,
      asset_id: "asset_wm",
      version_no,
      storage_key: `generated/a/v${version_no}.mp4`,
      sha256: `sha-${version_no}`,
      size_bytes: 1,
      mime_type: "video/mp4",
      width: 1280,
      height: 720,
      duration_seconds: 15,
      status: "ready",
      created_at: "2026-10-11T00:00:00Z",
    });
    const listVersions = vi.fn(async () => ({ versions: [version("version_asset_wm", 2), version("version_asset_wm_v1", 1)] }));
    const wf = workflow([WM_NODE, FIN_NODE], [asset("asset_wm"), asset("asset_fin")]);
    render(<SyncComparePanel workflow={wf} open onClose={() => undefined} listVersions={listVersions} />);
    const right = screen.getByTestId("sync-compare-video-right") as HTMLVideoElement;
    expect(right.getAttribute("src")).toContain("v=version_asset_fin");

    fireEvent.click(screen.getByTestId("sync-compare-prev-version"));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(listVersions).toHaveBeenCalledWith("asset_wm");
    expect(right.getAttribute("src")).toContain("v=version_asset_wm_v1");
    expect(screen.getByText(/上一版 v1/)).toBeTruthy();

    fireEvent.click(screen.getByTestId("sync-compare-prev-version"));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByTestId("sync-compare-version-note").textContent).toBe("已是链上最早版本");
  });
});
