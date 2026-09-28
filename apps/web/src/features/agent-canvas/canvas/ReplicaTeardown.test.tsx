/**
 * ReplicaTeardown tests — the 拉片复刻 entry (hypit-inspired MVP slice).
 *
 * Locks: the disabled surface without an uploaded video, the fetch contract
 * (asset_id + optional goal to /api/v1/replica/teardown), the report surface
 * (reading / beats / shot table / rhythm+systems / constraints / draft), the
 * clipboard copy of the replica storyboard draft, and the error surface.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReplicaTeardown, aspectFromDimensions } from "./ReplicaTeardown.tsx";
import type { TeardownReport } from "./ReplicaTeardown.tsx";

// The panel syncs the canvas through the workspace context after creating a
// blueprint node; mock the boundary so the panel renders without a provider.
const setAgentCanvasWorkflow = vi.fn();
const createAgentCanvasNode = vi.fn(async () => ({
  value: { workflow: {}, node: { node_id: "node_replica_1" } },
}));
vi.mock("../../../AppContextValue.ts", () => ({
  useApp: () => ({ setAgentCanvasWorkflow }),
}));
vi.mock("../../../api/agentCanvasApi.ts", () => ({
  agentCanvasApi: { createAgentCanvasNode: (...args: unknown[]) => createAgentCanvasNode(...(args as [])) },
}));

const REPORT: TeardownReport = {
  whole_piece_reading: "前3秒用错误示范制造焦虑，中段产品证明，结尾CTA。",
  format_name: "product-comparison",
  shots: [
    {
      index: 1,
      start_seconds: 0,
      end_seconds: 2.1,
      shot_size: "closeup",
      camera_motion: "static",
      subject_action: "唇部特写",
      on_screen_text: "别再这样洗脸",
      transition_to_next: "cut",
      note: "",
    },
    {
      index: 2,
      start_seconds: 2.1,
      end_seconds: 6,
      shot_size: "medium",
      camera_motion: "pushing_in",
      subject_action: "涂抹对比",
      on_screen_text: "第3天",
      transition_to_next: "dissolve",
      note: "",
    },
  ],
  beats: [
    { role: "hook", description: "错误示范抓注意力", start_seconds: 0, end_seconds: 3 },
    { role: "cta", description: "引导下单", start_seconds: 9, end_seconds: 12 },
  ],
  rhythm: { avg_shot_seconds: 2.4, cut_points_seconds: [0, 2.1], energy_curve: "前快后缓" },
  systems: {
    captions: "底部关键词高亮",
    music: "轻快电子",
    graphics: ["价格贴: 产品提到时弹入"],
    sfx: ["切换 whoosh"],
  },
  replica_storyboard_draft: "# 复刻分镜草稿（来自拉片复刻 · 参考片拆解）\n1. [0.0–2.1s] closeup / static",
  constraints: ["镜头边界与运动为 LLM 基于稀疏抽帧的推断值，非帧级测量"],
};

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(cleanup);

describe("ReplicaTeardown", () => {
  it("shows the link-entry surface without an asset", () => {
    render(<ReplicaTeardown assetId={null} />);
    expect(screen.getByText(/粘贴视频链接/)).toBeTruthy();
    expect(screen.queryByText("🎬 拉片复刻")).toBeNull();
  });

  it("ingests a pasted link and unlocks the teardown flow", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        status: 200,
        json: async () => ({
          success: true,
          asset_id: "ref_fromlink01",
          file_name: "ref_fromlink01.mp4",
          source_url: "https://example.com/v",
        }),
      })
      .mockResolvedValueOnce({
        status: 200,
        json: async () => ({ success: true, report: REPORT, num_frames_analyzed: 8 }),
      });
    vi.stubGlobal("fetch", fetchMock);

    render(<ReplicaTeardown assetId={null} />);
    fireEvent.change(screen.getByPlaceholderText(/bilibili\.com/), {
      target: { value: "https://example.com/v" },
    });
    fireEvent.click(screen.getByText("🔗 抓取"));

    await waitFor(() => expect(screen.getByText(/来源：链接导入/)).toBeTruthy());
    // 抓取成功后拉片入口解锁，且 asset_id 来自链接导入
    fireEvent.click(screen.getByText("🎬 拉片复刻"));
    await waitFor(() => expect(screen.getByText(/整片解读/)).toBeTruthy());
    const init = fetchMock.mock.calls[1][1] as RequestInit;
    expect((init.body as FormData).get("asset_id")).toBe("ref_fromlink01");
  });

  it("POSTs the asset_id and renders the teardown report", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      json: async () => ({ success: true, report: REPORT, num_frames_analyzed: 8 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ReplicaTeardown assetId="asset-123" />);
    fireEvent.click(screen.getByText("🎬 拉片复刻"));

    await waitFor(() => expect(screen.getByText(/整片解读/)).toBeTruthy());

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/replica/teardown");
    expect(init.method).toBe("POST");
    const body = (init as RequestInit).body as FormData;
    expect(body.get("asset_id")).toBe("asset-123");

    // report surfaces
    expect(screen.getByText(/product-comparison/)).toBeTruthy();
    expect(screen.getByText(/错误示范抓注意力/)).toBeTruthy();
    expect(screen.getByText(/唇部特写/)).toBeTruthy();
    expect(screen.getByText(/别再这样洗脸/)).toBeTruthy();
    expect(screen.getByText(/平均镜头 2.4s/)).toBeTruthy();
    expect(screen.getByText(/底部关键词高亮/)).toBeTruthy();
    expect(screen.getByText(/边界声明/)).toBeTruthy();
    // the bridge into the normal flow
    expect(screen.getAllByText(/复刻分镜草稿/).length).toBeGreaterThan(0);
    expect(screen.getByText(/1\. \[0\.0–2\.1s\] closeup/)).toBeTruthy();
  });

  it("surfaces the cache-hit provenance without claiming new LLM spend", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      json: async () => ({
        success: true,
        report: REPORT,
        num_frames_analyzed: 8,
        cached: true,
        cache_key: "abc123",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ReplicaTeardown assetId="asset-123" />);
    fireEvent.click(screen.getByText("🎬 拉片复刻"));

    await waitFor(() => expect(screen.getByText(/缓存命中/)).toBeTruthy());
    expect(screen.getByText(/未调用 LLM/)).toBeTruthy();
  });

  it("sends the selected replica goal as user_description", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      json: async () => ({ success: true, report: REPORT, num_frames_analyzed: 8 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ReplicaTeardown assetId="asset-123" />);
    fireEvent.change(screen.getByDisplayValue("整片复刻（保留全部结构）"), {
      target: { value: "换商品，保留人物与台词结构" },
    });
    fireEvent.click(screen.getByText("🎬 拉片复刻"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.body as FormData).get("user_description")).toBe("换商品，保留人物与台词结构");
  });

  it("copies the replica storyboard draft to the clipboard", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 200,
        json: async () => ({ success: true, report: REPORT, num_frames_analyzed: 8 }),
      }),
    );
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(<ReplicaTeardown assetId="asset-123" />);
    fireEvent.click(screen.getByText("🎬 拉片复刻"));
    await waitFor(() => expect(screen.getByText("📋 复制草稿")).toBeTruthy());

    fireEvent.click(screen.getByText("📋 复制草稿"));
    await waitFor(() => expect(screen.getByText("✓ 已复制")).toBeTruthy());
    expect(writeText).toHaveBeenCalledWith(REPORT.replica_storyboard_draft);
  });

  it("surfaces the HTTP error detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 400,
        json: async () => ({ detail: { error: "Video too long: 75.0s", error_type: "input" } }),
      }),
    );

    render(<ReplicaTeardown assetId="asset-123" />);
    fireEvent.click(screen.getByText("🎬 拉片复刻"));
    await waitFor(() => expect(screen.getByText(/Video too long/)).toBeTruthy());
  });
});


describe("ReplicaTeardown blueprint creation", () => {
  function teardownResponse() {
    return {
      status: 200,
      json: async () => ({ success: true, report: REPORT, num_frames_analyzed: 8 }),
    };
  }

  it("creates a replica blueprint node from the teardown report", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(teardownResponse())
      .mockResolvedValueOnce({
        status: 200,
        json: async () => ({
          success: true,
          blueprint: { blueprint_version: "replica-blueprint-v1", format_name: "product-comparison" },
          replica_script: "# 复刻脚本",
        }),
      }));

    render(<ReplicaTeardown assetId="asset-123" workflowId="wf-1" />);
    fireEvent.click(screen.getByText("🎬 拉片复刻"));
    await waitFor(() => expect(screen.getByText("🧬 创建复刻蓝图")).toBeTruthy());
    fireEvent.click(screen.getByText("🧬 创建复刻蓝图"));

    await waitFor(() => expect(screen.getByText(/node_replica_1/)).toBeTruthy());
    const calls = (fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls;
    expect(calls[1][0]).toBe("/api/v1/replica/blueprint");
    const body = JSON.parse((calls[1][1] as RequestInit).body as string);
    expect(body.source_video_asset_id).toBe("asset-123");
    expect(body.report).toBeTruthy();
    expect(createAgentCanvasNode).toHaveBeenCalledTimes(1);
    const [workflowId, request] = createAgentCanvasNode.mock.calls[0] as unknown as [
      string,
      { node_type: string; creative_role: string; structured_content: Record<string, unknown> },
    ];
    expect(workflowId).toBe("wf-1");
    expect(request.node_type).toBe("replica");
    expect(request.creative_role).toBe("replica_blueprint");
    expect(request.structured_content.blueprint_version).toBe("replica-blueprint-v1");
    expect(setAgentCanvasWorkflow).toHaveBeenCalled();
  });

  it("hides the create button without a workflow", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(teardownResponse()));
    render(<ReplicaTeardown assetId="asset-123" />);
    fireEvent.click(screen.getByText("🎬 拉片复刻"));
    await waitFor(() => expect(screen.getByText("🧬 创建复刻蓝图")).toBeTruthy());
    expect((screen.getByText("🧬 创建复刻蓝图") as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("ReplicaTeardown fluency & guidance", () => {
  it("shows live elapsed feedback and a cancel control while reading", async () => {
    let resolveFetch: ((value: unknown) => void) | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(
        new Promise((resolve) => {
          resolveFetch = resolve;
        }),
      ),
    );
    render(<ReplicaTeardown assetId="asset-123" />);
    fireEvent.click(screen.getByText("🎬 拉片复刻"));

    expect(screen.getByText(/已进行/)).toBeTruthy();
    const cancel = screen.getByText("⏹ 取消等待");
    expect(cancel).toBeTruthy();

    resolveFetch?.({
      status: 200,
      json: async () => ({ success: true, report: REPORT, num_frames_analyzed: 8 }),
    });
    await waitFor(() => expect(screen.getByText(/整片解读/)).toBeTruthy());
    // 完成后取消控件与进行中提示都消失
    expect(screen.queryByText("⏹ 取消等待")).toBeNull();
  });

  it("aborts the wait on cancel and surfaces the cancelled state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(
        (_url: unknown, init?: RequestInit) =>
          new Promise((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            );
          }),
      ),
    );
    render(<ReplicaTeardown assetId="asset-123" />);
    fireEvent.click(screen.getByText("🎬 拉片复刻"));
    fireEvent.click(screen.getByText("⏹ 取消等待"));
    await waitFor(() => expect(screen.getByText(/已取消等待/)).toBeTruthy());
    // 可重新发起拉片（按钮恢复可用）
    expect((screen.getByText("🎬 拉片复刻") as HTMLButtonElement).disabled).toBe(false);
  });

  it("carries real video metadata (duration/aspect) into the blueprint request", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        status: 200,
        json: async () => ({
          success: true,
          report: REPORT,
          num_frames_analyzed: 8,
          video_metadata: { duration_seconds: 12.0, width: 1080, height: 1920 },
        }),
      })
      .mockResolvedValueOnce({
        status: 200,
        json: async () => ({
          success: true,
          blueprint: { blueprint_version: "replica-blueprint-v1", format_name: "product-comparison" },
          replica_script: "# 复刻脚本",
        }),
      });
    vi.stubGlobal("fetch", fetchMock);

    render(<ReplicaTeardown assetId="asset-123" workflowId="wf-1" />);
    fireEvent.click(screen.getByText("🎬 拉片复刻"));
    await waitFor(() => expect(screen.getByText(/整片解读/)).toBeTruthy());
    // 元数据可见（报告头部），不再是静默丢弃
    expect(screen.getByText(/12\.0s · 9:16/)).toBeTruthy();

    fireEvent.click(screen.getByText("🧬 创建复刻蓝图"));
    await waitFor(() => expect(screen.getByText(/复刻蓝图已创建/)).toBeTruthy());
    const calls = (fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls;
    const body = JSON.parse(calls[1][1].body as string);
    expect(body.duration_seconds).toBe(12.0);
    expect(body.aspect).toBe("9:16");
    // 创建后的下一步引导可见
    expect(screen.getByText(/在画布上打开该「复刻蓝图」节点/)).toBeTruthy();
  });

  it("derives aspect ratios from resolutions (with snapping fallback)", () => {
    expect(aspectFromDimensions(1080, 1920)).toBe("9:16");
    expect(aspectFromDimensions(1920, 1080)).toBe("16:9");
    expect(aspectFromDimensions(1000, 1000)).toBe("1:1");
    expect(aspectFromDimensions(720, 1280)).toBe("9:16");
    expect(aspectFromDimensions(0, 0)).toBe("");
  });
});
