/**
 * OutlineStarter — 从一句话开始（2026-09-29 简约好用分支）。
 * Locks: expand calls the outline endpoint and renders the shot list; build
 * posts the reviewed shots; failures surface as text (never silent).
 */

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OutlineStarter } from "./OutlineStarter.tsx";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

function stubFetch(handler: (url: string, init?: RequestInit) => unknown) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const result = handler(url, init);
    return {
      ok: result !== null,
      status: result !== null ? 200 : 500,
      json: async () => result ?? { error: "boom" },
    } as unknown as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const SHOTS = [
  { summary: "果园晨光", visual: "阳光穿过苹果园，露珠滚动", duration_seconds: 5, on_screen_text: "新鲜，看得见" },
  { summary: "切开慢动作", visual: "苹果切开，汁水渗出", duration_seconds: 6, on_screen_text: "" },
];

async function startRun() {
  fireEvent.change(screen.getByRole("textbox", { name: "从一句话开始" }), { target: { value: "苹果广告" } });
  await act(async () => { fireEvent.click(screen.getByText("展开分镜")); });
  await act(async () => { fireEvent.click(screen.getByText("开始生成（2 镜）")); });
}

function runHandler(url: string) {
  if (url.includes("expand-outline")) return { success: true, shots: SHOTS };
  if (url.includes("build-from-outline")) return { success: true, film_node_ids: ["film1", "film2"] };
  if (url.includes("assemble-film")) return { render_id: "render1" };
  if (url.includes("/renders/")) return { status: "completed", output_url: "/output/movie.mp4" };
  return { nodes: [{ node_id: "film1", status: "ready" }, { node_id: "film2", status: "ready" }, { node_id: "old", title: "成片镜头旧", status: "ready" }] };
}

function countCalls(mock: ReturnType<typeof stubFetch>, part: string) {
  return mock.mock.calls.filter(([url]) => String(url).includes(part)).length;
}

