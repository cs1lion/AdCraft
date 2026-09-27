/**
 * The per-line dialogue contract, mirrored from
 * apps/api/app/services/dialogue/voice_cast_lines.py.
 *
 * The web half only needs the LIMITS and the parse/plan rules the editor
 * validates against — it never synthesizes. Keeping the numbers here (rather
 * than importing them) is deliberate: the frontend must fail the same way as
 * the payload builder without depending on Python at build time, and the
 * contract check pins the two together.
 */

export const MAX_DIALOGUE_LINES = 40;
export const MAX_LINE_CHARS = 400;
export const MAX_LINE_EMOTION_CHARS = 64;

/** One line as authored (before the executor's validation). */
export interface DialogueLineInput {
  id: string;
  text: string;
  emotion?: string;
}

export interface LineSynthesisPlan {
  entries: { lineId: string; needsSynthesis: boolean }[];
  toSynthesize: string[];
}

/** Which lines would be re-synthesized (a line whose take exists is reused). */
export function planLineSynthesis(
  lines: readonly DialogueLineInput[],
  options: { cacheDir: string; fileExists?: (path: string) => boolean; regenerateIds?: readonly string[] },
): LineSynthesisPlan {
  const exists = options.fileExists ?? (() => true);
  const forced = new Set((options.regenerateIds ?? []).map((id) => id.trim()));
  const entries = lines.map((line) => {
    const path = `${options.cacheDir}/${normalizeId(line.id)}__${contentKey(line)}.mp3`;
    const cached = exists(path);
    return { lineId: line.id, needsSynthesis: !cached || forced.has(line.id.trim()) };
  });
  return { entries, toSynthesize: entries.filter((entry) => entry.needsSynthesis).map((e) => e.lineId) };
}

/** Lines the payload builder would keep (ids/text/emotion rules, same shape). */
export function parseDialogueLines(raw: unknown): DialogueLineInput[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const kept: DialogueLineInput[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const record = entry as Record<string, unknown>;
    const id = String(record.id ?? record.line_id ?? "").trim();
    const text = String(record.text ?? "").trim();
    const emotion = String(record.emotion ?? "").trim();
    if (!id || !text || seen.has(id)) continue;
    seen.add(id);
    kept.push({ id, text, emotion });
  }
  return kept.slice(0, MAX_DIALOGUE_LINES);
}

function contentKey(line: DialogueLineInput): string {
  // Same digest surface as the Python side (order + separators matter); the
  // editor only uses it to NAME a cache path, never to compare takes.
  const seed = `${line.id}\u0000${line.text}\u0000${line.emotion ?? ""}`;
  let hash = 0;
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) | 0;
  }
  return Math.abs(hash).toString(16).padStart(12, "0").slice(0, 12);
}

function normalizeId(id: string): string {
  return id.replace(/[^A-Za-z0-9_-]/g, "_") || "line";
}
