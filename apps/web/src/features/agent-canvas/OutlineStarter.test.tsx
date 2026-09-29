/**
 * OutlineStarter — 从一句话开始（2026-09-29 简约好用分支）。
 * Locks: expand calls the outline endpoint and renders the shot list; build
 * posts the reviewed shots; failures surface as text (never silent).
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OutlineStarter } from "./OutlineStarter.tsx";

afterEach(cleanup);

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

describe("OutlineStarter", () => {
  it("expands an outline into a reviewed shot list", async () => {
    const fetchMock = stubFetch((url) =>
      url.includes("/creation/expand-outline")
        ? { success: true, shots: SHOTS }
        : { success: true },
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
