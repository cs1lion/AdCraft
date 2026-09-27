/**
 * WhiteModelOpLog tests. Locks the three render states (no report / applied
 * ops / MCP results incl. error status) and the op-label mapping so the log
 * never shows a raw op code to the user.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { WhiteModelOpLog } from "./WhiteModelOpLog.tsx";

afterEach(cleanup);

describe("WhiteModelOpLog", () => {
  it("renders nothing without a report", () => {
    const { container } = render(<WhiteModelOpLog report={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing for an empty report", () => {
    const { container } = render(
      <WhiteModelOpLog report={{ applied: [], mcp_results: [], operation_count: 0 }} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders applied ops with human labels and targets", () => {
    render(
      <WhiteModelOpLog
        report={{
          operation_count: 3,
          applied: [
            { index: 0, op: "add_environment", target: "env_1" },
            { index: 1, op: "add_character", target: "char_1" },
            { index: 2, op: "move_object", target: "cam1" },
          ],
          mcp_results: [],
        }}
      />,
    );
    const log = screen.getByTestId("white-model-op-log");
    expect(log.textContent).toContain("3/3 个操作");
    // Human labels, never raw op codes.
    expect(log.textContent).toContain("添加环境");
    expect(log.textContent).toContain("添加角色");
    expect(log.textContent).toContain("移动");
    expect(log.textContent).not.toContain("add_environment");
    expect(log.textContent).toContain("env_1");
    expect(log.textContent).toContain("cam1");
  });

  it("renders MCP extension results with status", () => {
    render(
      <WhiteModelOpLog
        report={{
          operation_count: 2,
          applied: [{ index: 0, op: "add_environment", target: "env_1" }],
          mcp_results: [
            { tool: "bevel", target: "env_1", is_error: false, content: [] },
            { tool: "subdivide", target: "wall_1", is_error: true, content: [] },
          ],
        }}
      />,
    );
    const log = screen.getByTestId("white-model-op-log");
    expect(log.textContent).toContain("2 个 MCP 扩展");
    expect(log.textContent).toContain("bevel → env_1");
    expect(log.textContent).toContain("subdivide → wall_1");
    expect(log.textContent).toContain("已执行");
    expect(log.textContent).toContain("失败");
  });

  it("shows partial application counts honestly", () => {
    render(
      <WhiteModelOpLog
        report={{
          operation_count: 5,
          applied: [{ index: 0, op: "add_environment", target: "env_1" }],
          mcp_results: [],
        }}
      />,
    );
    expect(screen.getByTestId("white-model-op-log").textContent).toContain("1/5 个操作");
  });
});
