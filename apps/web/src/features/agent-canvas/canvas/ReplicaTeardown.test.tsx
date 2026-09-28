/**
 * ReplicaTeardown tests — the 拉片复刻 entry (hypit-inspired MVP slice).
 *
 * Locks: the disabled surface without an uploaded video, the fetch contract
 * (asset_id + optional goal to /api/v1/replica/teardown), the report surface
 * (reading / beats / shot table / rhythm+systems / constraints / draft), the
 * clipboard copy of the replica storyboard draft, and the error surface.
 *
 * D8: teardown is a job — POST /teardown only submits (returns job_id);
 * results are polled from GET /teardown/jobs/{job_id}; cancel goes through
 * POST /teardown/jobs/{job_id}/cancel (real cancellation, not a client-side
 * abort that leaves the backend burning LLM quota).
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

/** 任务轮询的完成载荷（与后端 TeardownJobStatusResponse 同构）。 */
function completedStatus(overrides: Record<string, unknown> = {}) {
  return {
    status: "completed",
    success: true,
    report: REPORT,
    num_frames_analyzed: 8,
    ...overrides,
  };
}

/** 便捷构造：拆解任务流的 URL-aware fetch mock（提交 → 轮询 → 取消）。 */
function stubTeardownFlow(options: {
  statusSequence?: Array<Record<string, unknown>>;
} = {}) {
  const statuses = options.statusSequence ?? [completedStatus()];
  let statusCalls = 0;
  const fetchMock = vi.fn(async (url: string) => {
    const target = String(url);
    if (target.includes("/teardown/jobs/") && target.includes("/cancel")) {
      return {
        status: 200,
        json: async () => ({ success: true, job_id: "job_1", cancelled: true, status: "cancelled" }),
      };
    }
    if (target.includes("/teardown/jobs/")) {
      const body = statuses[Math.min(statusCalls, statuses.length - 1)];
      statusCalls += 1;
      return { status: 200, json: async () => body };
    }
    return {
      status: 200,
      json: async () => ({ success: true, job_id: "job_1", status: "pending" }),
    };
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

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
    const fetchMock = vi.fn(async (url: string) => {
      const target = String(url);
      if (target.includes("/teardown/jobs/")) {
        return { status: 200, json: async () => completedStatus() };
      }
      if (target.includes("ingest")) {
        return {
          status: 200,
          json: async () => ({
            success: true,
            asset_id: "ref_fromlink01",
            file_name: "ref_fromlink01.mp4",
            source_url: "https://example.com/v",
          }),
        };
      }
      return {
        status: 200,
        json: async () => ({ success: true, job_id: "job_link", status: "pending" }),
      };
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
    const submitCall = fetchMock.mock.calls.find((call) =>
      String(call[0]).includes("/replica/teardown"),
    );
    const init = submitCall?.[1] as RequestInit;
    expect((init.body as FormData).get("asset_id")).toBe("ref_fromlink01");
  });

  it("POSTs the asset_id and renders the teardown report", async () => {
    const fetchMock = stubTeardownFlow();

    render(<ReplicaTeardown assetId="asset-123" />);
    fireEvent.click(screen.getByText("🎬 拉片复刻"));

    await waitFor(() => expect(screen.getByText(/整片解读/)).toBeTruthy());

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/replica/teardown");
    expect(init.method).toBe("POST");
    const body = (init as RequestInit).body as FormData;
    expect(body.get("asset_id")).toBe("asset-123");
    // D8：提交只拿 job_id，载荷经任务轮询
    const pollCall = fetchMock.mock.calls.find((call) =>
      String(call[0]).includes("/teardown/jobs/"),
    );
    expect(pollCall).toBeTruthy();

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
    expect(screen.getByText(/1\. \[0\.0–2.1s\] closeup/)).toBeTruthy();
  });

  it("surfaces the cache-hit provenance without claiming new LLM spend", async () => {
    stubTeardownFlow({
      statusSequence: [completedStatus({ cached: true, cache_key: "abc123" })],
    });

    render(<ReplicaTeardown assetId="asset-123" />);
    fireEvent.click(screen.getByText("🎬 拉片复刻"));

    await waitFor(() => expect(screen.getByText(/缓存命中/)).toBeTruthy());
    expect(screen.getByText(/未调用 LLM/)).toBeTruthy();
  });

  it("sends the selected replica goal as user_description", async () => {
    const fetchMock = stubTeardownFlow();

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
    stubTeardownFlow();
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

  // D8：任务失败（含总预算超时）必须原样上屏——不是笼统的"失败"
  it("surfaces a job failure with the server error and type", async () => {
    stubTeardownFlow({
      statusSequence: [
        {
          status: "failed",
          error: "拆解超过总时限 900 秒仍未完成，已停止后续 LLM 调用（未产生完整报告）。可重试，或减少抽帧数后再次拆解。",
          error_type: "teardown_timeout",
        },
      ],
    });

    render(<ReplicaTeardown assetId="asset-123" />);
    fireEvent.click(screen.getByText("🎬 拉片复刻"));
    await waitFor(() => expect(screen.getByText(/拆解超过总时限/)).toBeTruthy());
    expect(screen.getByText(/可重试，或减少抽帧数/)).toBeTruthy();
  });

  it("surfaces a server-side cancelled job state", async () => {
    stubTeardownFlow({ statusSequence: [{ status: "cancelled" }] });

    render(<ReplicaTeardown assetId="asset-123" />);
    fireEvent.click(screen.getByText("🎬 拉片复刻"));
    await waitFor(() =>
      expect(screen.getByText(/已取消：后端在下次调用前已停止/)).toBeTruthy(),
    );
  });
});

describe("ReplicaTeardown blueprint creation", () => {
  it("creates a replica blueprint node from the teardown report", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      const target = String(url);
      if (target.includes("/teardown/jobs/")) {
        return { status: 200, json: async () => completedStatus() };
      }
      if (target.includes("/replica/blueprint")) {
        return {
          status: 200,
          json: async () => ({
            success: true,
            blueprint: { blueprint_version: "replica-blueprint-v1", format_name: "product-comparison" },
            replica_script: "# 复刻脚本",
          }),
        };
      }
      return { status: 200, json: async () => ({ success: true, job_id: "job_1", status: "pending" }) };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ReplicaTeardown assetId="asset-123" workflowId="wf-1" />);
    fireEvent.click(screen.getByText("🎬 拉片复刻"));
    await waitFor(() => expect(screen.getByText("🧬 创建复刻蓝图")).toBeTruthy());
    fireEvent.click(screen.getByText("🧬 创建复刻蓝图"));

    await waitFor(() => expect(screen.getByText(/node_replica_1/)).toBeTruthy());
    const calls = (fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls;
    const blueprintCall = calls.find((call) => String(call[0]).includes("/replica/blueprint"));
    expect(blueprintCall).toBeTruthy();
    const body = JSON.parse((blueprintCall?.[1] as RequestInit).body as string);
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
    stubTeardownFlow();
    render(<ReplicaTeardown assetId="asset-123" />);
    fireEvent.click(screen.getByText("🎬 拉片复刻"));
    await waitFor(() => expect(screen.getByText("🧬 创建复刻蓝图")).toBeTruthy());
    expect((screen.getByText("🧬 创建复刻蓝图") as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("ReplicaTeardown fluency & guidance", () => {
  it("shows live elapsed feedback and a cancel control while reading", async () => {
    let resolveStatus: ((value: unknown) => void) | null = null;
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).includes("/teardown/jobs/")) {
        return new Promise((resolve) => {
          resolveStatus = resolve;
        });
      }
      return { status: 200, json: async () => ({ success: true, job_id: "job_1", status: "pending" }) };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ReplicaTeardown assetId="asset-123" />);
    fireEvent.click(screen.getByText("🎬 拉片复刻"));

    await waitFor(() => expect(screen.getByText(/已进行/)).toBeTruthy());
    expect(screen.getByText("⏹ 取消等待")).toBeTruthy();

    resolveStatus?.({ status: 200, json: async () => completedStatus() });
    await waitFor(() => expect(screen.getByText(/整片解读/)).toBeTruthy());
    // 完成后取消控件与进行中提示都消失
    expect(screen.queryByText("⏹ 取消等待")).toBeNull();
  });

  // D8 完成判据：点了取消，后端真的停——取消必须打到取消端点（带 job_id），
  // 界面如实说明"不再消耗额度"，而不是旧那句"后端可能仍在跑"。
  it("cancels through the backend cancel endpoint (real cancel, D8)", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const target = String(url);
      if (target.includes("/teardown/jobs/") && target.includes("/cancel")) {
        return {
          status: 200,
          json: async () => ({ success: true, job_id: "job_1", cancelled: true, status: "cancelled" }),
        };
      }
      if (target.includes("/teardown/jobs/")) {
        // 轮询在途：abort 时拒绝（模拟浏览器对 signal 的行为）
        return new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        });
      }
      return { status: 200, json: async () => ({ success: true, job_id: "job_1", status: "pending" }) };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ReplicaTeardown assetId="asset-123" />);
    fireEvent.click(screen.getByText("🎬 拉片复刻"));
    await waitFor(() => expect(screen.getByText("⏹ 取消等待")).toBeTruthy());

    fireEvent.click(screen.getByText("⏹ 取消等待"));

    const cancelCall = await waitFor(() => {
      const found = fetchMock.mock.calls.find((call) =>
        String(call[0]).includes("/teardown/jobs/job_1/cancel"),
      );
      expect(found).toBeTruthy();
      return found;
    });
    expect((cancelCall as unknown as [string, RequestInit])[1].method).toBe("POST");
    await waitFor(() =>
      expect(screen.getByText(/已取消：后端在下次调用前已停止，不再消耗额度/)).toBeTruthy(),
    );
    // 旧的不诚实文案不许回来
    expect(screen.queryByText(/后端可能仍在完成本次拉片/)).toBeNull();
    // 可重新发起拉片（按钮恢复可用）
    expect((screen.getByText("🎬 拉片复刻") as HTMLButtonElement).disabled).toBe(false);
  });

  it("keeps the submit wait cancellable before a job id exists (abort path)", async () => {
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
    await waitFor(() => expect(screen.getByText(/已取消/)).toBeTruthy());
    // 可重新发起拉片（按钮恢复可用）
    expect((screen.getByText("🎬 拉片复刻") as HTMLButtonElement).disabled).toBe(false);
  });

  it("carries real video metadata (duration/aspect) into the blueprint request", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      const target = String(url);
      if (target.includes("/teardown/jobs/")) {
        return {
          status: 200,
          json: async () =>
            completedStatus({ video_metadata: { duration_seconds: 12.0, width: 1080, height: 1920 } }),
        };
      }
      if (target.includes("/replica/blueprint")) {
        return {
          status: 200,
          json: async () => ({
            success: true,
            blueprint: { blueprint_version: "replica-blueprint-v1", format_name: "product-comparison" },
            replica_script: "# 复刻脚本",
          }),
        };
      }
      return { status: 200, json: async () => ({ success: true, job_id: "job_1", status: "pending" }) };
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
    const blueprintCall = calls.find((call) => String(call[0]).includes("/replica/blueprint"));
    const body = JSON.parse((blueprintCall?.[1] as RequestInit).body as string);
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
