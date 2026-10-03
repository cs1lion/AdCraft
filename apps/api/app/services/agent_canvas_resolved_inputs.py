"""Compile persisted Agent Canvas bindings into immutable run inputs."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from app.schemas.agent_canvas import (
    AgentCanvasWorkflowV2,
    OmittedOptionalInputV2,
    ResolvedInputSnapshotV2,
    ResolvedMediaBindingInputV2,
    ResolvedMediaInputSnapshotV2,
    ResolvedNodeInputManifestV2,
    ResolvedTextBindingInputV2,
    ResolvedTextInputSnapshotV2,
    StorageAccessDescriptorV2,
)
from app.schemas.agent_canvas_runtime import NodeRunBindingSnapshotV2, ResolvedModelExecutionV1
from app.persistence.errors import V2PersistenceError
from app.services.agent_canvas_bindings import AgentCanvasBindingService
from app.services.agent_canvas_reference_composition import compose_reference_budget

if TYPE_CHECKING:
    from app.services.agent_canvas_world_setting_context import (
        WorldSettingContextResolverV2,
    )


class AgentCanvasResolvedInputCompiler:
    """Resolve only persisted target bindings in canonical order."""

    def __init__(
        self,
        bindings: AgentCanvasBindingService,
        *,
        world_settings: "WorldSettingContextResolverV2 | None" = None,
    ) -> None:
        self._bindings = bindings
        self._world_settings = world_settings

    def compile(
        self,
        *,
        workflow_id: str,
        target_node_id: str,
        execution_id: str,
        node_run_id: str,
        run_intent_snapshot_id: str | None = None,
        binding_snapshots: tuple[NodeRunBindingSnapshotV2, ...] | None = None,
    ) -> ResolvedNodeInputManifestV2:
        workflow = self._bindings.get_workflow(workflow_id)
        _require_explicit_document_source_bindings(workflow, target_node_id)
        if binding_snapshots is None:
            text_snapshot = self._bindings.capture_prompt_context_snapshot(
                workflow_id,
                target_node_id,
                node_run_id=node_run_id,
            )
            media_snapshots, omitted = self._bindings.resolve_media_input_snapshots(
                workflow_id,
                target_node_id,
            )
        else:
            frozen = self._bindings.resolve_frozen_run_input_resolution(
                workflow_id,
                target_node_id,
                binding_snapshots,
                node_run_id=node_run_id,
            )
            text_snapshot = self._bindings.get_prompt_context_snapshot_for_run(
                workflow_id,
                target_node_id,
                node_run_id=node_run_id,
            )
            media_snapshots = tuple(
                item for item in frozen.inputs if isinstance(item, ResolvedMediaInputSnapshotV2)
            )
            omitted = frozen.optional_omissions
        resolved_text_inputs = tuple(
            ResolvedTextBindingInputV2(
                binding_id=item.binding_id or _missing_binding_id(item.source_node_id),
                source_node_id=item.source_node_id,
                source_node_revision=item.source_node_revision,
                input_role=item.input_role,
                display_order=item.display_order,
                snapshot_id=text_snapshot.snapshot_id,
                document_kind=item.document_kind,
                content_digest=item.content_hash,
                content=item.content,
                source_semantic_role=item.source_semantic_role,
                binding_metadata=item.binding_metadata,
                source_structured_content=item.source_structured_content,
            )
            for item in text_snapshot.inputs
        )
        text_inputs: list[ResolvedTextBindingInputV2] = []
        world_setting_inputs = []
        omitted_list = list(omitted)
        for item in resolved_text_inputs:
            if item.source_semantic_role != "world_setting":
                text_inputs.append(item)
                continue
            if self._world_settings is None:
                error = V2PersistenceError(
                    "world_setting_context_unavailable",
                    "World Setting context resolution is unavailable.",
                    stage="agent_canvas_resolved_input_compiler",
                )
                raise error
            try:
                world_setting_inputs.append(
                    self._world_settings.resolve_for_run(
                        workflow_id=workflow_id,
                        source=item,
                    )
                )
            except V2PersistenceError:
                raise
        if len(world_setting_inputs) > 1:
            raise V2PersistenceError(
                "world_setting_binding_ambiguous",
                "A target Node cannot resolve more than one World Setting Binding.",
                stage="agent_canvas_resolved_input_compiler",
            )
        media_inputs = tuple(
            ResolvedMediaBindingInputV2(
                binding_id=item.binding_id or _missing_binding_id(item.asset_id),
                source_kind=item.source_kind,
                source_node_id=item.source_node_id,
                source_node_revision=item.source_node_revision,
                input_role=item.input_role,
                source_semantic_role=item.source_semantic_role,
                binding_metadata=item.binding_metadata,
                source_structured_content=item.source_structured_content,
                display_order=item.display_order,
                asset_id=item.asset_id,
                asset_version_id=item.asset_version_id,
                media_type=item.media_type,
                checksum=item.asset_checksum,
            )
            for item in media_snapshots
        )
        omitted_inputs = tuple(
            OmittedOptionalInputV2(
                binding_id=item["binding_id"],
                source_node_id=item.get("source_node_id"),
                reason_code=item["reason"],
            )
            for item in omitted_list
        )
        created_at = (
            text_snapshot.created_at
            if text_snapshot.inputs
            else self._bindings.get_workflow(workflow_id)
            .nodes[_node_index(workflow, target_node_id)]
            .updated_at
        )
        identity = {
            "workflow_id": workflow_id,
            "execution_id": execution_id,
            "node_run_id": node_run_id,
            "target_node_id": target_node_id,
            "workflow_revision": workflow.revision,
            "text_inputs": [item.model_dump(mode="json") for item in text_inputs],
            "world_setting_inputs": [item.model_dump(mode="json") for item in world_setting_inputs],
            "media_inputs": [item.model_dump(mode="json") for item in media_inputs],
            "omitted_optional_inputs": [item.model_dump(mode="json") for item in omitted_inputs],
            "run_intent_snapshot_id": run_intent_snapshot_id,
        }
        manifest_digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ResolvedNodeInputManifestV2(
            manifest_id=f"input_manifest_{manifest_digest[:24]}",
            created_at=created_at,
            manifest_digest=manifest_digest,
            delivered_asset_version_ids=tuple(
                item.asset_version_id for item in media_inputs if item.asset_version_id is not None
            ),
            **identity,
        )

    def materialize_inputs(
        self,
        manifest: ResolvedNodeInputManifestV2,
    ) -> tuple[ResolvedInputSnapshotV2, ...]:
        text_inputs = tuple(
            ResolvedTextInputSnapshotV2(
                source_node_id=item.source_node_id,
                source_node_revision=item.source_node_revision,
                document_kind=item.document_kind,
                content=item.content,
                content_hash=item.content_digest,
                binding_id=item.binding_id,
                input_role=item.input_role,
                display_order=item.display_order,
            )
            for item in manifest.text_inputs
        )
        media_inputs = []
        for item in manifest.media_inputs:
            asset = self._bindings.resolve_asset_version(
                item.asset_id,
                item.asset_version_id,
            )
            media_inputs.append(
                ResolvedMediaInputSnapshotV2(
                    source_kind=item.source_kind,
                    source_node_id=item.source_node_id,
                    source_node_revision=item.source_node_revision,
                    binding_kind=item.input_role,
                    source_semantic_role=item.source_semantic_role,
                    binding_metadata=item.binding_metadata,
                    source_structured_content=item.source_structured_content,
                    asset_id=item.asset_id,
                    asset_version_id=item.asset_version_id,
                    media_type=item.media_type,
                    asset_checksum=item.checksum,
                    access_descriptor=StorageAccessDescriptorV2(
                        asset_id=item.asset_id,
                        media_url=asset.media_url or "",
                        checksum=item.checksum,
                    ),
                    binding_id=item.binding_id,
                    input_role=item.input_role,
                    display_order=item.display_order,
                )
            )
        return tuple(
            sorted(
                (*text_inputs, *media_inputs),
                key=lambda item: (item.display_order, item.binding_id or ""),
            )
        )


def substitute_previs_keyframes_for_videoless_models(
    manifest: ResolvedNodeInputManifestV2,
    model_resolution: ResolvedModelExecutionV1,
) -> ResolvedNodeInputManifestV2:
    """Swap un-deliverable previs video references for their published keyframes.

    ADR 0017 closing ADR 0005 §4a's loop for models like ``agnes-video-2.5-flash``
    whose catalog row declares ``video: 0``: without this, binding a previs clip
    to a shot under flash degrades to a log warning and the reference simply
    vanishes — the connection exists on the canvas but contributes nothing.
    The clip's published keyframes ride the image channel instead, the original
    video binding is recorded as
    ``previs_clip_keyframes_substituted`` (queryable, never silent), and each
    substituted image carries ``previs_control_level: "images_only"`` in its
    binding metadata. Models that accept video references are untouched.

    Runs *before* ``apply_provider_reference_limits``: the keyframes enter the
    image budget like any other image reference, so composition policy (grid
    grounding first, design references, then these) still decides what survives.
    Keyframe count is pre-trimmed to the model's image headroom so the limits
    pass is not left to silently drop the tail.
    """

    metadata = model_resolution.capability_metadata
    raw_limits = metadata.get("reference_limits")
    limits = raw_limits if isinstance(raw_limits, dict) else {}
    video_limit = limits.get("video")
    image_limit = limits.get("image")
    if not (isinstance(video_limit, int) and not isinstance(video_limit, bool) and video_limit == 0):
        return manifest
    image_headroom: int | None = (
        image_limit
        if isinstance(image_limit, int) and not isinstance(image_limit, bool) and image_limit > 0
        else None
    )
    if image_headroom is None:
        return manifest

    substituted: list[tuple[ResolvedMediaBindingInputV2, list[dict[str, object]]]] = []
    omitted = list(manifest.omitted_optional_inputs)
    kept: list[ResolvedMediaBindingInputV2] = []
    for item in manifest.media_inputs:
        keyframes = _previs_keyframes(item)
        if item.media_type != "video" or keyframes is None:
            kept.append(item)
            continue
        omitted.append(
            OmittedOptionalInputV2(
                binding_id=item.binding_id,
                source_node_id=item.source_node_id,
                reason_code="previs_clip_keyframes_substituted",
                asset_id=item.asset_id,
                asset_version_id=item.asset_version_id,
                media_type=item.media_type,
                checksum=item.checksum,
            )
        )
        substituted.append((item, keyframes))
    if not substituted:
        return manifest

    image_count = sum(1 for item in kept if item.media_type == "image")
    headroom = max(image_headroom - image_count, 0)
    for item, keyframes in substituted:
        if not headroom:
            continue
        for index, keyframe in enumerate(_even_subset(keyframes, headroom)):
            metadata_kv: dict[str, object] = {
                "previs_control_level": "images_only",
                "derived_from_binding_id": item.binding_id,
                "derived_from_asset_id": item.asset_id,
                "offset_seconds": keyframe.get("offset_seconds"),
            }
            instruction = keyframe.get("reference_instruction")
            if isinstance(instruction, str) and instruction.strip():
                metadata_kv["reference_instruction"] = instruction.strip()
            kept.append(
                ResolvedMediaBindingInputV2(
                    binding_id=f"{item.binding_id}:previs_kf{index}",
                    # image_asset snapshots must not carry a source node (the
                    # resolved-snapshot validator rejects that pairing): the
                    # clip's lineage rides in binding_metadata instead.
                    source_kind="image_asset",
                    source_node_id=None,
                    source_node_revision=None,
                    input_role="image_reference",
                    source_semantic_role=item.source_semantic_role,
                    binding_metadata=metadata_kv,
                    source_structured_content=item.source_structured_content,
                    display_order=item.display_order,
                    asset_id=str(keyframe["asset_id"]),
                    asset_version_id=(
                        str(keyframe["asset_version_id"])
                        if keyframe.get("asset_version_id")
                        else None
                    ),
                    media_type="image",
                    checksum=str(keyframe.get("checksum") or keyframe["asset_id"]),
                )
            )
            headroom -= 1
    return manifest.model_copy(
        update={
            "media_inputs": tuple(kept),
            "omitted_optional_inputs": tuple(omitted),
        }
    )


def _previs_keyframes(item: ResolvedMediaBindingInputV2) -> list[dict[str, object]] | None:
    """The published keyframes of a previs clip binding, or None if it isn't one.

    Both marks are required: the source semantic role alone would also catch
    role-bearing nodes whose content predates keyframe publication, and an
    empty keyframe list would silently turn the reference into nothing.
    """

    if item.source_semantic_role != "scene_3d_previs_clip":
        return None
    content = item.source_structured_content
    if not isinstance(content, dict) or content.get("previs_clip_version") != "previs-clip-v1":
        return None
    raw = content.get("previs_keyframes")
    if not isinstance(raw, list) or not raw:
        return None
    valid = [
        entry
        for entry in raw
        if isinstance(entry, dict)
        and isinstance(entry.get("asset_id"), str)
        and entry["asset_id"]
    ]
    return valid or None


def _even_subset(entries: list[dict[str, object]], count: int) -> list[dict[str, object]]:
    """Evenly sample ``count`` keyframes, preserving their temporal order."""

    if len(entries) <= count:
        return list(entries)
    picked_indexes = sorted(
        {round(index * (len(entries) - 1) / (count - 1)) for index in range(count)}
    )
    return [entries[index] for index in picked_indexes]


def apply_provider_reference_limits(
    manifest: ResolvedNodeInputManifestV2,
    model_resolution: ResolvedModelExecutionV1,
) -> ResolvedNodeInputManifestV2:
    """Freeze a deterministic reference subset for one resolved provider model.

    Which references survive is not a race in persisted binding order.  The
    character and scene *design* references are admitted first, up to roughly two
    fifths of the image budget, then the rough-model *camera-motion* references,
    then everything else (see ``agent_canvas_reference_composition``).  A design
    reference past that share is withheld and recorded rather than let back in
    through the common pool, because two fifths that can be exceeded is not a
    ratio.  Walking in that order is what keeps a finished look and a motion
    authority in the same request: a first-come walk delivers whichever the
    operator happened to bind first, and a shot can only ever be as finished as
    the references it was actually sent.
    """

    metadata = model_resolution.capability_metadata
    raw_limits = metadata.get("reference_limits")
    limits = raw_limits if isinstance(raw_limits, dict) else {}
    raw_total_limit = metadata.get("max_references")
    total_limit = (
        raw_total_limit
        if isinstance(raw_total_limit, int) and not isinstance(raw_total_limit, bool)
        else None
    )
    typed_limits = {
        media_type: value
        for media_type, value in limits.items()
        if media_type in {"image", "video", "audio"}
        and isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    }
    if total_limit is None and not typed_limits:
        return manifest

    image_limit = typed_limits.get("image")
    composition = compose_reference_budget(manifest.media_inputs, image_limit=image_limit)
    admission = {binding_id: rank for rank, binding_id in enumerate(composition.admission)}
    selected: list[ResolvedMediaBindingInputV2] = []
    omitted = list(manifest.omitted_optional_inputs)
    selected_counts = {"image": 0, "video": 0, "audio": 0}
    already_omitted = {item.binding_id for item in omitted}
    for item in sorted(
        manifest.media_inputs,
        key=lambda candidate: (
            admission.get(candidate.binding_id, len(admission)),
            candidate.display_order,
            candidate.binding_id,
        ),
    ):
        if item.binding_id in composition.withheld:
            # Our own share policy, not the provider's limit: recording it as a
            # provider limit would tell the operator to ask the provider for more
            # slots when the answer is to bind fewer design references.
            if item.binding_id not in already_omitted:
                omitted.append(
                    OmittedOptionalInputV2(
                        binding_id=item.binding_id,
                        source_node_id=item.source_node_id,
                        reason_code="omitted_reference_share",
                        asset_id=item.asset_id,
                        asset_version_id=item.asset_version_id,
                        media_type=item.media_type,
                        checksum=item.checksum,
                    )
                )
            continue
        media_limit = typed_limits.get(item.media_type)
        over_media_limit = (
            media_limit is not None and selected_counts[item.media_type] >= media_limit
        )
        over_total_limit = total_limit is not None and len(selected) >= total_limit
        if over_media_limit or over_total_limit:
            if item.binding_id not in already_omitted:
                omitted.append(
                    OmittedOptionalInputV2(
                        binding_id=item.binding_id,
                        source_node_id=item.source_node_id,
                        reason_code="omitted_provider_reference_limit",
                        asset_id=item.asset_id,
                        asset_version_id=item.asset_version_id,
                        media_type=item.media_type,
                        checksum=item.checksum,
                    )
                )
            continue
        selected.append(item)
        selected_counts[item.media_type] += 1

    updated = manifest.model_copy(
        update={
            "media_inputs": tuple(selected),
            "omitted_optional_inputs": tuple(omitted),
            "delivered_asset_version_ids": tuple(
                item.asset_version_id for item in selected if item.asset_version_id is not None
            ),
        }
    )
    identity = updated.model_dump(
        mode="json",
        exclude={
            "manifest_id",
            "manifest_digest",
            "delivered_asset_version_ids",
            "created_at",
        },
    )
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return updated.model_copy(
        update={
            "manifest_id": f"input_manifest_{digest[:24]}",
            "manifest_digest": digest,
        }
    )


def _missing_binding_id(identity: str) -> str:
    return f"binding_{hashlib.sha256(identity.encode()).hexdigest()[:16]}"


def _require_explicit_document_source_bindings(
    workflow: AgentCanvasWorkflowV2,
    target_node_id: str,
) -> None:
    target = workflow.nodes[_node_index(workflow, target_node_id)]
    required_sources = target.metadata.get("required_agent_document_source_node_ids", ())
    if not isinstance(required_sources, (list, tuple)) or not all(
        isinstance(item, str) and item for item in required_sources
    ):
        return
    bound_sources = {
        binding.source.source_node_id
        for binding in workflow.bindings
        if binding.target_node_id == target_node_id and binding.source.kind == "node_output"
    }
    missing = tuple(source_id for source_id in required_sources if source_id not in bound_sources)
    if missing:
        raise V2PersistenceError(
            "agent_document_binding_required",
            "A required Agent document source has no persisted Canvas Binding.",
            stage="agent_canvas_resolved_input_compiler",
            details={"missing_source_node_ids": list(missing)},
        )


def _node_index(workflow: AgentCanvasWorkflowV2, node_id: str) -> int:
    return next(index for index, node in enumerate(workflow.nodes) if node.node_id == node_id)
