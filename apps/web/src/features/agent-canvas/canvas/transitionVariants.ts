/**
 * Durable transition variants on a scene-3d node (V0.2 §9 局部分叉).
 *
 * The research's exact scenario: Scene 02 → Scene 03 has several legitimate
 * readings (A 连续运动 / B 特写切换 / C 环绕…), and the author should be able
 * to KEEP them side by side — "用户可以直接播放多个版本，而不是反复覆盖同
 * 一个结果". Applying a reading used to overwrite the draft, so the only way
 *  to compare was to remember (or re-derive) what the other one was.
 *
 * A variant is a labelled snapshot of the whole SceneScript at the moment
 * the author said "keep this one". Whole-script (not a patch) on purpose:
 * the readings differ in camera AND character keyframes, and a partial
 * snapshot would silently mix two readings on restore. The doc's own
 * warning — branches explode — is why variants are LOCAL: they hang off the
 * node that owns the transition, and the panel caps how many are worth
 * keeping (see MAX_TRANSITION_VARIANTS).
 *
 * Same tolerant-parse discipline as the dialogue lines: a half-written
 * block must not crash the panel.
 */

/** Key under node structured_content carrying the variants. */
export const TRANSITION_VARIANTS_CONTENT_KEY = "transition_variants";

/**
 * How many variants a node keeps. The research warns that branches explode;
 * the cap is the product's answer, and the panel states it rather than
 * silently dropping the oldest save.
 */
export const MAX_TRANSITION_VARIANTS = 4;

export interface TransitionVariant {
  id: string;
  /** Author-facing label (defaults to 方案 A/B/C…). */
  label: string;
  /** Which reading produced it, when saved from one (else null). */
  proposal_id: string | null;
  /** The whole SceneScript at save time. */
  scene_script: Record<string, unknown>;
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/**
 * Parse a stored variants block. Returns [] when the key is absent or
 * unusable — the panel treats that as "nothing saved yet".
 */
export function parseTransitionVariants(raw: unknown): TransitionVariant[] {
  if (!Array.isArray(raw)) return [];
  const variants: TransitionVariant[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) continue;
    const record = entry as Record<string, unknown>;
    const sceneScript = record.scene_script;
    // A variant without a script cannot be restored; skipping it beats
    // restoring a blank scene over the author's work.
    if (!sceneScript || typeof sceneScript !== "object" || Array.isArray(sceneScript)) continue;
    const label = asString(record.label).trim();
    const proposal = asString(record.proposal_id).trim();
    variants.push({
      id: asString(record.id).trim() || `variant_${variants.length + 1}`,
      label: label || `方案 ${String.fromCharCode(65 + variants.length)}`,
      proposal_id: proposal || null,
      scene_script: sceneScript as Record<string, unknown>,
    });
  }
  return variants;
}

/** Serialize for structured_content (keeps at most the cap, newest last). */
export function serializeTransitionVariants(
  variants: readonly TransitionVariant[],
): TransitionVariant[] {
  return variants.slice(-MAX_TRANSITION_VARIANTS).map((variant) => ({
    id: variant.id,
    label: variant.label,
    proposal_id: variant.proposal_id,
    scene_script: variant.scene_script,
  }));
}

/** The next label in the 方案 A/B/C series, skipping the ones already used. */
export function nextVariantLabel(variants: readonly TransitionVariant[]): string {
  const used = new Set(variants.map((variant) => variant.label));
  for (let index = 0; index < 26; index += 1) {
    const label = `方案 ${String.fromCharCode(65 + index)}`;
    if (!used.has(label)) return label;
  }
  return `方案 ${variants.length + 1}`;
}
