/**
 * Scene3DRenderControls tests — E6: the 3D line's render entry
 * (scene-3d render/async family: submit → poll progress → real cancel).
 *
 * Locks: the submit call and job handle, progress surfacing while in
 * flight, the completed result (video + warnings), a failed job's error
 * text, and that cancel goes to the backend cancel endpoint (not a
 * client-side "pretend").
 */

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Scene3DRenderControls } from "./Scene3DRenderControls.tsx";
import type { SceneScriptRoot } from "../../../types/scene-script";

function script(): SceneScriptRoot {
  return {
    scene: { name: "lab", environment: "indoor", duration: 4, frame_rate: 30 },
    characters: [],
    props: [],
    environment: [],
    cameras: [
      {
        id: "cam1",
        shot_type: "wide",
        keyframes: [{ frame: 0, position: [5, -6, 2.6], look_at: [0, 0, 1.2] }],
      },
    ],
    shots: [{ id: "s1", camera: "cam1", start_frame: 0, end_frame: 60 }],
    speech_bindings: [],
  } as unknown as SceneScriptRoot;
}

function stubRenderFlow(options: {
  statuses?: Array<Record<string, unknown>>;
  cancel?: Record<string, unknown>;
} = {}) {
  const statuses = options.statuses ?? [
    {
      job_id: "job_1",
      status: "completed",
      progress: 1,
      result: {
        video_path: "data/media/renders/previs.mp4",
        frame_count: 120,
        warnings: ["音频床混入失败，已输出无声预演"],
      },
    },
  ];
  let statusCalls = 0;
  const fetchMock = vi.fn(async (url: string) => {
    const target = String(url);
    if (target.includes("/render/async")) {
      return {
        status: 200,
        json: async () => ({ job_id: "job_1", status: "pending", message: "submitted" }),
      };
    }
    if (target.includes("/cancel")) {
      return {
        status: 200,
        json: async () => options.cancel ?? { job_id: "job_1", status: "cancelled" },
      };
    }
    if (target.includes("/render/")) {
      const body = statuses[Math.min(statusCalls, statuses.length - 1)];
      statusCalls += 1;
      return { status: 200, json: async () => body };
    }
    return { status: 200, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Scene3DRenderControls (E6)", () => {
  it("plays the published animatic URL rather than an inaccessible host path", async () => {
    stubRenderFlow({ statuses: [{ job_id: "job_1", status: "completed", progress: 1, result: {
      video_path: "C:\\private\\previs.mp4", video_url: "/media/scene3d/job_1/previs.mp4",
      animatic_video_url: "/media/scene3d/job_1/animatic.mp4", warnings: [],
    } }] });
    render(<Scene3DRenderControls sceneScript={script()} />);
    fireEvent.click(screen.getByText("🎬 预览渲染"));
    await screen.findByTestId("scene-3d-render-result");
    expect(screen.getByTestId("scene-3d-render-result").querySelector("video")?.getAttribute("src"))
      .toBe("/media/scene3d/job_1/animatic.mp4");
  });
  it("submits the scene script and polls to a completed render", async () => {
    const fetchMock = stubRenderFlow();

    render(<Scene3DRenderControls sceneScript={script()} />);
    fireEvent.click(screen.getByText("🎬 预览渲染"));

    // 提交：当前场景脚本进 render/async
    await waitFor(() =>
      expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/render/async"))).toBe(true),
    );
    const submitBody = JSON.parse(
      (fetchMock.mock.calls.find((call) => String(call[0]).includes("/render/async")) as unknown as [string, RequestInit])[1]
        .body as string,
    );
    expect(submitBody.scene_script.scene.name).toBe("lab");

    // 轮询到终态：完成 + 产物 + warnings（降级可见）
    await waitFor(() => expect(screen.getByTestId("scene-3d-render-result")).toBeTruthy());
    expect(screen.getByText("✓ 渲染完成")).toBeTruthy();
    expect(screen.getByText(/音频床混入失败，已输出无声预演/)).toBeTruthy();
    const video = document.querySelector("video");
    expect(video?.getAttribute("src")).toContain("previs.mp4");
  });

  it("shows progress while the job is in flight", async () => {
    stubRenderFlow({
      statuses: [{ job_id: "job_1", status: "running", progress: 0.42 }],
    });

    render(<Scene3DRenderControls sceneScript={script()} />);
    fireEvent.click(screen.getByText("🎬 预览渲染"));

    await waitFor(() => expect(screen.getByText(/42%/)).toBeTruthy());
    expect(screen.getByTestId("scene-3d-render-progress")).toBeTruthy();
    expect(screen.getByText("⏹ 取消渲染")).toBeTruthy();
  });

  it("cancels through the backend cancel endpoint (real cancel)", async () => {
    const fetchMock = stubRenderFlow({
      statuses: [{ job_id: "job_1", status: "running", progress: 0.3 }],
    });

    render(<Scene3DRenderControls sceneScript={script()} />);
    fireEvent.click(screen.getByText("🎬 预览渲染"));
    await waitFor(() => expect(screen.getByText("⏹ 取消渲染")).toBeTruthy());

    fireEvent.click(screen.getByText("⏹ 取消渲染"));

    await waitFor(() => {
      const cancelCall = fetchMock.mock.calls.find((call) =>
        String(call[0]).includes("/render/job_1/cancel"),
      );
      expect(cancelCall).toBeTruthy();
      expect((cancelCall as unknown as [string, RequestInit])[1].method).toBe("POST");
    });
    await waitFor(() => expect(screen.getByTestId("scene-3d-render-notice")).toBeTruthy());
    expect(screen.getByText(/已取消：后端已接受取消请求/)).toBeTruthy();
    // 不说"渲染已停止"：协作式取消只保证阶段边界停（同 D8 口径）
    expect(screen.getByText(/渲染将在阶段边界停止/)).toBeTruthy();
  });

  it("surfaces a failed job with the server error", async () => {
    stubRenderFlow({
      statuses: [
        {
          job_id: "job_1",
          status: "failed",
          progress: 0,
          error: "Blender is not available: [Errno 2] No such file or directory: 'blender'",
        },
      ],
    });

    render(<Scene3DRenderControls sceneScript={script()} />);
    fireEvent.click(screen.getByText("🎬 预览渲染"));

    await waitFor(() => expect(screen.getByTestId("scene-3d-render-error")).toBeTruthy());
    expect(screen.getByText(/Blender is not available/)).toBeTruthy();
  });

  it("surfaces a submit failure (e.g. schema validation) without entering polling", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        status: 422,
        json: async () => ({ detail: "SceneScript failed schema validation: shots[0]" }),
      })),
    );

    render(<Scene3DRenderControls sceneScript={script()} />);
    fireEvent.click(screen.getByText("🎬 预览渲染"));

    await waitFor(() => expect(screen.getByTestId("scene-3d-render-error")).toBeTruthy());
    expect(screen.getByText(/SceneScript failed schema validation/)).toBeTruthy();
    // 没有进入轮询
    expect(screen.queryByTestId("scene-3d-render-progress")).toBeNull();
  });
});

