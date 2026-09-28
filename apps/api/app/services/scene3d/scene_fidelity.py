"""Scene fidelity tiers (V3 ④ LOD 阶梯) — per-object coarseness as ops.

Design (from the V3 plan): every object carries a coarseness tier
(``"rough" | "standard" | "detailed"``). A white model starts at
``rough`` (a single primitive stands in); "refine this table" only raises
that one object's tier. The preview renders the tier, and — by default —
only ``detailed`` objects inside the active shot's camera view cone get the
detailed geometry: "what the camera is looking at is worth the detail".

The backend is deliberately tiny:

- ``LOD_TIER_OPS`` — the canonical op names the LLM / UI may emit
  (``set_lod_tier``). The expansion lives here, not in the tool service, so
  the op never reaches a raw geometry list (ADR 0012: intent in, ops out,
  one expansion point).
- ``resolve_lod_tier`` — tolerant parse of a tier value (unknown values
  degrade to ``standard`` + a warning, mirroring the nearest-primitive
  fallback convention: degrade and report, never silent).
- ``camera_view_candidates`` — which object ids sit inside the active
  camera's view cone at the playhead frame, plus how far they are (near
  objects are worth refining). Pure geometry over the SceneScript; the
  caller decides the policy.
"""

from __future__ import annotations

import math
from typing import Any

from app.schemas.scene_script import SceneScriptRoot

LOD_TIERS: tuple[str, ...] = ("rough", "standard", "detailed")

#: The op name the LLM/UI layer may emit; the only expansion point is here.
LOD_TIER_OP = "set_lod_tier"


class LodTierError(ValueError):
    """Raised when a tier command is malformed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_lod_tier(raw: Any) -> tuple[str, str | None]:
    """Tolerant parse of a tier value.

    Returns ``(tier, warning)``. Known tiers pass through unchanged; anything
    else degrades to ``"standard"`` with a warning that names the input —
    the same degrade-and-report convention as the prop fallback table.
    """
    if raw in LOD_TIERS:
        return raw, None
    return "standard", f"tier '{raw}' is not one of {list(LOD_TIERS)}; using 'standard'"


def expand_set_lod_tier(operation: dict[str, Any]) -> dict[str, Any]:
    """Validate + normalize one ``set_lod_tier`` op into apply-ops form.

    The op records its parameters (kind/id/tier) so the batch stays a
    replayable record, mirroring the director-motion contract.
    """
    tier_raw = operation.get("tier")
    tier, warning = resolve_lod_tier(tier_raw)
    if not operation.get("id") or not operation.get("kind"):
        raise LodTierError(
            "lod_tier_target_missing", "set_lod_tier requires kind and id"
        )
    result: dict[str, Any] = dict(operation)
    result["tier"] = tier
    if warning:
        result["warning"] = warning
    return result


def camera_view_candidates(
    script: SceneScriptRoot,
    *,
    fov_radians: float = math.radians(60.0),
    min_radius: float = 0.5,
) -> list[dict[str, Any]]:
    """Objects inside the active camera's view cone at frame 0 / its pose.

    For each shot we take the camera keyframe at the shot's midpoint; the
    cone test is a dot-product against the look direction with the camera's
    FOV. Results are sorted nearest-first (a near object is the one worth
    refining first). Pure function of the SceneScript — no rendering, no
    assets — so it can run in the gate and in the preview alike.
    """
    candidates: list[dict[str, Any]] = []
    for shot in script.shots:
        camera = next((c for c in script.cameras if c.id == shot.camera), None)
        if camera is None or not camera.keyframes:
            continue
        mid_frame = (shot.start_frame + shot.end_frame) // 2
        pose = camera.keyframes[min(
            len(camera.keyframes) - 1,
            max(
                0,
                min(
                    (
                        i
                        for i, keyframe in enumerate(camera.keyframes)
                        if keyframe.frame >= mid_frame
                    ),
                    default=len(camera.keyframes) - 1,
                ),
            ),
        )]
        position = list(pose.position)
        look_at = list(pose.look_at)
        direction = _normalize([
            look_at[0] - position[0],
            look_at[1] - position[1],
            look_at[2] - position[2],
        ])
        cos_half = math.cos(fov_radians / 2.0)
        for kind, objects in (("prop", script.props), ("environment", script.environment)):
            for obj in objects:
                world = list(obj.position)
                to_obj = [world[0] - position[0], world[1] - position[1], world[2] - position[2]]
                distance = math.sqrt(sum(v * v for v in to_obj))
                if distance < min_radius:
                    continue
                dot = sum(a * b for a, b in zip(direction, to_obj)) / distance
                if dot < cos_half:
                    continue
                candidates.append(
                    {
                        "kind": kind,
                        "id": obj.id,
                        "distance": distance,
                        "shot_id": shot.id,
                    }
                )
        for character in script.characters:
            keyframe = character.keyframes[0]
            world = list(keyframe.position)
            to_obj = [world[0] - position[0], world[1] - position[1], world[2] - position[2]]
            distance = math.sqrt(sum(v * v for v in to_obj))
            if distance < min_radius:
                continue
            dot = sum(a * b for a, b in zip(direction, to_obj)) / distance
            if dot < cos_half:
                continue
            candidates.append(
                {
                    "kind": "character",
                    "id": character.id,
                    "distance": distance,
                    "shot_id": shot.id,
                }
            )
    candidates.sort(key=lambda entry: entry["distance"])
    return candidates


def _normalize(vector: list[float]) -> list[float]:
    length = math.sqrt(sum(v * v for v in vector))
    if length < 1e-9:
        return [0.0, 0.0, 0.0]
    return [v / length for v in vector]
