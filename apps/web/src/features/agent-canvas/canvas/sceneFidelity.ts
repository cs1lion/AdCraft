/**
 * Scene fidelity tiers (V3 ④ LOD 阶梯), frontend mirror of
 * ``apps/api/app/services/scene3d/scene_fidelity.py``.
 *
 * A white-model object may carry a coarse tier that says "this one is a
 * stand-in". The preview renders the tier instead of the full asset
 * geometry: ``rough`` collapses to a single primitive, ``standard`` keeps
 * the real geometry, and ``detailed`` is the tier the camera-cue suggests
 * promoting when an object sits in the active shot's view cone.
 *
 * The tier is a display decision only — it never rewrites the SceneScript,
 * so the gate and the Blender converter keep seeing the authored geometry.
 */

export const LOD_TIERS = ["rough", "standard", "detailed"] as const;

export type LodTier = (typeof LOD_TIERS)[number];

/** Tolerant read of an optional tier field (absent -> standard). */
export function resolveLodTier(raw: unknown): LodTier {
  if (raw === "rough" || raw === "standard" || raw === "detailed") {
    return raw;
  }
  return "standard";
}

/** The object's tier when it is declared, otherwise the default. */
export function objectLodTier(
  object: { lod_tier?: unknown } | null | undefined,
): LodTier {
  return object ? resolveLodTier(object.lod_tier) : "standard";
}
