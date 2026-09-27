/**
 * Active-dialogue lookup for the 3D speech overlay.
 *
 * Pure on purpose: the viewport renders, the inspector shows timings, and
 * the subtitle track publishes cues — all three must agree on WHICH line is
 * being spoken at a given frame, so the rule lives here once.
 *
 * A line is active from its start (inclusive) to the next same-speaker
 * line's start (exclusive) — NOT to its own end. The bed carries no per-line
 * end times (the provider returns none), so an estimated end would drift
 * the overlay away from the subtitle cues; "until the next line" is exact
 * regardless of what an estimate would have said.
 */

export interface ActiveDialogueLineInput {
  character_id: string;
  text: string;
  start_time: number;
  end_time?: number | null;
}

/**
 * The line `characterId` is speaking at `frame` (converted with `frameRate`),
 * or null when the speaker is silent at that moment.
 */
export function activeDialogueLineAtFrame(
  lines: readonly ActiveDialogueLineInput[],
  characterId: string,
  frame: number,
  frameRate: number,
): ActiveDialogueLineInput | null {
  if (lines.length === 0 || frameRate <= 0 || !Number.isFinite(frameRate)) return null;
  const seconds = frame / frameRate;
  const own = lines
    .filter((line) => line.character_id === characterId && Number.isFinite(line.start_time))
    .sort((a, b) => a.start_time - b.start_time);
  for (let index = 0; index < own.length; index += 1) {
    const line = own[index];
    if (seconds < line.start_time) return null; // before the first line
    const next = own[index + 1];
    if (!next || seconds < next.start_time) return line;
  }
  return null;
}
