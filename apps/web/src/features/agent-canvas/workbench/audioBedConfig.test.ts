/**
 * Audio bed config tests (voice-cast unified mode).
 *
 * Locks the parse/serialize round-trip against the freeform node block, the
 * validation rules the backend enforces (so the editor and the executor
 * agree), and the char-budget telemetry. The mutation check removes the
 * speaker-validation branch and fails, proving it binds.
 */

import { describe, expect, it } from "vitest";

import {
  AUDIO_BED_DEFAULT_FORMAT,
  audioBedCharBudget,
  emptyAudioBedConfig,
  parseAudioBedConfig,
  serializeAudioBedConfig,
  validateAudioBedConfig,
  type AudioBedConfig,
} from "./audioBedConfig.ts";

function config(overrides: Partial<AudioBedConfig> = {}): AudioBedConfig {
  return {
    roles: [{ name: "林澈", description: "二十多岁的男性，嗓音低沉冷静", character_id: "" }],
    scripts: [
      { speaker: "", text: "[地下研究所 B2 层，低频电机嗡鸣]", emotion: "" },
      { speaker: "林澈", text: "（压低声音，警惕）就是这里，信号源在墙后面。", emotion: "" },
    ],
    instruction: "废弃地下研究所，悬疑氛围",
    response_format: "mp3",
    ...overrides,
  };
}

describe("parseAudioBedConfig", () => {
  it("parses a well-formed block", () => {
    const parsed = parseAudioBedConfig({
      roles: [{ name: "A", description: "d", character_id: "" }],
      scripts: [{ speaker: "A", text: "hi" }, { text: "[rain]" }],
      instruction: "mood",
      response_format: "wav",
    });
    expect(parsed).toEqual({
      roles: [{ name: "A", description: "d", character_id: "" }],
      scripts: [
        { speaker: "A", text: "hi", emotion: "" },
        { speaker: "", text: "[rain]", emotion: "" },
      ],
      instruction: "mood",
      response_format: "wav",
    });
  });

  it("returns null for non-objects", () => {
    expect(parseAudioBedConfig(null)).toBeNull();
    expect(parseAudioBedConfig("nope")).toBeNull();
    expect(parseAudioBedConfig([1, 2])).toBeNull();
  });

  it("skips malformed rows and normalizes the format", () => {
    const parsed = parseAudioBedConfig({
      roles: ["garbage", { name: "A" }, null],
      scripts: ["garbage", { text: "ok" }],
      response_format: "aiff",
    });
    expect(parsed?.roles).toEqual([{ name: "A", description: "", character_id: "" }]);
    expect(parsed?.scripts).toEqual([{ speaker: "", text: "ok", emotion: "" }]);
    expect(parsed?.response_format).toBe(AUDIO_BED_DEFAULT_FORMAT);
  });

  it("seeds an empty script row when scripts are missing", () => {
    const parsed = parseAudioBedConfig({ instruction: "bgm only" });
    expect(parsed?.scripts).toEqual([{ speaker: "", text: "", emotion: "" }]);
  });
});

describe("serializeAudioBedConfig", () => {
  it("round-trips a clean config", () => {
    const parsed = parseAudioBedConfig(serializeAudioBedConfig(config()));
    expect(parsed).toEqual(config());
  });

  it("drops empty rows and speaker-less keys", () => {
    const payload = serializeAudioBedConfig(
      config({
        roles: [
          { name: "A", description: "d" },
          { name: "", description: "" },
          { name: "B", description: "" }, // incomplete: dropped, not sent
        ],
        scripts: [
          { speaker: "A", text: "hi" },
          { speaker: "", text: "   " }, // empty: dropped
          { speaker: "", text: "[rain]" },
        ],
      }),
    );
    expect(payload.roles).toEqual([{ name: "A", description: "d" }]);
    expect(payload.scripts).toEqual([
      { speaker: "A", text: "hi" },
      { text: "[rain]" },
    ]);
  });

  it("omits empty collections and keeps the format", () => {
    const payload = serializeAudioBedConfig(emptyAudioBedConfig());
    expect(payload).toEqual({ response_format: "mp3" });
    expect(
      serializeAudioBedConfig(config({ response_format: "flac" })).response_format,
    ).toBe("flac");
  });
});

