/**
 * VoiceCastDialogueLines tests (V0.2 §14.7 内容层/表演层).
 *
 * The property this surface exists for: **改了哪一句就只重做哪一句**. The
 * editor's job is to say so BEFORE the run (which lines will be reused, which
 * re-synthesized) and to carry the executor's manifest afterwards, so an
 * author can see that a one-word change cost one provider call.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CanvasNodeV2 } from "../../../types-v2.ts";
import {
  VoiceCastDialogueLines,
  dialogueLinesFromNode,
  validateDialogueLines,
} from "./VoiceCastDialogueLines.tsx";

afterEach(cleanup);

function node(structuredContent: Record<string, unknown>): CanvasNodeV2 {
  return {
    node_id: "voice-1",
    workflow_id: "wf-1",
    node_type: "voice-cast",
    creative_role: "voice_cast",
    title: "Voice",
    status: "ready",
    position: { x: 0, y: 0 },
    revision: 1,
    created_at: "2026-09-27T00:00:00Z",
    updated_at: "2026-09-27T00:00:00Z",
    structured_content: structuredContent,
  } as unknown as CanvasNodeV2;
}

const LINES = [
  { id: "l1", text: "就是这里", emotion: "压低声音" },
  { id: "l2", text: "别出声" },
];

describe("dialogueLinesFromNode", () => {
  it("reads the authored rows, dropping nothing that has content", () => {
    expect(dialogueLinesFromNode(node({ dialogue_lines: LINES }))).toEqual([
      { id: "l1", text: "就是这里", emotion: "压低声音", regenerate: false },
      { id: "l2", text: "别出声", emotion: "", regenerate: false },
    ]);
  });

  it("treats a node without the block as no rows at all", () => {
    expect(dialogueLinesFromNode(node({}))).toEqual([]);
  });
});

describe("validateDialogueLines", () => {
  const row = (overrides: Partial<{ id: string; text: string; emotion: string }> = {}) => ({
    id: "l1",
    text: "一句",
    emotion: "",
    regenerate: false,
    ...overrides,
  });

  it("accepts a clean set of rows", () => {
    expect(validateDialogueLines([row(), row({ id: "l2", text: "二句" })])).toEqual([]);
  });

  it("requires an id, a text, and unique ids", () => {
    const codes = validateDialogueLines([
      row({ id: "", text: "x" }),
      row({ text: "" }),
      row(),
    ]).map((issue) => issue.code);
    expect(codes).toContain("dialogue_line_id_required");
    expect(codes).toContain("dialogue_line_text_required");
    expect(codes).toContain("dialogue_line_id_duplicate");
  });

  it("rejects an id that cannot survive a filename", () => {
    const codes = validateDialogueLines([row({ id: "has space" })]).map((i) => i.code);
    expect(codes).toContain("dialogue_line_id_invalid");
  });

  it("bounds the text and the emotion the same way the backend does", () => {
    const codes = validateDialogueLines([
      row({ text: "x".repeat(401) }),
      row({ id: "l2", text: "ok", emotion: "e".repeat(65) }),
    ]).map((issue) => issue.code);
    expect(codes).toContain("dialogue_line_too_long");
    expect(codes).toContain("dialogue_line_emotion_too_long");
  });

  it("says so when there are no rows yet", () => {
    expect(validateDialogueLines([])[0].code).toBe("dialogue_lines_required");
  });
});

describe("VoiceCastDialogueLines", () => {
  it("tells the author which lines a replay would reuse before they run it", () => {
    render(<VoiceCastDialogueLines node={node({ dialogue_lines: LINES })} patchNode={vi.fn()} />);
    // Both lines already have takes (the reuse probe assumes the cache is warm),
    // so a plain save must promise a pure re-join.
    const hint = screen.getByTestId("voice-cast-lines-reuse");
    expect(hint.textContent).toContain("只会重新拼接，不调 TTS");
  });

  it("accounts for a per-line 重做 request in that promise", () => {
    render(
      <VoiceCastDialogueLines
        node={node({ dialogue_lines: LINES, regenerate_line_ids: ["l2"] })}
        patchNode={vi.fn()}
      />,
    );
    expect(screen.getByTestId("voice-cast-lines-reuse").textContent).toContain(
      "1 句沿用现成录音，1 句重新合成",
    );
  });

  it("PATCHes the rows, the emotions, and the regenerate request (merged)", () => {
    const patchNode = vi.fn().mockResolvedValue(undefined);
    render(
      <VoiceCastDialogueLines
        node={node({ dialogue_lines: LINES, narration: "keep me" })}
        patchNode={patchNode}
      />,
    );
    // Make l2 dirty and mark it for a fresh take.
    fireEvent.change(screen.getByLabelText("第 2 行台词"), { target: { value: "千万别出声" } });
    fireEvent.click(screen.getByLabelText("重做第 2 行"));
    fireEvent.click(screen.getByTestId("voice-cast-lines-save"));

    expect(patchNode).toHaveBeenCalledTimes(1);
    const [nodeId, patch] = patchNode.mock.calls[0];
    expect(nodeId).toBe("voice-1");
    expect(patch.structured_content.narration).toBe("keep me");
    expect(patch.structured_content.dialogue_lines).toEqual([
      { id: "l1", text: "就是这里", emotion: "压低声音" },
      { id: "l2", text: "千万别出声" },
    ]);
    // "Same words, a new performance" is only sayable per line.
    expect(patch.structured_content.regenerate_line_ids).toEqual(["l2"]);
  });

  it("keeps a row with no emotion free of an empty emotion key", () => {
    const patchNode = vi.fn().mockResolvedValue(undefined);
    render(
      <VoiceCastDialogueLines
        node={node({ dialogue_lines: [{ id: "l1", text: "一句" }] })}
        patchNode={patchNode}
      />,
    );
    fireEvent.change(screen.getByLabelText("第 1 行情绪"), { target: { value: "急" } });
    fireEvent.change(screen.getByLabelText("第 1 行情绪"), { target: { value: "" } });
    fireEvent.click(screen.getByTestId("voice-cast-lines-save"));
    expect(patchNode.mock.calls[0][1].structured_content.dialogue_lines).toEqual([
      { id: "l1", text: "一句" },
    ]);
  });

  it("gates save on the same rules the backend enforces", () => {
    render(<VoiceCastDialogueLines node={node({ dialogue_lines: LINES })} patchNode={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("第 1 行 id"), { target: { value: "l2" } });
    expect(screen.getByTestId("voice-cast-lines-issues")).toBeTruthy();
    expect(
      (screen.getByTestId("voice-cast-lines-save") as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("shows the executor's manifest after a run (which line, how long, rebuilt?)", () => {
    render(
      <VoiceCastDialogueLines
        node={node({
          dialogue_lines: LINES,
          dialogue_line_manifest: [
            {
              line_id: "l1",
              text: "就是这里",
              emotion: "压低声音",
              duration_seconds: 1.4,
              offset_seconds: 0,
              regenerated: false,
            },
            {
              line_id: "l2",
              text: "别出声",
              emotion: "",
              duration_seconds: 2.1,
              offset_seconds: 1.4,
              regenerated: true,
            },
          ],
        })}
        patchNode={vi.fn()}
      />,
    );
    const table = screen.getByTestId("voice-cast-lines-manifest");
    expect(table.textContent).toContain("l1");
    expect(table.textContent).toContain("1.4");
    expect(table.textContent).toContain("2.1");
  });

  it("publishes the rows the backend dropped, rather than hiding them", () => {
    render(
      <VoiceCastDialogueLines
        node={node({
          dialogue_lines: LINES,
          dialogue_lines_dropped: ["dialogue_lines[2]（x）没有台词文本，已忽略。"],
        })}
        patchNode={vi.fn()}
      />,
    );
    expect(screen.getByTestId("voice-cast-lines-dropped").textContent).toContain(
      "没有台词文本",
    );
  });

  it("adds and removes rows without a save round-trip", () => {
    render(<VoiceCastDialogueLines node={node({})} patchNode={vi.fn()} />);
    fireEvent.click(screen.getByText("+ 一行"));
    expect(screen.getByLabelText("第 1 行 id")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("第 1 行 id"), { target: { value: "a" } });
    fireEvent.change(screen.getByLabelText("第 1 行台词"), { target: { value: "hi" } });
    fireEvent.click(screen.getByLabelText("删除第 1 行"));
    expect(screen.queryByLabelText("第 1 行 id")).toBeNull();
  });
});
