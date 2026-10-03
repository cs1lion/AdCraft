"""Previs clip publishing (ADR 0017): scene-3d shot → canvas video node.

The publisher is the whole "导演台 → 预演参考片段" relationship in one
transaction-shaped run: cut the shot out of the scene-3d node's animatic,
publish the clip plus its keyframes as derived assets, create the canvas
video node (creative role ``scene_3d_previs_clip``) bound back to the
scene-3d node, and record the reverse lineage on the scene-3d node itself.
Every refusal is a named error code — a shot that cannot be published must
say why, not just not appear.
"""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    CanvasBindingCreateRequestV2,
    CanvasBindingSourceNodeV2,
    CanvasNodeCreateRequestV2,
    CanvasNodePatchRequestV2,
    CanvasPositionV2,
    ProjectAssetV2,
)
from app.schemas.agent_canvas_ad_media import PrevisClipContentV2, PrevisClipKeyframeV2
from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.previs_clip_media import extract_keyframes, trim_previs_clip

PREVIS_CLIP_ROLE = "scene_3d_previs_clip"


class _NodesService(Protocol):
    def create(
        self,
        workflow_id: str,
        request: CanvasNodeCreateRequestV2,
        *,
        expected_revision: int | None,
    ) -> Any: ...

    def patch(
        self,
        workflow_id: str,
        node_id: str,
        request: CanvasNodePatchRequestV2,
        *,
        expected_revision: int | None,
    ) -> Any: ...


class _BindingsService(Protocol):
    def create(
        self,
        workflow_id: str,
        request: CanvasBindingCreateRequestV2,
        *,
        expected_revision: int | None,
    ) -> Any: ...


class _AssetsService(Protocol):
    def resolve_asset_path(self, asset_id: str) -> Any: ...

    def publish_generated_bytes(self, *args: Any, **kwargs: Any) -> ProjectAssetV2: ...

    def validate_asset_backed_node(self, asset_id: str, node_type: str) -> None: ...


class _RoleValidationService(Protocol):
    def validate(
        self, *, node_type: str, semantic_role: str, structured_content: dict[str, Any]
    ) -> Any: ...


@dataclass(frozen=True)
class PublishedPrevisClip:
    node: Any
    binding: Any
    clip_asset: ProjectAssetV2
    keyframe_asset_ids: tuple[str, ...]


