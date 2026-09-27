/**
 * Audio bed configuration contract (voice-cast unified mode).
 *
 * The node's ``structured_content.audio_bed`` block is freeform on the wire;
 * this module is the single place that parses it into a typed draft,
 * serializes the draft back (dropping empty rows the backend would reject
 * or silently ignore), and validates it against the StepAudio 3 Gen rules
 * the backend enforces (see app/tools/step_audio_gen.py):
 * - at least one script entry;
 * - a speaker-tagged script requires a role with that name;
 * - a role needs BOTH name and description (or neither).
 *
 * Keeping validation here means the editor and the node executor fail on
 * the same rules — no "the UI let me save it but the node rejected it".
 */

export type AudioBedResponseFormat = "mp3" | "wav" | "flac" | "opus" | "pcm";

export const AUDIO_BED_RESPONSE_FORMATS: readonly AudioBedResponseFormat[] = [
  "mp3",
  "wav",
  "flac",
  "opus",
  "pcm",
];

export interface AudioBedRole {
  name: string;
  description: string;
  /**
   * Optional link to a scene-3d character id. The StepAudio 3 Gen wire
   * contract has no such field (the provider payload builder drops it), so
   * it costs nothing at the provider — but it is what lets the dialogue-
   * driven chain map bed speakers onto scene characters when the author
   * names roles with display names (林澈) instead of ids (char_a).
   * Optional: minimal bed literals (tests, defaults) omit it.
   */
  character_id?: string;
}

export interface AudioBedScript {
  /** Empty string marks a [sfx/ambience/bgm] entry (no speaker). */
  speaker: string;
  text: string;
  /**
   * Per-line performance direction (V0.2 §14.7 表演层): "这一句是哭着的".
   * Sent to the provider as its documented ``(emotion)`` annotation, so it
   * must stay one short phrase — the same limit the payload builder enforces.
   */
  emotion: string;
}

/** Longest per-line emotion annotation (mirrors STEP_AUDIO_GEN_MAX_EMOTION_CHARS). */
export const AUDIO_BED_MAX_EMOTION_CHARS = 64;

export interface AudioBedConfig {
  roles: AudioBedRole[];
  scripts: AudioBedScript[];
  instruction: string;
  response_format: AudioBedResponseFormat;
}

export const AUDIO_BED_DEFAULT_FORMAT: AudioBedResponseFormat = "mp3";

/** Key under node structured_content carrying the bed block. */
export const AUDIO_BED_CONTENT_KEY = "audio_bed";

