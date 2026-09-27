import { describe, expect, it } from "vitest";

import {
  DIALOGUE_LINES_CONTENT_KEY,
  dialogueLinesEqual,
  parseDialogueLines,
  serializeDialogueLines,
} from "./dialogueLinesPersistence.ts";

describe("dialogueLinesPersistence", () => {
  it("round-trips the shape the lip-sync service consumes", () => {
    const stored = serializeDialogueLines([
      { character_id: "char_a", text: "就是这里。", start_time: 1.25, emotion: null },
    ]);

    expect(stored).toEqual([
      { character_id: "char_a", text: "就是这里。", start_time: 1.25, emotion: null },
    ]);
    expect(parseDialogueLines(stored)).toEqual(stored);
  });

  it("drops rows without text on serialize", () => {
    const stored = serializeDialogueLines([
      { character_id: "char_a", text: "  ", start_time: null, emotion: null },
      { character_id: "char_b", text: "第二句。", start_time: null, emotion: null },
    ]);

    expect(stored).toHaveLength(1);
    expect(stored[0].character_id).toBe("char_b");
  });

  it("parses tolerantly (half-written blocks do not crash the panel)", () => {
    const parsed = parseDialogueLines([
      "garbage",
      null,
      { character_id: "char_a", text: "台词", start_time: -1 },
      { character_id: "char_b", text: "两句", start_time: "3" },
    ]);

    // Negative and non-numeric starts normalize to null (the service
    // estimates), rather than storing invalid timing.
    expect(parsed).toEqual([
      { character_id: "char_a", text: "台词", start_time: null, emotion: null },
      { character_id: "char_b", text: "两句", start_time: null, emotion: null },
    ]);
  });

  it("returns null for missing/unusable blocks", () => {
    expect(parseDialogueLines(undefined)).toBeNull();
    expect(parseDialogueLines("nope")).toBeNull();
    expect(parseDialogueLines({})).toBeNull();
  });

  it("compares by value so no-op patches are skipped", () => {
    const a = [{ character_id: "char_a", text: "x", start_time: 1, emotion: null }];
    const b = [{ character_id: "char_a", text: "x", start_time: 1, emotion: null }];

    expect(dialogueLinesEqual(a, b)).toBe(true);
    expect(dialogueLinesEqual(a, null)).toBe(false);
    expect(dialogueLinesEqual(a, [{ ...b[0], start_time: 2 }])).toBe(false);
    expect(dialogueLinesEqual(null, null)).toBe(true);
  });

  it("carries word timings through a round trip", () => {
    const lines = serializeDialogueLines([
      {
        character_id: "lin",
        text: "别出声",
        start_time: 1.0,
        emotion: null,
        word_timings: [
          { text: "别", start: 1.0, end: 1.5 },
          { text: "出声", start: 1.6, end: 2.3 },
        ],
      },
    ]);
    expect(lines[0].word_timings).toHaveLength(2);
    const parsed = parseDialogueLines(lines);
    expect(parsed?.[0].word_timings).toEqual(lines[0].word_timings);
  });

  it("drops unusable word timings instead of trusting them", () => {
    const parsed = parseDialogueLines([
      {
        character_id: "lin",
        text: "别出声",
        start_time: 1.0,
        word_timings: [
          { text: "backwards", start: 2.0, end: 1.0 },
          { text: "no-times" },
          { text: "ok", start: 1.0, end: 1.4 },
        ],
      },
    ]);
    expect(parsed?.[0].word_timings).toEqual([{ text: "ok", start: 1.0, end: 1.4 }]);
  });

  it("serializes without the key when a line has no word timings", () => {
    const [line] = serializeDialogueLines([
      { character_id: "lin", text: "就是这里", start_time: null, emotion: null },
    ]);
    expect("word_timings" in line).toBe(false);
  });

  it("exposes a stable content key", () => {
    expect(DIALOGUE_LINES_CONTENT_KEY).toBe("dialogue_lines");
  });
});