class PrevisClipPublisher:
    """Cut one SceneScript shot out of a scene-3d animatic onto the canvas."""

    def __init__(
        self,
        *,
        nodes: _NodesService,
        bindings: _BindingsService,
        assets: _AssetsService,
        role_validation: _RoleValidationService,
    ) -> None:
        self._nodes = nodes
        self._bindings = bindings
        self._assets = assets
        self._role_validation = role_validation

    def publish(
        self,
        *,
        workflow_id: str,
        source_node: Any,
        shot_id: str,
        take_id: str | None = None,
    ) -> PublishedPrevisClip:
        if getattr(source_node, "node_type", None) != "scene-3d":
            raise _error(
                "previs_clip_source_not_scene3d",
                "Previs clips publish from scene-3d nodes.",
            )
        structured = dict(getattr(source_node, "structured_content", {}) or {})
        raw_script = structured.get("scene_script")
        if not isinstance(raw_script, dict):
            raise _error(
                "previs_clip_scene_script_missing",
                "The scene-3d node has no SceneScript to cut a shot from.",
            )
        scene_script = SceneScriptRoot.model_validate(raw_script)
        shot = next((item for item in scene_script.shots if item.id == shot_id), None)
        if shot is None:
            raise _error(
                "previs_clip_shot_not_found",
                f"Shot '{shot_id}' is not in this SceneScript.",
                details={"shot_ids": [item.id for item in scene_script.shots]},
            )
        animatic_asset_id = getattr(source_node, "output_asset_id", None)
        if not animatic_asset_id:
            raise _error(
                "scene3d_animatic_missing",
                "Render the scene-3d node first: publishing a shot clip needs its "
                "animatic video (run the node or submit a full render).",
            )
        frame_rate = scene_script.scene.frame_rate
        start_seconds = shot.start_frame / frame_rate
        end_seconds = shot.end_frame / frame_rate
        duration_seconds = end_seconds - start_seconds
        shot_label = (shot.description or "").strip() or shot.id

        source_path = self._assets.resolve_asset_path(animatic_asset_id)
        # Deterministic per (workflow, shot, take): republishing the same shot
        # with the same source bytes lands on the same asset id, so asset-level
        # re-publication is idempotent even though node creation is not.
        publish_node_id = _publish_node_id(workflow_id, shot_id, take_id)
        with tempfile.TemporaryDirectory(prefix="previs_clip_") as tmp_dir:
            clip_path = f"{tmp_dir}/previs_{shot.id}.mp4"
            trimmed = trim_previs_clip(
                source_path,
                clip_path,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
            )
            if not trimmed.success or trimmed.output_path is None:
                raise _error(
                    "previs_clip_trim_failed",
                    trimmed.error or "Previs clip trim failed.",
                )
            clip_bytes = Path(trimmed.output_path).read_bytes()
            keyframes = extract_keyframes(trimmed.output_path, duration_seconds=duration_seconds)

        clip_asset = self._publish_bytes(
            workflow_id,
            publish_node_id=publish_node_id,
            source_node=source_node,
            shot_id=shot.id,
            filename=f"previs-{shot.id}.mp4",
            mime_type="video/mp4",
            content=clip_bytes,
            fingerprint=hashlib.sha256(clip_bytes).hexdigest()[:32],
        )
        keyframe_entries: list[PrevisClipKeyframeV2] = []
        for index, keyframe in enumerate(keyframes):
            asset = self._publish_bytes(
                workflow_id,
                publish_node_id=publish_node_id,
                source_node=source_node,
                shot_id=shot.id,
                filename=f"previs-{shot.id}-kf{index}.jpg",
                mime_type="image/jpeg",
                content=keyframe.png_bytes,
                fingerprint=f"kf{index}-{hashlib.sha256(keyframe.png_bytes).hexdigest()[:24]}",
            )
            keyframe_entries.append(
                PrevisClipKeyframeV2(
                    asset_id=asset.asset_id,
                    asset_version_id=asset.version_id or asset.asset_id,
                    checksum=asset.checksum,
                    offset_seconds=keyframe.offset_seconds,
                    reference_instruction=(
                        f"3D previs keyframe {index + 1} of {len(keyframes)} for this shot; "
                        "follow its composition, camera framing and motion trajectory"
                    ),
                )
            )

        content = PrevisClipContentV2(
            scene_3d_node_id=source_node.node_id,
            scene_3d_node_title=getattr(source_node, "title", "") or "",
            shot_id=shot.id,
            shot_label=shot_label,
            take_id=take_id,
            source_asset_id=str(animatic_asset_id),
            clip_asset_id=clip_asset.asset_id,
            clip_asset_version_id=clip_asset.version_id or clip_asset.asset_id,
            frame_range=(shot.start_frame, shot.end_frame),
            duration_seconds=round(duration_seconds, 3),
            previs_keyframes=tuple(keyframe_entries),
            previs_control_level="video",
        )
        content_dict = content.model_dump(mode="json")
        self._role_validation.validate(
            node_type="video",
            semantic_role=PREVIS_CLIP_ROLE,
            structured_content=content_dict,
        )
        self._assets.validate_asset_backed_node(clip_asset.asset_id, "video")

        source_position = getattr(source_node, "position", None)
        position = (
            CanvasPositionV2(x=source_position.x + 160.0, y=source_position.y + 80.0)
            if source_position is not None
            else CanvasPositionV2(x=0.0, y=0.0)
        )
        node = self._nodes.create(
            workflow_id,
            CanvasNodeCreateRequestV2(
                node_type="video",
                creative_role=PREVIS_CLIP_ROLE,
                role_contract_version="ad-media-role-v2",
                title=f"预演片段 · {shot_label}",
                summary_prompt=None,
                generation_prompt=None,
                structured_content=content_dict,
                model_selection_mode="default",
                model_ref=None,
                parameters={},
                position=position,
                source_asset_id=clip_asset.asset_id,
            ),
            expected_revision=None,
        )
        binding = self._bindings.create(
            workflow_id,
            CanvasBindingCreateRequestV2(
                source=CanvasBindingSourceNodeV2(source_node_id=source_node.node_id),
                target_node_id=node.node_id,
                input_role="video_reference",
                label="预演参考",
            ),
            expected_revision=None,
        )

        published = list(structured.get("published_previs_clips") or [])
        published.append(
            {
                "node_id": node.node_id,
                "shot_id": shot.id,
                "clip_asset_id": clip_asset.asset_id,
                "take_id": take_id,
            }
        )
        self._nodes.patch(
            workflow_id,
            source_node.node_id,
            CanvasNodePatchRequestV2(
                structured_content={**structured, "published_previs_clips": published}
            ),
            expected_revision=None,
        )
        return PublishedPrevisClip(
            node=node,
            binding=binding,
            clip_asset=clip_asset,
            keyframe_asset_ids=tuple(entry.asset_id for entry in keyframe_entries),
        )

    def _publish_bytes(
        self,
        workflow_id: str,
        *,
        publish_node_id: str,
        source_node: Any,
        shot_id: str,
        filename: str,
        mime_type: str,
        content: bytes,
        fingerprint: str,
    ) -> ProjectAssetV2:
        return self._assets.publish_generated_bytes(
            workflow_id,
            node_id=publish_node_id,
            execution_id=f"previs-publish-{uuid.uuid4().hex}",
            filename=filename,
            mime_type=mime_type,
            content=content,
            fingerprint=fingerprint,
            source_type="derived",
            source_semantic_role=PREVIS_CLIP_ROLE,
            publication_metadata={
                "previs_clip_source": {
                    "scene_3d_node_id": source_node.node_id,
                    "shot_id": shot_id,
                }
            },
        )


def _publish_node_id(workflow_id: str, shot_id: str, take_id: str | None) -> str:
    seed = f"{workflow_id}:{shot_id}:{take_id or ''}"
    return f"previs_{hashlib.sha256(seed.encode()).hexdigest()[:20]}"


def _error(code: str, message: str, *, details: dict[str, Any] | None = None) -> V2PersistenceError:
    error = V2PersistenceError(code, message, stage="previs_clip_publisher")
    if details:
        error.details = details
    return error
