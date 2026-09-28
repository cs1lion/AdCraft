/**
 * Director takes — a labelled snapshot of the SceneScript for A/B
 * comparison and "go back to that version".
 *
 * A take is the unit the director compares: "use the left one" is a take
 * id, not a re-derivation. The module mirrors the backend data model in
 * ``director_takes.py``: a whole-script snapshot (not a patch) plus the
 * ops diff that produced it, a creator-facing label, and the capture
 * frame. The cap is small and deliberate — takes are for *comparison*,
 * not version control — matching the transition-variants cap.
 *
 * The workbench persists takes on the node under a structured_content
 * key, mirroring the transition-variants pattern.
 */

export const DIRECTOR_TAKES_CONTENT_KEY = "director_takes";

/** How many takes a node keeps (same cap as transition variants). */
export const MAX_DIRECTOR_TAKES = 4;

export interface DirectorTake {
  id: string;
  /** Creator-facing label (defaults to "Take 1", "Take 2", …). */
  label: string;
  /** The full SceneScript JSON at save time. */
  scene_script: Record<string, unknown>;
  /** The ops diff that produced this take (the replayable record). */
  operations: Record<string, unknown>[];
  /** The frame the take was captured at, when meaningful. */
  frame?: number | null;
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/**
 * Tolerant parse of the structured_content block. Returns [] when the key
 * is absent or unusable — the workbench treats that as "no takes saved
 * yet". A take without a scene_script is skipped: restoring a blank scene
 * over the director's work is worse than losing one take.
 */
export function parseDirectorTakes(raw: unknown): DirectorTake[] {
  if (!Array.isArray(raw)) return [];
  const takes: DirectorTake[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) continue;
    const record = entry as Record<string, unknown>;
    const sceneScript = record.scene_script;
    if (!sceneScript || typeof sceneScript !== "object" || Array.isArray(sceneScript)) continue;
    const id = asString(record.id).trim() || `take_${takes.length + 1}`;
    const label = asString(record.label).trim();
    const operationsRaw = record.operations;
    const operations = Array.isArray(operationsRaw)
      ? operationsRaw.filter((op): op is Record<string, unknown> => op !== null && typeof op === "object" && !Array.isArray(op))
      : [];
    const frameRaw = record.frame;
    const frame = typeof frameRaw === "number" && Number.isFinite(frameRaw) ? frameRaw : null;
    takes.push({
      id,
      label: label || `Take ${takes.length + 1}`,
      scene_script: sceneScript as Record<string, unknown>,
      operations,
      frame,
    });
  }
  return takes;
}

/** Serialize for structured_content (keeps at most the cap, newest last). */
export function serializeDirectorTakes(takes: readonly DirectorTake[]): DirectorTake[] {
  return takes.slice(-MAX_DIRECTOR_TAKES).map((take) => ({
    id: take.id,
    label: take.label,
    scene_script: take.scene_script,
    operations: take.operations,
    frame: take.frame ?? null,
  }));
}

/** The next label in the Take 1/2/3… series, skipping the ones already used. */
export function nextTakeLabel(takes: readonly DirectorTake[]): string {
  const used = new Set(takes.map((take) => take.label));
  let index = 1;
  while (used.has(`Take ${index}`)) index += 1;
  return `Take ${index}`;
}
