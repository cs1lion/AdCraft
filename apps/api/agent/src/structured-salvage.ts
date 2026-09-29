/**
 * Local salvage for common LLM structured-output breakage.
 *
 * 2026-09-29 live findings that this module exists for:
 *
 * 1. The model echoes prompt context back into the structured answer.  The
 *    chat intent contract (``CompactTurnIntentDecisionV3``,
 *    ``additionalProperties: false``) rejected ``session_exists`` /
 *    ``mentioned_node_ids`` / ``mentioned_image_asset_ids`` as
 *    ``extra_forbidden`` and the run died before a repair could help.  The
 *    fields are context, not answer: prune them and re-validate locally
 *    instead of burning a provider round-trip.
 * 2. The model returns prose-wrapped or trailing-comma JSON.  A balanced-brace
 *    extraction plus a trailing-comma pass parses most of them.
 *
 * Both salvages run BEFORE the repair call: they cost no provider round-trip
 * and no model budget, so a flake that used to kill the turn now just works.
 */

export interface SalvageViolation {
  readonly path?: string | null;
  readonly code?: string | null;
}

/** Prune keys the validator flagged ``extra_forbidden`` (top-level or nested). */
export function salvageExtraFields(
  value: Readonly<Record<string, unknown>>,
  violations: readonly SalvageViolation[],
): Record<string, unknown> | undefined {
  const paths = violations
    .filter((violation) => violation.code === "extra_forbidden")
    .map((violation) => String(violation.path ?? "").replace(/^\$\.?/, ""))
    .filter((path) => path.length > 0);
  if (paths.length === 0) return undefined;

  const clone: Record<string, unknown> = structuredClone(value);
  let pruned = 0;
  for (const path of paths) {
    const segments = path.split(".").filter((segment) => segment.length > 0);
    if (segments.length === 0) continue;
    let cursor: Record<string, unknown> = clone;
    let reachable = true;
    for (let index = 0; index < segments.length - 1; index += 1) {
      const key = segments[index];
      const next = key === undefined ? undefined : cursor[key];
      if (!next || typeof next !== "object" || Array.isArray(next)) {
        reachable = false;
        break;
      }
      cursor = next as Record<string, unknown>;
    }
    if (!reachable) continue;
    const leaf = segments[segments.length - 1];
    if (leaf !== undefined && Object.prototype.hasOwnProperty.call(cursor, leaf)) {
      delete cursor[leaf];
      pruned += 1;
    }
  }
  return pruned > 0 ? clone : undefined;
}

/** Extract and repair the outermost JSON object from raw model text. */
export function salvageJsonObject(raw: string | undefined | null): Record<string, unknown> | undefined {
  if (typeof raw !== "string" || raw.trim().length === 0) return undefined;
  for (const candidate of objectCandidates(raw)) {
    const parsed = parseLooseObject(candidate);
    if (parsed) return parsed;
  }
  return undefined;
}

function objectCandidates(raw: string): string[] {
  const candidates: string[] = [];
  const fenced = raw.match(/```(?:json5?|jsonc)?\s*([\s\S]*?)```/gi);
  if (fenced) {
    for (const block of fenced) {
      candidates.push(block.replace(/```(?:json5?|jsonc)?/gi, "").trim());
    }
  }
  const first = raw.indexOf("{");
  const last = raw.lastIndexOf("}");
  if (first !== -1 && last > first) {
    candidates.push(raw.slice(first, last + 1));
  }
  candidates.push(raw);
  return candidates;
}

function parseLooseObject(text: string): Record<string, unknown> | undefined {
  const trimmed = text.trim();
  if (!trimmed.startsWith("{")) return undefined;
  const variants = [trimmed, trimmed.replace(/,(\s*[}\]])/g, "$1")];
  for (const variant of variants) {
    try {
      const parsed: unknown = JSON.parse(variant);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>;
      }
    } catch {
      // try the next repair variant
    }
  }
  return undefined;
}
