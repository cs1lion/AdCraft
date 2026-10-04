import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FilmInstructionBar } from "./SceneScript3DEditor.tsx";

// vitest runs without `globals`, so Testing Library's automatic cleanup never
// registers itself — every render would otherwise leak into the next case.
afterEach(cleanup);

describe("FilmInstructionBar", () => {
  it("shows the reference framework's placeholder", () => {
    render(<FilmInstructionBar onSubmit={vi.fn()} />);
    expect(screen.getByLabelText("AI 场景指令").getAttribute("placeholder")).toBe(
      "选中一个元素或机位，描述如何调整..",
    );
  });

  it("clears the field and forwards the trimmed instruction on submit", () => {
    const onSubmit = vi.fn();
    render(<FilmInstructionBar onSubmit={onSubmit} />);
    const input = screen.getByLabelText("AI 场景指令") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "  把飞船往左移两米  " } });
    fireEvent.click(screen.getByLabelText("发送指令"));
    // Trimmed: the agent must not receive padding it would have to re-trim.
    expect(onSubmit).toHaveBeenCalledWith("把飞船往左移两米");
    expect(input.value).toBe("");
  });

  it("cannot send an empty instruction", () => {
    const onSubmit = vi.fn();
    render(<FilmInstructionBar onSubmit={onSubmit} />);
    const send = screen.getByLabelText("发送指令") as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("AI 场景指令"), { target: { value: "   " } });
    expect(send.disabled).toBe(true);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("says it is not wired instead of pretending to accept input", () => {
    // No onSubmit: the agent channel does not exist yet. A disabled input labelled
    // "未接线" is honest; an enabled one that silently drops the text is not.
    render(<FilmInstructionBar />);
    const input = screen.getByLabelText("AI 场景指令") as HTMLInputElement;
    expect(input.disabled).toBe(true);
    expect(screen.getByText("未接线")).toBeTruthy();
    expect(screen.queryByLabelText("发送指令")).toBeNull();
  });
});