export function emptyAudioBedConfig(): AudioBedConfig {
  return {
    roles: [],
    scripts: [{ speaker: "", text: "", emotion: "" }],
    instruction: "",
    response_format: AUDIO_BED_DEFAULT_FORMAT,
  };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/**
 * Parse a freeform audio_bed block into a typed draft. Unknown keys are
 * dropped; malformed rows are skipped (the editor shows a clean slate rather
 * than crashing on a half-written block).
 */
export function parseAudioBedConfig(raw: unknown): AudioBedConfig | null {
  const record = asRecord(raw);
  if (!record) return null;
  const roles: AudioBedRole[] = [];
  if (Array.isArray(record.roles)) {
    for (const entry of record.roles) {
      const role = asRecord(entry);
      if (!role) continue;
      roles.push({
        name: asString(role.name),
        description: asString(role.description),
        character_id: asString(role.character_id),
      });
    }
  }
  const scripts: AudioBedScript[] = [];
  if (Array.isArray(record.scripts)) {
    for (const entry of record.scripts) {
      const script = asRecord(entry);
      if (!script) continue;
      scripts.push({
        speaker: asString(script.speaker),
        text: asString(script.text),
        emotion: asString(script.emotion),
      });
    }
  }
  const format = asString(record.response_format);
  return {
    roles,
    scripts: scripts.length > 0 ? scripts : [{ speaker: "", text: "", emotion: "" }],
    instruction: asString(record.instruction),
    response_format: AUDIO_BED_RESPONSE_FORMATS.includes(format as AudioBedResponseFormat)
      ? (format as AudioBedResponseFormat)
      : AUDIO_BED_DEFAULT_FORMAT,
  };
}

/**
 * Serialize the draft for structured_content: empty rows are dropped, the
 * response format is normalized, and empty collections are omitted so a
 * text-only bed (instruction + [bgm] script) stays minimal.
 */
export function serializeAudioBedConfig(config: AudioBedConfig): Record<string, unknown> {
  const roles = config.roles
    .map((role): AudioBedRole => ({
      name: role.name.trim(),
      description: role.description.trim(),
      // Local orchestration key: empty means "no link" and is omitted below.
      character_id: (role.character_id ?? "").trim(),
    }))
    .filter((role) => role.name && role.description);
  const scripts = config.scripts
    .map((script) => ({
      speaker: script.speaker.trim(),
      text: script.text.trim(),
      // ``?? ""`` because the node block is freeform: a payload written
      // before per-line emotion existed has no such key, and re-saving it
      // must not crash on a missing optional field.
      emotion: (script.emotion ?? "").trim(),
    }))
    .filter((script) => script.text)
    // A line that needs no direction keeps the payload minimal: the provider
    // reads an empty annotation as noise, not as silence.
    .map((script) => {
      const entry: Record<string, string> = {};
      if (script.speaker) entry.speaker = script.speaker;
      entry.text = script.text;
      if (script.emotion) entry.emotion = script.emotion;
      return entry;
    });
  const payload: Record<string, unknown> = {};
  if (roles.length > 0) {
    payload.roles = roles.map((role) =>
      role.character_id ? role : { name: role.name, description: role.description },
    );
  }
  if (scripts.length > 0) payload.scripts = scripts;
  const instruction = config.instruction.trim();
  if (instruction) payload.instruction = instruction;
  payload.response_format = config.response_format;
  return payload;
}

export interface AudioBedIssue {
  code: string;
  message: string;
}

/** Validate the draft against the backend's rules (save gate + display). */
export function validateAudioBedConfig(config: AudioBedConfig): AudioBedIssue[] {
  const issues: AudioBedIssue[] = [];
  const scripts = config.scripts.filter((script) => script.text.trim());
  if (scripts.length === 0) {
    issues.push({
      code: "audio_bed_scripts_required",
      message: "至少需要一条脚本（台词或 [音效/环境音/BGM] 描述）。",
    });
    return issues;
  }
  const roles = config.roles.filter((role) => role.name.trim() || role.description.trim());
  const roleNames = new Set(
    roles.map((role) => role.name.trim()).filter((name) => name.length > 0),
  );
  const completeRoles = new Set(
    roles
      .filter((role) => role.name.trim() && role.description.trim())
      .map((role) => role.name.trim()),
  );
  for (const role of roles) {
    if (role.name.trim() && !role.description.trim()) {
      issues.push({
        code: "audio_bed_role_incomplete",
        message: `角色「${role.name.trim()}」缺少音色描述。`,
      });
    }
    if (!role.name.trim() && role.description.trim()) {
      issues.push({
        code: "audio_bed_role_incomplete",
        message: "有音色描述但缺少角色名称。",
      });
    }
  }
  for (const script of scripts) {
    const speaker = script.speaker.trim();
    const emotion = (script.emotion ?? "").trim();
    if (emotion) {
      if (emotion.length > AUDIO_BED_MAX_EMOTION_CHARS) {
        issues.push({
          code: "audio_bed_emotion_too_long",
          message: `情绪标注超过 ${AUDIO_BED_MAX_EMOTION_CHARS} 个字符：它会被拼进台词，写成一句短语（如"压低声音"）。`,
        });
      }
      if (/[()\n\r\t]/.test(emotion)) {
        issues.push({
          code: "audio_bed_emotion_unbalanced",
          message: "情绪标注不能含括号或换行： provider 把它读作 (情绪) 注释，括号会提前收尾。",
        });
      }
    }
    if (emotion && script.text.trimStart().startsWith("(")) {
      issues.push({
        code: "audio_bed_emotion_ambiguous",
        message: "这一行文本已经以 ( 开头——它自己就是注释；再填情绪会被读两遍。去掉其中一个。",
      });
    }
    if (!speaker) continue;
    if (!roleNames.has(speaker)) {
      issues.push({
        code: "audio_bed_unknown_speaker",
        message: `台词指定了说话人「${speaker}」，但角色表中没有该名称。`,
      });
    } else if (!completeRoles.has(speaker)) {
      issues.push({
        code: "audio_bed_role_incomplete",
        message: `说话人「${speaker}」的音色描述还不完整。`,
      });
    }
  }
  // Duplicate role names would make speaker resolution ambiguous.
  const seen = new Set<string>();
  for (const role of roles) {
    const name = role.name.trim();
    if (!name) continue;
    if (seen.has(name)) {
      issues.push({
        code: "audio_bed_duplicate_role",
        message: `角色名称「${name}」重复。`,
      });
    }
    seen.add(name);
  }
  return issues;
}

/** Rough per-element budget telemetry shown in the editor (chars, not promises). */
export function audioBedCharBudget(config: AudioBedConfig): {
  scriptsChars: number;
  scriptsLimit: number;
  rolesChars: number;
  rolesLimit: number;
  instructionChars: number;
  instructionLimit: number;
} {
  // The annotation rides inside the text, so it counts toward the same budget.
  const scriptsChars = config.scripts.reduce(
    (total, script) =>
      total + script.text.length + (script.emotion ? script.emotion.length + 3 : 0),
    0,
  );
  const rolesChars = config.roles.reduce(
    (total, role) => total + role.name.length + role.description.length,
    0,
  );
  return {
    scriptsChars,
    scriptsLimit: 1000,
    rolesChars,
    rolesLimit: 500,
    instructionChars: config.instruction.length,
    instructionLimit: 500,
  };
}
