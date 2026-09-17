"""Node-type dispatch boundary for Agent Canvas runs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from typing import Any, Protocol

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
from app.schemas.agent_canvas_runtime import (
    EffectiveMediaParameterSnapshotV2,
    ResolvedModelExecutionV1,
)
from app.schemas.workflow_v2 import V2ProviderResult
from app.schemas.seedance_inputs import (
    SeedanceDeliveredMediaInputV1,
    SeedanceInputManifestAuditV1,
    SeedanceInputManifestV1,
)
from app.schemas.agent_canvas_world_setting import WorldSettingContextEnvelopeV2
from app.services.agent_canvas_seedance_inputs import AgentCanvasSeedanceInputCompiler
from app.services.durable_pi_run import DurablePiRunService
from app.services.agent_operation_policy import AgentRunRequestFactory
from app.services.agent_run_context_registry import validate_video_agent_operation_context
from app.services.pi_agent_runtime_client import PiAgentRuntimeClient, PiAgentRuntimeError
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


@dataclass(frozen=True, slots=True)
class GeneratedMediaPayload:
    content: bytes
    mime_type: str
    filename: str
    metadata: dict[str, object] = field(default_factory=dict)


def _deadline_cap(timeout_seconds: float | None = None) -> datetime:
    """Deadline for one Agent run, defaulting to the configured run timeout.

    The effective deadline is the larger of the class hard deadline and the
    call-site cap, so a cap smaller than the policy budget cannot shorten
    the frozen budget below what the operation policy grants.
    """
    if timeout_seconds is None:
        timeout_seconds = get_settings().agent_runtime_run_timeout_seconds
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
    durable_runner: DurablePiRunService | None = None
    model_defaults: Mapping[str, str] | None = None


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

    def prepare(self, context: NodeExecutionContext) -> NodeExecutionContext:
        """Resolve provider-safe media before the scheduler starts provider work."""

        require_node_runnable(context.node)
        if context.node.node_type not in {"image", "video", "audio", "scene-3d"}:
            return context
        # P0-2: scene-3d nodes that already carry a Seedance manifest have
        # their media references pre-delivered; the Blender path (no
        # manifest) needs no provider-side reference delivery, only the
        # LLM SceneScript generation + Blender render.
        if context.node.node_type == "scene-3d" and context.seedance_manifest is None:
            return context
        _require_character_identity_master_input(context)
        media_inputs = tuple(
            item for item in context.inputs if isinstance(item, ResolvedMediaInputSnapshotV2)
        )
        AgentCanvasRoleReferencePolicyService().require_derivative_runtime_inputs(
            context.node,
            media_inputs,
        )
        if context.node.node_type in {"video", "scene-3d"}:
            if context.seedance_manifest is not None:
                return context
            if context.delivered_references:
                return context
        delivery = None
        if media_inputs:
            if context.model_resolution is None:
                raise _error(
                    "model_resolution_missing",
                    "Media reference delivery requires a frozen model resolution.",
                )
            delivery = self._reference_delivery.deliver_canvas_inputs(
                model_resolution=context.model_resolution,
                inputs=media_inputs,
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
        if context.node.node_type not in {"video", "scene-3d"}:
            return replace(
                context,
                delivered_references=delivered_references,
                optional_input_omissions=optional_input_omissions,
            )
        delivered_media = tuple(
            SeedanceDeliveredMediaInputV1(
                binding_id=reference.binding_id or f"asset_{reference.asset_id}",
                asset_id=reference.asset_id,
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
                if context.node.node_type == "video":
                    raise _error(
                        "model_resolution_missing",
                        "Video execution requires a frozen model resolution.",
                    )
            manifest, audit = self._seedance_inputs.compile(
                context.node,
                model_id=context.model_id
                or (context.model_resolution.model_ref if context.model_resolution else "none"),
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
            )
        except ValueError as error:
            code = str(error)
            if code != "v2_video_prompt_empty":
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
        if media_type == "video":
            return self._execute_seedance_video(self.prepare(context))
        effective_parameters = (
            context.effective_parameters.effective
            if context.effective_parameters is not None
            else context.node.parameters
        )
        if context.node.semantic_role == "bgm":
            _require_bgm_duration(effective_parameters)
        prompt = _saved_prompt(context)
        provider_payload: dict[str, Any] = {
            "provider_prompt": prompt,
            "prompt": prompt,
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
        prepared = self.prepare(context)
        if prepared.delivered_references:
            provider_payload["reference_assets"] = [
                reference.provider_asset() for reference in prepared.delivered_references
            ]
            provider_payload["reference_asset_ids"] = [
                reference.asset_id for reference in prepared.delivered_references
            ]
        intent = self._prepare_submission_intent(context, provider_payload)
        if intent is not None and intent.provider_idempotency_token is not None:
            provider_payload["idempotency_token"] = intent.provider_idempotency_token
        try:
            result = self._provider.execute_minimal(
                workflow_id=context.node.workflow_id,
                slot_type=context.node.semantic_role,
                media_type=media_type,
                provider_payload=provider_payload,
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
            mime_type, filename = _generated_media_identity(media_type, content)
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
            if intent is not None:
                self._submission_intents.complete(intent, now=self._clock())
            structured_content = None
            if context.node.node_type == "scene-3d":
                existing = dict(context.node.structured_content)
                reference_video = manifest.video_inputs[0] if manifest.video_inputs else None
                structured_content = {
                    **existing,
                    "scene_3d_provenance": {
                        "previs_asset_id": reference_video.asset_id if reference_video else None,
                        "model_id": result.provider_model,
                        "provider": result.provider,
                    },
                }
            return NodeExecutionOutcome(
                media=GeneratedMediaPayload(
                    content=content,
                    mime_type="video/mp4",
                    filename="video.mp4",
                    metadata={
                        "provider": result.provider,
                        "model_id": result.provider_model,
                        **dict(result.metadata),
                    },
                ),
                provider=result.provider,
                remote_task_id=result.remote_task_id,
                result_descriptor=dict(result.metadata),
                structured_content=structured_content,
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


def _generated_media_identity(media_type: str, content: bytes) -> tuple[str, str]:
    if media_type == "image" and content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "image.jpg"
    return {
        "image": ("image/png", "image.png"),
        "video": ("video/mp4", "video.mp4"),
        "audio": ("audio/mpeg", "audio.mp3"),
    }[media_type]


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
        scene_3d_executor: NodeExecutor | None = None,
        voice_cast_executor: NodeExecutor | None = None,
    ) -> None:
        self._executors = {
            "text": text_executor,
            "script": script_executor,
            "image": image_executor,
            "video": video_executor,
            "audio": audio_executor,
            "scene-3d": scene_3d_executor,
            "voice-cast": voice_cast_executor,
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

        def fake_scene_3d(context: NodeExecutionContext) -> NodeExecutionOutcome:
            """Fake scene-3d: return a minimal placeholder with scene_script."""
            prompt = (
                context.node.generation_prompt
                or context.node.summary_prompt
                or context.node.title
            )
            scene_script = context.node.structured_content.get("scene_script") or {
                "scene": {
                    "environment": "indoor",
                    "duration": 1,
                    "frame_rate": 24,
                    "characters": [],
                    "objects": [],
                    "camera": {"keyframes": []},
                }
            }
            return NodeExecutionOutcome(
                media=GeneratedMediaPayload(
                    content=b"\x00\x00\x00\x18ftypmp42FAKE_SCENE3D",
                    mime_type="video/mp4",
                    filename="scene_3d_fake.mp4",
                    metadata={"source_prompt": prompt},
                ),
                structured_content={
                    "scene_script": scene_script,
                    "frame_count": 24,
                    "fake": True,
                },
            )

        return NodeExecutionDispatcher(
            text_executor=fake_text,
            script_executor=fake_script,
            image_executor=fake_media,
            video_executor=fake_video,
            audio_executor=fake_media,
            scene_3d_executor=fake_scene_3d,
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

    def _build_durable_runner() -> DurablePiRunService:
        return DurablePiRunService(
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
        )

    def _scene_3d_executor(context: NodeExecutionContext) -> NodeExecutionOutcome:
        """scene-3d executor.

        Two paths:
        - seeded manifest present -> the previs render has already been
          published upstream and the scheduler now wants the video model to
          consume it (P0-2); run the provider Seedance flow instead;
        - no manifest -> Blender render (generate SceneScript via LLM when
          the node only carries a prompt).
        """
        if context.seedance_manifest is not None:
            return media._execute_seedance_video(media.prepare(context))
        if context.durable_runner is None and settings.agent_runtime_internal_token:
            context = replace(context, durable_runner=_build_durable_runner())
        return execute_scene_3d(context)

    return NodeExecutionDispatcher(
        text_executor=(
            TextNodeExecutor(
                _build_durable_runner(),
                timeout_seconds=settings.agent_runtime_run_timeout_seconds,
            )
            if settings.agent_runtime_internal_token
            else unavailable
        ),
        script_executor=(
            ScriptNodeExecutor(
                _build_durable_runner(),
                timeout_seconds=settings.agent_runtime_run_timeout_seconds,
            )
            if settings.agent_runtime_internal_token
            else unavailable
        ),
        image_executor=media,
        video_executor=media,
        audio_executor=media,
        scene_3d_executor=_scene_3d_executor,
        voice_cast_executor=execute_voice_cast,
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


def _json_input(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value



def execute_voice_cast(context: NodeExecutionContext) -> NodeExecutionOutcome:
    """Generate speech audio from dialogue lines via TTS.

    Expects a list of speech segments in node.structured_content["speech_segments"],
    each with: character_id, text, start_time (optional), end_time (optional),
    emotion (optional), voice_id (optional).

    If no speech_segments are found, falls back to using generation_prompt as
    a single dialogue line.

    Execution chain:
      speech_segments -> TTS per segment -> ffmpeg concat -> GeneratedMediaPayload (audio/wav)
    """
    import os
    import tempfile
    import subprocess

    from app.core.config import get_settings
    from app.services.scene3d.tts_engine_factory import create_tts_engine_from_settings

    settings = get_settings()

    # 1. Get speech segments from structured_content; fall back to prompt
    speech_segments = context.node.structured_content.get("speech_segments")
    if not speech_segments:
        prompt = context.node.generation_prompt or context.node.summary_prompt or context.node.title
        if not prompt or not prompt.strip():
            raise _error(
                "speech_segments_missing",
                "No speech segments found. Add dialogue lines to the node prompt "
                "or structured_content.speech_segments.",
            )
        speech_segments = [{"character_id": "narrator", "text": prompt.strip()}]

    # 2. Create TTS engine
    try:
        tts_engine = create_tts_engine_from_settings(settings)
    except Exception as exc:
        raise _error("tts_engine_creation_failed", f"Failed to create TTS engine: {exc}") from exc

    # 3. Generate audio for each segment
    output_dir = tempfile.mkdtemp(prefix="voice_cast_")
    audio_files = []
    segment_metadata = []

    for idx, segment in enumerate(speech_segments):
        character_id = segment.get("character_id", f"character_{idx}")
        text = segment.get("text", "").strip()
        emotion = segment.get("emotion")
        voice_id = segment.get("voice_id")

        if not text:
            continue

        output_path = os.path.join(output_dir, f"segment_{idx:04d}.mp3")
        try:
            result_path = tts_engine.synthesize(
                text=text,
                character_id=character_id,
                output_path=output_path,
                emotion=emotion,
                voice_id=voice_id,
            )
            if os.path.exists(result_path) and os.path.getsize(result_path) > 0:
                audio_files.append(result_path)
                segment_metadata.append({
                    "character_id": character_id,
                    "text": text,
                    "emotion": emotion,
                    "voice_id": voice_id,
                    "index": idx,
                })
        except Exception as exc:
            # Log but continue with other segments
            print(f"Warning: TTS failed for segment {idx}: {exc}")
            continue

    if not audio_files:
        raise _error(
            "tts_all_segments_failed",
            "All TTS segments failed. Check your TTS API key and provider configuration.",
        )

    # 4. Convert MP3 to WAV and concatenate
    wav_files = []
    for i, mp3_file in enumerate(audio_files):
        wav_file = os.path.join(output_dir, f"segment_{i:04d}_converted.wav")
        convert_cmd = [
            "ffmpeg", "-y", "-i", mp3_file,
            "-acodec", "pcm_s16le", "-ar", "24000", "-ac", "1",
            wav_file
        ]
        try:
            result = subprocess.run(convert_cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0 and os.path.exists(wav_file):
                wav_files.append(wav_file)
            else:
                print(f"Warning: ffmpeg convert failed for {mp3_file}: {result.stderr[:200]}")
                wav_files.append(mp3_file)  # fallback to original
        except Exception as e:
            print(f"Warning: ffmpeg convert exception: {e}")
            wav_files.append(mp3_file)  # fallback

    final_output = os.path.join(output_dir, "voice_cast_final.wav")
    if len(wav_files) == 1:
        # Single segment: just copy
        import shutil
        shutil.copy2(wav_files[0], final_output)
    else:
        # Multiple segments: use ffmpeg concat
        concat_file = os.path.join(output_dir, "concat_list.txt")
        with open(concat_file, "w", encoding="utf-8") as f:
            for wav_file in wav_files:
                # Use absolute paths with forward slashes for ffmpeg
                safe_path = wav_file.replace("\\", "/")
                f.write(f"file '{safe_path}'\n")

        ffmpeg_cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_file, "-c:a", "pcm_s16le", final_output
        ]
        try:
            result = subprocess.run(
                ffmpeg_cmd, capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0 or not os.path.exists(final_output):
                # Fallback: use first wav file
                import shutil
                shutil.copy2(wav_files[0], final_output)
        except Exception:
            # Fallback: use first wav file
            import shutil
            shutil.copy2(wav_files[0], final_output)

    # 5. Read final audio and return payload
    with open(final_output, "rb") as f:
        audio_content = f.read()

    return NodeExecutionOutcome(
        media=GeneratedMediaPayload(
            content=audio_content,
            mime_type="audio/wav",
            filename="voice_cast.wav",
            metadata={
                "segment_count": len(segment_metadata),
                "segments": segment_metadata,
                "tts_provider": getattr(tts_engine, "__class__", type(tts_engine)).__name__,
            },
        ),
        structured_content={
            "speech_segments": speech_segments,
            "generated_segments": segment_metadata,
        },
    )


def execute_scene_3d(context: NodeExecutionContext) -> NodeExecutionOutcome:
    """Render a SceneScript to video via Blender headless, with optional narration.

    Expects scene_script JSON in node.structured_content["scene_script"].
    Optional narration in node.structured_content["narration"] (text) and
    "narration_voice" (voice id, default "default").

    For sync execution, limits to 30 frames; longer scenes should use
    the POST /scene-3d/render/async endpoint.

    Execution chain:
      scene_script -> Blender PNG frames -> ffmpeg MP4
        -> (optional) TTS narration -> ffmpeg audio mux -> GeneratedMediaPayload
    """
    import os
    import tempfile

    from app.schemas.scene_script import SceneScriptRoot

    # 1. Get scene_script from structured_content; fall back to NL prompt
    #    generation (LLM) when the node only carries a generation_prompt.
    scene_script_data = context.node.structured_content.get("scene_script")
    if scene_script_data is None:
        scene_script_data = _generate_scene_script_from_prompt(context)
        # Persist the generated SceneScript on the outcome so _complete_member
        # publishes it with the node (frozen_node stays immutable; the live
        # node is what gets updated).
    if scene_script_data is None:
        raise _error(
            "scene_script_missing",
            "No SceneScript found and generation failed. Describe your scene "
            "in the node prompt to generate one, or use POST /scene-3d/parse "
            "with your prompt.",
        )
    try:
        scene_script = SceneScriptRoot.model_validate(scene_script_data)
    except Exception as exc:
        raise _error("scene_script_invalid", f"Invalid SceneScript: {exc}") from exc

    # 3. Sync executions render with a bounded frame budget; longer scenes
    # should go through the async render endpoint instead of blocking the
    # scheduler for minutes.  240 frames @ 30fps = 8s, well within the
    # 300s sync render budget (Eevee renders at ~0.8s/frame on CPU).
    total_frames = scene_script.total_frames
    sync_frame_limit = 300
    if total_frames > sync_frame_limit:
        raise _error(
            "scene_too_long_for_sync",
            f"Scene has {total_frames} frames (> {sync_frame_limit}). "
            "Use POST /scene-3d/render/async for long scenes.",
        )

    # 4. Render via Blender (PNG frames), with the geometric control passes
    #    (depth/normal/flow) produced in the same pass so downstream video
    #    models can consume them as control signals (ADR 0005 §4, P5).
    from app.services.scene3d.blender_renderer import render_scene_script
    from app.services.scene3d.control_passes import collect_control_passes

    # BLENDER_EXECUTABLE is an operator-local path, read from the process
    # environment; apps/api/.env supplies it via load_dotenv at startup.
    blender_exe = os.environ.get("BLENDER_EXECUTABLE")
    output_dir = tempfile.mkdtemp(prefix="scene3d_")
    render_result = render_scene_script(
        scene_script=scene_script,
        output_dir=output_dir,
        executable=blender_exe,
        timeout_seconds=300,
        include_control_passes=True,
    )
    if not render_result.success:
        raise _error(
            "blender_render_failed",
            render_result.error or "Blender render failed",
        )
    control_result = collect_control_passes(scene_script, output_dir)
    control_signals = {
        "completeness": control_result.completeness,
        "degradation_markers": control_result.degradation_markers,
    }

    # 5. Encode PNG frames to MP4
    from app.services.scene3d.encoder import encode_png_sequence

    video_path = os.path.join(output_dir, "output.mp4")
    encode_result = encode_png_sequence(
        input_dir=output_dir,
        output_path=video_path,
        fps=scene_script.scene.frame_rate,
    )
    if not encode_result.success or encode_result.output_path is None:
        raise _error(
            "video_encode_failed",
            encode_result.error or "Video encoding failed",
        )

    # 5b. Optional: generate narration audio via TTS and mux into video
    narration = context.node.structured_content.get("narration")
    narration_voice = context.node.structured_content.get("narration_voice", "default")
    has_narration = bool(narration and str(narration).strip())
    final_video_path = encode_result.output_path

    if has_narration:
        try:
            from app.core.config import get_settings
            from app.services.scene3d.tts_engine_factory import create_tts_engine_from_settings
            from app.services.scene3d.encoder import mux_audio_to_video

            settings = get_settings()
            tts_engine = create_tts_engine_from_settings(settings)
            audio_path = os.path.join(output_dir, "narration.mp3")
            tts_engine.synthesize(str(narration), str(narration_voice), audio_path)

            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                muxed_path = os.path.join(output_dir, "output_with_audio.mp4")
                mux_result = mux_audio_to_video(
                    video_path=encode_result.output_path,
                    audio_path=audio_path,
                    output_path=muxed_path,
                )
                if mux_result.success and mux_result.output_path:
                    final_video_path = mux_result.output_path
        except Exception as exc:
            # TTS/audio mux is best-effort; video without narration still works
            import logging
            logging.getLogger(__name__).warning(
                "Narration TTS/mux failed, continuing with video-only: %s", exc
            )

    # 6. Read video content
    with open(final_video_path, "rb") as f:
        video_content = f.read()

    if len(video_content) == 0:
        raise _error("video_empty", "Rendered video file is empty")

    # 7. Return outcome with media + structured_content.  The outcome's
    # structured_content is a full replacement at publish time, so it must
    # carry every key the user may have set directly (narration, etc.) plus
    # the new render results.
    existing_structured = dict(context.node.structured_content)
    return NodeExecutionOutcome(
        media=GeneratedMediaPayload(
            content=video_content,
            mime_type="video/mp4",
            filename="scene_3d_output.mp4",
            metadata={
                "frame_count": render_result.frame_count,
                "render_duration_seconds": getattr(
                    render_result, "duration_seconds", None
                ),
                "has_narration": has_narration,
                "narration_voice": str(narration_voice) if has_narration else None,
            },
        ),
        structured_content={
            **existing_structured,
            "scene_script": scene_script.model_dump(mode="json"),
            "frame_count": render_result.frame_count,
            "control_signals": control_signals,
        },
    )


def _generate_scene_script_from_prompt(
    context: NodeExecutionContext,
) -> dict[str, object] | None:
    """Generate a SceneScript from the node's natural-language prompt.

    Uses the LLM (via the 3D Storyboard skill) to produce a SceneScript
    JSON object, then validates it via the parser. Returns the validated
    dict, or None when no runner/prompt is available. Provider-level
    failures and parse failures raise ``scene_script_generation_failed`` /
    ``scene_script_parse_failed`` so the node error carries the real cause.
    """
    prompt = _saved_prompt(context)
    if not prompt.strip():
        return None

    from app.core.config import get_settings
    from app.services.agent_operation_policy import AgentRunRequestFactory
    from app.services.agent_run_context_registry import validate_video_agent_operation_context
    from app.schemas.agent_runtime import AgentRunContext, AgentRunCompletedPayload
    from app.services.scene3d.parser import parse_llm_output

    settings = get_settings()
    if not hasattr(settings, "agent_runtime_mode") or settings.agent_runtime_mode == "fake":
        # In fake mode, no real LLM is available; return None so the caller
        # surfaces a clear "no scene_script" error instead of a silent stub.
        return None

    # Reuse the same durable runner as the text/script executors so the
    # SceneScript generation path goes through the same agent runtime.
    durable_runner = context.durable_runner
    if durable_runner is None:
        return None

    run_context = AgentRunContext(
        operation="execute_canvas_scene_3d",
        user_input=prompt,
        workflow_id=context.node.workflow_id,
        world_setting=context.world_setting,
        target=None,
        input_payload={"resolved_inputs": [_json_input(item) for item in context.inputs]},
    )
    validate_video_agent_operation_context("execute_canvas_scene_3d", run_context)

    request = AgentRunRequestFactory().build(
        run_id="candidate_agent_run",
        request_id="candidate_agent_request",
        agent_name="video_agent",
        operation="execute_canvas_scene_3d",
        deadline_cap=_deadline_cap(),
        model_ref=_scene_3d_model_ref(context),
        context=run_context,
        contract_name="AgentCanvasScene3DOutput",
        contract_schema=_agent_canvas_scene_3d_output_schema(),
        audit_metadata={"tool_mode": "structured_only"},
    )

    try:
        result = durable_runner.run(
            request,
            identity_fields={
                "workflow_id": context.node.workflow_id,
                "execution_id": context.execution_id,
                "node_id": context.node.node_id,
                "node_revision": context.node.revision,
                "agent_name": "video_agent",
                "operation": "execute_canvas_scene_3d",
            },
            model_ref=_scene_3d_model_ref(context),
        )
    except PiAgentRuntimeError as error:
        # A terminal failure from the agent runtime (provider timeout,
        # structured-output invalid after repair attempts, ...) is a real
        # generation failure: surface it with the stable error code instead
        # of silently producing "generation failed" with no detail.
        raise _error(
            error.code or "scene_script_generation_failed",
            error.message or "SceneScript generation failed.",
            details={"stage": "scene_script_generation"},
        ) from error
    except Exception as error:
        raise _error(
            "scene_script_generation_failed",
            "SceneScript generation failed: " + str(error),
            details={"stage": "scene_script_generation"},
        ) from error

    completed = AgentRunCompletedPayload.model_validate(result.terminal_payload)
    raw_output = completed.value.get("raw_output", "")
    if not isinstance(raw_output, str) or not raw_output.strip():
        # The skill instructs the model to emit ONLY a ```json-fenced
        # SceneScript object.  Depending on how the structured tool wraps
        # the LLM text, it may end up under ``content`` / ``raw_output`` /
        # the top-level value.  Try them in order.
        raw_output = ""
        for key in ("raw_output", "content", "output", "text"):
            candidate = completed.value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                raw_output = candidate
                break
        if not raw_output:
            return None

    parse_result = parse_llm_output(raw_output)
    if not parse_result.success or parse_result.scene_script is None:
        raise _error(
            "scene_script_parse_failed",
            parse_result.error or "LLM output could not be parsed into a SceneScript.",
            details={"raw_output_preview": raw_output[:500], "parse_errors": parse_result.error_details},
        )
    return parse_result.scene_script.model_dump(mode="json")


def _agent_canvas_scene_3d_output_schema() -> dict[str, object]:
    from app.schemas.agent_runtime import AgentCanvasScene3DOutput

    return AgentCanvasScene3DOutput.model_json_schema()


def _scene_3d_model_ref(context: NodeExecutionContext) -> str:
    """Resolve the Agent text model ref for scene-3d SceneScript generation.

    Scene-3d nodes carry no model resolution of their own (model_selection
    is bypassed for node_type "scene-3d"), so the NL->SceneScript LLM step
    falls back to the installation Agent text default ("agent" key) from the
    provider model catalog repository.
    """
    if context.model_resolution is not None:
        return context.model_resolution.model_ref
    agent_default = (context.model_defaults or {}).get("agent")
    if agent_default is None:
        from app.core.config import get_settings
        from app.persistence.database import create_v2_database
        from app.persistence.provider_model_repository import ProviderModelRepository

        settings = get_settings()
        database = create_v2_database(settings.media_data_dir)
        defaults = ProviderModelRepository(database).get_defaults()
        agent_default = next(
            (record.model_ref for record in defaults.values() if record.default_key == "agent"),
            None,
        )
    if agent_default is None:
        raise _error(
            "agent_model_default_missing",
            "No Agent text default is configured; SceneScript generation "
            "requires the 'agent' model default.",
        )
    return agent_default.model_ref if hasattr(agent_default, "model_ref") else str(agent_default)


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
        "required": source.required if source is not None else True,
        "reason": failure.reason,
    }


def _require_character_identity_master_input(context: NodeExecutionContext) -> None:
    if not (
        context.node.node_type == "image"
        and context.node.creative_role == "character"
        and context.node.structured_content.get("character_asset_kind") == "turnaround"
    ):
        return
    candidates = tuple(
        item
        for item in context.inputs
        if isinstance(item, ResolvedMediaInputSnapshotV2)
        and item.source_kind == "node_output"
        and item.source_semantic_role == "character"
        and item.media_type == "image"
        and item.input_role == "image_reference"
        and item.required
        and item.binding_metadata.get("reference_purpose") == "identity_master"
        and item.binding_metadata.get("semantic_reference_role") == "subject_reference"
    )
    if len(candidates) != 1:
        raise _error(
            "character_identity_master_binding_invalid",
            "Character Turnaround requires exactly one Ready Character Main image Binding.",
            details={"target_node_id": context.node.node_id},
        )


def _seedance_checksum(asset_id: str, version_id: str | None) -> str:
    return hashlib.sha256(f"{asset_id}:{version_id or ''}".encode()).hexdigest()
