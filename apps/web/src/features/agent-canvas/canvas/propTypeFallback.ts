/**
 * Nearest-primitive fallback table for unknown prop / environment types.
 *
 * When the LLM (white-model generator) or the director command bar emits an
 * object type the schema does not know ("vending machine", "locker", "neon
 * sign"), the backend gate degrades the type to the closest known primitive
 * instead of rejecting the batch. This module is the frontend mirror of
 * ``app/services/scene3d/prop_type_fallback.py`` — the same table drives
 * both the optimistic preview (the editor's ``addPropObject`` /
 * ``addEnvironmentObject`` path) and the backend's authoritative gate.
 *
 * The table is intentionally small and conservative: an entry is added only
 * when the primitive geometry is a reasonable white-model stand-in.
 */

import type {
  EnvironmentTypeName,
  PropTypeName,
} from "../../../types/scene-script.generated";

// ---------------------------------------------------------------------------
// Fallback tables (mirrors the backend prop_type_fallback.py)
// ---------------------------------------------------------------------------

/** Unknown prop type → nearest known PropType. Keys are lowercase free-form. */
const PROP_FALLBACKS: Record<string, PropTypeName> = {
  // table / seating
  desk: "rect_table",
  desk_table: "rect_table",
  coffee_table: "rect_table",
  side_table: "rect_table",
  dining_table: "round_table",
  bench: "stool",
  seat: "chair",
  throne: "chair",
  sofa: "rect_table",
  couch: "rect_table",
  footstool: "stool",
  // box / storage
  locker: "box",
  cabinet: "box",
  chest: "box",
  crate_stack: "crate",
  pallet: "crate",
  storage_bin: "box",
  vending_machine: "box",
  fridge: "box",
  refrigerator: "box",
  atm: "box",
  // light
  street_lamp: "lantern",
  torch: "lantern",
  candle: "lantern",
  fireplace: "lantern",
  neon_sign: "lantern",
  light_fixture: "lantern",
  spotlight: "lantern",
  // vessel
  mug: "cup",
  glass: "cup",
  bowl: "cup",
  pot: "cup",
  kettle: "cup",
  bottle: "vase",
  jug: "vase",
  flask: "vase",
  // weapon / tool
  sword: "weapon",
  dagger: "weapon",
  axe: "weapon",
  hammer: "weapon",
  tool: "weapon",
  club: "weapon",
  // book / scroll
  notebook: "book",
  tablet: "book",
  codex: "book",
  pamphlet: "book",
  leaflet: "scroll",
  flag: "scroll",
  banner: "scroll",
  // misc
  pottery: "vase",
  urn: "vase",
  planter: "vase",
  pedestal: "box",
  plinth: "box",
  block: "box",
};

/** Unknown environment type → nearest known EnvironmentType. */
const ENVIRONMENT_FALLBACKS: Record<string, EnvironmentTypeName> = {
  // wall / structure
  column: "pillar",
  post: "pillar",
  support: "pillar",
  pole: "pillar",
  // roof
  canopy: "flat_roof",
  awning: "flat_roof",
  carport: "flat_roof",
  // door / window
  gate: "door",
  entry: "door",
  opening: "door",
  glass_window: "window",
  panel: "window",
  // stairs / platform
  ramp: "stairs",
  escalator: "stairs",
  steps: "stairs",
  podium: "platform",
  stage: "platform",
  podium_block: "platform",
  // tree / rock / fence
  bush: "tree",
  shrub: "tree",
  sapling: "tree",
  palm: "tree",
  boulder: "rock",
  stone: "rock",
  boulder_field: "rock",
  hedge: "fence",
  railing: "fence",
  barrier: "fence",
  guard_rail: "fence",
  // ground / floor
  flooring: "floor",
  carpet: "floor",
  mat: "floor",
  terrain: "ground",
  path: "ground",
  road: "ground",
};

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Fold a free-form type word onto a table key.
 *
 * The table is keyed ``vending_machine`` but an LLM writes "Vending
 * Machine", "vending-machine" and "vending  machine" for the same object;
 * all of them must land on the same key, or this module's own documented
 * example silently fails to resolve. Mirrors ``_normalize_type_key`` in
 * ``app/services/scene3d/prop_type_fallback.py`` — keep the two in lockstep.
 */
function normalizeTypeKey(unknownType: string): string {
  let folded = unknownType.trim().toLowerCase();
  for (const separator of ["-", " ", "\t", "\n", "/", "\\"]) {
    folded = folded.split(separator).join("_");
  }
  while (folded.includes("__")) {
    folded = folded.split("__").join("_");
  }
  return folded;
}

/**
 * Resolve an unknown prop type to the nearest known PropType.
 * Returns `undefined` when the type is already known or has no fallback.
 */
export function resolvePropFallback(unknownType: string): PropTypeName | undefined {
  return PROP_FALLBACKS[normalizeTypeKey(unknownType)];
}

/**
 * Resolve an unknown environment type to the nearest known EnvironmentType.
 * Returns `undefined` when the type is already known or has no fallback.
 */
export function resolveEnvironmentFallback(
  unknownType: string,
): EnvironmentTypeName | undefined {
  return ENVIRONMENT_FALLBACKS[normalizeTypeKey(unknownType)];
}

/**
 * A single degradation record for the frontend to surface in a status line.
 */
export interface PropTypeFallbackReport {
  kind: "add_prop" | "add_environment";
  requested: string;
  resolvedTo: PropTypeName | EnvironmentTypeName | null;
  message: string;
}

/**
 * Build a degradation report for a requested (unknown) type.
 * The caller uses this to decide whether to emit an optimistic op or reject.
 */
export function buildFallbackReport(
  kind: "add_prop" | "add_environment",
  requested: string,
): PropTypeFallbackReport {
  if (kind === "add_prop") {
    const resolved = resolvePropFallback(requested);
    return {
      kind,
      requested,
      resolvedTo: resolved ?? null,
      message: resolved
        ? `'${requested}' is not a known prop; using '${resolved}' as stand-in.`
        : `'${requested}' has no known prop fallback; the op was skipped.`,
    };
  }
  const resolved = resolveEnvironmentFallback(requested);
  return {
    kind,
    requested,
    resolvedTo: resolved ?? null,
    message: resolved
      ? `'${requested}' is not a known environment; using '${resolved}' as stand-in.`
      : `'${requested}' has no known environment fallback; the op was skipped.`,
  };
}