describe("validateAudioBedConfig", () => {
  it("accepts a well-formed config", () => {
    expect(validateAudioBedConfig(config())).toEqual([]);
  });

  it("requires at least one script and short-circuits", () => {
    const issues = validateAudioBedConfig(config({ scripts: [{ speaker: "", text: "" }] }));
    expect(issues).toHaveLength(1);
    expect(issues[0].code).toBe("audio_bed_scripts_required");
  });

  it("rejects a speaker with no matching role", () => {
    // Mutation-locked: removing this rule would let the executor's backend
    // 400 become a user-visible surprise after a save.
    const issues = validateAudioBedConfig(
      config({ scripts: [{ speaker: "Ghost", text: "有人吗？", emotion: "" }] }),
    );
    expect(issues.map((issue) => issue.code)).toContain("audio_bed_unknown_speaker");
  });

  it("rejects incomplete roles", () => {
    const issues = validateAudioBedConfig(
      config({ roles: [{ name: "A", description: "", character_id: "" }] }),
    );
    expect(issues.map((issue) => issue.code)).toContain("audio_bed_role_incomplete");
  });

  it("rejects duplicate role names", () => {
    const issues = validateAudioBedConfig(
      config({
        roles: [
          { name: "A", description: "one" },
          { name: "A", description: "two" },
        ],
      }),
    );
    expect(issues.map((issue) => issue.code)).toContain("audio_bed_duplicate_role");
  });

  it("accepts an instruction-only bed with a [bgm] script and no roles", () => {
    const bed = config({
      roles: [],
      scripts: [{ speaker: "", text: "[温暖的钢琴渐强 BGM]" }],
      instruction: "日落海边",
    });
    expect(validateAudioBedConfig(bed)).toEqual([]);
  });
});

describe("audioBedCharBudget", () => {
  it("counts script/role/instruction characters against documented limits", () => {
    const budget = audioBedCharBudget(config());
    expect(budget.scriptsChars).toBe(
      "[地下研究所 B2 层，低频电机嗡鸣]".length
        + "（压低声音，警惕）就是这里，信号源在墙后面。".length,
    );
    expect(budget.scriptsLimit).toBe(1000);
    expect(budget.rolesChars).toBe("林澈".length + "二十多岁的男性，嗓音低沉冷静".length);
    expect(budget.rolesLimit).toBe(500);
    expect(budget.instructionChars).toBe("废弃地下研究所，悬疑氛围".length);
    expect(budget.instructionLimit).toBe(500);
  });
});


describe("per-line emotion (V0.2 §14.7 表演层)", () => {
  it("parses the emotion off the wire", () => {
    const parsed = parseAudioBedConfig({
      scripts: [{ speaker: "A", text: "跟紧我", emotion: "压低声音" }],
      roles: [{ name: "A", description: "d" }],
    });
    expect(parsed?.scripts[0].emotion).toBe("压低声音");
  });

  it("round-trips an emotion through parse and serialize", () => {
    const payload = serializeAudioBedConfig(
      config({
        scripts: [{ speaker: "林澈", text: "跟紧我", emotion: "压低声音" }],
      }),
    );
    expect(payload.scripts).toEqual([
      { speaker: "林澈", text: "跟紧我", emotion: "压低声音" },
    ]);
    expect(parseAudioBedConfig(payload)?.scripts[0].emotion).toBe("压低声音");
  });

  it("keeps a line with no direction minimal (no empty emotion key)", () => {
    const payload = serializeAudioBedConfig(
      config({ scripts: [{ speaker: "林澈", text: "跟紧我", emotion: "  " }] }),
    );
    expect(payload.scripts).toEqual([{ speaker: "林澈", text: "跟紧我" }]);
  });

  it("counts the annotation toward the provider's script budget", () => {
    const budget = audioBedCharBudget(
      config({ scripts: [{ speaker: "", text: "abcd", emotion: "xy" }] }),
    );
    // The annotation rides INSIDE the text the provider reads.
    expect(budget.scriptsChars).toBe("abcd".length + "xy".length + 3);
  });

  it("refuses an emotion the provider would misread (parens / newlines)", () => {
    for (const emotion of ["a)b", "two\nlines"]) {
      const issues = validateAudioBedConfig(
        config({ scripts: [{ speaker: "林澈", text: "x", emotion }] }),
      );
      expect(issues.map((issue) => issue.code)).toContain("audio_bed_emotion_unbalanced");
    }
  });

  it("refuses an emotion on a line that already annotates itself", () => {
    const issues = validateAudioBedConfig(
      config({ scripts: [{ speaker: "林澈", text: "(低声) 跟紧我", emotion: "sad" }] }),
    );
    expect(issues.map((issue) => issue.code)).toContain("audio_bed_emotion_ambiguous");
  });

  it("bounds the emotion so a prompt cannot hide inside one line", () => {
    const issues = validateAudioBedConfig(
      config({ scripts: [{ speaker: "林澈", text: "x", emotion: "x".repeat(65) }] }),
    );
    expect(issues.map((issue) => issue.code)).toContain("audio_bed_emotion_too_long");
  });

  it("leaves a full-width parenthesised line alone (the author's own style)", () => {
    // 全角括号不是 provider 的注释语法；别把它当成歧义来报。
    const issues = validateAudioBedConfig(
      config({ scripts: [{ speaker: "林澈", text: "（低声）跟紧我", emotion: "sad" }] }),
    );
    expect(issues).toEqual([]);
  });
});
