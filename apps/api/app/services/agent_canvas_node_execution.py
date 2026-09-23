"""Node-type dispatch boundary for Agent Canvas runs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Any, Protocol

from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_runtime import (
    AgentCanvasScriptOutput,
    AgentCanvasTextOutput,
    AgentRunCompletedPayload,
    AgentRunContext,
)
from app.schemas.agent_canvas import (
    CanvasNodeV2,
    ResolvedInputSnapshotV2,
    ResolvedMediaInputSnapshotV2,
    ResolvedNodeInputManifestV2,
    ResolvedTextInputSnapshotV2,
)
from app.schemas.agent_canvas_ad_media import (
    AdReferenceBundleV2,
    CompiledProviderPromptV2,
)
from app.schemas.agent_canvas_errors import ActionableFailureV1
from app.schemas.agent_canvas_runtime import (
    EffectiveMediaParameterSnapshotV2,
    ResolvedModelExecutionV1,
    ResolvedModelExecutionV2,
)
from app.schemas.workflow_v2 import V2ProviderResult
from app.schemas.seedance_inputs import (
    SeedanceDeliveredMediaInputV1,
    SeedanceInputManifestAuditV1,
    SeedanceInputManifestV1,
    StoryboardGridGroundingPlanV1,
)
from app.schemas.agent_canvas_world_setting import WorldSettingContextEnvelopeV2
from app.services.agent_canvas_media_output_gate import (
    inspect_media_output,
    media_output_gate_failure,
    media_output_identity,
)
from app.services.agent_canvas_seedance_inputs import AgentCanvasSeedanceInputCompiler
from app.services.agent_canvas_execution_mode import (
    CanvasExecutionModeV2,
    CanvasSemanticExtractionModeV2,
)
from app.services.agent_canvas_storyboard_grounding import (
    GroundingPlanError,
    build_storyboard_grid_grounding_plan,
)
from app.services.agent_canvas_grounding_roles import canonical_storyboard_reference_role
from app.services.durable_pi_run import DurablePiRunService
from app.services.agent_operation_policy import AgentRunRequestFactory
from app.services.agent_run_context_registry import validate_video_agent_operation_context
from app.services.pi_agent_runtime_client import PiAgentRuntimeClient
from app.services.v2_provider_reference_input_delivery import (
    V2DeliveredProviderReference,
    V2ReferenceInputDeliveryFailure,
    V2ProviderReferenceDeliveryError,
    V2ProviderReferenceInputDeliveryService,
)
from app.services.agent_canvas_role_reference_policy import (
    AgentCanvasRoleReferencePolicyService,
)
from app.services.agent_canvas_authoring_validation import require_node_runnable
from app.tools.mock_media_fixtures import (
    MockMediaFixtureError,
    deterministic_mock_media_bytes,
)
from app.tools.seedance_adapter import VolcengineSeedanceAdapter
from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.blender_converter import keyframe_render_frames
from app.services.scene3d.blender_renderer import (
    get_blender_capability,
    render_scene_script,
)
from app.services.scene3d.encoder import encode_png_sequence
from app.services.scene3d.keyframes import rendered_frame_files
from app.services.scene3d.previs_trajectory import previs_trajectory
from app.services.scene3d.scene_script_generator import (
    SceneScriptGenerationError,
    SceneScriptGenerator,
)
from app.services.scene3d.tts_engine_factory import (
    create_tts_engine_from_settings,
    tts_provider_ids,
)


@dataclass(frozen=True, slots=True)
class GeneratedMediaPayload:
    content: bytes
    mime_type: str
    filename: str
    metadata: dict[str, object] = field(default_factory=dict)


def _deadline_cap(timeout_seconds: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)


@dataclass(frozen=True, slots=True)
class NodeExecutionContext:
    execution_id: str
    node: CanvasNodeV2
    inputs: tuple[ResolvedInputSnapshotV2 | object, ...]
    # Revision observed when this admission preparation began.  A run may
    # intentionally execute its immutable accepted snapshot after an
    # authoring edit that happened before preparation; edits that happen
    # during or after preparation must still be fenced.
    authoring_revision_observed: int | None = None
    model_id: str | None = None
    provider_id: str | None = None
    model_resolution: ResolvedModelExecutionV1 | None = None
    compiled_prompt: CompiledProviderPromptV2 | None = None
    reference_bundle: AdReferenceBundleV2 | None = None
    effective_parameters: EffectiveMediaParameterSnapshotV2 | None = None
    seedance_manifest: SeedanceInputManifestV1 | None = None
    seedance_input_audit: SeedanceInputManifestAuditV1 | None = None
    delivered_references: tuple[V2DeliveredProviderReference, ...] = ()
    input_manifest: ResolvedNodeInputManifestV2 | None = None
    optional_input_omissions: tuple[dict[str, str], ...] = ()
    world_setting: WorldSettingContextEnvelopeV2 | None = None
    execution_mode: CanvasExecutionModeV2 = "agent_assisted"
    semantic_extraction: CanvasSemanticExtractionModeV2 = "agent"


@dataclass(frozen=True, slots=True)
class NodeExecutionOutcome:
    structured_content: dict[str, object] | None = None
    media: GeneratedMediaPayload | None = None
    provider_task_id: str | None = None
    remote_task_id: str | None = None
    provider: str | None = None
    result_descriptor: dict[str, object] | None = None
    prompt_metadata: dict[str, object] | None = None
    submission_intent_id: str | None = None


NodeExecutor = Callable[[NodeExecutionContext], NodeExecutionOutcome]


def generated_asset_publication_metadata(
    context: NodeExecutionContext,
) -> dict[str, object]:
    """Project bounded immutable execution provenance into asset metadata."""

    prompt = (
        context.compiled_prompt.prompt
        if context.compiled_prompt is not None
        else _saved_prompt(context)
    )
    metadata: dict[str, object] = {
        "node_run_id": (
            context.input_manifest.node_run_id if context.input_manifest is not None else None
        ),
        "provider": context.provider_id,
        "model_id": context.model_id,
        "model_resolution": (
            context.model_resolution.model_dump(mode="json")
            if context.model_resolution is not None
            else None
        ),
        "prompt_digest": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "input_manifest_id": (
            context.input_manifest.manifest_id if context.input_manifest is not None else None
        ),
        "node_run_snapshot_id": (
            context.input_manifest.run_intent_snapshot_id
            if context.input_manifest is not None
            else None
        ),
        "compiled_prompt_digest": (
            context.compiled_prompt.prompt_digest if context.compiled_prompt is not None else None
        ),
        "prompt_registry_ref": (
            context.compiled_prompt.prompt_registry_ref
            if context.compiled_prompt is not None
            else None
        ),
        "prompt_registry_digest": (
            context.compiled_prompt.prompt_registry_digest
            if context.compiled_prompt is not None
            else None
        ),
        "source_asset_ids": (
            [item.asset_id for item in context.input_manifest.media_inputs]
            if context.input_manifest is not None
            else []
        ),
        "source_asset_version_ids": (
            list(context.input_manifest.delivered_asset_version_ids)
            if context.input_manifest is not None
            else []
        ),
        "requested_parameters": (
            context.effective_parameters.requested
            if context.effective_parameters is not None
            else context.node.parameters
        ),
        "effective_parameters": (
            context.effective_parameters.effective
            if context.effective_parameters is not None
            else context.node.parameters
        ),
        "parameter_compilation_snapshot_id": (
            context.effective_parameters.parameter_compilation_snapshot_id
            if context.effective_parameters is not None
            else None
        ),
        "normalizations": (
            [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in context.effective_parameters.normalizations
            ]
            if context.effective_parameters is not None
            else []
        ),
        "execution_mode": context.execution_mode,
        "semantic_extraction": context.semantic_extraction,
    }
    if context.world_setting is not None:
        metadata["world_setting_context"] = {
            "source_node_id": context.world_setting.source_node_id,
            "source_node_revision": context.world_setting.source_node_revision,
            "source_content_digest": context.world_setting.source_content_digest,
            "source_core_digest": context.world_setting.source_core_digest,
            "target_audience": context.world_setting.target_audience,
            "compiler_id": context.world_setting.compiler_id,
            "compiler_digest": context.world_setting.compiler_digest,
            "context_digest": context.world_setting.context_digest,
        }
    audit = context.seedance_input_audit
    if audit is not None:
        metadata.update(
            {
                "requested_duration_seconds": audit.requested_duration_seconds,
                "effective_duration_seconds": audit.effective_duration_seconds,
                "resolution": audit.resolution,
                "aspect_ratio": audit.aspect_ratio,
                "generate_audio": audit.generate_audio,
                "normalizations": list(audit.normalizations),
            }
        )
    elif context.node.parameters:
        for key in (
            "requested_duration_seconds",
            "effective_duration_seconds",
            "duration_seconds",
            "resolution",
            "aspect_ratio",
            "width",
            "height",
        ):
            if key in context.node.parameters:
                metadata[key] = context.node.parameters[key]
    if context.node.node_type == "video":
        audio_intent = {
            key: context.node.structured_content[key]
            for key in (
                "dialogue",
                "voice_style",
                "environment_sound",
                "action_effects",
                "background_music",
            )
            if key in context.node.structured_content
        }
        if audio_intent:
            metadata["audio_intent"] = audio_intent
    if context.node.creative_role == "character":
        metadata.update(
            {
                "character_asset_kind": context.node.structured_content.get("character_asset_kind"),
                "reference_rendering_mode": context.node.structured_content.get(
                    "reference_rendering_mode"
                ),
                "negative_boundary_digest": (
                    hashlib.sha256(
                        context.compiled_prompt.negative_prompt.encode("utf-8")
                    ).hexdigest()
                    if context.compiled_prompt is not None
                    else None
                ),
            }
        )
    if context.seedance_input_audit is not None:
        grounding_audit = context.seedance_input_audit.grounding_audit
        if grounding_audit is not None:
            metadata["storyboard_grid_grounding"] = grounding_audit.model_dump(mode="json")
    return {key: value for key, value in metadata.items() if value is not None}


class _MinimalProviderExecutor(Protocol):
    def execute_minimal(
        self,
        *,
        workflow_id: str,
        slot_type: str,
        media_type: str,
        provider_payload: dict[str, Any],
    ) -> V2ProviderResult: ...


class _AgentCanvasSeedanceExecutor(Protocol):
    def execute_agent_canvas_seedance_video(
        self,
        *,
        workflow_id: str,
        node_id: str,
        manifest: SeedanceInputManifestV1,
        audit: SeedanceInputManifestAuditV1,
    ) -> V2ProviderResult: ...


class ScriptNodeExecutor:
    """Execute one saved Script draft through the isolated Pi Script Writer."""

    def __init__(self, durable_runner: DurablePiRunService, *, timeout_seconds: float) -> None:
        self._durable_runner = durable_runner
        self._timeout_seconds = timeout_seconds

    def __call__(self, context: NodeExecutionContext) -> NodeExecutionOutcome:
        run_context = AgentRunContext(
            operation="execute_canvas_script",
            user_input=_saved_prompt(context),
            workflow_id=context.node.workflow_id,
            world_setting=context.world_setting,
            target=None,
            input_payload={"resolved_inputs": [_json_input(item) for item in context.inputs]},
        )
        validate_video_agent_operation_context("execute_canvas_script", run_context)
        request = AgentRunRequestFactory().build(
            run_id="candidate_agent_run",
            request_id="candidate_agent_request",
            agent_name="video_agent",
            operation="execute_canvas_script",
            deadline_cap=_deadline_cap(self._timeout_seconds),
            model_ref=_frozen_text_model_ref(context),
            context=run_context,
            contract_name="AgentCanvasScriptOutput",
            contract_schema=AgentCanvasScriptOutput.model_json_schema(),
            audit_metadata={"tool_mode": "structured_only"},
        )
        result = self._durable_runner.run(
            request,
            identity_fields={
                "workflow_id": context.node.workflow_id,
                "execution_id": context.execution_id,
                "node_id": context.node.node_id,
                "node_revision": context.node.revision,
                "agent_name": "video_agent",
                "operation": "execute_canvas_script",
            },
            model_ref=context.model_resolution.model_ref,
        )
        completed = AgentRunCompletedPayload.model_validate(result.terminal_payload)
        content = completed.value.get("content")
        if not isinstance(content, str) or not content.strip():
            raise _error(
                "script_provider_output_invalid",
                "Script Writer output did not include content.",
            )
        return NodeExecutionOutcome(structured_content=dict(completed.value))


class TextNodeExecutor:
    """Execute one saved Text draft through the bounded Quick Media Agent."""

    def __init__(self, durable_runner: DurablePiRunService, *, timeout_seconds: float) -> None:
        self._durable_runner = durable_runner
        self._timeout_seconds = timeout_seconds

    def __call__(self, context: NodeExecutionContext) -> NodeExecutionOutcome:
        run_context = AgentRunContext(
            operation="execute_canvas_text",
            user_input=_saved_prompt(context),
            workflow_id=context.node.workflow_id,
            world_setting=context.world_setting,
            target=None,
            input_payload={"resolved_inputs": [_json_input(item) for item in context.inputs]},
        )
        validate_video_agent_operation_context("execute_canvas_text", run_context)
        request = AgentRunRequestFactory().build(
            run_id="candidate_agent_run",
            request_id="candidate_agent_request",
            agent_name="video_agent",
            operation="execute_canvas_text",
            deadline_cap=_deadline_cap(self._timeout_seconds),
            model_ref=_frozen_text_model_ref(context),
            context=run_context,
            contract_name="AgentCanvasTextOutput",
            contract_schema=AgentCanvasTextOutput.model_json_schema(),
            audit_metadata={"tool_mode": "structured_only"},
        )
        result = self._durable_runner.run(
            request,
            identity_fields={
                "workflow_id": context.node.workflow_id,
                "execution_id": context.execution_id,
                "node_id": context.node.node_id,
                "node_revision": context.node.revision,
                "agent_name": "video_agent",
                "operation": "execute_canvas_text",
            },
            model_ref=context.model_resolution.model_ref,
        )
        completed = AgentRunCompletedPayload.model_validate(result.terminal_payload)
        content = completed.value.get("content")
        if not isinstance(content, str) or not content.strip():
            raise _error(
                "text_provider_output_invalid",
                "Quick Media Agent output did not include content.",
            )
        return NodeExecutionOutcome(structured_content=dict(completed.value))


class MediaNodeExecutor:
    """Adapt node-native media requests to the existing provider boundary."""

    def __init__(
        self,
        provider: _MinimalProviderExecutor,
        *,
        data_dir: Path,
        settings: Settings | None = None,
        reference_delivery: V2ProviderReferenceInputDeliveryService | None = None,
        seedance_inputs: AgentCanvasSeedanceInputCompiler | None = None,
        submission_intents=None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._provider = provider
        self._data_dir = data_dir.resolve()
        self._settings = settings or get_settings()
        self._reference_delivery = reference_delivery or V2ProviderReferenceInputDeliveryService(
            self._data_dir,
            settings=self._settings,
        )
        self._seedance_inputs = seedance_inputs or AgentCanvasSeedanceInputCompiler()
        self._submission_intents = submission_intents
        self._clock = clock

    def _submit_with_transient_retry(
        self,
        *,
        workflow_id: str,
        slot_type: str,
        media_type: str,
        provider_payload: dict[str, Any],
        intent: Any,
    ) -> V2ProviderResult:
        """Submit once, retrying only failures our classifier calls transient.

        A Volcengine 503 ``engine_overloaded`` is answered with the literal
        text "please try again later"; treating it as terminal left the node red
        with no recovery path until the provider recovered on its own.  Only
        results flagged ``retryable`` by the executor are retried, so a genuine
        contract error (bad prompt, unsupported model) still fails immediately
        instead of burning quota.

        Note the deliberate tension: StepFun's step_plan gateway marks its image
        503 ``X-Should-Retry: false``, and ``_overload_hint`` repeats that to the
        operator instead of promising a retry.  We still retry, because
        ``retryable`` is *our* classification of the status and one provider's
        header must not be able to switch off retry for every caller -- but the
        retry budget is small (three attempts, ~7s), so being wrong here costs
        seconds rather than an operator's afternoon.  When the two disagree the
        node error carries both verdicts.
        """

        attempts = max(1, int(getattr(self._settings, "provider_transient_retry_attempts", 1)))
        base_delay = max(
            0.0,
            float(getattr(self._settings, "provider_transient_retry_base_delay_seconds", 0.0)),
        )
        result: V2ProviderResult | None = None
        retries_used = 0
        for attempt in range(1, attempts + 1):
            result = self._provider.execute_minimal(
                workflow_id=workflow_id,
                slot_type=slot_type,
                media_type=media_type,
                provider_payload=dict(provider_payload),
            )
            retryable = result.status == "failed" and bool(
                result.metadata.get("retryable")
            )
            if result.status != "failed" or not retryable or attempt == attempts:
                if retries_used:
                    # This executor holds no event sink, so the retry bookkeeping
                    # rides on the result metadata that the node records anyway.
                    # Without it a node that only succeeded on attempt 3 is
                    # indistinguishable from one that succeeded first try, and
                    # the provider's overload stay invisible.
                    result.metadata["provider_retry_attempts"] = retries_used + 1
                    result.metadata["provider_retry_attempts_total"] = attempts
                return result
            retries_used += 1
            # Exponential backoff: 1s, 2s, 4s ... capped so a long retry chain
            # cannot hold the execution lease past its TTL indefinitely.
            time.sleep(min(base_delay * (2 ** (attempt - 1)), 30.0))
        assert result is not None  # loop always assigns at least once
        return result

    def prepare(self, context: NodeExecutionContext) -> NodeExecutionContext:
        """Resolve provider-safe media before the scheduler starts provider work."""

        require_node_runnable(context.node)
        if context.node.node_type not in {"image", "video", "audio"}:
            return context
        _require_character_identity_master_input(context)
        media_inputs = tuple(
            item for item in context.inputs if isinstance(item, ResolvedMediaInputSnapshotV2)
        )
        AgentCanvasRoleReferencePolicyService().require_derivative_runtime_inputs(
            context.node,
            media_inputs,
            (
                context.input_manifest.omitted_optional_inputs
                if context.input_manifest is not None
                else ()
            ),
        )
        if context.node.node_type == "video" and context.seedance_manifest is not None:
            return context
        if context.node.node_type != "video" and context.delivered_references:
            return context
        try:
            grounding_plan = _seedance_grounding_plan(context, media_inputs)
        except GroundingPlanError as error:
            raise _error(error.code, str(error)) from error
        delivery = None
        if media_inputs:
            if context.model_resolution is None:
                raise _error(
                    "model_resolution_missing",
                    "Media reference delivery requires a frozen model resolution.",
                )
            delivery = self._reference_delivery.deliver_canvas_inputs(
                model_resolution=context.model_resolution,
                inputs=_delivery_inputs_with_validated_character_identity_semantics(
                    context.node,
                    media_inputs,
                ),
                grounding_plan=grounding_plan,
            )
            try:
                delivery.raise_for_canvas_failures()
            except V2ProviderReferenceDeliveryError as error:
                raise _error(
                    error.code,
                    str(error),
                    details={
                        "target_node_id": context.node.node_id,
                        "failures": [
                            _delivery_failure_identity(failure, media_inputs)
                            for failure in error.failures
                        ],
                    },
                ) from error
        delivered_references = tuple(delivery.references) if delivery is not None else ()
        optional_delivery_omissions = (
            tuple(
                {
                    "binding_id": failure.binding_id or "",
                    "source_node_id": failure.node_id or failure.slot_id,
                    "reason": failure.reason,
                }
                for failure in delivery.omitted_optional_inputs
            )
            if delivery is not None
            else ()
        )
        optional_input_omissions = (
            *context.optional_input_omissions,
            *optional_delivery_omissions,
        )
        if context.node.node_type != "video":
            return replace(
                context,
                delivered_references=delivered_references,
                optional_input_omissions=optional_input_omissions,
            )
        if getattr(context.model_resolution, "transport_kind", "") == "minimax_video_native":
            return replace(
                context,
                delivered_references=delivered_references,
                optional_input_omissions=optional_input_omissions,
            )
        delivered_media = tuple(
            SeedanceDeliveredMediaInputV1(
                binding_id=reference.binding_id or f"asset_{reference.asset_id}",
                asset_id=reference.asset_id,
                version_id=reference.version_id,
                media_type=reference.media_type,  # type: ignore[arg-type]
                input_role=reference.input_role,  # type: ignore[arg-type]
                source_semantic_role=reference.source_semantic_role,
                required=reference.required,
                display_order=reference.display_order,
                provider_input_type=reference.provider_input_type,
                provider_input_value=reference.provider_input_value,
                checksum=reference.checksum
                or _seedance_checksum(reference.asset_id, reference.version_id),
                byte_count=reference.byte_count,
            )
            for reference in delivered_references
        )
        try:
            if context.model_resolution is None or not context.model_id:
                raise _error(
                    "model_resolution_missing",
                    "Video execution requires a frozen model resolution.",
                )
            manifest, audit = self._seedance_inputs.compile(
                context.node,
                model_id=context.model_id,
                resolved_inputs=tuple(
                    item
                    for item in context.inputs
                    if isinstance(
                        item,
                        (ResolvedTextInputSnapshotV2, ResolvedMediaInputSnapshotV2),
                    )
                ),
                delivered_media=delivered_media,
                compiled_prompt=(
                    context.compiled_prompt.prompt if context.compiled_prompt is not None else None
                ),
                effective_parameters=context.effective_parameters,
                grounding_plan=grounding_plan,
            )
        except (GroundingPlanError, ValueError) as error:
            code = str(error)
            if isinstance(error, GroundingPlanError):
                pass
            elif code != "v2_video_prompt_empty" and not code.startswith(
                "v2_storyboard_reference_"
            ):
                code = "provider_inputs_unsupported"
            raise _error(code, str(error)) from error
        return replace(
            context,
            seedance_manifest=manifest,
            seedance_input_audit=audit,
            delivered_references=delivered_references,
            optional_input_omissions=optional_input_omissions,
        )

    def __call__(self, context: NodeExecutionContext) -> NodeExecutionOutcome:
        require_node_runnable(context.node)
        media_type = context.node.node_type
        if media_type not in {"image", "video", "audio"}:
            raise _error("node_not_runnable", "Node type cannot use a media executor.")
        if context.model_resolution is None:
            raise _error(
                "model_resolution_missing",
                "Media execution requires a frozen model resolution.",
            )
        if media_type == "video" and getattr(
            context.model_resolution, "transport_kind", ""
        ) not in {
            "minimax_video_native",
        }:
            return self._execute_seedance_video(self.prepare(context))
        effective_parameters = (
            context.effective_parameters.effective
            if context.effective_parameters is not None
            else context.node.parameters
        )
        if context.node.semantic_role == "bgm":
            _require_bgm_duration(effective_parameters)
        prompt = _saved_prompt(context)
        prepared = self.prepare(context)
        provider_only_instructions = tuple(
            reference.reference_instruction
            for reference in prepared.delivered_references
            if (
                reference.reference_instruction is not None
                and reference.reference_instruction_transport == "provider_only"
            )
        )
        provider_prompt = _provider_prompt_with_reference_instructions(
            prompt,
            provider_only_instructions,
        )
        provider_payload: dict[str, Any] = {
            "provider_prompt": provider_prompt,
            "prompt": provider_prompt,
            "node_id": context.node.node_id,
            "semantic_role": context.node.semantic_role,
            "model_id": context.model_resolution.provider_model_id,
            **effective_parameters,
        }
        provider_payload.update(
            {
                "model_ref": context.model_resolution.model_ref,
                "provider_id": context.model_resolution.provider_id,
                "provider_model_id": context.model_resolution.provider_model_id,
            }
        )
        provider_payload.update(_frozen_adapter_identity_payload(context.model_resolution))
        if prepared.delivered_references:
            provider_payload["reference_assets"] = [
                reference.provider_asset() for reference in prepared.delivered_references
            ]
            provider_payload["reference_asset_ids"] = [
                reference.asset_id for reference in prepared.delivered_references
            ]
            if provider_only_instructions:
                provider_payload["provider_only_reference_instructions"] = list(
                    provider_only_instructions
                )
        intent = self._prepare_submission_intent(context, provider_payload)
        if intent is not None and intent.provider_idempotency_token is not None:
            provider_payload["idempotency_token"] = intent.provider_idempotency_token
        try:
            result = self._submit_with_transient_retry(
                workflow_id=context.node.workflow_id,
                slot_type=context.node.semantic_role,
                media_type=media_type,
                provider_payload=provider_payload,
                intent=intent,
            )
        except Exception as error:
            self._handle_submission_error(intent, error)
            raise
        if result.status == "completed":
            content = result.asset_bytes
            if content is None and result.local_file_path:
                content = self._read_provider_file(result.local_file_path)
            if content is None:
                raise _error(
                    "provider_output_missing",
                    "Provider result did not include media content.",
                )
            mime_type, filename, gate = accepted_provider_media(media_type, content)
            if intent is not None:
                self._submission_intents.complete(intent, now=self._clock())
            return NodeExecutionOutcome(
                media=GeneratedMediaPayload(
                    content=content,
                    mime_type=mime_type,
                    filename=filename,
                    metadata={
                        "provider": result.provider,
                        "model_id": result.provider_model,
                        "media_output_gate": gate,
                        **dict(result.metadata),
                    },
                ),
                provider=result.provider,
                remote_task_id=result.remote_task_id,
                result_descriptor=dict(result.metadata),
                submission_intent_id=(intent.intent_id if intent is not None else None),
            )
        if result.status == "waiting" and result.remote_task_id:
            task_digest = hashlib.sha256(
                f"{context.execution_id}:{context.node.node_id}:{result.remote_task_id}".encode()
            ).hexdigest()[:24]
            if intent is not None:
                intent = self._submission_intents.confirm_remote_task(
                    intent,
                    provider_task_id=f"task_{task_digest}",
                    remote_task_id=result.remote_task_id,
                    now=self._clock(),
                )
            return NodeExecutionOutcome(
                provider_task_id=f"task_{task_digest}",
                remote_task_id=result.remote_task_id,
                provider=result.provider,
                result_descriptor={
                    "media_type": media_type,
                    "provider": result.provider,
                    "provider_model": result.provider_model,
                    "provider_payload": result.provider_payload_snapshot,
                    **result.metadata,
                },
                submission_intent_id=(intent.intent_id if intent is not None else None),
            )
        raise _error(
            result.error_code or "provider_generation_failed",
            result.error_message or "Provider generation failed.",
            # safe_execution_error() projects retryable=True only when the
            # exception carries the flag in details AND the code is approved
            # transient. Dropping it here is what turned a 503 the classifier
            # had already called transient into a permanently red node.
            details={"retryable": bool(result.metadata.get("retryable"))},
        )

    def _execute_seedance_video(self, context: NodeExecutionContext) -> NodeExecutionOutcome:
        manifest = context.seedance_manifest
        audit = context.seedance_input_audit
        if manifest is None or audit is None:
            raise _error(
                "provider_inputs_unsupported", "Seedance manifest preparation is required."
            )
        execute = getattr(self._provider, "execute_agent_canvas_seedance_video", None)
        if not callable(execute):
            raise _error(
                "provider_reference_delivery_unavailable",
                "The configured provider does not support Agent Canvas Seedance manifests.",
            )
        try:
            VolcengineSeedanceAdapter(self._settings).payload_for_manifest(manifest)
        except ValueError as error:
            raise _error(str(error), str(error)) from error
        intent = self._prepare_submission_intent(
            context,
            {
                "manifest": manifest.model_dump(mode="json"),
                "audit": audit.model_dump(mode="json"),
            },
        )
        try:
            result = execute(
                workflow_id=context.node.workflow_id,
                node_id=context.node.node_id,
                manifest=manifest,
                audit=audit,
            )
        except Exception as error:
            self._handle_submission_error(intent, error)
            raise
        audit_payload = {"seedance_input_manifest": audit.model_dump(mode="json")}
        if result.status == "completed":
            content = result.asset_bytes
            if content is None and result.local_file_path:
                content = self._read_provider_file(result.local_file_path)
            if content is None:
                raise _error(
                    "provider_output_missing", "Provider result did not include media content."
                )
            mime_type, filename, gate = accepted_provider_media("video", content)
            if intent is not None:
                self._submission_intents.complete(intent, now=self._clock())
            return NodeExecutionOutcome(
                media=GeneratedMediaPayload(
                    content=content,
                    mime_type=mime_type,
                    filename=filename,
                    metadata={
                        "provider": result.provider,
                        "model_id": result.provider_model,
                        "media_output_gate": gate,
                        **dict(result.metadata),
                    },
                ),
                provider=result.provider,
                remote_task_id=result.remote_task_id,
                result_descriptor=dict(result.metadata),
                prompt_metadata=audit_payload,
                submission_intent_id=(intent.intent_id if intent is not None else None),
            )
        if result.status == "waiting" and result.remote_task_id:
            task_digest = hashlib.sha256(
                f"{context.execution_id}:{context.node.node_id}:{result.remote_task_id}".encode()
            ).hexdigest()[:24]
            if intent is not None:
                intent = self._submission_intents.confirm_remote_task(
                    intent,
                    provider_task_id=f"task_{task_digest}",
                    remote_task_id=result.remote_task_id,
                    now=self._clock(),
                )
            return NodeExecutionOutcome(
                provider_task_id=f"task_{task_digest}",
                remote_task_id=result.remote_task_id,
                provider=result.provider,
                result_descriptor={
                    "media_type": "video",
                    "provider": result.provider,
                    "provider_model": result.provider_model,
                    "provider_payload": result.provider_payload_snapshot,
                    **result.metadata,
                },
                prompt_metadata=audit_payload,
                submission_intent_id=(intent.intent_id if intent is not None else None),
            )
        raise _error(
            result.error_code or "provider_generation_failed",
            result.error_message or "Provider generation failed.",
            # Same contract as the media executor: without the flag in details
            # the node is projected as permanently failed even when the provider
            # reported a transient condition.
            details={"retryable": bool(result.metadata.get("retryable"))},
        )

    def _prepare_submission_intent(self, context, request_payload):
        if self._submission_intents is None or context.model_resolution is None:
            return None
        return self._submission_intents.prepare(
            workflow_id=context.node.workflow_id,
            execution_id=context.execution_id,
            node_id=context.node.node_id,
            model_resolution=context.model_resolution,
            request_payload=request_payload,
            now=self._clock(),
        )

    def _handle_submission_error(self, intent, error: Exception) -> None:
        if intent is None or self._submission_intents is None:
            return
        updated = self._submission_intents.mark_outcome_unknown(intent, now=self._clock())
        if updated.state == "outcome_unknown":
            raise _error(
                "provider_submission_outcome_unknown",
                "Provider submission outcome cannot be recovered automatically.",
            ) from error

    def _read_provider_file(self, value: str) -> bytes:
        candidate = Path(value)
        path = candidate if candidate.is_absolute() else self._data_dir / candidate
        resolved = path.resolve()
        if not resolved.is_relative_to(self._data_dir) or not resolved.is_file():
            raise _error(
                "provider_output_invalid",
                "Provider output path is outside managed storage.",
            )
        return resolved.read_bytes()


def _require_bgm_duration(parameters: dict[str, object]) -> None:
    duration = parameters.get("duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
        raise _error(
            "model_parameter_unsupported",
            "BGM execution requires a positive integer duration_seconds.",
        )


def _frozen_adapter_identity_payload(
    resolution: ResolvedModelExecutionV1,
) -> dict[str, object]:
    """Expose only adapter identity already frozen in the V2 resolution."""

    if not isinstance(resolution, ResolvedModelExecutionV2):
        return {}
    return {
        "adapter_id": resolution.adapter_id,
        "transport_kind": resolution.transport_kind,
        "conformance_status": resolution.conformance_status,
        "capability_revision": resolution.capability_revision,
        "adapter_revision": resolution.adapter_revision,
        "requested_parameter_fingerprint": resolution.requested_parameter_fingerprint,
        "effective_parameter_fingerprint": resolution.effective_parameter_fingerprint,
    }


def accepted_provider_media(
    media_type: str,
    content: bytes,
    *,
    filename: str | None = None,
) -> tuple[str, str, dict[str, object]]:
    """Gate one provider payload, then label it after what its bytes really are.

    Raising here is the point: this is the last moment the payload is still
    "bytes a provider sent" rather than "this node's published asset".  Past
    this line the node is marked ready and the asset is what a film gets cut
    from, so a truncated download has to fail the node instead of landing in
    the timeline.

    The report comes back too, so the verdict is recorded on the asset rather
    than living only in the moment it was checked.  A caller that has a name
    worth keeping -- a voice-cast node's ``voice-cast.mp3`` -- passes it in;
    the gate renames nothing.
    """

    report = inspect_media_output(media_type=media_type, content=content)
    if not report.passed:
        raise media_output_gate_failure(report)
    mime_type, derived_filename = media_output_identity(content, media_type)
    return mime_type, filename or derived_filename, report.to_dict()


def _voice_cast_text(context: NodeExecutionContext) -> str:
    """Collect dialogue text for a voice-cast node.

    Prefer authored content on the node (``structured_content.content``,
    then the prepared ``generation_prompt``); fall back to bound text
    inputs only when the node carries no text of its own.
    """

    node = context.node
    content = node.structured_content.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if (node.generation_prompt or "").strip():
        return node.generation_prompt.strip()
    if context.input_manifest is not None:
        bound = [
            item.content.strip()
            for item in context.input_manifest.text_inputs
            if item.content.strip()
        ]
        if bound:
            return "\n".join(bound)
    return ""


def _tts_engine_is_live(engine: Any) -> bool:
    check = getattr(engine, "is_configured", None)
    if callable(check):
        return bool(check())
    return bool(getattr(engine, "api_key", None))


def _tts_provider_label(engine: Any) -> str:
    """A stable provider label for the TTS engine that actually spoke.

    The concrete engines (``StepFunTTSEngine`` / ``FishAudioTTSEngine``)
    carry no ``provider`` attribute, so falling back to the class name would
    put ``StepFunTTSEngine`` on the asset row -- a name that matches neither
    the ``tts_provider_ids()`` the factory advertises nor the provider ids
    used anywhere else.  Recognising the engine by its class name against
    those advertised ids keeps the two in step, so a new provider needs no
    edit here.  A duck-typed engine that declares ``provider`` itself (a
    fake, or a future engine with a real vendor id) keeps its own label, so a
    test double never masquerades as a real vendor.
    """

    explicit = getattr(engine, "provider", None)
    if explicit:
        return str(explicit)
    class_name = type(engine).__name__
    compact = class_name.casefold().replace("_", "")
    for provider_id in tts_provider_ids():
        if provider_id.casefold().replace("_", "") in compact:
            return provider_id
    suffix = "TTSEngine"
    if class_name.endswith(suffix) and len(class_name) > len(suffix):
        stem = class_name[: -len(suffix)]
        return re.sub(r"(?<!^)(?=[A-Z])", "_", stem).lower()
    return class_name


def _tts_model_label(engine: Any) -> str | None:
    """The model the engine was configured with, when it exposes one."""

    for attribute in ("model", "model_id"):
        value = getattr(engine, attribute, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


class VoiceCastNodeExecutor:
    """Synthesize dialogue locally through the configured TTS engine.

    A voice-cast node does not call a catalog provider: its speech is
    produced by one of the scene3d TTS engines (StepFun / Fish Audio),
    selected by ``tts_engine_factory`` from the installation settings.
    When no real TTS engine is configured the executor fails closed
    rather than publishing a fake audio asset (ADR 0003).
    """

    def __init__(self, settings: Settings, *, engine: Any | None = None) -> None:
        self._settings = settings
        self._engine = engine

    def __call__(self, context: NodeExecutionContext) -> NodeExecutionOutcome:
        text = _voice_cast_text(context)
        if not text:
            raise _error(
                "node_prompt_empty",
                "Voice Cast requires dialogue text before it can speak.",
            )
        engine = self._engine or create_tts_engine_from_settings(self._settings)
        if not _tts_engine_is_live(engine):
            raise _error(
                "voicecast_tts_unconfigured",
                "No TTS provider is configured. Add a StepFun or Fish Audio API key.",
            )
        with tempfile.TemporaryDirectory(prefix="voicecast_") as tmp_dir:
            output_path = os.path.join(tmp_dir, "voice-cast.mp3")
            try:
                engine.synthesize(text, character_id="", output_path=output_path)
            except Exception as exc:  # noqa: BLE001 - re-raised as a coded error.
                # A transport/HTTP failure used to escape as a bare RuntimeError
                # whose text was the only clue as to *which* vendor to
                # re-credential -- ``StepFun TTS API error 401: ...`` buried in a
                # free-form attempt error.  Name the provider and the remedy in
                # structured ``details`` instead, so the caller can act on it
                # without parsing prose (ADR 0005: queryable, never silent).
                provider = _tts_provider_label(engine)
                raise _error(
                    "voicecast_tts_failed",
                    f"The {provider} TTS request failed: {exc}",
                    details={
                        "tts_provider": provider,
                        "tts_model": _tts_model_label(engine),
                        "failure": str(exc),
                        "failure_type": type(exc).__name__,
                        "remedy": (
                            "The configured TTS credential was rejected or is "
                            "unreachable. Check the key is current and the "
                            "endpoint is reachable, then retry the node."
                        ),
                        # Routed through the *already projected* disposition
                        # rather than raw ``details``: ``safe_execution_error``
                        # lifts only ``retryable`` / ``actionable_failure`` (plus
                        # the role-contract keys) onto ``CanvasNodeErrorV2``, so
                        # anything else in ``details`` never reaches the client.
                        # ``external`` + ``revise`` is what tells the workbench
                        # "fix the credential", and ``retry_scope="none"`` keeps
                        # ``retryable`` False -- re-running a revoked key changes
                        # nothing.
                        "actionable_failure": ActionableFailureV1(
                            failure_class="external",
                            retry_scope="none",
                            user_action="revise",
                        ),
                    },
                ) from exc
            if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
                raise _error(
                    "voicecast_tts_failed",
                    "The TTS engine returned no audio.",
                    details={"tts_provider": _tts_provider_label(engine)},
                )
            audio_bytes = Path(output_path).read_bytes()
        # A voice-cast node reads back the file the TTS engine wrote, so this is
        # the same gate a provider payload gets: an engine that claims success
        # and writes a truncation must fail the node, not the film.
        audio_mime, audio_filename, audio_gate = accepted_provider_media(
            "audio", audio_bytes, filename="voice-cast.mp3"
        )
        provider = _tts_provider_label(engine)
        model = _tts_model_label(engine)
        # ``provider``/``model_id`` are first-class columns on the asset row
        # (see ``publish_generated_bytes``) and every other media modality
        # stamps them.  A voice-cast node resolves no catalog model, so
        # without this the published asset reads as "no provider, no model"
        # even though a real StepFun / Fish Audio engine produced the audio.
        return NodeExecutionOutcome(
            media=GeneratedMediaPayload(
                content=audio_bytes,
                mime_type=audio_mime,
                filename=audio_filename,
                metadata={
                    "provider": provider,
                    "model_id": model,
                    "tts_provider": provider,
                    "tts_model": model,
                    "media_output_gate": audio_gate,
                },
            ),
            structured_content={"tts_provider": provider, "tts_model": model},
        )


def _scene_script_from_node(node: CanvasNodeV2) -> SceneScriptRoot | None:
    """Read and validate the SceneScript stored on a scene-3d node."""

    raw = node.structured_content.get("scene_script")
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    try:
        return SceneScriptRoot.model_validate(raw)
    except ValidationError:
        return None


def _scene_description_text(context: NodeExecutionContext) -> str:
    """Collect a natural-language scene description for a scene-3d node.

    Prefer the node's own prepared prompt; fall back to bound text/script
    inputs from upstream nodes.
    """

    node = context.node
    if (node.generation_prompt or "").strip():
        return node.generation_prompt.strip()
    if context.input_manifest is not None:
        bound = [
            item.content.strip()
            for item in context.input_manifest.text_inputs
            if item.content.strip()
        ]
        if bound:
            return "\n".join(bound)
    return ""


# Shared across every Scene3DNodeExecutor in the process, because the node
# dispatcher (and therefore this executor) is rebuilt per request: a per-instance
# semaphore would serialize the leases of ONE run while letting two concurrent
# "Run all" requests each spawn their own Blender and starve each other exactly
# as before. Tests inject their own slot instead of touching this global.
_DEFAULT_SCENE3D_RENDER_SLOT: threading.Semaphore | None = None
_DEFAULT_SCENE3D_RENDER_SLOT_LOCK = threading.Lock()


def _shared_scene3d_render_slot(settings: Settings) -> threading.Semaphore:
    """The one Blender gate in this process, sized from the operator's setting.

    Sized on first use so ``SCENE3D_MAX_CONCURRENT_RENDERS`` keeps meaning
    something; every later executor reuses the same gate rather than creating a
    second one that would let renders overlap again.
    """
    global _DEFAULT_SCENE3D_RENDER_SLOT
    with _DEFAULT_SCENE3D_RENDER_SLOT_LOCK:
        if _DEFAULT_SCENE3D_RENDER_SLOT is None:
            _DEFAULT_SCENE3D_RENDER_SLOT = threading.Semaphore(
                max(1, int(getattr(settings, "scene3d_max_concurrent_renders", 1)))
            )
        return _DEFAULT_SCENE3D_RENDER_SLOT


# Which semantic role on a delivered reference maps onto which SceneScript
# element kind.  The canonical aliases come from
# ``agent_canvas_grounding_roles._ROLE_ALIASES``; a role outside this map is
# still published as a binding, it just cannot name an element.
_SCENE3D_ROLE_TO_ELEMENT: dict[str, str] = {
    "scene": "environment",
    "scene_board": "environment",
    "scene_reference": "environment",
    "environment_reference": "environment",
    "character": "character",
    "character_reference": "character",
    "subject_reference": "character",
    "product": "prop",
    "product_reference": "prop",
    "prop": "prop",
    "prop_reference": "prop",
}

# SceneScript element kind -> the P0 asset-id field that records the binding.
_SCENE3D_ELEMENT_TO_FIELD: dict[str, str] = {
    "environment": "scene_asset_id",
    "character": "character_asset_id",
    "prop": "prop_asset_id",
}


def _scene3d_reference_bindings(context: NodeExecutionContext) -> list[dict[str, Any]]:
    """Describe the media references delivered to a scene-3d node.

    ``Scene3DNodeExecutor`` renders a SceneScript through Blender, so unlike a
    video node it has nowhere to put a reference image -- the renderer has no
    input slot for one.  The reference is still delivered (see
    ``MediaNodeExecutor.prepare``), and dropping it silently would make a bound
    scene design board look like it had been honoured.  This records what
    arrived so the node surface can show it and a later run can disagree with it.
    """

    references = getattr(context, "delivered_references", ()) or ()
    if not references:
        return []
    described: list[dict[str, Any]] = []
    for reference in sorted(references, key=lambda item: item.display_order):
        semantic_role = reference.source_semantic_role or ""
        described.append(
            {
                "binding_id": reference.binding_id,
                "asset_id": reference.asset_id,
                "asset_version_id": reference.version_id,
                "semantic_role": semantic_role,
                # "recorded" says the asset id is carried on the matching
                # SceneScript element; the render itself is unchanged either
                # way, because a SceneScript has no image input.
                "recorded_on": _SCENE3D_ELEMENT_TO_FIELD.get(
                    _SCENE3D_ROLE_TO_ELEMENT.get(semantic_role, ""), None
                ),
                "media_type": reference.media_type,
            }
        )
    return described


def _apply_scene3d_reference_bindings(
    scene_script: SceneScriptRoot,
    reference_bindings: list[dict[str, Any]],
    *,
    generated: bool,
) -> SceneScriptRoot:
    """Carry each delivered asset id onto the SceneScript element it matches.

    ``SceneEnvironmentObject.scene_asset_id``, ``SceneCharacter.character_asset_id``
    and ``SceneProp.prop_asset_id`` exist precisely to answer "which asset is
    this element from", and all three were left null on every previs node
    because nothing on the canvas path ever filled them.

    An element is only stamped when it is unambiguous: with one character and
    one scene, "the character came from the turnaround" is a true statement.
    With four props and one prop reference it would be a guess, so the
    reference stays visible in ``scene3d_reference_bindings`` and the elements
    stay honest.

    ``generated=False`` means the script already lives on the node and is not
    republished, so stamping it would change memory only.
    """

    by_element: dict[str, list[str]] = {}
    for binding in reference_bindings:
        element = _SCENE3D_ROLE_TO_ELEMENT.get(
            str(binding.get("semantic_role") or ""), None
        )
        asset_id = binding.get("asset_id")
        if element is None or not asset_id:
            continue
        by_element.setdefault(element, []).append(str(asset_id))
    if not by_element:
        return scene_script

    collections = {
        "environment": scene_script.environment,
        "character": scene_script.characters,
        "prop": scene_script.props,
    }
    updates: dict[str, tuple[str, str]] = {}
    for element, asset_ids in by_element.items():
        items = collections[element]
        # Only the first asset of a role can be attributed without guessing.
        asset_id = asset_ids[0]
        if len(items) == 1:
            updates[items[0].id] = (element, asset_id)

    if not updates or not generated:
        return scene_script

    for element, collection in collections.items():
        field = _SCENE3D_ELEMENT_TO_FIELD[element]
        for item in collection:
            if item.id in updates:
                attributed_element, asset_id = updates[item.id]
                if attributed_element != element:
                    continue
                if getattr(item, field, None) in (None, ""):
                    setattr(item, field, asset_id)
    return scene_script


class Scene3DNodeExecutor:
    """Render the node's SceneScript locally through headless Blender.

    The SceneScript is either already stored on the node
    (``structured_content["scene_script"]``) or generated from the node's
    natural-language scene description through the injected
    ``script_generator`` (LLM in real runtime, template in fake runtime).
    The executor renders low-fidelity PNG frames with Blender and publishes
    the camera trajectory alongside them, plus an MP4 of the frames unless the
    operator turned video off (ADR 0005 §2). A freshly generated script is
    returned in ``structured_content`` so it is persisted on the node for
    downstream video nodes to bind. When the script cannot be produced or
    Blender is not installed the executor fails closed with an explicit error
    instead of silently degrading.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        capability_probe: Callable[[], Any] | None = None,
        renderer: Callable[..., Any] | None = None,
        encoder: Callable[..., Any] | None = None,
        script_generator: SceneScriptGenerator | None = None,
        render_slot: Any | None = None,
    ) -> None:
        self._settings = settings
        self._capability_probe = capability_probe or get_blender_capability
        self._renderer = renderer or render_scene_script
        self._encoder = encoder or encode_png_sequence
        self._script_generator = script_generator
        # Flat ceiling: an operator who needs more headroom raises this rather
        # than the per-frame slope.  The actual budget handed to Blender is
        # derived per render (see ``_render_timeout_for``), so a 6-shot draft
        # gets ~3 minutes instead of the 30 minutes a full pass would need.
        self._render_timeout_seconds = max(
            30,
            min(3600, int(getattr(settings, "scene3d_render_timeout_seconds", 1800))),
        )
        self._render_startup_seconds = max(
            0, int(getattr(settings, "scene3d_render_startup_seconds", 90))
        )
        self._render_seconds_per_frame = max(
            0.0, float(getattr(settings, "scene3d_render_seconds_per_frame", 6.0))
        )
        # The canvas output is a previs the *next* node binds: a video model
        # needs reference frames, not 90 interpolated ones.  Rendering only the
        # keyframes turns a 6-shot node from ~19 minutes into ~20 seconds and
        # changes none of the images the full pass would have produced at those
        # instants.  Set SCENE3D_RENDER_KEYFRAMES_ONLY=false for a real
        # animation when someone wants to watch it.
        self._keyframes_only = bool(
            getattr(settings, "scene3d_render_keyframes_only", True)
        )
        # The MP4 is the *optional* half of the deliverable.  What a downstream
        # video node or a reviewer actually needs is the camera trajectory and
        # the keyframe schedule, which the node now always publishes as
        # structured content; encoding a video on top of that is for humans who
        # want to press play.  Operators running the node purely as a data
        # source set SCENE3D_EMIT_VIDEO=false and skip the encoder entirely.
        self._emit_video = bool(getattr(settings, "scene3d_emit_video", True))
        # "Run all" dispatches every lease at once, so N Blender processes would
        # otherwise starve each other and hit the timeout together.  Serializing
        # the renders keeps concurrent dispatch intact while giving each render
        # the full timeout budget it was granted.
        self._render_slot = (
            render_slot if render_slot is not None else _shared_scene3d_render_slot(settings)
        )

    def _render_timeout_for(self, scene_script: SceneScriptRoot) -> int:
        """Seconds this particular scene should be allowed to take.

        A flat timeout cannot fit both a 5-frame draft (which measured 7.7s
        end to end) and a 240-frame animation: too generous and the draft waits
        30 minutes for a failure that was visible after two, too tight and the
        full pass is killed mid-render with 150 of 240 frames already written.

        So the budget follows the work: Blender's fixed startup cost plus a
        per-frame allowance, capped by the configured ceiling.  The frame count
        is what the *draft* pass will actually write, not the scene length --
        that is the whole point of the draft.
        """

        frames = len(keyframe_render_frames(scene_script)) if self._keyframes_only else 0
        if frames == 0:
            frames = max(1, scene_script.total_frames)
        derived = self._render_startup_seconds + self._render_seconds_per_frame * frames
        return max(30, min(self._render_timeout_seconds, int(round(derived))))

    def __call__(self, context: NodeExecutionContext) -> NodeExecutionOutcome:
        scene_script = _scene_script_from_node(context.node)
        generated = False
        if scene_script is None:
            description = _scene_description_text(context)
            if not description or self._script_generator is None:
                raise _error(
                    "scene3d_scene_script_missing",
                    "The Scene-3D node has no valid SceneScript or scene description to render.",
                )
            try:
                scene_script = self._script_generator.generate(description=description)
            except SceneScriptGenerationError as error:
                raise _error(error.code, str(error)) from error
            generated = True
        capability = self._capability_probe()
        if getattr(capability, "state", "unsupported") == "unsupported":
            detail = getattr(capability, "error", "")
            raise _error(
                "scene3d_blender_unavailable",
                f"Blender is not available: {detail}".rstrip(),
            )
        with tempfile.TemporaryDirectory(prefix="scene3d_") as tmp_dir:
            frames_dir = os.path.join(tmp_dir, "frames")
            os.makedirs(frames_dir, exist_ok=True)
            with self._render_slot:
                result = self._renderer(
                    scene_script,
                    frames_dir,
                    timeout_seconds=self._render_timeout_for(scene_script),
                    keyframes_only=self._keyframes_only,
                )
            if not getattr(result, "success", False) or getattr(result, "frame_count", 0) == 0:
                raise _error(
                    "scene3d_render_failed",
                    getattr(result, "error", None) or "Blender rendered no frames.",
                )
            blender_version = getattr(result, "blender_version", None)
            # Surface which assets fell back to placeholder geometry so a
            # low-fidelity previs is never mistaken for a faithful one.
            degraded_assets = tuple(getattr(result, "degraded_assets", ()) or ())
            rendered_frames = getattr(result, "rendered_frames", "animation")
            # The camera trajectory is the deliverable proper: it is what a
            # downstream video node binds and what a reviewer reads instead of
            # watching the clip.  Built whether or not a video is encoded, so
            # the data half never depends on ffmpeg being installed.
            trajectory = previs_trajectory(
                scene_script, rendered_frames=rendered_frames
            )
            media: GeneratedMediaPayload
            if self._emit_video:
                video_path = os.path.join(tmp_dir, "previs.mp4")
                encoded = self._encoder(
                    frames_dir,
                    video_path,
                    fps=scene_script.scene.frame_rate,
                )
                if not getattr(encoded, "success", False):
                    raise _error(
                        "scene3d_encode_failed",
                        getattr(encoded, "error", "PNG sequence could not be encoded."),
                    )
                media = GeneratedMediaPayload(
                    content=Path(video_path).read_bytes(),
                    mime_type="video/mp4",
                    filename="previs.mp4",
                    metadata=self._previs_metadata(
                        scene_script,
                        rendered_frames=rendered_frames,
                        degraded_assets=degraded_assets,
                        blender_version=blender_version,
                    ),
                )
            else:
                # No video: publish the establishing frame instead, so the node
                # still carries a real image a human can look at and a video
                # node can still bind.  The trajectory names every frame that
                # exists, which is what keeps "one still" from reading as
                # "the whole previs".
                media = self._still_payload(
                    scene_script,
                    frames_dir=frames_dir,
                    rendered_frames=rendered_frames,
                    degraded_assets=degraded_assets,
                    blender_version=blender_version,
                )
        structured_content: dict[str, Any] | None = {
            "previs_trajectory": trajectory
        }
        if generated:
            # publish_node_output merges this onto the existing column, so
            # panel-authored structured fields are preserved.
            structured_content["scene_script"] = scene_script.model_dump(mode="json")
        reference_bindings = _scene3d_reference_bindings(context)
        if reference_bindings:
            # The previs itself is Blender's output and cannot be shaped by a
            # reference image: what a scene design board or a character
            # turnaround *can* do is decide which of those designs this script
            # was authored against, and that is a fact a consumer must be able
            # to ask for.  Publishing the bindings makes the edge visible from
            # the node surface; leaving them out would let a bound reference
            # vanish -- the scene board the author attached simply not being
            # part of the story the previs tells.
            structured_content["scene3d_reference_bindings"] = reference_bindings
            scene_script = _apply_scene3d_reference_bindings(
                scene_script,
                reference_bindings,
                generated=generated,
            )
            if generated:
                structured_content["scene_script"] = scene_script.model_dump(mode="json")
        return NodeExecutionOutcome(media=media, structured_content=structured_content)

    def _previs_metadata(
        self,
        scene_script: SceneScriptRoot,
        *,
        rendered_frames: str,
        degraded_assets: tuple[str, ...],
        blender_version: str | None,
    ) -> dict[str, Any]:
        """Metadata describing how faithful this previs is.

        Everything here exists so a consumer can *ask* what it is looking at
        rather than assume (ADR 0005 §4): which renderer produced it, whether
        the frames are a draft or a full pass, and which assets were degraded
        to placeholder geometry.
        """

        metadata: dict[str, Any] = {
            "scene3d_renderer": "blender",
            "blender_version": blender_version,
            # "keyframes" means the clip is a slideshow of each shot's keyframe
            # frames, not an animation.  Downstream consumers that assume a
            # continuous sequence (or measure duration against the scene's
            # frame count) must be able to tell the difference.
            "scene3d_rendered_frames": rendered_frames,
        }
        if rendered_frames == "keyframes":
            metadata["scene3d_keyframe_frames"] = list(
                keyframe_render_frames(scene_script)
            )
        if degraded_assets:
            metadata["degraded_assets"] = list(degraded_assets)
        return metadata

    def _still_payload(
        self,
        scene_script: SceneScriptRoot,
        *,
        frames_dir: str,
        rendered_frames: str,
        degraded_assets: tuple[str, ...],
        blender_version: str | None,
    ) -> GeneratedMediaPayload:
        """Publish one rendered frame as the node's image asset."""

        candidates = (
            keyframe_render_frames(scene_script)
            if rendered_frames == "keyframes"
            else list(range(scene_script.total_frames))
        )
        on_disk = rendered_frame_files(frames_dir)
        still: Path | None = None
        still_frame = -1
        for frame in candidates:
            found = on_disk.get(frame)
            if found is not None:
                still, still_frame = found, frame
                break
        if still is None:
            raise _error(
                "scene3d_render_failed",
                "Blender reported frames but none of them could be read back.",
            )
        metadata = self._previs_metadata(
            scene_script,
            rendered_frames=rendered_frames,
            degraded_assets=degraded_assets,
            blender_version=blender_version,
        )
        metadata["scene3d_still_frame"] = still_frame
        return GeneratedMediaPayload(
            content=still.read_bytes(),
            mime_type="image/png",
            filename="previs_still.png",
            metadata=metadata,
        )


