"""Tests for the V3 ④ fidelity tier layer (LOD 阶梯)."""

from __future__ import annotations

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.scene_fidelity import (
    LOD_TIER_OP,
    camera_view_candidates,
    expand_set_lod_tier,
    resolve_lod_tier,
)


def _script() -> SceneScriptRoot:
    return SceneScriptRoot.model_validate(
        {
            "scene": {
                "name": "lod",
                "environment": "indoor",
                "lighting": "neutral",
                "duration": 5,
                "frame_rate": 30,
            },
            "characters": [
                {
                    "id": "char1",
                    "type": "lowpoly_human",
                    "appearance": {"color": "#8B4513", "height": 1.7, "scale": 1.0},
                    "keyframes": [
                        {"frame": 0, "position": [0.0, 1.0, 0.0], "rotation_y": 0.0, "action": "stand"},
                    ],
                }
            ],
            "props": [
                {
                    "id": "table",
                    "type": "round_table",
                    "position": [0.0, 1.0, 2.0],
                    "scale": 1.0,
                    "rotation_y": 0.0,
                }
            ],
            "environment": [
                {
                    "id": "wall1",
                    "type": "wall",
                    "position": [0.0, 0.0, 5.0],
                    "scale": 1.0,
                    "rotation_y": 0.0,
                }
            ],
            "cameras": [
                {
                    "id": "cam1",
                    "shot_type": "wide",
                    "keyframes": [
                        {"frame": 0, "position": [0.0, 1.6, -2.0], "look_at": [0.0, 1.0, 2.0]},
                    ],
                }
            ],
            "shots": [
                {"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 150}
            ],
            "speech_bindings": [],
        }
    )


def test_resolve_lod_tier_passes_known_values() -> None:
    for tier in ("rough", "standard", "detailed"):
        assert resolve_lod_tier(tier) == (tier, None)


def test_resolve_lod_tier_degrades_unknown_with_warning() -> None:
    tier, warning = resolve_lod_tier("ultra")
    assert tier == "standard"
    assert warning is not None and "ultra" in warning


def test_expand_set_lod_tier_requires_target() -> None:
    try:
        expand_set_lod_tier({"op": LOD_TIER_OP, "tier": "detailed"})
        raise AssertionError("expected LodTierError")
    except Exception as exc:
        assert getattr(exc, "code", None) == "lod_tier_target_missing"


def test_expand_set_lod_tier_records_parameters() -> None:
    op = expand_set_lod_tier(
        {"op": LOD_TIER_OP, "kind": "prop", "id": "table", "tier": "detailed"}
    )
    assert op["tier"] == "detailed"
    assert op["kind"] == "prop"
    assert op["id"] == "table"


def test_camera_view_candidates_finds_near_objects_in_cone() -> None:
    candidates = camera_view_candidates(_script())
    ids = {entry["id"] for entry in candidates}
    # The table (in front of the camera) and the character (in the cone) are
    # candidates; the wall at z=5 is 5m ahead but still inside the cone.
    assert "table" in ids
    assert "char1" in ids
    # Nearest-first: the table at distance ~4 beats the wall at ~7.
    distances = {entry["id"]: entry["distance"] for entry in candidates}
    assert distances["table"] < distances["wall1"]


def test_camera_view_candidates_ignores_out_of_cone_objects() -> None:
    script = _script()
    # Move the camera to face the opposite way: the table is now BEHIND it.
    script.cameras[0].keyframes[0].position = [0.0, 1.6, 6.0]
    script.cameras[0].keyframes[0].look_at = [0.0, 1.0, 8.0]
    candidates = camera_view_candidates(script)
    ids = {entry["id"] for entry in candidates}
    assert "table" not in ids
