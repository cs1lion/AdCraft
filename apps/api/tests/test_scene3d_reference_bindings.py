"""A reference bound to a previs node must be visible, not silently dropped.

``Scene3DNodeExecutor`` renders a SceneScript through Blender.  Unlike a video
node it has no input slot for a reference image, so an image bound to it is
delivered and then ignored: ``__call__`` reads
``_scene_script_from_node`` and ``_scene_description_text`` and nothing else.

The rose canvas made that concrete.  Six previs nodes existed, all six had zero
incoming bindings, and the ``scene_asset_id`` / ``character_asset_id`` /
``prop_asset_id`` fields that SceneScript carries to answer "which asset is
this element from" were null on every one of them.

These tests pin two things: the delivered references are *described* in the
node's structured content (so the edge can be shown and audited), and the
asset id is carried onto the SceneScript element it matches -- but only where
that statement is true rather than a guess.
"""

from __future__ import annotations

import types

from app.schemas.scene_script import SceneScriptRoot
from app.services.agent_canvas_node_execution import (
    _apply_scene3d_reference_bindings,
    _scene3d_reference_bindings,
)
from app.services.v2_provider_reference_input_delivery import (
    V2DeliveredProviderReference,
)


def _reference(
    *,
    asset_id: str,
    semantic_role: str | None,
    binding_id: str = "binding_x",
    display_order: int = 0,
    media_type: str = "image",
) -> V2DeliveredProviderReference:
    return V2DeliveredProviderReference.model_construct(
        asset_id=asset_id,
        version_id=f"version_{asset_id}",
        binding_id=binding_id,
        semantic_role=semantic_role,
        source_semantic_role=semantic_role,
        display_order=display_order,
        media_type=media_type,
        mime_type="image/png",
        provider_input_type="image_url",
        provider_input_value="https://example.invalid/x.png",
        source="public_url",
    )


def _context(**overrides):
    fields = {
        "node": None,
        "delivered_references": (),
        "input_manifest": None,
        "optional_input_omissions": (),
        "model_resolution": None,
    }
    fields.update(overrides)
    return types.SimpleNamespace(**fields)


def _script(environment=5, characters=1, props=3) -> SceneScriptRoot:
    return SceneScriptRoot(
        scene={
            "name": "probe",
            "environment": "outdoor",
            "lighting": "warm",
            "duration": 4.0,
            "frame_rate": 24,
        },
        characters=[
            {
                "id": "her",
                "type": "lowpoly_human",
                "keyframes": [{"frame": 0, "position": [0, 0, 0], "rotation_y": 0}],
            }
            for _ in range(characters)
        ],
        environment=[
            {"id": f"env_{i}", "type": "floor", "position": [i, 0, 0], "scale": 1.0}
            for i in range(environment)
        ],
        props=[
            {"id": f"prop_{i}", "type": "cup", "position": [i, 0, 0], "scale": 1.0}
            for i in range(props)
        ],
        cameras=[
            {
                "id": "cam_main",
                "shot_type": "wide",
                "keyframes": [
                    {"frame": 0, "position": [0, 2, 8], "look_at": [0, 1, 0]}
                ],
            }
        ],
        shots=[{"id": "shot1", "camera": "cam_main", "start_frame": 0, "end_frame": 95}],
    )


def test_no_delivered_references_means_no_binding_record() -> None:
    assert _scene3d_reference_bindings(_context()) == []


def test_delivered_references_are_described_not_dropped() -> None:
    context = _context(
        delivered_references=(
            _reference(asset_id="asset_scene", semantic_role="scene_reference"),
            _reference(
                asset_id="asset_her",
                semantic_role="character_reference",
                display_order=1,
                binding_id="binding_y",
            ),
        )
    )

    described = _scene3d_reference_bindings(context)

    assert [item["semantic_role"] for item in described] == [
        "scene_reference",
        "character_reference",
    ]
    assert described[0]["asset_id"] == "asset_scene"
    assert described[0]["asset_version_id"] == "version_asset_scene"
    assert described[0]["recorded_on"] == "scene_asset_id"
    assert described[1]["recorded_on"] == "character_asset_id"


def test_unique_scene_and_character_are_stamped_onto_the_script() -> None:
    script = _script(environment=1, characters=1)
    references = _scene3d_reference_bindings(
        _context(
            delivered_references=(
                _reference(asset_id="asset_scene", semantic_role="scene_reference"),
                _reference(asset_id="asset_her", semantic_role="character_reference"),
            )
        )
    )

    stamped = _apply_scene3d_reference_bindings(script, references, generated=True)

    assert stamped.environment[0].scene_asset_id == "asset_scene"
    assert stamped.characters[0].character_asset_id == "asset_her"


def test_ambiguous_collection_is_left_rather_than_guessed() -> None:
    """Four props and one prop reference cannot say which prop it came from."""

    script = _script(props=4)
    references = _scene3d_reference_bindings(
        _context(
            delivered_references=(
                _reference(asset_id="asset_prop", semantic_role="prop_reference"),
            )
        )
    )

    stamped = _apply_scene3d_reference_bindings(script, references, generated=True)

    assert [item.prop_asset_id for item in stamped.props] == [None, None, None, None]
    # The reference is still published, so it never looks like it was honoured.
    assert references[0]["semantic_role"] == "prop_reference"


def test_a_stored_script_is_never_rewritten_in_place() -> None:
    """``generated=False`` means the node already owns the script."""

    script = _script()
    original = script.characters[0].model_dump()
    references = _scene3d_reference_bindings(
        _context(
            delivered_references=(
                _reference(asset_id="asset_her", semantic_role="character_reference"),
            )
        )
    )

    returned = _apply_scene3d_reference_bindings(script, references, generated=False)

    assert returned is script
    assert script.characters[0].model_dump() == original


def test_an_existing_binding_is_NOT_overwritten() -> None:
    script = _script()
    script.characters[0].character_asset_id = "asset_primary"
    references = _scene3d_reference_bindings(
        _context(
            delivered_references=(
                _reference(asset_id="asset_her", semantic_role="character_reference"),
            )
        )
    )

    stamped = _apply_scene3d_reference_bindings(script, references, generated=True)

    assert stamped.characters[0].character_asset_id == "asset_primary"
