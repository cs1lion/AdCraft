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
    expect(onSubmit).toHaveBeenCalledWith("把飞船往左移两米", null);
    expect(input.value).toBe("");
  });

  it("carries the target with the instruction", () => {
    // A bar that shows the target but submits without it would make the future
    // executor guess once between the author's intent and what it received.
    const onSubmit = vi.fn();
    const subject = { label: "机位02 | 飞船俯瞰", scope: "shot", targetId: "shot2" };
    render(<FilmInstructionBar onSubmit={onSubmit} subject={subject} />);
    expect(screen.getByTestId("film-instruction-subject").textContent).toContain("飞船俯瞰");
    expect(screen.getByLabelText("AI 场景指令").getAttribute("placeholder")).toBe(
      "描述如何调整「机位02 | 飞船俯瞰」..",
    );
    fireEvent.change(screen.getByLabelText("AI 场景指令"), { target: { value: "拉远一点" } });
    fireEvent.click(screen.getByLabelText("发送指令"));
    expect(onSubmit).toHaveBeenCalledWith("拉远一点", subject);
  });

  it("returns to shot scope when the object target is cleared", () => {
    const onClearSubject = vi.fn();
    const subject = { label: "crate1", scope: "object", targetId: "crate1" };
    render(
      <FilmInstructionBar
        onSubmit={vi.fn()}
        subject={subject}
        onClearSubject={onClearSubject}
      />,
    );
    expect(screen.getByLabelText("AI 场景指令").getAttribute("placeholder")).toBe(
      "描述如何调整「crate1」..",
    );
    fireEvent.click(screen.getByLabelText("改调整个镜头"));
    expect(onClearSubject).toHaveBeenCalledTimes(1);
  });

  it("keeps the reference placeholder while nothing is selected", () => {
    render(<FilmInstructionBar onSubmit={vi.fn()} subject={null} />);
    expect(screen.getByLabelText("AI 场景指令").getAttribute("placeholder")).toBe(
      "选中一个元素或机位，描述如何调整..",
    );
    expect(screen.queryByTestId("film-instruction-subject")).toBeNull();
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