class NodeExecutionDispatcher:
    """Dispatch only runnable node types without prompt rewriting."""

    def __init__(
        self,
        *,
        text_executor: NodeExecutor | None = None,
        script_executor: NodeExecutor | None = None,
        image_executor: NodeExecutor | None = None,
        video_executor: NodeExecutor | None = None,
        audio_executor: NodeExecutor | None = None,
        voice_cast_executor: NodeExecutor | None = None,
        scene_3d_executor: NodeExecutor | None = None,
    ) -> None:
        self._executors = {
            "text": text_executor,
            "script": script_executor,
            "image": image_executor,
            "video": video_executor,
            "audio": audio_executor,
            "voice-cast": voice_cast_executor,
            "scene-3d": scene_3d_executor,
        }

    def execute(self, context: NodeExecutionContext) -> NodeExecutionOutcome:
        require_node_runnable(context.node)
        if context.node.node_type not in self._executors:
            raise _error("node_not_runnable", "Node type cannot be run.")
        executor = self._executors[context.node.node_type]
        if executor is None:
            raise _error(
                "node_executor_unavailable",
                "The configured node executor is unavailable.",
            )
        return executor(context)

    def prepare(self, context: NodeExecutionContext) -> NodeExecutionContext:
        require_node_runnable(context.node)
        executor = self._executors.get(context.node.node_type)
        prepare = getattr(executor, "prepare", None)
        return prepare(context) if callable(prepare) else context


