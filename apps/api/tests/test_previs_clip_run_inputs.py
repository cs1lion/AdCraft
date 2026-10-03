"""Flash degradation channel and run guard for previs clips (ADR 0017).

Two validators live here, and per the mutation discipline each test says
what it locks and watches the input flip red once:

* ``substitute_previs_keyframes_for_videoless_models`` — a video-capable
  model, a non-previs video reference, or a previs clip without published
  keyframes must each leave the manifest untouched; only flash + previs clip
  + keyframes turns one video reference into image references carrying
  ``previs_control_level: "images_only"``.
* ``require_node_runnable`` — a previs clip video node must be refused from
  generation with ``previs_clip_publish_only``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    ResolvedMediaBindingInputV2,
    ResolvedNodeInputManifestV2,
)
from app.schemas.agent_canvas_runtime import ResolvedModelExecutionV1
from app.services.agent_canvas_authoring_validation import require_node_runnable
from app.services.agent_canvas_resolved_inputs import (
    substitute_previs_keyframes_for_videoless_models,
)


def _media_input(
    *,
    binding_id: str,
    media_type: str,
    asset_id: str,
    semantic_role: str | None = None,
    structured: dict | None = None,
) -> ResolvedMediaBindingInputV2:
    return ResolvedMediaBindingInputV2(
        binding_id=binding_id,
        source_kind="node_output",
        source_node_id="node_src",
        input_role="video_reference" if media_type == "video" else "image_reference",
        source_semantic_role=semantic_role,
        binding_metadata={},
        source_structured_content=structured or {},
        display_order=0,
        asset_id=asset_id,
        asset_version_id=f"version_{asset_id}",
        media_type=media_type,  # type: ignore[arg-type]
        checksum="c" * 64,
    )


def _manifest(media_inputs: tuple) -> ResolvedNodeInputManifestV2:
    return ResolvedNodeInputManifestV2(
        manifest_id="manifest_1",
        workflow_id="wf_1",
        execution_id="exec_1",
        node_run_id="run_1",
        target_node_id="node_target",
        workflow_revision=1,
        media_inputs=media_inputs,
        created_at=datetime.now(timezone.utc),
    )


def _resolution(*, video: int | None, image: int | None) -> ResolvedModelExecutionV1:
    limits: dict = {}
    if video is not None:
        limits["video"] = video
    if image is not None:
        limits["image"] = image
    return ResolvedModelExecutionV1(
        model_ref="volcengine_ark:agnes-video-2.5-flash",
        provider_id="volcengine_ark",
        provider_model_id="agnes-video-2.5-flash",
        capability="video",
        provider_protocol="openai_videos",
        credential_revision=1,
        catalog_revision=1,
        capability_metadata={"reference_limits": limits},
    )


def _previs_clip_structured(keyframe_count: int = 5) -> dict:
    return {
        "previs_clip_version": "previs-clip-v1",
        "previs_keyframes": [
            {
                "asset_id": f"asset_kf{i}",
                "asset_version_id": f"version_asset_kf{i}",
                "checksum": "k" * 64,
                "offset_seconds": float(i),
                "reference_instruction": "follow this previs framing",
            }
            for i in range(keyframe_count)
        ],
    }


class TestKeyframeSubstitution:
    def test_flash_previs_clip_becomes_image_references(self) -> None:
        """Locks: flash (video 0) + previs clip + keyframes → images_only channel."""

        manifest = _manifest(
            (
                _media_input(
                    binding_id="b_previs",
                    media_type="video",
                    asset_id="asset_clip",
                    semantic_role="scene_3d_previs_clip",
                    structured=_previs_clip_structured(),
                ),
            )
        )
        result = substitute_previs_keyframes_for_videoless_models(manifest, _resolution(video=0, image=5))
        assert [item.media_type for item in result.media_inputs] == ["image"] * 5
        first = result.media_inputs[0]
        assert first.binding_metadata["previs_control_level"] == "images_only"
        assert first.asset_id == "asset_kf0"
        assert first.input_role == "image_reference"
        # image_asset snapshots must not carry a source node (validator rule).
        assert first.source_node_id is None
        assert first.source_kind == "image_asset"
        omitted = {item.binding_id: item.reason_code for item in result.omitted_optional_inputs}
        assert omitted["b_previs"] == "previs_clip_keyframes_substituted"

    def test_video_capable_model_is_untouched(self) -> None:
        """Mutation: flip the model to video-capable → no substitution (locks the gate)."""

        manifest = _manifest(
            (
                _media_input(
                    binding_id="b_previs",
                    media_type="video",
                    asset_id="asset_clip",
                    semantic_role="scene_3d_previs_clip",
                    structured=_previs_clip_structured(),
                ),
            )
        )
        result = substitute_previs_keyframes_for_videoless_models(manifest, _resolution(video=1, image=5))
        assert result.media_inputs == manifest.media_inputs
        assert result.omitted_optional_inputs == ()

    def test_non_previs_video_reference_is_not_substituted(self) -> None:
        manifest = _manifest(
            (
                _media_input(
                    binding_id="b_video",
                    media_type="video",
                    asset_id="asset_clip",
                    semantic_role="general_video",
                ),
            )
        )
        result = substitute_previs_keyframes_for_videoless_models(manifest, _resolution(video=0, image=5))
        assert result.media_inputs == manifest.media_inputs

    def test_previs_clip_without_keyframes_is_left_for_the_limits_pass(self) -> None:
        """A clip published before keyframes existed contributes nothing — visibly."""

        manifest = _manifest(
            (
                _media_input(
                    binding_id="b_previs",
                    media_type="video",
                    asset_id="asset_clip",
                    semantic_role="scene_3d_previs_clip",
                    structured={"previs_clip_version": "previs-clip-v1"},
                ),
            )
        )
        result = substitute_previs_keyframes_for_videoless_models(manifest, _resolution(video=0, image=5))
        assert result.media_inputs == manifest.media_inputs
        assert result.omitted_optional_inputs == ()

    def test_keyframes_respect_image_headroom(self) -> None:
        manifest = _manifest(
            (
                _media_input(
                    binding_id="b_img",
                    media_type="image",
                    asset_id="asset_board",
                    semantic_role="scene",
                ),
                _media_input(
                    binding_id="b_previs",
                    media_type="video",
                    asset_id="asset_clip",
                    semantic_role="scene_3d_previs_clip",
                    structured=_previs_clip_structured(keyframe_count=5),
                ),
            )
        )
        result = substitute_previs_keyframes_for_videoless_models(manifest, _resolution(video=0, image=3))
        images = [item for item in result.media_inputs if item.media_type == "image"]
        assert len(images) == 3  # 1 bound image + 2 keyframe slots left
        assert {item.asset_id for item in images} == {"asset_board", "asset_kf0", "asset_kf4"}

    def test_unlimited_models_are_untouched(self) -> None:
        manifest = _manifest(
            (
                _media_input(
                    binding_id="b_previs",
                    media_type="video",
                    asset_id="asset_clip",
                    semantic_role="scene_3d_previs_clip",
                    structured=_previs_clip_structured(),
                ),
            )
        )
        resolution = ResolvedModelExecutionV1(
            model_ref="volcengine_ark:agnes-video-2.5",
            provider_id="volcengine_ark",
            provider_model_id="agnes-video-2.5",
            capability="video",
            provider_protocol="openai_videos",
            credential_revision=1,
            catalog_revision=1,
            capability_metadata={},
        )
        result = substitute_previs_keyframes_for_videoless_models(manifest, resolution)
        assert result.media_inputs == manifest.media_inputs


class TestRunGuard:
    def test_previs_clip_node_is_not_generatable(self) -> None:
        node = type(
            "Node",
            (),
            {"execution_mode": "generative", "node_type": "video", "creative_role": "scene_3d_previs_clip"},
        )()
        with pytest.raises(V2PersistenceError) as excinfo:
            require_node_runnable(node)
        assert excinfo.value.code == "previs_clip_publish_only"

    def test_ordinary_video_node_still_runs(self) -> None:
        node = type(
            "Node",
            (),
            {"execution_mode": "generative", "node_type": "video", "creative_role": "storyboard_video"},
        )()
        require_node_runnable(node)

    def test_source_only_still_rejected_first(self) -> None:
        node = type(
            "Node",
            (),
            {"execution_mode": "source_only", "node_type": "video", "creative_role": "scene_3d_previs_clip"},
        )()
        with pytest.raises(V2PersistenceError) as excinfo:
            require_node_runnable(node)
        assert excinfo.value.code == "source_only_node_not_runnable"
