/**
 * Durable dialogue lines on a scene-3d node (the C mode's editing state).
 *
 * The lip-sync panel's lines used to live only in React state: an author who
 * aligned the bed, nudged a start time, then reloaded lost ALL of it — the
 * bed scripts keep speaker+text but not the per-line timing or the
 * speaker->character mapping. This module is the small, honest fix: the
 * lines ride on the node's structured_content like every other piece of
 * authoring state.
 *
 * The parse is deliberately tolerant (a half-written block must not crash
 * the panel) and the serialize keeps the exact shape the lip-sync service
 * consumes.
 */

/** Key under node structured_content carrying the dialogue lines. */
export const DIALOGUE_LINES_CONTENT_KEY = "dialogue_lines";

/** One word's timing, as the forced alignment reports it. */
export interface PersistedWordTiming {
  text: string;
  start: number;
  end: number;
}

export interface PersistedDialogueLine {
  character_id: string;
  text: string;
  /** null = the service estimates from reading speed. */
  start_time: number | null;
  emotion: string | null;
  /**
   * Word-level timings (whisperX): the mouth moves WITH the words instead of
   * on a metronome. Absent when the alignment had none — the service then
   * keeps its syllable fallback.
   */
  word_timings?: PersistedWordTiming[] | null;
}

/** Tolerant parse of one word-timings block (null when unusable). */
function parseWordTimings(raw: unknown): PersistedWordTiming[] | null {
  if (!Array.isArray(raw)) return null;
  const words: PersistedWordTiming[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const word = entry as Record<string, unknown>;
    const start = word.start;
    const end = word.end;
    if (typeof start !== "number" || typeof end !== "number") continue;
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) continue;
    words.push({
      text: typeof word.text === "string" ? word.text : "",
      start,
      end,
    });
  }
  return words.length > 0 ? words : null;
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/**
 * Parse a stored dialogue-lines block. Returns null when the key is absent
 * or unusable — the panel treats that as "nothing persisted yet" rather
 * than as an error.
 */
export function parseDialogueLines(raw: unknown): PersistedDialogueLine[] | null {
  if (!Array.isArray(raw)) return null;
  const lines: PersistedDialogueLine[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) continue;
    const record = entry as Record<string, unknown>;
    const start = record.start_time;
    const line: PersistedDialogueLine = {
      character_id: asString(record.character_id),
      text: asString(record.text),
      start_time:
        typeof start === "number" && Number.isFinite(start) && start >= 0 ? start : null,
      emotion: typeof record.emotion === "string" && record.emotion ? record.emotion : null,
    };
    // Only present when usable: a line without word timings keeps the exact
    // shape the service (and every existing consumer) expects.
    const wordTimings = parseWordTimings(record.word_timings);
    if (wordTimings) line.word_timings = wordTimings;
    lines.push(line);
  }
  return lines;
}
/** Serialize for structured_content: rows without text are dropped. */
export function serializeDialogueLines(
  lines: readonly PersistedDialogueLine[],
): PersistedDialogueLine[] {
  return lines
    .filter((line) => line.text.trim())
    .map((line) => ({
      character_id: line.character_id,
      text: line.text,
      start_time: line.start_time,
      emotion: line.emotion,
      ...(line.word_timings && line.word_timings.length > 0
        ? { word_timings: line.word_timings }
        : {}),
    }));
}

/** Deep-ish equality that skips no-op persistence PATCHes. */
export function dialogueLinesEqual(
  a: readonly PersistedDialogueLine[] | null,
  b: readonly PersistedDialogueLine[] | null,
): boolean {
  if (a === b) return true;
  if (!a || !b || a.length !== b.length) return false;
  return a.every(
    (line, index) =>
      line.character_id === b[index].character_id
      && line.text === b[index].text
      && line.start_time === b[index].start_time
      && line.emotion === b[index].emotion
      && wordTimingsEqual(line.word_timings, b[index].word_timings),
  );
}

/** Deep-enough equality for word-timing blocks (order matters). */
export function wordTimingsEqual(
  a: readonly PersistedWordTiming[] | null | undefined,
  b: readonly PersistedWordTiming[] | null | undefined,
): boolean {
  if (a === b) return true;
  if (!a || !b || a.length !== b.length) return false;
  return a.every(
    (word, index) =>
      word.text === b[index].text
      && word.start === b[index].start
      && word.end === b[index].end,
  );
}