def build_default_node_dispatcher(
    settings: Settings,
    *,
    provider_executor: _MinimalProviderExecutor | None = None,
    fake_media_bytes_override: Callable[[str], bytes | None] | None = None,
    submission_intents=None,
) -> NodeExecutionDispatcher:
    """Build deterministic fakes or configured node-native provider adapters."""

    if settings.agent_runtime_mode == "fake" or settings.media_mode == "mock":

        def fake_script(context: NodeExecutionContext) -> NodeExecutionOutcome:
            return NodeExecutionOutcome(
                structured_content={
                    "content": context.node.generation_prompt
                    or context.node.summary_prompt
                    or context.node.title
                }
            )

        def fake_text(context: NodeExecutionContext) -> NodeExecutionOutcome:
            return NodeExecutionOutcome(
                structured_content={
                    "content": context.node.generation_prompt
                    or context.node.summary_prompt
                    or context.node.title
                }
            )

        def fake_media(context: NodeExecutionContext) -> NodeExecutionOutcome:
            prompt = (
                context.compiled_prompt.prompt
                if context.compiled_prompt is not None
                else context.node.generation_prompt
            )
            now = datetime.now(timezone.utc)
            intent = (
                submission_intents.prepare(
                    workflow_id=context.node.workflow_id,
                    execution_id=context.execution_id,
                    node_id=context.node.node_id,
                    model_resolution=context.model_resolution,
                    request_payload={
                        "node_type": context.node.node_type,
                        "prompt": prompt,
                    },
                    now=now,
                )
                if submission_intents is not None and context.model_resolution is not None
                else None
            )
            seed = hashlib.sha256(
                (f"{context.node.node_type}:{prompt}:{context.model_id}").encode()
            ).digest()
            mime_type, filename, signature = {
                "image": ("image/png", "image.png", b"\x89PNG\r\n\x1a\n"),
                "video": ("video/mp4", "video.mp4", b"\x00\x00\x00\x18ftypmp42"),
                "audio": ("audio/mpeg", "audio.mp3", b"ID3\x04\x00\x00"),
            }[context.node.node_type]
            overridden_content = (
                fake_media_bytes_override(context.node.node_type)
                if fake_media_bytes_override is not None
                else None
            )
            try:
                content = overridden_content or (
                    deterministic_mock_media_bytes(
                        context.node.node_type,
                        data_dir=settings.media_data_dir,
                        ffmpeg_path=settings.ffmpeg_path,
                        native_audio=(
                            context.node.node_type == "video"
                            and (
                                context.node.parameters.get("generate_audio") is True
                                or (
                                    context.effective_parameters is not None
                                    and context.effective_parameters.effective.get("generate_audio")
                                    is True
                                )
                            )
                        ),
                    )
                    if context.node.node_type in {"image", "video", "audio"}
                    else signature + b"ADCRAFT_FAKE_MEDIA\n" + seed
                )
            except MockMediaFixtureError as error:
                raise _error(
                    "mock_media_fixture_unavailable",
                    "Deterministic Mock media could not be created.",
                ) from error
            outcome = NodeExecutionOutcome(
                media=GeneratedMediaPayload(
                    content=content,
                    mime_type=mime_type,
                    filename=filename,
                ),
                submission_intent_id=(intent.intent_id if intent is not None else None),
            )
            if intent is not None:
                submission_intents.complete(intent, now=now)
            return outcome

        fake_video = MediaNodeExecutor(
            provider_executor or _default_provider_executor(settings),
            data_dir=settings.media_data_dir,
            settings=settings,
            submission_intents=submission_intents,
        )

        from app.services.scene3d.scene_script_generator import (
            TemplateSceneScriptGenerator,
        )

        return NodeExecutionDispatcher(
            text_executor=fake_text,
            script_executor=fake_script,
            image_executor=fake_media,
            video_executor=fake_video,
            audio_executor=fake_media,
            voice_cast_executor=VoiceCastNodeExecutor(settings),
            scene_3d_executor=Scene3DNodeExecutor(
                settings,
                script_generator=TemplateSceneScriptGenerator(),
            ),
        )

    from app.services.scene3d.scene_script_generator import (
        LLMSceneScriptGenerator,
    )

    media = MediaNodeExecutor(
        provider_executor or _default_provider_executor(settings),
        data_dir=settings.media_data_dir,
        settings=settings,
        submission_intents=submission_intents,
    )

    def unavailable(_: NodeExecutionContext) -> NodeExecutionOutcome:
        raise _error(
            "node_executor_unavailable",
            "Agent Canvas Script Writer runtime is not configured.",
        )

    return NodeExecutionDispatcher(
        text_executor=(
            TextNodeExecutor(
                DurablePiRunService(
                    settings=settings,
                    client=PiAgentRuntimeClient(
                        base_url=settings.agent_runtime_base_url,
                        internal_token=settings.agent_runtime_internal_token,
                        protocol_version=settings.agent_runtime_protocol_version,
                        connect_timeout_seconds=settings.agent_runtime_connect_timeout_seconds,
                        read_timeout_seconds=settings.agent_runtime_read_timeout_seconds,
                        run_timeout_seconds=settings.agent_runtime_run_timeout_seconds,
                        max_event_bytes=settings.agent_runtime_max_event_bytes,
                        max_stream_bytes=settings.agent_runtime_max_stream_bytes,
                    ),
                ),
                timeout_seconds=settings.agent_runtime_run_timeout_seconds,
            )
            if settings.agent_runtime_internal_token
            else unavailable
        ),
        script_executor=(
            ScriptNodeExecutor(
                DurablePiRunService(
                    settings=settings,
                    client=PiAgentRuntimeClient(
                        base_url=settings.agent_runtime_base_url,
                        internal_token=settings.agent_runtime_internal_token,
                        protocol_version=settings.agent_runtime_protocol_version,
                        connect_timeout_seconds=settings.agent_runtime_connect_timeout_seconds,
                        read_timeout_seconds=settings.agent_runtime_read_timeout_seconds,
                        run_timeout_seconds=settings.agent_runtime_run_timeout_seconds,
                        max_event_bytes=settings.agent_runtime_max_event_bytes,
                        max_stream_bytes=settings.agent_runtime_max_stream_bytes,
                    ),
                ),
                timeout_seconds=settings.agent_runtime_run_timeout_seconds,
            )
            if settings.agent_runtime_internal_token
            else unavailable
        ),
        image_executor=media,
        video_executor=media,
        audio_executor=media,
        voice_cast_executor=VoiceCastNodeExecutor(settings),
        scene_3d_executor=Scene3DNodeExecutor(
            settings,
            script_generator=LLMSceneScriptGenerator(settings),
        ),
    )


