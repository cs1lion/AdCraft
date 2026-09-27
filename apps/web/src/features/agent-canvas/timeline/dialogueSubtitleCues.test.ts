import { describe, expect, it } from "vitest";

import { buildSubtitleCues } from "./dialogueSubtitleCues.ts";

describe("buildSubtitleCues", () => {
  it("publishes one cue per segment with the service's boundaries", () => {
    const { cues, skipped } = buildSubtitleCues([
      { segment_id: "s0", character_id: "lin", text: "第一句。", start_time: 0.5, end_time: 2.0 },
      { segment_id: "s1", character_id: "su", text: "第二句。", start_time: 3.0, end_time: 4.25 },
    ]);

    expect(skipped).toEqual([]);
    expect(cues).toEqual([
      { start_time: 0.5, duration: 1.5, subtitle_text: "第一句。", label: "lin: 第一句。" },
      { start_time: 3, duration: 1.25, subtitle_text: "第二句。", label: "su: 第二句。" },
    ]);
  });

  it("clamps an overlapping cue to the next cue's start (cross-talk)", () => {
    // su starts talking 0.2s before lin finishes: the cue must not stack.
    const { cues } = buildSubtitleCues([
      { character_id: "lin", text: "很长的第一句台词", start_time: 0, end_time: 3 },
      { character_id: "su", text: "（抢话）等一下", start_time: 2.8, end_time: 4 },
    ]);

    expect(cues[0].duration).toBeCloseTo(2.8, 3);
    expect(cues[1].start_time).toBe(2.8);
  });

  it("sorts unsorted segments defensively before clamping", () => {
    const { cues } = buildSubtitleCues([
      { character_id: "su", text: "第二", start_time: 3, end_time: 4 },
      { character_id: "lin", text: "第一", start_time: 0, end_time: 2 },
    ]);

    expect(cues.map((cue) => cue.subtitle_text)).toEqual(["第一", "第二"]);
  });

  it("drops empty text, invalid times and zero-length cues with reasons", () => {
    const { cues, skipped } = buildSubtitleCues([
      { segment_id: "a", character_id: "lin", text: "   ", start_time: 0, end_time: 1 },
      { segment_id: "b", character_id: "lin", text: "坏了", start_time: 2, end_time: 2 },
      { segment_id: "c", character_id: "lin", text: "反的", start_time: 4, end_time: 3 },
      { segment_id: "d", character_id: "lin", text: "好的", start_time: 5, end_time: 6 },
    ]);

    expect(cues).toHaveLength(1);
    expect(cues[0].subtitle_text).toBe("好的");
    expect(skipped).toEqual([
      { segment_id: "a", reason: "empty_text" },
      { segment_id: "b", reason: "invalid_times" },
      { segment_id: "c", reason: "invalid_times" },
    ]);
  });

  it("drops a cue that clamps below the readable minimum", () => {
    // Two lines 30ms apart: the first cue clamps to 30ms — publishing such a
    // caption is worse than dropping it, and the drop is reported.
    const { cues, skipped } = buildSubtitleCues([
      { segment_id: "x", character_id: "lin", text: "瞬间", start_time: 0, end_time: 1 },
      { segment_id: "y", character_id: "su", text: "下一句", start_time: 0.03, end_time: 2 },
    ]);

    expect(cues).toHaveLength(1);
    expect(cues[0].subtitle_text).toBe("下一句");
    expect(skipped[0]).toEqual({ segment_id: "x", reason: "non_positive_duration" });
  });

  it("truncates long cue text but keeps the speaker in the label", () => {
    const long = "台词".repeat(80);
    const { cues } = buildSubtitleCues([
      { character_id: "lin", text: long, start_time: 0, end_time: 1 },
    ]);

    expect(cues[0].subtitle_text.length).toBe(60);
    expect(cues[0].label.startsWith("lin: ")).toBe(true);
  });
});
