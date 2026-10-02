/** 语言搭建组件测试（2026-09-29 简约好用分支）。 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SceneLanguageBuilder } from "./SceneLanguageBuilder";
import type { SceneScriptRoot } from "../../../types/scene-script";

afterEach(cleanup);

function script(): SceneScriptRoot {
  return {
    scene: { name: "lab", environment: "indoor", duration: 4, frame_rate: 30 },
    characters: [],
    props: [],
    environment: [],
    cameras: [],
    shots: [],
  } as SceneScriptRoot;
}

describe("SceneLanguageBuilder", () => {
  it("adds a prop from free text and reports it", () => {
    const onChange = vi.fn();
    render(<SceneLanguageBuilder script={script()} onChange={onChange} />);
    fireEvent.change(screen.getByPlaceholderText(/加一张桌子在左边/), {
      target: { value: "加一张方桌在左边" },
    });
    fireEvent.click(screen.getByText("添加"));
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    expect(next.props).toHaveLength(1);
    expect(next.props[0]).toMatchObject({ type: "rect_table" });
    expect(next.props[0].position[0]).toBeLessThan(0);
    expect(screen.getByText(/✓ 已添加道具/)).toBeTruthy();
  });

  it("adds an environment object from a quick chip", () => {
    const onChange = vi.fn();
    render(<SceneLanguageBuilder script={script()} onChange={onChange} />);
    fireEvent.click(screen.getByText("加一棵树"));
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    expect(next.environment).toHaveLength(1);
    expect(next.environment[0]).toMatchObject({ type: "tree" });
  });

  it("keeps the author informed when it cannot parse", () => {
    const onChange = vi.fn();
    render(<SceneLanguageBuilder script={script()} onChange={onChange} />);
    fireEvent.change(screen.getByPlaceholderText(/加一张桌子在左边/), {
      target: { value: "今天天气不错" },
    });
    fireEvent.click(screen.getByText("添加"));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText(/没听懂/)).toBeTruthy();
  });

  it("places a chair behind an existing table via a relative phrase", () => {
    const onChange = vi.fn();
    const base = script();
    base.props = [
      { id: "prop_rect_table_1", type: "rect_table", position: [2, 1, 0], scale: 1 },
    ] as never;
    render(<SceneLanguageBuilder script={base} onChange={onChange} />);
    fireEvent.change(screen.getByPlaceholderText(/加一张桌子在左边/), {
      target: { value: "加一把椅子放在桌子后面" },
    });
    fireEvent.click(screen.getByText("添加"));
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    expect(next.props).toHaveLength(2);
    expect(next.props[1]).toMatchObject({ type: "chair" });
    expect(next.props[1].position[1]).toBeCloseTo(2.5);
    expect(screen.getByText(/✓ 已添加道具/)).toBeTruthy();
  });
});

describe("SceneLanguageBuilder AI fallback", () => {
  const UNPARSED = "铺一张波斯地毯";

  function typeUnparsed() {
    fireEvent.change(screen.getByPlaceholderText(/加一张桌子在左边/), {
      target: { value: UNPARSED },
    });
    fireEvent.click(screen.getByText("添加"));
  }

  it("offers the AI fallback on a miss and adopts the applied script", async () => {
    const onChange = vi.fn();
    const applied = script();
    applied.props = [
      { id: "prop_rug_1", type: "box", position: [0.5, 0, 0] },
    ] as never;
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        operation_count: 2,
        applied_scene_script: applied,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    try {
      render(<SceneLanguageBuilder script={script()} onChange={onChange} />);
      typeUnparsed();
      expect(screen.getByText(/没听懂/)).toBeTruthy();

      fireEvent.click(screen.getByTestId("scene-language-ai-fallback"));

      expect(await screen.findByText(/✓ AI 已按/)).toBeTruthy();
      expect(onChange).toHaveBeenCalledTimes(1);
      expect(onChange.mock.calls[0][0]).toBe(applied);
      expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/scene-3d/language-fallback");
      const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
      expect(body.text).toBe(UNPARSED);
      // 已处理，不再给重试按钮
      expect(screen.queryByTestId("scene-language-ai-fallback")).toBeNull();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("keeps the sentence and the retry button when the AI path is rejected", async () => {
    const onChange = vi.fn();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        success: false,
        error: "LLM is not configured: set LLM_API_KEY and LLM_BASE_URL.",
        error_code: "white_model_llm_unconfigured",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    try {
      render(<SceneLanguageBuilder script={script()} onChange={onChange} />);
      typeUnparsed();

      fireEvent.click(screen.getByTestId("scene-language-ai-fallback"));

      expect(await screen.findByText(/AI 没搭出来/)).toBeTruthy();
      expect(screen.getByText(/white_model_llm_unconfigured|LLM is not configured/)).toBeTruthy();
      expect(onChange).not.toHaveBeenCalled();
      // 句子留着可重试
      expect(screen.getByTestId("scene-language-ai-fallback")).toBeTruthy();
      expect(
        (screen.getByPlaceholderText(/加一张桌子在左边/) as HTMLInputElement).value,
      ).toBe(UNPARSED);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