def _default_provider_executor(settings: Settings) -> _MinimalProviderExecutor:
    from app.services.v2_provider_executor import V2ProviderExecutor

    return V2ProviderExecutor(settings=settings, data_dir=settings.media_data_dir)


def _frozen_text_model_ref(context: NodeExecutionContext) -> str:
    resolution = context.model_resolution
    if resolution is None:
        raise _error(
            "model_resolution_missing",
            "Text and Script Nodes require a frozen model resolution.",
        )
    if resolution.capability != "text":
        raise _error(
            "agent_model_incompatible",
            "Text and Script Nodes require a compatible text model.",
        )
    return resolution.model_ref


def _saved_prompt(context: NodeExecutionContext) -> str:
    prompt = (
        context.compiled_prompt.prompt
        if context.compiled_prompt is not None
        else context.node.generation_prompt
    )
    parts = [str(prompt or context.node.summary_prompt or context.node.title).strip()]
    text_inputs = sorted(
        (
            item
            for item in context.inputs
            if isinstance(item, ResolvedTextInputSnapshotV2) and item.content.strip()
        ),
        key=lambda item: (item.display_order, item.binding_id or ""),
    )
    if text_inputs:
        parts.append(
            "Bound text context:\n"
            + "\n".join(
                f"{index}. {item.content.strip()}"
                for index, item in enumerate(text_inputs, start=1)
            )
        )
    media_inputs = sorted(
        (item for item in context.inputs if isinstance(item, ResolvedMediaInputSnapshotV2)),
        key=lambda item: (item.display_order, item.binding_id or ""),
    )
    if media_inputs:
        parts.append(
            "Bound media references:\n"
            + "\n".join(
                f"{index}. {item.media_type} {item.asset_id} ({item.input_role})"
                for index, item in enumerate(media_inputs, start=1)
            )
        )
    return "\n\n".join(parts)


