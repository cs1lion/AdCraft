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
});
