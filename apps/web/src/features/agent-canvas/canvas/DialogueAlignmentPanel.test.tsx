/**
 * DialogueAlignmentPanel tests — the C mode's UI trigger.
 *
 * Locks the trigger conditions (asset + speaker-tagged lines required), the
 * fetch contract (asset_id + lines to /scene-3d/align-speech), the per-line
 * display with confidence, the low-confidence warning, and the engine label
 * (estimated alignment is honestly displayed as unmeasured).
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DialogueAlignmentPanel } from "./DialogueAlignmentPanel.tsx";

const SCRIPTS = [
  { speaker: "林澈", text: "（压低声音，警惕）就是这里，信号源在墙后面。" },
  { text: "[地下研究所 B2 层，低频电机嗡鸣]" }, // SFX line: not speaker-tagged
  { speaker: "苏晴", text: "（轻声）你确定要进去吗？" },
];

function alignResponse() {
  return {
    status: 200,
    json: async () => ({
      success: true,
      align_source: "estimated",
      segments: [
        {
          segment_id: "seg_0",
          character_id: "林澈",
          text: "（压低声音，警惕）就是这里，信号源在墙后面。",
          start_time: 0.0,
          end_time: 1.8,
          confidence: 0.4,
          align_source: "estimated",
          regenerated: true,
          duration_source: "measured",
        },
        {
          segment_id: "seg_1",
          character_id: "苏晴",
          text: "（轻声）你确定要进去吗？",
          start_time: 1.8,
          end_time: 4.3,
          confidence: 0.4,
          align_source: "estimated",
          regenerated: true,
          duration_source: "measured",
        },
      ],
      low_confidence_ids: ["seg_0", "seg_1"],
      regenerated_ids: ["seg_0", "seg_1"],
      regeneration_duration_source: "measured",
      bed_duration_seconds: 4.5,
      warnings: [],
    }),
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(cleanup);

describe("DialogueAlignmentPanel", () => {
  it("renders nothing without an output asset", () => {
    const { container } = render(
      <DialogueAlignmentPanel assetId={null} scripts={SCRIPTS} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when no line is speaker-tagged", () => {
    const { container } = render(
      <DialogueAlignmentPanel
        assetId="asset-1"
        scripts={[{ text: "[wind only]" }]}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("runs alignment over the asset and displays per-line timings", async () => {
    const fetchMock = vi.fn().mockResolvedValue(alignResponse());
    vi.stubGlobal("fetch", fetchMock);
    render(<DialogueAlignmentPanel assetId="asset-audio-1" scripts={SCRIPTS} />);

    fireEvent.click(screen.getByText("🎯 台词对齐"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/scene-3d/align-speech");
    const body = JSON.parse((options as RequestInit).body as string);
    expect(body.asset_id).toBe("asset-audio-1");
    expect(body.lines).toHaveLength(2); // SFX lines excluded
    expect(body.lines[0].character_id).toBe("林澈");

    // The honest engine label + low-confidence warning + per-line rows.
    expect(screen.getByText(/确定性估算铺排/)).toBeTruthy();
    expect(screen.getByText(/2 句低于唇形置信阈值/)).toBeTruthy();
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("0.00s – 1.80s");
    expect(rows[0].textContent).toContain("40%");
    // B-mode regeneration is visible: the summary names the source, and the
    // rows carry the per-line badge.
    expect(screen.getByTestId("dialogue-alignment-regenerated").textContent).toContain(
      "TTS 实测",
    );
    expect(screen.getByTestId("dialogue-alignment-regen-seg_0").textContent).toContain(
      "B 模式重测",
    );
  });

  it("surfaces the API error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 400,
        json: async () => ({
          detail: { error: "Audio file not found: /x", error_code: "alignment_audio_missing" },
        }),
      }),
    );
    render(<DialogueAlignmentPanel assetId="asset-1" scripts={SCRIPTS} />);

    fireEvent.click(screen.getByText("🎯 台词对齐"));

    await waitFor(() => {
      expect(screen.getByText("Audio file not found: /x")).toBeTruthy();
    });
  });
});

describe("DialogueAlignmentPanel — C-mode handoff", () => {
  afterEach(cleanup);

  it("reports aligned lines to the scene-3d side via onLinesAligned", async () => {
    const fetchMock = vi.fn().mockResolvedValue(alignResponse());
    vi.stubGlobal("fetch", fetchMock);
    const onLinesAligned = vi.fn();
    render(
      <DialogueAlignmentPanel
        assetId="asset-audio-1"
        scripts={SCRIPTS}
        onLinesAligned={onLinesAligned}
      />,
    );

    fireEvent.click(screen.getByText("🎯 台词对齐"));

    await waitFor(() => {
      expect(onLinesAligned).toHaveBeenCalledTimes(1);
    });
    const handed = onLinesAligned.mock.calls[0][0] as {
      character_id: string;
      text: string;
      start_time: number;
      align_source: string;
    }[];
    expect(handed).toHaveLength(2);
    expect(handed[0].character_id).toBe("林澈");
    expect(handed[0].start_time).toBeCloseTo(0.0, 3);
    expect(handed[0].align_source).toBe("estimated"); // passthrough of the engine label
  });

  it("does not report lines when alignment fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => null }),
    );
    const onLinesAligned = vi.fn();
    render(
      <DialogueAlignmentPanel
        assetId="asset-audio-1"
        scripts={SCRIPTS}
        onLinesAligned={onLinesAligned}
      />,
    );

    fireEvent.click(screen.getByText("🎯 台词对齐"));

    await waitFor(() => {
      expect(screen.getByText(/对齐失败/)).toBeTruthy();
    });
    expect(onLinesAligned).not.toHaveBeenCalled();
  });
});

describe("DialogueAlignmentPanel — speaker/character mapping", () => {
  afterEach(cleanup);

  it("hands the scene side character ids and shows the mapping", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(alignResponse()));
    const onLinesAligned = vi.fn();
    render(
      <DialogueAlignmentPanel
        assetId="asset-audio-1"
        scripts={SCRIPTS}
        onLinesAligned={onLinesAligned}
        speakerCharacterMap={{ 林澈: "char_a", 苏晴: "char_b" }}
      />,
    );

    fireEvent.click(screen.getByText("🎯 台词对齐"));

    await waitFor(() => {
      expect(onLinesAligned).toHaveBeenCalledTimes(1);
    });
    const handed = onLinesAligned.mock.calls[0][0] as { character_id: string }[];
    // The handoff carries scene ids — the lip-sync editor can select them.
    expect(handed.map((line) => line.character_id)).toEqual(["char_a", "char_b"]);

    // The alignment itself stays faithful to the bed, with the mapping shown.
    expect(screen.getByText(/林澈/)).toBeTruthy();
    expect(screen.getByText(/→\s*char_a/)).toBeTruthy();
  });

  it("falls back to raw speaker names without a mapping", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(alignResponse()));
    const onLinesAligned = vi.fn();
    render(
      <DialogueAlignmentPanel
        assetId="asset-audio-1"
        scripts={SCRIPTS}
        onLinesAligned={onLinesAligned}
      />,
    );

    fireEvent.click(screen.getByText("🎯 台词对齐"));

    await waitFor(() => {
      expect(onLinesAligned).toHaveBeenCalledTimes(1);
    });
    const handed = onLinesAligned.mock.calls[0][0] as { character_id: string }[];
    expect(handed.map((line) => line.character_id)).toEqual(["林澈", "苏晴"]);
    expect(screen.queryByText(/→\s*char_a/)).toBeNull();
  });
});