def _seedance_grounding_plan(
    context: NodeExecutionContext,
    media_inputs: tuple[ResolvedMediaInputSnapshotV2, ...],
) -> StoryboardGridGroundingPlanV1 | None:
    """Build grounding only for persisted sequence video nodes with a grid binding."""

    if context.node.creative_role != "storyboard_video":
        return None
    sequence_id = context.node.metadata.get("source_sequence_id")
    if not isinstance(sequence_id, str) or not sequence_id.strip():
        return None
    grid_input = next(
        (
            item
            for item in media_inputs
            if item.media_type == "image"
            and (
                item.source_semantic_role in {"storyboard_grid", "storyboard_sequence"}
                or item.binding_metadata.get("semantic_reference_role")
                == "storyboard_visual_reference"
            )
        ),
        None,
    )
    if context.model_resolution is None:
        raise GroundingPlanError("v2_storyboard_grid_provider_payload_invalid")
    limits = context.model_resolution.capability_metadata.get("reference_limits")
    provider_reference_limit = limits.get("image") if isinstance(limits, dict) else None
    if not isinstance(provider_reference_limit, int):
        raise GroundingPlanError("v2_storyboard_grid_provider_payload_invalid")
    if grid_input is None:
        # A persisted storyboard-video prompt already contains the ordered
        # storyboard direction.  When the optional grid image is still a
        # Draft output, continue with that prompt and the other available
        # references; a published grid remains the strict grounding path.
        return None
    revision = context.node.metadata.get("source_plan_revision")
    grid_with_revision = grid_input.model_copy(
        update={
            "binding_metadata": {
                **grid_input.binding_metadata,
                "storyboard_revision": str(revision) if revision is not None else "",
            }
        }
    )
    try:
        ordered_references = tuple(
            {
                "asset_id": item.asset_id,
                "version_id": item.asset_version_id,
                "checksum": item.asset_checksum,
                "semantic_role": canonical_storyboard_reference_role(
                    binding_role=item.binding_metadata.get("semantic_reference_role"),
                    source_role=item.source_semantic_role,
                ),
                "binding_id": item.binding_id or f"asset:{item.asset_id}",
                "media_type": item.media_type,
                "required": True,
                "display_order": item.display_order,
            }
            for item in media_inputs
            if item is not grid_input and item.media_type == "image"
        )
    except ValueError as error:
        raise GroundingPlanError(str(error)) from error
    return build_storyboard_grid_grounding_plan(
        node=context.node,
        grid_input=grid_with_revision,
        storyboard_content=grid_input.source_structured_content,
        target_shot_id=sequence_id,
        prompt_snapshot=context.node.generation_prompt or "",
        ordered_references=ordered_references,
        provider_reference_limit=provider_reference_limit,
        expected_storyboard_revision=(str(revision) if revision is not None else None),
    )