it("does not poll the previous job during a delayed second submission", async () => {
  const client = await import("./directorOperationsClient.ts");
  let complete!: (id: string) => void;
  vi.spyOn(client, "submitScene3DRender").mockResolvedValueOnce("old").mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
  const poll = vi.spyOn(client, "fetchScene3DRenderJob").mockImplementation(async (id) => ({ job_id: id, status: id === "old" ? "completed" : "running", progress: 0.2 }));
  render(<Scene3DRenderControls sceneScript={script()} />);
  fireEvent.click(screen.getByText("🎬 预览渲染"));
  await screen.findByText("✓ 渲染完成");
  fireEvent.click(screen.getByText("🎬 预览渲染"));
  await waitFor(() => expect(screen.getByText("⏳ 渲染中…")).toBeTruthy());
  expect(screen.getByRole("status").textContent).toContain("正在提交任务");
  expect((screen.getByRole("button", { name: "⏹ 取消渲染" }) as HTMLButtonElement).disabled).toBe(true);
  complete("new");
  await waitFor(() => expect(poll).toHaveBeenCalledWith("new"));
  expect(poll.mock.calls.filter(([id]) => id === "old")).toHaveLength(1);
});

it("resumes polling when cancellation fails", async () => {
  const client = await import("./directorOperationsClient.ts");
  vi.spyOn(client, "submitScene3DRender").mockResolvedValue("job");
  const poll = vi.spyOn(client, "fetchScene3DRenderJob").mockResolvedValue({ job_id: "job", status: "running", progress: 0.2 });
  vi.spyOn(client, "cancelScene3DRender").mockRejectedValue(new Error("network"));
  render(<Scene3DRenderControls sceneScript={script()} />);
  fireEvent.click(screen.getByText("🎬 预览渲染"));
  await screen.findByText("⏹ 取消渲染");
  await waitFor(() => expect(poll).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByText("⏹ 取消渲染"));
  await waitFor(() => expect(poll.mock.calls.length).toBeGreaterThan(1));
  expect(screen.getByText(/取消失败/)).toBeTruthy();
});

it("stops polling after the bounded 150 attempts", async () => {
  vi.useFakeTimers();
  try {
    const client = await import("./directorOperationsClient.ts");
    vi.spyOn(client, "submitScene3DRender").mockResolvedValue("job");
    const poll = vi.spyOn(client, "fetchScene3DRenderJob").mockResolvedValue({job_id:"job",status:"running",progress:0.1});
    render(<Scene3DRenderControls sceneScript={script()}/>);
    await act(async () => { fireEvent.click(screen.getByText("🎬 预览渲染")); });
    await act(async () => { await vi.advanceTimersByTimeAsync(302000); });
    expect(poll).toHaveBeenCalledTimes(150);
    expect(screen.queryByText("⏳ 渲染中…")).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(20000); });
    expect(poll).toHaveBeenCalledTimes(150);
    expect(screen.getByRole("alert").textContent).toContain("任务可能仍在后台进行");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "继续查询原任务" })); });
    expect(poll).toHaveBeenCalledTimes(151);
    expect(poll).toHaveBeenLastCalledWith("job");
    expect(client.submitScene3DRender).toHaveBeenCalledTimes(1);
  } finally { cleanup(); vi.useRealTimers(); }
});
