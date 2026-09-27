import { describe, expect, it } from "vitest";

import { activeDialogueLineAtFrame } from "./activeDialogueLine.ts";

const LINES = [
  { character_id: "char_a", text: "就是这里。", start_time: 0 },
  { character_id: "char_b", text: "（抢话）等一下——", start_time: 2.5 },
  { character_id: "char_a", text: "你跟紧我。", start_time: 5 },
];

describe("activeDialogueLineAtFrame", () => {
  it("returns the line covering the frame for that speaker", () => {
    expect(activeDialogueLineAtFrame(LINES, "char_a", 0, 30)?.text).toBe("就是这里。");
    expect(activeDialogueLineAtFrame(LINES, "char_a", 60, 30)?.text).toBe("就是这里。");
    // The speaker's SECOND line at its start frame.
    expect(activeDialogueLineAtFrame(LINES, "char_a", 150, 30)?.text).toBe("你跟紧我。");
  });

  it("keeps a line active until the NEXT line of the same speaker", () => {
    // char_a's first line runs to 5s (char_b's interjection at 2.5s does not
    // cut it — the overlay tracks each speaker's own thread).
    expect(activeDialogueLineAtFrame(LINES, "char_a", 75, 30)?.start_time).toBe(0);
    expect(activeDialogueLineAtFrame(LINES, "char_a", 149, 30)?.start_time).toBe(0);
  });

  it("returns null before the first line and for other speakers", () => {
    const beforeFirst = [{ character_id: "char_a", text: "晚一点。", start_time: 3 }];
    expect(activeDialogueLineAtFrame(beforeFirst, "char_a", 30, 30)).toBeNull();
    expect(activeDialogueLineAtFrame(LINES, "char_c", 60, 30)).toBeNull();
  });

  it("survives unsorted input and an unusable frame rate", () => {
    const unsorted = [
      { character_id: "char_a", text: "后一句。", start_time: 5 },
      { character_id: "char_a", text: "前一句。", start_time: 0 },
    ];
    expect(activeDialogueLineAtFrame(unsorted, "char_a", 0, 30)?.text).toBe("前一句。");
    expect(activeDialogueLineAtFrame(LINES, "char_a", 0, 0)).toBeNull();
  });

  it("returns null with no lines at all", () => {
    expect(activeDialogueLineAtFrame([], "char_a", 0, 30)).toBeNull();
  });
});