def _provider_prompt_with_reference_instructions(
    prompt: str,
    instructions: tuple[str, ...],
) -> str:
    """Append bounded provider-only semantics without changing Node prompt authority."""

    if not instructions:
        return prompt
    section = "Provider-only reference instructions:\n" + "\n".join(
        f"{index}. {instruction}" for index, instruction in enumerate(instructions, start=1)
    )
    return f"{prompt}\n\n{section}"


def _json_input(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _error(
    code: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> V2PersistenceError:
    return V2PersistenceError(
        code,
        message,
        stage="agent_canvas_node_execution",
        details=details,
    )


def _delivery_failure_identity(
    failure: V2ReferenceInputDeliveryFailure,
    inputs: tuple[ResolvedMediaInputSnapshotV2, ...],
) -> dict[str, object]:
    source = next(
        (item for item in inputs if item.asset_id == failure.asset_id),
        None,
    )
    return {
        "binding_id": failure.binding_id or (source.binding_id if source is not None else None),
        "source_node_id": (
            failure.node_id or (source.source_node_id if source is not None else None)
        ),
        "asset_id": failure.asset_id,
        "required": True,
        "reason": failure.reason,
    }


def _require_character_identity_master_input(context: NodeExecutionContext) -> None:
    if not (
        context.node.node_type == "image"
        and context.node.creative_role == "character"
        and context.node.structured_content.get("character_asset_kind") == "turnaround"
    ):
        return
    target_pair_id = context.node.metadata.get("character_pair_id")
    target_occurrence_id = context.node.metadata.get("occurrence_id")
    target_phase = context.node.metadata.get("character_phase")
    candidates = tuple(
        item
        for item in context.inputs
        if isinstance(item, ResolvedMediaInputSnapshotV2)
        and item.source_kind == "node_output"
        and item.source_semantic_role == "character"
        and item.media_type == "image"
        and item.input_role == "image_reference"
        and item.binding_metadata.get("reference_purpose") == "identity_master"
        and item.binding_metadata.get("semantic_reference_role") == "subject_reference"
        and (
            not isinstance(target_pair_id, str)
            or item.binding_metadata.get("character_pair_id") == target_pair_id
        )
        and (
            not isinstance(target_occurrence_id, str)
            or item.binding_metadata.get("occurrence_id") == target_occurrence_id
        )
        and (
            not isinstance(target_phase, str)
            or item.binding_metadata.get("character_phase") == target_phase
        )
    )
    if len(candidates) != 1:
        omissions = (
            context.input_manifest.omitted_optional_inputs
            if context.input_manifest is not None
            else ()
        )
        if AgentCanvasRoleReferencePolicyService.has_valid_derivative_no_output_omission(
            context.node,
            omissions,
        ):
            return
        raise _error(
            "character_identity_master_binding_invalid",
            "Character Turnaround requires exactly one Ready Character Main image Binding.",
            details={"target_node_id": context.node.node_id},
        )


def _delivery_inputs_with_validated_character_identity_semantics(
    node: CanvasNodeV2,
    inputs: tuple[ResolvedMediaInputSnapshotV2, ...],
) -> tuple[ResolvedMediaInputSnapshotV2, ...]:
    """Project validated Character identity semantics into the delivery compiler."""

    if not (
        node.node_type == "image"
        and node.creative_role == "character"
        and node.structured_content.get("character_asset_kind") == "turnaround"
    ):
        return inputs
    return tuple(
        item.model_copy(
            update={
                "binding_metadata": {
                    **item.binding_metadata,
                    "reference_kind": "character_main",
                    "reference_purpose": "identity_guidance",
                }
            }
        )
        for item in inputs
    )


def _seedance_checksum(asset_id: str, version_id: str | None) -> str:
    return hashlib.sha256(f"{asset_id}:{version_id or ''}".encode()).hexdigest()