describe("OutlineStarter", () => {
  it("waits for all returned IDs rather than assembling old ready nodes", async () => {
    vi.useFakeTimers();
    let allReady = false;
    const mock = stubFetch((url) => url === "/api/v2/workflows/wf_1" && !allReady
      ? { nodes: [{ node_id: "film1", status: "ready" }, { node_id: "old", title: "成片镜头旧", status: "ready" }] }
      : runHandler(url));
    render(<OutlineStarter workflowId="wf_1" />);
    await startRun();
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(countCalls(mock, "assemble-film")).toBe(0);
    expect(screen.getByRole("status").textContent).toContain("1/2");
    allReady = true;
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(countCalls(mock, "assemble-film")).toBe(1);
  });

  it("pauses failed shot queries and manually resumes without another build", async () => {
    vi.useFakeTimers();
    let available = false;
    const mock = stubFetch((url) => url === "/api/v2/workflows/wf_1" && !available ? null : runHandler(url));
    render(<OutlineStarter workflowId="wf_1" />);
    await startRun();
    await act(async () => { await vi.advanceTimersByTimeAsync(18000); });
    expect(countCalls(mock, "/api/v2/workflows/")).toBe(3);
    available = true;
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "重新查询镜头" })); await vi.advanceTimersByTimeAsync(6000); });
    expect(countCalls(mock, "build-from-outline")).toBe(1);
    expect(countCalls(mock, "assemble-film")).toBe(1);
  });

  it("ignores assembly acceptance after a project switch and does not poll its render", async () => {
    vi.useFakeTimers();
    let finish!: (response: Response) => void;
    const mock = vi.fn((input: RequestInfo | URL) => String(input).includes("assemble-film")
      ? new Promise<Response>((resolve) => { finish = resolve; })
      : Promise.resolve({ ok: true, json: async () => runHandler(String(input)) } as Response));
    vi.stubGlobal("fetch", mock);
    const { rerender } = render(<OutlineStarter workflowId="wf_1" />);
    await startRun();
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    rerender(<OutlineStarter workflowId="wf_2" />);
    await act(async () => { finish({ ok: true, json: async () => ({ render_id: "old-render" }) } as Response); await vi.advanceTimersByTimeAsync(10000); });
    expect(mock.mock.calls.some(([url]) => String(url).includes("/renders/"))).toBe(false);
    expect(screen.queryByText(/成片渲染中/)).toBeNull();
  });

  it("pauses completed renders with missing or unsafe output URLs instead of exposing links", async () => {
    vi.useFakeTimers();
    const output: { url?: string } = {};
    const mock = stubFetch((path) => path.includes("/renders/") ? { status: "completed", output_url: output.url } : runHandler(path));
    render(<OutlineStarter workflowId="wf_1" />);
    await startRun();
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(screen.getByRole("alert").textContent).toContain("视频地址");
    output.url = "javascript:alert(1)";
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "重新查询原渲染" })); });
    expect(screen.queryByRole("link", { name: "打开成片" })).toBeNull();
    expect(countCalls(mock, "assemble-film")).toBe(1);
  });
  it("retries only assembly using cached scoped ready shots and previews compact completion", async () => {
    vi.useFakeTimers();
    let assemblies = 0;
    const mock = stubFetch((url) => url.includes("assemble-film") && ++assemblies === 1 ? null : runHandler(url));
    const { rerender, container } = render(<OutlineStarter workflowId="wf_1" />);
    await startRun();
    rerender(<OutlineStarter workflowId="wf_1" showEntry={false} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(screen.getByRole("button", { name: "仅重试合成" })).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "仅重试合成" }));
      fireEvent.click(screen.getByRole("button", { name: "仅重试合成" }));
    });
    expect(countCalls(mock, "assemble-film")).toBe(2);
    expect(countCalls(mock, "build-from-outline")).toBe(1);
    expect(countCalls(mock, "expand-outline")).toBe(1);
    const requests = mock.mock.calls.filter(([url]) => String(url).includes("assemble-film"));
    for (const [, init] of requests) expect(JSON.parse(String(init?.body)).node_ids).toEqual(["film1", "film2"]);
    expect(container.querySelector("video")?.getAttribute("src")).toBe("/output/movie.mp4");
    expect(container.querySelector("video")?.hasAttribute("controls")).toBe(true);
    expect(container.querySelector("details")?.open).toBe(false);
    expect(screen.getByRole("link", { name: "打开成片", hidden: true })).toBeTruthy();
    expect(screen.getByRole("link", { name: "下载成片", hidden: true }).hasAttribute("download")).toBe(true);
  });

  it("reports progress and only explicitly reassembles terminal render failures", async () => {
    vi.useFakeTimers();
    let polls = 0;
    const mock = stubFetch((url) => url.includes("/renders/") ? ++polls === 1 ? { status: "rendering", progress_percent: 42 } : { status: "failed", error_message: "编码失败" } : runHandler(url));
    render(<OutlineStarter workflowId="wf_1" />);
    await startRun();
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(screen.getByRole("status").textContent).toContain("42%");
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByRole("alert").textContent).toContain("编码失败");
    expect(countCalls(mock, "assemble-film")).toBe(1);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "仅重试合成" })); });
    expect(countCalls(mock, "assemble-film")).toBe(2);
    expect(countCalls(mock, "build-from-outline")).toBe(1);
  });

  it("bounds transient render failures and requeries the original render without assembly", async () => {
    vi.useFakeTimers();
    let available = false;
    const mock = stubFetch((url) => url.includes("/renders/") && !available ? null : runHandler(url));
    render(<OutlineStarter workflowId="wf_1" />);
    await startRun();
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(countCalls(mock, "/renders/")).toBe(3);
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(countCalls(mock, "/renders/")).toBe(3);
    available = true;
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "重新查询原渲染" })); });
    expect(screen.getByText("✓ 成片已完成")).toBeTruthy();
    expect(countCalls(mock, "assemble-film")).toBe(1);
    expect(mock.mock.calls.filter(([url]) => String(url).includes("/renders/")).every(([url]) => String(url).endsWith("/renders/render1"))).toBe(true);
  });

  it("requeries timed out original renders without creating another render", async () => {
    vi.useFakeTimers();
    const mock = stubFetch((url) => url.includes("/renders/") ? { status: "rendering" } : runHandler(url));
    render(<OutlineStarter workflowId="wf_1" />);
    await startRun();
    await act(async () => { await vi.advanceTimersByTimeAsync(306000); });
    expect(countCalls(mock, "/renders/")).toBe(150);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "重新查询原渲染" })); });
    expect(countCalls(mock, "/renders/")).toBe(151);
    expect(countCalls(mock, "assemble-film")).toBe(1);
  });

  it("never guesses old titled films when accepted build omits film IDs", async () => {
    vi.useFakeTimers();
    const mock = stubFetch((url) => url.includes("build-from-outline") ? { success: true } : runHandler(url));
    render(<OutlineStarter workflowId="wf_1" />);
    await startRun();
    expect(screen.getByRole("alert").textContent).toContain("未返回本次成片镜头编号");
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(countCalls(mock, "assemble-film")).toBe(0);
    expect(countCalls(mock, "/api/v2/workflows/")).toBe(0);
    expect((screen.getByText("已开始生成") as HTMLButtonElement).disabled).toBe(true);
  });

  it("ignores an old render response after project switch or unmount", async () => {
    vi.useFakeTimers();
    let finish!: (response: Response) => void;
    const mock = vi.fn((input: RequestInfo | URL) => String(input).includes("/renders/")
      ? new Promise<Response>((resolve) => { finish = resolve; })
      : Promise.resolve({ ok: true, json: async () => runHandler(String(input)) } as Response));
    vi.stubGlobal("fetch", mock);
    const { rerender, unmount } = render(<OutlineStarter workflowId="wf_1" />);
    await startRun();
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    rerender(<OutlineStarter workflowId="wf_2" />);
    await act(async () => { finish({ ok: true, json: async () => ({ status: "completed", output_url: "/old.mp4" }) } as Response); });
    expect(screen.queryByLabelText("成片预览")).toBeNull();
    expect(screen.queryByText("✓ 成片已完成")).toBeNull();
    await startRun();
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    unmount();
    await act(async () => { finish({ ok: true, json: async () => ({ status: "rendering" }) } as Response); await vi.advanceTimersByTimeAsync(10000); });
    expect(mock.mock.calls.filter(([url]) => String(url).includes("/renders/"))).toHaveLength(2);
  });
  it("edits one reviewed shot without another model expansion", async () => {
    const fetchMock = stubFetch((url) => url.includes("expand-outline") ? { success: true, shots: SHOTS } : { success: true, film_node_ids: ["film1", "film2"] });
    render(<OutlineStarter workflowId="wf_1" />);
    fireEvent.change(screen.getByRole("textbox", { name: "从一句话开始" }), { target: { value: "苹果广告" } });
    fireEvent.click(screen.getByText("展开分镜"));
    await screen.findByText("果园晨光");
    expect(screen.getByText("屏上文字：新鲜，看得见")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "修改镜头 1" }));
    fireEvent.change(screen.getByRole("textbox", { name: "镜头 1 画面" }), { target: { value: "桌上的苹果，近景" } });
    fireEvent.change(screen.getByRole("textbox", { name: "镜头 1 屏上文字" }), { target: { value: "刚刚采摘" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: "镜头 1 时长（秒）" }), { target: { value: "4" } });
    fireEvent.click(screen.getByText("开始生成（2 镜）"));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("build-from-outline"))).toBe(true));
    const request = fetchMock.mock.calls.find(([url]) => String(url).includes("build-from-outline"))!;
    expect(JSON.parse(String(request[1]?.body)).shots[0]).toEqual({ ...SHOTS[0], visual: "桌上的苹果，近景", on_screen_text: "刚刚采摘", duration_seconds: 4 });
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("expand-outline"))).toHaveLength(1);
  });

  it("keeps accepted generation tracking alive when canvas nodes arrive", async () => {
    vi.useFakeTimers();
    const fetchMock = stubFetch((url) => url.includes("expand-outline") ? { success: true, shots: SHOTS } : url.includes("build-from-outline") ? { success: true, film_node_ids: ["film1", "film2"] } : url.includes("assemble-film") ? { success: true, clip_count: 2, render_id: "render1" } : url.includes("/renders/") ? { status: "rendering", progress_percent: 25 } : { nodes: [{ node_id: "film1", status: "ready" }, { node_id: "film2", status: "ready" }] });
    const { rerender } = render(<OutlineStarter workflowId="wf_1" />);
    fireEvent.change(screen.getByRole("textbox", { name: "从一句话开始" }), { target: { value: "苹果广告" } });
    await act(async () => { fireEvent.click(screen.getByText("展开分镜")); });
    await act(async () => { fireEvent.click(screen.getByText("开始生成（2 镜）")); });
    rerender(<OutlineStarter workflowId="wf_1" showEntry={false} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("assemble-film"))).toHaveLength(1);
    expect(screen.getByRole("status").textContent).toContain("成片渲染中");
    expect(screen.queryByRole("textbox", { name: "从一句话开始" })).toBeNull();
  });
  it("requires a fresh reviewed preview after the brief changes", async () => {
    stubFetch(() => ({ success: true, shots: SHOTS }));
    render(<OutlineStarter workflowId="wf_1" />);
    fireEvent.change(screen.getByRole("textbox", { name: "从一句话开始" }), { target: { value: "苹果广告" } });
    fireEvent.click(screen.getByText("展开分镜"));
    await screen.findByText("果园晨光");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "改成橙子广告" } });
    expect((screen.getByText("开始生成（2 镜）") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/避免按旧分镜生成/)).toBeTruthy();
  });

  it("does not carry preview or responses into a different project", async () => {
    let finish!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { finish = resolve; })));
    const { rerender } = render(<OutlineStarter workflowId="wf_1" />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "旧项目广告" } });
    fireEvent.click(screen.getByText("展开分镜"));
    rerender(<OutlineStarter workflowId="wf_2" />);
    finish({ ok: true, json: async () => ({ success: true, shots: SHOTS }) } as Response);
    await waitFor(() => expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe(""));
    expect(screen.queryByText("果园晨光")).toBeNull();
  });
  it("expands an outline into a reviewed shot list", async () => {
    const fetchMock = stubFetch((url) =>
      url.includes("/creation/expand-outline")
        ? { success: true, shots: SHOTS }
        : { success: true, film_node_ids: ["film1", "film2"] },
    );
    render(<OutlineStarter workflowId="wf_1" />);

    fireEvent.change(screen.getByPlaceholderText(/红苹果清晨广告/), {
      target: { value: "一条 20 秒的红苹果清晨广告" },
    });
    fireEvent.click(screen.getByText("展开分镜"));

    await waitFor(() => expect(screen.getByText("果园晨光")).toBeTruthy());
    expect(screen.getByText(/切开慢动作/)).toBeTruthy();
    // 审核后的一键生成按钮带着镜数
    expect(screen.getByText("开始生成（2 镜）")).toBeTruthy();

    fireEvent.click(screen.getByText("开始生成（2 镜）"));
    await waitFor(() => {
      const buildCall = fetchMock.mock.calls.find((call) =>
        String(call[0]).includes("/creation/build-from-outline"),
      );
      expect(buildCall).toBeTruthy();
      const body = JSON.parse(String((buildCall as unknown as [string, RequestInit])[1].body));
      expect(body.workflow_id).toBe("wf_1");
      expect(body.shots).toHaveLength(2);
    });
    await waitFor(() => expect(screen.getByText(/已开画/)).toBeTruthy());
  });

  it("surfaces expansion failure as text", async () => {
    stubFetch(() => null);
    render(<OutlineStarter workflowId="wf_1" />);
    fireEvent.change(screen.getByPlaceholderText(/红苹果清晨广告/), {
      target: { value: "随便写点什么" },
    });
    fireEvent.click(screen.getByText("展开分镜"));
    await waitFor(() => expect(screen.getByText("boom")).toBeTruthy());
    // 失败后不给"开始生成"（没有镜头可建）
    expect(screen.queryByText(/开始生成/)).toBeNull();
  });
});
