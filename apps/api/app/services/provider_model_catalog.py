"""Trusted model manifests and deterministic provider catalog synchronization."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from app.persistence.provider_model_repository import (
    ModelDefaultRecord,
    ProviderModelConformanceRunRecord,
    ProviderModelRecord,
    ProviderModelRepository,
)
from app.schemas.provider_models import ProviderAdapterProfileV1
from app.services.openrouter_policy import build_openrouter_routing_policy
from app.services.provider_credentials import ProviderHttpTransport, UrllibProviderHttpTransport
from app.services.agnes_image_contract import (
    AGNES_IMAGE_RATIOS,
    AGNES_IMAGE_SIZES_BY_ASPECT_RATIO,
)
from app.services.stepfun_image_contract import STEPFUN_IMAGE_SIZES_BY_ASPECT_RATIO


class ProviderCatalogAdapter(Protocol):
    """Expose provider-visible IDs without granting application capabilities."""

    provider_id: str

    def discover_model_ids(self) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class TrustedModelManifest:
    provider_id: str
    provider_model_id: str
    display_name: str
    capability: str
    capability_metadata: Mapping[str, Any]
    adapter_profile: Mapping[str, Any] | None = None

    @property
    def model_ref(self) -> str:
        return f"{self.provider_id}:{self.provider_model_id}"


@dataclass(frozen=True)
class CatalogSyncResult:
    sync_run_id: str
    provider_id: str
    status: str
    catalog_revision: int | None


GUIDED_IMAGE_SIZES_BY_ASPECT_RATIO: Mapping[str, str] = {
    "1:1": "2048x2048",
    "16:9": "2560x1440",
    "9:16": "1440x2560",
    "4:3": "2304x1728",
    "3:4": "1728x2304",
}


def _adapter_profile(
    *,
    model_ref: str,
    adapter_id: str,
    transport_kind: str,
    capability: str,
    request_mode: str,
    accepted_input_modes: tuple[str, ...],
    max_images: int,
    allowed_roles: tuple[str, ...],
    parameter_schema_id: str,
    result_protocol: str,
    supports_remote_task_lookup: bool,
    supports_provider_idempotency: bool,
    conformance_status: str,
    adapter_revision: str,
    capability_revision: str,
    release_tier: str = "optional",
    parameter_matrix: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "model_ref": model_ref,
        "adapter_id": adapter_id,
        "transport_kind": transport_kind,
        "capability": capability,
        "request_mode": request_mode,
        "accepted_input_modes": list(accepted_input_modes),
        "reference_policy": {
            "modes": [
                {
                    "mode": mode,
                    "max_references": max_images if mode != "text_only" else 0,
                    "allowed_roles": list(allowed_roles) if mode != "text_only" else [],
                }
                for mode in accepted_input_modes
            ],
            "max_images": max_images,
        },
        "parameter_schema_id": parameter_schema_id,
        "result_protocol": result_protocol,
        "supports_remote_task_lookup": supports_remote_task_lookup,
        "supports_provider_idempotency": supports_provider_idempotency,
        "release_tier": release_tier,
        "conformance_status": conformance_status,
        "adapter_revision": adapter_revision,
        "capability_revision": capability_revision,
    }
    if parameter_matrix is not None:
        profile["parameter_matrix"] = dict(parameter_matrix)
    return profile


def _parameter_matrix(
    *,
    schema_id: str,
    descriptors: tuple[Mapping[str, Any], ...],
    legal_combinations: tuple[Mapping[str, Any], ...] = (),
) -> dict[str, Any]:
    return {
        "schema_id": schema_id,
        "revision": f"{schema_id}-v1",
        "descriptors": [dict(descriptor) for descriptor in descriptors],
        "legal_combinations": [dict(combination) for combination in legal_combinations],
    }


def _image_profile(
    model_ref: str,
    *,
    adapter_id: str,
    transport_kind: str,
    conformance_status: str = "compatible",
    parameter_matrix: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return _adapter_profile(
        model_ref=model_ref,
        adapter_id=adapter_id,
        transport_kind=transport_kind,
        capability="image",
        request_mode="image_generation",
        accepted_input_modes=("text_only", "native_reference_slots"),
        max_images=4,
        allowed_roles=("product_reference", "scene_reference", "character_reference"),
        parameter_schema_id=(
            str(parameter_matrix["schema_id"])
            if parameter_matrix is not None
            else "image-generation-v1"
        ),
        result_protocol="image_data",
        supports_remote_task_lookup=False,
        supports_provider_idempotency=False,
        conformance_status=conformance_status,
        adapter_revision=f"{adapter_id}-v1",
        capability_revision=f"{model_ref.replace(':', '-')}-v1",
        parameter_matrix=parameter_matrix,
    )


def _stepfun_image_metadata() -> dict[str, Any]:
    """Capability metadata for a StepFun step_plan image model.

    Deliberately adapter-free (see the comment in ``_TRUSTED_MANIFESTS``): the
    model is executed through the real-media path keyed off
    ``IMAGE_GENERATION_ENDPOINT`` / ``IMAGE_GENERATION_API_KEY``, so the
    capability record only has to describe what the model accepts.  The
    ``provider_protocol`` stays ``ark_image`` because
    ``serialize_volcengine_image_generation_request`` is the wire shape the
    gateway accepts -- that function's name is historical; the endpoint it
    targets is StepFun's.
    """

    return {
        "accepted_input_types": ["text", "image"],
        "max_references": 8,
        "reference_limits": {"image": 8, "video": 0, "audio": 0},
        "supported_parameters": ["aspect_ratio", "size"],
        "supported_aspect_ratios": list(STEPFUN_IMAGE_SIZES_BY_ASPECT_RATIO),
        # StepFun's own size table, not the Volcengine Ark one.  The Ark table
        # (2048x2048 / 2560x1440 / ...) was advertised here until 2026-09-21,
        # which told every caller these models accept resolutions they have
        # never accepted -- and the guided-parameter compiler reads exactly this
        # field to pick a size, so the wrong table produced wrong requests.
        "supported_sizes_by_aspect_ratio": dict(STEPFUN_IMAGE_SIZES_BY_ASPECT_RATIO),
        # Deliberately loose.  The largest documented ``step-image-edit-2``
        # *output* frame is 1360x768, but this gate only asks "could this
        # provider serve a node asking for this size?" -- the serializer maps
        # anything outside the documented set onto the nearest supported value,
        # so being permissive here and precise there is the correct split.  The
        # 4096 ceiling is the documented maximum input image resolution.
        "pixel_bounds": [256, 4096],
        "provider_protocol": "ark_image",
        "openai_compatible_image_generation": True,
        "supports_provider_idempotency_token": False,
        "supports_remote_task_lookup": False,
    }


def _agnes_image_metadata() -> dict[str, Any]:
    """Capability metadata for an Agnes image model.

    Adapter-free for the same reason the StepFun rows are: there is no native
    adapter transport for these, so ``_execute_native_minimal`` falls through to
    the real-media path keyed off ``IMAGE_GENERATION_ENDPOINT`` -- which is where
    the Agnes contract is actually honoured.  Adding an adapter profile would
    turn a working model into ``provider_transport_unavailable``.

    The ``provider_protocol`` stays ``ark_image`` because
    ``serialize_volcengine_image_generation_request`` remains the wire shape;
    that function branches per provider and is where ``watermark`` and
    ``sequential_image_generation`` are dropped for Agnes.
    """

    return {
        "accepted_input_types": ["text", "image"],
        "max_references": 8,
        "reference_limits": {"image": 8, "video": 0, "audio": 0},
        "supported_parameters": ["aspect_ratio", "size"],
        "supported_aspect_ratios": list(AGNES_IMAGE_RATIOS),
        # Agnes' own table, which is ``width x height`` -- the opposite
        # orientation convention from StepFun's ``height x width``.  The guided
        # parameter compiler reads exactly this field to choose a size, so
        # copying the StepFun table in here would rotate every Agnes frame.
        "supported_sizes_by_aspect_ratio": dict(AGNES_IMAGE_SIZES_BY_ASPECT_RATIO),
        # Looser than the table, for the same reason as the StepFun rows: this
        # gate asks "could this provider serve a node asking for this size?",
        # and Agnes normalizes an off-table size server-side rather than
        # refusing it.  The ceiling is the documented 4K tier.
        "pixel_bounds": [256, 6272],
        "provider_protocol": "ark_image",
        "openai_compatible_image_generation": True,
        "supports_provider_idempotency_token": False,
        "supports_remote_task_lookup": False,
    }


def _ark_video_profile(
    model_ref: str,
    *,
    release_tier: str = "optional",
) -> dict[str, Any]:
    return _adapter_profile(
        model_ref=model_ref,
        adapter_id="ark-video-native",
        transport_kind="ark_video_native",
        capability="video",
        request_mode="video_generation",
        accepted_input_modes=("text_only", "native_reference_slots"),
        max_images=15,
        allowed_roles=(
            "character_turnaround",
            "product_reference",
            "scene_reference",
            "storyboard",
        ),
        parameter_schema_id="ark-video-generation-v1",
        result_protocol="async_file",
        supports_remote_task_lookup=True,
        supports_provider_idempotency=False,
        conformance_status="compatible",
        adapter_revision="ark-video-native-v1",
        capability_revision=f"{model_ref.replace(':', '-')}-v1",
        release_tier=release_tier,
        parameter_matrix=_parameter_matrix(
            schema_id="ark-video-generation-v1",
            descriptors=(
                {
                    "name": "duration_seconds",
                    "value_type": "integer",
                    "minimum": 1,
                    "maximum": 15,
                    "default": 5,
                },
                {
                    "name": "resolution",
                    "value_type": "enum",
                    "allowed_values": ("480p", "720p", "1080p"),
                },
                {
                    "name": "aspect_ratio",
                    "value_type": "enum",
                    "allowed_values": ("16:9", "9:16", "1:1"),
                },
                {"name": "generate_audio", "value_type": "boolean", "default": False},
            ),
        ),
    )


def _minimax_video_profile(model_ref: str, provider_model_id: str) -> dict[str, Any]:
    return _adapter_profile(
        model_ref=model_ref,
        adapter_id="minimax-video-native",
        transport_kind="minimax_video_native",
        capability="video",
        request_mode="video_generation",
        accepted_input_modes=("text_only", "text_plus_single_first_frame_image"),
        max_images=1,
        allowed_roles=("storyboard", "scene_reference", "character_turnaround"),
        parameter_schema_id="minimax-hailuo-i2v-v1",
        result_protocol="async_file",
        supports_remote_task_lookup=True,
        supports_provider_idempotency=True,
        conformance_status="unverified",
        adapter_revision="minimax-video-native-v1",
        capability_revision=f"minimax-{provider_model_id}-i2v-v1",
        parameter_matrix=_parameter_matrix(
            schema_id="minimax-hailuo-i2v-v1",
            descriptors=(
                {
                    "name": "duration",
                    "value_type": "integer",
                    "minimum": 6,
                    "maximum": 10,
                },
                {
                    "name": "resolution",
                    "value_type": "enum",
                    "allowed_values": ("768P", "1080P"),
                },
                {
                    "name": "aspect_ratio",
                    "value_type": "enum",
                    "allowed_values": ("16:9", "9:16", "1:1"),
                },
                {"name": "generate_audio", "value_type": "boolean"},
            ),
            legal_combinations=(
                {"duration": 6, "resolution": "768P"},
                {"duration": 6, "resolution": "1080P"},
                {"duration": 10, "resolution": "768P"},
                {"duration": 10, "resolution": "1080P"},
            ),
        ),
    )


_HISTORICAL_OPENAI_IMAGE_PROFILE = _image_profile(
    "openai:gpt-image-2",
    adapter_id="openai-image-native",
    transport_kind="openai_images_native",
    conformance_status="unverified",
    parameter_matrix=_parameter_matrix(
        schema_id="openai-gpt-image-2-v1",
        descriptors=(
            {
                "name": "size",
                "value_type": "enum",
                "allowed_values": ("1024x1024", "1536x1024", "1024x1536", "auto"),
            },
            {
                "name": "quality",
                "value_type": "enum",
                "allowed_values": ("low", "medium", "high", "auto"),
            },
            {
                "name": "background",
                "value_type": "enum",
                "allowed_values": ("transparent", "opaque", "auto"),
            },
            {
                "name": "output_format",
                "value_type": "enum",
                "allowed_values": ("png", "jpeg", "webp"),
            },
            {
                "name": "moderation",
                "value_type": "enum",
                "allowed_values": ("low", "auto"),
            },
        ),
    ),
)
_OPENROUTER_IMAGE_ADAPTER_REVISION = "openrouter-image-native-v1"
_OPENROUTER_IMAGE_CAPABILITY_REVISION = "openrouter-openai/gpt-image-2-v1"
_OPENROUTER_IMAGE_PROFILE = _image_profile(
    "openrouter:openai/gpt-image-2",
    adapter_id="openrouter-image-native",
    transport_kind="openrouter_images_native",
    conformance_status="unverified",
    parameter_matrix=_parameter_matrix(
        schema_id="openrouter-gpt-image-2-v1",
        descriptors=(
            {
                "name": "size",
                "value_type": "enum",
                "allowed_values": ["1024x1024", "1536x1024", "1024x1536", "auto"],
            },
            {
                "name": "quality",
                "value_type": "enum",
                "allowed_values": ["low", "medium", "high", "auto"],
            },
            {
                "name": "background",
                "value_type": "enum",
                "allowed_values": ["transparent", "opaque", "auto"],
            },
            {
                "name": "output_format",
                "value_type": "enum",
                "allowed_values": ["png", "jpeg", "webp"],
            },
            {
                "name": "output_compression",
                "value_type": "integer",
                "minimum": 0,
                "maximum": 100,
            },
            {
                "name": "resolution",
                "value_type": "enum",
                "allowed_values": ["1K", "2K", "4K"],
            },
            {
                "name": "aspect_ratio",
                "value_type": "enum",
                "allowed_values": ["1:1", "16:9", "9:16", "4:3", "3:4"],
            },
        ),
    ),
)
_OPENROUTER_IMAGE_ROUTING = build_openrouter_routing_policy(
    model_ref="openrouter:openai/gpt-image-2",
    adapter_revision=_OPENROUTER_IMAGE_ADAPTER_REVISION,
    capability_revision=_OPENROUTER_IMAGE_CAPABILITY_REVISION,
    operation_contract="openrouter-gpt-image-2-v1",
)

_OPENROUTER_TEXT_ADAPTER_REVISION = "openrouter-pi-agent-v1"
_OPENROUTER_TEXT_CAPABILITY_REVISION = "openrouter-openai-gpt-5-6-sol-agent-v1"
_OPENROUTER_TEXT_PROFILE = _adapter_profile(
    model_ref="openrouter:openai/gpt-5.6-sol",
    adapter_id="openrouter-pi-agent-v1",
    transport_kind="pi_native_openai_compatible",
    capability="text",
    request_mode="agent_structured",
    accepted_input_modes=("text_only",),
    max_images=0,
    allowed_roles=(),
    parameter_schema_id="openrouter-agent-text-v1",
    result_protocol="structured_agent_result",
    supports_remote_task_lookup=False,
    supports_provider_idempotency=False,
    conformance_status="unverified",
    adapter_revision=_OPENROUTER_TEXT_ADAPTER_REVISION,
    capability_revision=_OPENROUTER_TEXT_CAPABILITY_REVISION,
)
_OPENROUTER_TEXT_ROUTING = build_openrouter_routing_policy(
    model_ref="openrouter:openai/gpt-5.6-sol",
    adapter_revision=_OPENROUTER_TEXT_ADAPTER_REVISION,
    capability_revision=_OPENROUTER_TEXT_CAPABILITY_REVISION,
    operation_contract="openrouter-agent-text-v1",
)
_MINIMAX_VIDEO_PROFILES = {
    model_id: _minimax_video_profile(f"minimax:{model_id}", model_id)
    for model_id in (
        "MiniMax-Hailuo-2.3",
        "MiniMax-Hailuo-2.3-Fast",
        "MiniMax-Hailuo-02",
    )
}


def _video_capability_metadata(
    profile: Mapping[str, Any],
    *,
    duration_range_seconds: tuple[int, int] = (1, 15),
    max_references: int = 15,
    provider_protocol: str = "ark_video",
) -> dict[str, Any]:
    return {
        "accepted_input_types": ["text", "image", "video", "audio"],
        "max_references": max_references,
        "reference_limits": {"image": min(max_references, 9), "video": 3, "audio": 3},
        "supported_parameters": [
            "aspect_ratio",
            "resolution",
            "duration_seconds",
            "generate_audio",
        ],
        "supported_aspect_ratios": ["16:9", "9:16", "1:1"],
        "supported_resolutions": ["480p", "720p", "1080p"],
        "duration_range_seconds": list(duration_range_seconds),
        "supports_native_audio": True,
        "provider_protocol": provider_protocol,
        "supports_provider_idempotency_token": False,
        "supports_remote_task_lookup": True,
        "adapter_profile": dict(profile),
    }


_TRUSTED_MANIFESTS = (
    TrustedModelManifest(
        provider_id="siliconflow",
        provider_model_id="zai-org/GLM-5.2",
        display_name="GLM-5.2",
        capability="text",
        capability_metadata={
            "agent_compatible": True,
            "provider_protocol": "openai_compatible",
            "accepted_input_types": ["text"],
            "supports_structured_output": True,
            "supports_tool_calls": True,
            "supports_streaming": True,
            "supports_streamed_tool_calls": False,
            "supports_reasoning_controls": True,
            "thinking_format": "zai",
            "reasoning_control": "enable_thinking",
            "structured_transport": "non_streaming_json_object",
            "default_max_output_tokens": 8192,
        },
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seed-2-0-mini-260428",
        display_name="Doubao Seed 2.0 Mini",
        capability="text",
        capability_metadata={
            "agent_compatible": True,
            "adapter_id": "volcengine_ark-pi-agent-v1",
            "adapter_revision": "volcengine_ark-pi-agent-v1",
            "transport_kind": "pi_native_openai_compatible",
            "capability_revision": ("volcengine-ark-doubao-seed-2-0-mini-260428-agent-v1"),
            "provider_protocol": "openai_compatible",
            "accepted_input_types": ["text"],
            "supports_structured_output": True,
            "supports_tool_calls": True,
            "supports_streaming": True,
            "supports_streamed_tool_calls": False,
            "supports_reasoning_controls": False,
            "thinking_format": "none",
            "reasoning_control": "none",
            "structured_transport": "non_streaming_tool_call",
            "default_max_output_tokens": 8192,
        },
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seed-2-1-pro-260628",
        display_name="Doubao Seed 2.1 Pro",
        capability="text",
        capability_metadata={
            "agent_compatible": True,
            "adapter_id": "volcengine_ark-pi-agent-v1",
            "adapter_revision": "volcengine_ark-pi-agent-v1",
            "transport_kind": "pi_native_openai_compatible",
            "capability_revision": "volcengine-ark-doubao-seed-2-1-pro-260628-agent-v1",
            "provider_protocol": "openai_compatible",
            "accepted_input_types": ["text"],
            "supports_structured_output": True,
            "supports_tool_calls": False,
            "supports_streaming": False,
            "supports_streamed_tool_calls": False,
            "supports_reasoning_controls": True,
            "thinking_format": "none",
            "reasoning_control": "reasoning_effort",
            "structured_transport": "non_streaming_json_object",
            "default_max_output_tokens": 8192,
        },
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seedream-5-0-lite-260128",
        display_name="Doubao Seedream 5.0 Lite",
        capability="image",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 8,
            "reference_limits": {"image": 8, "video": 0, "audio": 0},
            "supported_parameters": ["aspect_ratio", "size"],
            "supported_aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
            "supported_sizes_by_aspect_ratio": dict(GUIDED_IMAGE_SIZES_BY_ASPECT_RATIO),
            "pixel_bounds": [512, 4096],
            "provider_protocol": "ark_image",
            "supports_provider_idempotency_token": False,
            "supports_remote_task_lookup": False,
            "adapter_profile": _image_profile(
                "volcengine_ark:doubao-seedream-5-0-lite-260128",
                adapter_id="ark-image-native",
                transport_kind="ark_image_native",
            ),
        },
    ),
    # StepFun's step_plan gateway is the only image endpoint this deployment is
    # configured against (``IMAGE_GENERATION_ENDPOINT``), and it proxies exactly
    # two 文生图 models.  Both are registered WITHOUT an ``adapter_profile`` on
    # purpose: there is no native adapter for them (no transport is injected for
    # ``ark_image_native``/``stepfun_image_native`` anywhere in
    # ``provider_adapter_registry``), so ``_execute_native_minimal`` must fall
    # through to the real-media path that reads ``IMAGE_GENERATION_*`` -- which
    # is how ``step-image-edit-2`` has always actually run.  Adding an adapter
    # profile here would turn a working model into
    # ``provider_transport_unavailable``.
    TrustedModelManifest(
        provider_id="stepfun",
        provider_model_id="step-image-edit-2",
        display_name="Step Image Edit 2",
        capability="image",
        capability_metadata=_stepfun_image_metadata(),
    ),
    TrustedModelManifest(
        provider_id="stepfun",
        provider_model_id="step-2x-large",
        display_name="Step 2X Large",
        capability="image",
        capability_metadata=_stepfun_image_metadata(),
    ),
    # Agnes is the fallback image vendor, on a different host with a different
    # key (``VIDEO_GENERATION_API_KEY`` -- see ``Settings.image_generation_credential``).
    # It exists because StepFun's image engine answered 503 ``engine_overloaded``
    # to every request for two days while the rest of that host kept working, and
    # an operator had no way to route around it.  Both rows are adapter-free for
    # the same reason the StepFun rows are.  ``agnes-image-2.1-flash`` is kept
    # because the documented request shape is written against it and 2.5 Flash
    # declares itself parameter-compatible with it.
    TrustedModelManifest(
        provider_id="agnes",
        provider_model_id="agnes-image-2.5-flash",
        display_name="Agnes Image 2.5 Flash",
        capability="image",
        capability_metadata=_agnes_image_metadata(),
    ),
    TrustedModelManifest(
        provider_id="agnes",
        provider_model_id="agnes-image-2.1-flash",
        display_name="Agnes Image 2.1 Flash",
        capability="image",
        capability_metadata=_agnes_image_metadata(),
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seedance-2-0-fast-260128",
        display_name="Doubao Seedance 2.0 Fast",
        capability="video",
        capability_metadata={
            "accepted_input_types": ["text", "image", "video", "audio"],
            "max_references": 15,
            "reference_limits": {"image": 9, "video": 3, "audio": 3},
            "supported_parameters": [
                "aspect_ratio",
                "resolution",
                "duration_seconds",
                "generate_audio",
            ],
            "supported_aspect_ratios": ["16:9", "9:16", "1:1"],
            "supported_resolutions": ["480p", "720p", "1080p"],
            "duration_range_seconds": [1, 15],
            "supports_native_audio": True,
            "default_parameters": {
                "duration_seconds": 5,
                "resolution": "720p",
                "aspect_ratio": "16:9",
                "generate_audio": False,
            },
            "provider_protocol": "ark_video",
            "supports_provider_idempotency_token": False,
            "supports_remote_task_lookup": True,
            "adapter_profile": _ark_video_profile(
                "volcengine_ark:doubao-seedance-2-0-fast-260128",
                release_tier="default",
            ),
        },
    ),
    # The video endpoint this deployment actually calls
    # (``VIDEO_GENERATION_MODEL=agnes-video-2.5``,
    # ``VIDEO_GENERATION_ENDPOINT``).  It is registered under ``volcengine_ark``
    # because that is the protocol family and the credential slot it runs on, and
    # WITHOUT an ``adapter_profile`` for the same reason the StepFun and Agnes
    # image rows carry none: the request goes out through
    # ``seedance_adapter``'s Agnes branch, not through a native adapter.
    #
    # This row used to name ``agnes-video-2.5-flash``, and it was switched to the
    # non-flash SKU on 09-24 because ``-flash`` does not accept the ``videos``
    # parameter at all -- not "one element", *none*.  What the endpoint said,
    # verbatim:
    #
    #     400 invalid_request
    #     {"code":"invalid_request","message":"当前模型不支持 videos",
    #      "data":{"param":"videos"}}
    #
    # The refusal is for the request as a whole, so a bound previs clip did not
    # merely get dropped -- it took the whole segment down.  Any future request
    # that puts a URL in ``videos`` has to go to this SKU; ``-flash`` can only
    # ever carry ``images``/``audio``.
    #
    # Both of the image limits below -- the count and the aspect-ratio window --
    # were measured on ``-flash``, because that was the SKU this deployment ran
    # when they were learned.  Nothing re-measured them on this one.  They are
    # kept as-is because under-declaring costs budget while over-declaring costs
    # the whole request, and the documented numbers were never an accepted
    # request from *any* Agnes endpoint.
    #
    # ``reference_limits.image`` is 5, not the 9 the Doubao rows use.  The Agnes
    # endpoint enforces its own cap and says so in the refusal:
    #
    #     400 invalid_request
    #     {"code":"invalid_request","message":"images 数量不能超过 5",
    #      "data":{"max_images":5,"param":"images"}}
    #
    # which is what a bound shot carrying more than five image references got on
    # 09-22 -- the node failed non-retryably with ``provider_generation_failed``
    # while our own metadata said nine were fine, so the reference budget walked
    # in eight and the provider rejected the request we built.  Declaring nine
    # here is what let that happen; nothing in our code re-checks a provider's
    # own limit before submitting.
    #
    # The Agnes documentation for this SKU family states that ``images`` holds at
    # most **8**, which is not the number below.  The ``400`` above was observed
    # on ``-flash`` -- the SKU this row used to name -- and it says 5; the 8 is
    # documentation, never an accepted request from *this* endpoint.  Declaring 8
    # would buy three more slots for requests the endpoint may well refuse whole,
    # which is the exact failure this value exists to prevent.  **Leave it at 5**;
    # revisit only with a 200 from ``agnes-video-2.5`` that carries more.
    #
    # ``reference_limits.video`` is 1, because the endpoint's ``videos`` field is
    # a one-element array; a second clip in the request is refused, not ignored.
    # This row used to declare 3, which let ``apply_provider_reference_limits``
    # walk three previs clips into a request that could carry one -- three of
    # them for this shot.  It stayed wrong because the channel it governs was
    # unreachable: nothing in the stack could produce a publicly reachable video
    # URL, and the Agnes branch of ``seedance_adapter.payload_for_manifest``
    # never built a ``videos`` array at all.  Both of those are fixed now, so the
    # number is load-bearing and said plainly.
    #
    # **The 1 is now observed, not documented.**  On 09-24 this SKU accepted a
    # request carrying one previs clip in ``videos`` alongside two image
    # references and rendered it: ``task_Rs42UF9UxpleZPta0TWBychhX90UPLMM``, 7s,
    # 2,767,095 bytes, stored by the provider at
    # ``.../videos/agnes-video-2.5/<task id>.mp4``.  What is still *not*
    # observed is a request carrying **two** clips -- the endpoint's schema says
    # the array holds one, and that remains the only evidence for the cap.
    # If a second clip is ever refused, that is the value to revisit, not this 1.
    #
    # ``reference_limits.audio`` is 3, which matches the endpoint's own cap.
    #
    # ``reference_image_aspect_ratio_range`` records the second limit this same
    # endpoint enforces on its ``images`` field, which we did not declare and so
    # could not check:
    #
    #     400 invalid_request
    #     {"code":"invalid_request",
    #      "message":"输入图宽高比必须在 0.4–2.5 之间","data":{"param":"images"}}
    #
    # The 09-23 run that carried every prior fix still died on exactly this: the
    # two character turnaround sheets are 2896x540, a 5.36:1 strip of five views,
    # and the request was refused as a whole -- the six 1.76:1 scene boards that
    # were also attached were thrown away with it.  The value is ``width/height``
    # in the direction the provider states it, and it is enforced per reference in
    # ``deliver_canvas_inputs`` so one out-of-range binding can no longer take the
    # other four down with it.
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="agnes-video-2.5",
        display_name="Agnes Video 2.5",
        capability="video",
        capability_metadata={
            "accepted_input_types": ["text", "image", "video", "audio"],
            "max_references": 15,
            "reference_limits": {"image": 5, "video": 1, "audio": 3},
            "reference_image_aspect_ratio_range": [0.4, 2.5],
            "supported_parameters": [
                "aspect_ratio",
                "resolution",
                "duration_seconds",
                "generate_audio",
            ],
            "supported_aspect_ratios": ["16:9", "9:16", "1:1"],
            "supported_resolutions": ["480p", "720p", "1080p"],
            "duration_range_seconds": [4, 12],
            "default_parameters": {
                "duration_seconds": 5,
                "resolution": "720p",
                "aspect_ratio": "16:9",
                "generate_audio": False,
            },
            "supports_native_audio": True,
            # ADR 0005 §4/§4a previs fingerprint: reference video consumed;
            # geometric control passes (depth/normal/flow) not yet accepted.
            "previs_control_signal_support": {"depth": False, "normal": False, "flow": False},
            "provider_protocol": "ark_video",
            "openai_compatible_video_generation": True,
            "supports_provider_idempotency_token": False,
            "supports_remote_task_lookup": True,
        },
    ),
    # The ``-flash`` SKU this deployment used to call, kept in the catalog rather
    # than dropped so that its row in the database says the same thing the code
    # says.  ``upsert_models`` never deletes a row that left the catalog, so
    # removing this entry would not remove the row -- it would freeze it at
    # whatever it said last and let an operator select a SKU whose metadata is
    # no longer maintained.
    #
    # The only difference from the row above is ``reference_limits.video``: 0.
    # That is the whole reason this SKU stopped being the default.  The endpoint
    # refused a request carrying a previs clip with:
    #
    #     400 invalid_request
    #     {"code":"invalid_request","message":"当前模型不支持 videos",
    #      "data":{"param":"videos"}}
    #
    # It used to declare 1 here, then 3 before that, and neither number was ever
    # true -- the ``videos`` channel was simply unreachable, so nothing observed
    # the refusal.  With a 0 below, a node bound to this SKU cannot accumulate a
    # video reference at all, which is the correct behaviour for an endpoint that
    # rejects the parameter outright.
    #
    # 2026-09-29 作者裁定（测试期口径"只传图片"）：``audio`` 从 3 收口为 0，
    # ``accepted_input_types`` 同步去掉 ``audio``。上一段"``-flash`` can only
    # ever carry ``images``/``audio``"是 09-24 的观测，本轮按作者口径再收紧：
    # 少声明只会损失预算（少送一路参考），多声明会整单 400——与本行一贯的
    # "under-declare"哲学同向。限免期/preview 结束或 flash 支持视频参数后，
    # 凭一次被接受的请求把 video（及 audio）放回去。
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="agnes-video-2.5-flash",
        display_name="Agnes Video 2.5 Flash",
        capability="video",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 8,
            "reference_limits": {"image": 5, "video": 0, "audio": 0},
            "reference_image_aspect_ratio_range": [0.4, 2.5],
            "supported_parameters": [
                "aspect_ratio",
                "resolution",
                "duration_seconds",
                "generate_audio",
            ],
            "supported_aspect_ratios": ["16:9", "9:16", "1:1"],
            # Flash validates size before queuing: its only accepted size is 720P.
            "supported_resolutions": ["720p"],
            "duration_range_seconds": [4, 12],
            "default_parameters": {
                "duration_seconds": 5,
                "resolution": "720p",
                "aspect_ratio": "16:9",
                "generate_audio": False,
            },
            "supports_native_audio": True,
            "previs_control_signal_support": {"depth": False, "normal": False, "flow": False},
            "provider_protocol": "ark_video",
            "openai_compatible_video_generation": True,
            "supports_provider_idempotency_token": False,
            "supports_remote_task_lookup": True,
        },
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seedream-5-0-pro-260628",
        display_name="Doubao Seedream 5.0 Pro",
        capability="image",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 4,
            "reference_limits": {"image": 4, "video": 0, "audio": 0},
            "supported_parameters": ["aspect_ratio", "size"],
            "provider_protocol": "ark_image",
            "supports_provider_idempotency_token": False,
            "supports_remote_task_lookup": False,
            "adapter_profile": _image_profile(
                "volcengine_ark:doubao-seedream-5-0-pro-260628",
                adapter_id="ark-image-native",
                transport_kind="ark_image_native",
            ),
        },
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seedream-4-5-251128",
        display_name="Doubao Seedream 4.5",
        capability="image",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 4,
            "reference_limits": {"image": 4, "video": 0, "audio": 0},
            "supported_parameters": ["aspect_ratio", "size"],
            "provider_protocol": "ark_image",
            "supports_provider_idempotency_token": False,
            "supports_remote_task_lookup": False,
            "adapter_profile": _image_profile(
                "volcengine_ark:doubao-seedream-4-5-251128",
                adapter_id="ark-image-native",
                transport_kind="ark_image_native",
            ),
        },
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seedream-4-0-250828",
        display_name="Doubao Seedream 4.0",
        capability="image",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 4,
            "reference_limits": {"image": 4, "video": 0, "audio": 0},
            "supported_parameters": ["aspect_ratio", "size"],
            "provider_protocol": "ark_image",
            "supports_provider_idempotency_token": False,
            "supports_remote_task_lookup": False,
            "adapter_profile": _image_profile(
                "volcengine_ark:doubao-seedream-4-0-250828",
                adapter_id="ark-image-native",
                transport_kind="ark_image_native",
            ),
        },
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seedance-2-0-mini-260615",
        display_name="Doubao Seedance 2.0 Mini",
        capability="video",
        capability_metadata=_video_capability_metadata(
            _ark_video_profile("volcengine_ark:doubao-seedance-2-0-mini-260615")
        ),
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seedance-2-0-260128",
        display_name="Doubao Seedance 2.0",
        capability="video",
        capability_metadata=_video_capability_metadata(
            _ark_video_profile("volcengine_ark:doubao-seedance-2-0-260128")
        ),
    ),
    TrustedModelManifest(
        provider_id="volcengine_ark",
        provider_model_id="doubao-seedance-2-5-260628",
        display_name="Doubao Seedance 2.5",
        capability="video",
        capability_metadata=_video_capability_metadata(
            _ark_video_profile("volcengine_ark:doubao-seedance-2-5-260628")
        ),
    ),
    TrustedModelManifest(
        provider_id="openrouter",
        provider_model_id="openai/gpt-image-2",
        display_name="GPT Image 2",
        capability="image",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 4,
            "reference_limits": {"image": 4, "video": 0, "audio": 0},
            "supported_parameters": [
                "size",
                "quality",
                "background",
                "output_format",
                "output_compression",
                "resolution",
                "aspect_ratio",
            ],
            "provider_protocol": "openrouter_images",
            "supports_provider_idempotency_token": False,
            "supports_remote_task_lookup": False,
            "adapter_profile": dict(_OPENROUTER_IMAGE_PROFILE),
            "openrouter_routing": _OPENROUTER_IMAGE_ROUTING.model_dump(mode="json"),
        },
    ),
    TrustedModelManifest(
        provider_id="openrouter",
        provider_model_id="openai/gpt-5.6-sol",
        display_name="GPT-5.6 Sol",
        capability="text",
        capability_metadata={
            "agent_compatible": True,
            "provider_protocol": "openai_compatible",
            "accepted_input_types": ["text"],
            "supports_structured_output": True,
            "supports_tool_calls": True,
            "supports_streaming": True,
            "supports_streamed_tool_calls": False,
            "supports_reasoning_controls": True,
            "thinking_format": "openai",
            "reasoning_control": "reasoning_effort",
            "structured_transport": "non_streaming_json_schema",
            "default_max_output_tokens": 8192,
            "adapter_id": _OPENROUTER_TEXT_ADAPTER_REVISION,
            "adapter_revision": _OPENROUTER_TEXT_ADAPTER_REVISION,
            "transport_kind": "pi_native_openai_compatible",
            "capability_revision": _OPENROUTER_TEXT_CAPABILITY_REVISION,
            "conformance_status": "unverified",
            "adapter_profile": dict(_OPENROUTER_TEXT_PROFILE),
            "openrouter_routing": _OPENROUTER_TEXT_ROUTING.model_dump(mode="json"),
        },
    ),
    TrustedModelManifest(
        provider_id="minimax",
        provider_model_id="MiniMax-Hailuo-2.3",
        display_name="MiniMax Hailuo 2.3",
        capability="video",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 1,
            "reference_limits": {"image": 1, "video": 0, "audio": 0},
            "supported_parameters": ["duration", "resolution", "aspect_ratio", "generate_audio"],
            "duration_seconds": [6, 10],
            "provider_protocol": "minimax_video_generation",
            "supports_provider_idempotency_token": True,
            "supports_remote_task_lookup": True,
            "adapter_profile": dict(_MINIMAX_VIDEO_PROFILES["MiniMax-Hailuo-2.3"]),
        },
    ),
    TrustedModelManifest(
        provider_id="minimax",
        provider_model_id="MiniMax-Hailuo-2.3-Fast",
        display_name="MiniMax Hailuo 2.3 Fast",
        capability="video",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 1,
            "reference_limits": {"image": 1, "video": 0, "audio": 0},
            "supported_parameters": ["duration", "resolution", "aspect_ratio", "generate_audio"],
            "duration_seconds": [6, 10],
            "provider_protocol": "minimax_video_generation",
            "supports_provider_idempotency_token": True,
            "supports_remote_task_lookup": True,
            "adapter_profile": dict(_MINIMAX_VIDEO_PROFILES["MiniMax-Hailuo-2.3-Fast"]),
        },
    ),
    TrustedModelManifest(
        provider_id="minimax",
        provider_model_id="MiniMax-Hailuo-02",
        display_name="MiniMax Hailuo 02",
        capability="video",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 1,
            "reference_limits": {"image": 1, "video": 0, "audio": 0},
            "supported_parameters": ["duration", "resolution", "aspect_ratio", "generate_audio"],
            "duration_seconds": [6, 10],
            "provider_protocol": "minimax_video_generation",
            "supports_provider_idempotency_token": True,
            "supports_remote_task_lookup": True,
            "adapter_profile": dict(_MINIMAX_VIDEO_PROFILES["MiniMax-Hailuo-02"]),
        },
    ),
    TrustedModelManifest(
        provider_id="tianpuyue",
        provider_model_id="TemPolor-i3",
        display_name="TemPolor i3",
        capability="audio",
        capability_metadata={
            "accepted_input_types": ["text"],
            "max_references": 0,
            "reference_limits": {"image": 0, "video": 0, "audio": 0},
            "supported_parameters": ["duration_seconds"],
            "duration_range_seconds": [1, 120],
            "automatic_tier_priority": 1,
            "provider_protocol": "tianpuyue_audio",
            "supports_provider_idempotency_token": False,
            "supports_remote_task_lookup": True,
        },
    ),
    TrustedModelManifest(
        provider_id="tianpuyue",
        provider_model_id="TemPolor-i3.5",
        display_name="TemPolor i3.5",
        capability="audio",
        capability_metadata={
            "accepted_input_types": ["text"],
            "max_references": 0,
            "reference_limits": {"image": 0, "video": 0, "audio": 0},
            "supported_parameters": ["duration_seconds"],
            "duration_range_seconds": [1, 270],
            "automatic_tier_priority": 2,
            "provider_protocol": "tianpuyue_audio",
            "supports_provider_idempotency_token": False,
            "supports_remote_task_lookup": True,
        },
    ),
    TrustedModelManifest(
        provider_id="fake",
        provider_model_id="deterministic-text",
        display_name="Deterministic Text",
        capability="text",
        capability_metadata={
            "agent_compatible": True,
            "provider_protocol": "fake",
            "accepted_input_types": ["text"],
            "supports_structured_output": True,
            "supports_tool_calls": True,
            "supports_streaming": True,
            "supports_streamed_tool_calls": False,
            "supports_reasoning_controls": False,
            "thinking_format": "none",
            "reasoning_control": "none",
            "structured_transport": "non_streaming_tool_call",
            "default_max_output_tokens": 8192,
        },
    ),
    TrustedModelManifest(
        provider_id="fake",
        provider_model_id="deterministic-image",
        display_name="Deterministic Image",
        capability="image",
        capability_metadata={
            "accepted_input_types": ["text", "image"],
            "max_references": 8,
            "reference_limits": {"image": 8, "video": 0, "audio": 0},
            "supported_parameters": ["aspect_ratio", "size"],
            "supported_aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
            "supported_sizes_by_aspect_ratio": dict(GUIDED_IMAGE_SIZES_BY_ASPECT_RATIO),
            "pixel_bounds": [512, 4096],
            "provider_protocol": "fake",
            "supports_reference_only_generation": True,
            "supports_provider_idempotency_token": True,
            "supports_remote_task_lookup": True,
        },
    ),
    TrustedModelManifest(
        provider_id="fake",
        provider_model_id="deterministic-video",
        display_name="Deterministic Video",
        capability="video",
        capability_metadata={
            "accepted_input_types": ["text", "image", "video", "audio"],
            "max_references": 15,
            "reference_limits": {"image": 9, "video": 3, "audio": 3},
            "supported_parameters": [
                "aspect_ratio",
                "resolution",
                "duration_seconds",
                "generate_audio",
            ],
            "supported_aspect_ratios": ["16:9", "9:16", "1:1"],
            "supported_resolutions": ["480p", "720p", "1080p"],
            "duration_range_seconds": [1, 15],
            "default_parameters": {
                "duration_seconds": 5,
                "resolution": "720p",
                "aspect_ratio": "16:9",
                "generate_audio": False,
            },
            "supports_native_audio": True,
            "provider_protocol": "fake",
            "supports_provider_idempotency_token": True,
            "supports_remote_task_lookup": True,
        },
    ),
    TrustedModelManifest(
        provider_id="fake",
        provider_model_id="deterministic-audio",
        display_name="Deterministic Audio",
        capability="audio",
        capability_metadata={
            "accepted_input_types": ["text"],
            "max_references": 0,
            "reference_limits": {"image": 0, "video": 0, "audio": 0},
            "supported_parameters": ["duration_seconds"],
            "duration_range_seconds": [1, 600],
            "provider_protocol": "fake",
            "supports_provider_idempotency_token": True,
            "supports_remote_task_lookup": True,
        },
    ),
)

_RETIRED_MODEL_REFS = frozenset(
    {
        "volcengine_ark:doubao-seed-2-0-mini-260428",
        "volcengine_ark:doubao-seedream-5-0-250128",
        "volcengine_ark:doubao-seedream-5-0-260128",
        # Retired 2026-09-20: the four Seedream rows answer 404 ``model_invalid``
        # on the only image endpoint this deployment is configured against
        # (StepFun's step_plan gateway), and they carry an ``ark_image_native``
        # adapter profile for which no transport is ever injected, so they
        # cannot execute natively either.  Kept in ``_TRUSTED_MANIFESTS`` (rather
        # than deleted) so the projection path can flip the existing rows to
        # ``deprecated`` instead of leaving them lying as ``available``.
        "volcengine_ark:doubao-seedream-4-0-250828",
        "volcengine_ark:doubao-seedream-4-5-251128",
        "volcengine_ark:doubao-seedream-5-0-lite-260128",
        "volcengine_ark:doubao-seedream-5-0-pro-260628",
        # A StepFun model that used to be filed under the Volcengine provider
        # id.  It has no volcengine_ark manifest, so it lands in the
        # "previously known but not visible" branch below, which only rewrites
        # retired refs -- without this entry the row would sit at
        # ``available`` forever, advertising a provider that cannot serve it.
        "volcengine_ark:step-image-edit-2",
        "openai:gpt-image-2",
    }
)
_BLOCKING_RETIRED_DEFAULT_REFS = frozenset({"openai:gpt-image-2"})
_CREDENTIAL_INDEPENDENT_SELECTION_REFS = frozenset({"openrouter:openai/gpt-image-2"})


class StaticProviderCatalogAdapter:
    """Default deterministic adapter used until a provider implements discovery."""

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id

    def discover_model_ids(self) -> tuple[str, ...]:
        return tuple(
            manifest.provider_model_id
            for manifest in _TRUSTED_MANIFESTS
            if manifest.provider_id == self.provider_id
        )


class OpenRouterCatalogAdapter:
    """Confirm the two trusted OpenRouter slugs from bounded metadata reads."""

    provider_id = "openrouter"
    _APPROVED_BASE_URL = "https://openrouter.ai/api/v1"
    _TEXT_MODEL_ID = "openai/gpt-5.6-sol"
    _IMAGE_MODEL_ID = "openai/gpt-image-2"

    def __init__(
        self,
        *,
        api_key: str,
        text_base_url: str = _APPROVED_BASE_URL,
        image_base_url: str = _APPROVED_BASE_URL,
        transport: ProviderHttpTransport | None = None,
        timeout_seconds: float = 5.0,
        max_response_bytes: int = 256 * 1024,
    ) -> None:
        normalized_key = api_key.strip()
        if not normalized_key or any(char in normalized_key for char in ("\r", "\n", "\x00")):
            raise ValueError("model_catalog_sync_failed")
        self._api_key = normalized_key
        self._text_base_url = self._approved_base_url(text_base_url)
        self._image_base_url = self._approved_base_url(image_base_url)
        self._transport = transport or UrllibProviderHttpTransport()
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes

    def discover_model_ids(self) -> tuple[str, ...]:
        discovered: list[str] = []
        if self._endpoint_has_model(
            url=f"{self._text_base_url}/models",
            model_id=self._TEXT_MODEL_ID,
            output_modality="text",
        ):
            discovered.append(self._TEXT_MODEL_ID)
        if self._endpoint_has_model(
            url=f"{self._image_base_url}/models?output_modalities=image",
            model_id=self._IMAGE_MODEL_ID,
            output_modality="image",
        ):
            discovered.append(self._IMAGE_MODEL_ID)
        return tuple(sorted(discovered))

    @classmethod
    def _approved_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if normalized != cls._APPROVED_BASE_URL:
            raise ValueError("model_catalog_sync_failed")
        return normalized

    def _endpoint_has_model(
        self,
        *,
        url: str,
        model_id: str,
        output_modality: str,
    ) -> bool:
        try:
            response = self._transport.get(
                url=url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout_seconds=self._timeout_seconds,
                max_response_bytes=self._max_response_bytes,
            )
        except (OSError, TimeoutError) as exc:
            raise ValueError("model_catalog_sync_failed") from exc
        if not 200 <= response.status_code < 300:
            raise ValueError("model_catalog_sync_failed")
        try:
            payload = json.loads(response.body)
        except (TypeError, ValueError) as exc:
            raise ValueError("model_catalog_sync_failed") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("model_catalog_sync_failed")
        for item in payload["data"]:
            if not isinstance(item, dict) or item.get("id") != model_id:
                continue
            architecture = item.get("architecture")
            modalities = (
                architecture.get("output_modalities") if isinstance(architecture, dict) else None
            )
            if not isinstance(modalities, list) or output_modality not in modalities:
                raise ValueError("model_catalog_sync_failed")
            return True
        return False


class ProviderModelCatalogService:
    """Own trusted model metadata, availability, query filtering, and defaults."""

    def __init__(
        self,
        repository: ProviderModelRepository,
        *,
        adapters: tuple[ProviderCatalogAdapter, ...] | None = None,
        openrouter_adapter: ProviderCatalogAdapter | None = None,
        capability_available: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._repository = repository
        configured_adapters = adapters or tuple(
            StaticProviderCatalogAdapter(provider_id)
            for provider_id in (
                "siliconflow",
                "volcengine_ark",
                "tianpuyue",
                "openrouter",
                "minimax",
                "fake",
                # StepFun hosts the image models this deployment actually calls
                # (see ``IMAGE_GENERATION_ENDPOINT``) plus the TTS/BGM rows, so
                # it needs a static discovery adapter too -- without one
                # ``_visible_model_ids`` raises ``provider_not_supported`` and
                # the stepfun image manifests can never be reconciled.
                "stepfun",
                # Agnes is the other image vendor this deployment can be pointed
                # at.  Same omission, same consequence: without a static adapter
                # its manifests cannot be reconciled and the fallback models
                # would exist in ``_TRUSTED_MANIFESTS`` but never reach the
                # database, so no node could select them.
                "agnes",
            )
        )
        self._adapters = {adapter.provider_id: adapter for adapter in configured_adapters}
        if openrouter_adapter is not None:
            if openrouter_adapter.provider_id != "openrouter":
                raise ValueError("provider_not_supported")
            self._adapters["openrouter"] = openrouter_adapter
        self._capability_available = capability_available or self._repository_capability_available

    def sync(self, provider_id: str, *, now: str) -> CatalogSyncResult:
        if provider_id not in self._adapters:
            raise ValueError("provider_not_supported")
        sync_run_id = f"sync_{uuid4().hex}"
        try:
            visible_model_ids = self._visible_model_ids(provider_id)
        except Exception as exc:
            self._repository.record_sync_run(
                sync_run_id=sync_run_id,
                provider_id=provider_id,
                status="failed",
                catalog_revision=None,
                summary={"visible_model_count": 0},
                error_code="model_catalog_sync_failed",
                created_at=now,
            )
            raise ValueError("model_catalog_sync_failed") from exc

        models = self._project_models(provider_id, visible_model_ids)
        persisted = self._repository.upsert_models(
            provider_id=provider_id,
            models=models,
            updated_at=now,
        )
        revision = max((model.catalog_revision for model in persisted), default=None)
        self._repository.record_sync_run(
            sync_run_id=sync_run_id,
            provider_id=provider_id,
            status="succeeded",
            catalog_revision=revision,
            summary={"visible_model_count": len(visible_model_ids)},
            error_code=None,
            created_at=now,
        )
        return CatalogSyncResult(
            sync_run_id=sync_run_id,
            provider_id=provider_id,
            status="succeeded",
            catalog_revision=revision,
        )

    def reconcile_trusted_models(
        self,
        provider_id: str,
        *,
        now: str,
    ) -> tuple[ProviderModelRecord, ...]:
        """Converge code-owned model projections without touching user policy."""

        visible_model_ids = self._visible_model_ids(provider_id)
        projected = tuple(
            model
            for model in self._project_models(provider_id, visible_model_ids)
            if model["source"] == "built_in"
        )
        existing = {
            model.model_ref: model
            for model in self._repository.list_models(provider_id=provider_id)
        }
        changed = tuple(
            model
            for model in projected
            if _trusted_projection_changed(existing.get(str(model["model_ref"])), model)
        )
        if not changed:
            return ()
        return self._repository.upsert_models(
            provider_id=provider_id,
            models=changed,
            updated_at=now,
        )

    def reconcile_retired_models(self, *, now: str) -> tuple[ProviderModelRecord, ...]:
        """Preserve retired built-ins while removing them from active provider sync."""

        model_ref = "openai:gpt-image-2"
        try:
            existing = self._repository.get_model(model_ref)
        except ValueError:
            existing = None
        metadata = (
            existing.capability_metadata
            if existing is not None
            else {
                "historical": True,
                "adapter_profile": dict(_HISTORICAL_OPENAI_IMAGE_PROFILE),
            }
        )
        projected = {
            "model_ref": model_ref,
            "provider_model_id": "gpt-image-2",
            "display_name": "GPT Image 2",
            "capability": "image",
            "capability_metadata": metadata,
            "source": "built_in",
            "availability": "deprecated",
            "unavailable_reason": "provider_model_retired",
        }
        if not _trusted_projection_changed(existing, projected):
            return ()
        return self._repository.upsert_models(
            provider_id="openai",
            models=(projected,),
            updated_at=now,
        )

    def ensure_no_retired_defaults(self) -> None:
        if any(
            default.model_ref in _BLOCKING_RETIRED_DEFAULT_REFS
            for default in self._repository.get_defaults().values()
        ):
            raise ValueError("retired_model_default_conflict")

    def _visible_model_ids(self, provider_id: str) -> set[str]:
        adapter = self._adapters.get(provider_id)
        if adapter is None:
            raise ValueError("provider_not_supported")
        return set(adapter.discover_model_ids())

    def _project_models(
        self,
        provider_id: str,
        visible_model_ids: set[str],
    ) -> list[dict[str, Any]]:
        trusted = {
            manifest.provider_model_id: manifest
            for manifest in _TRUSTED_MANIFESTS
            if manifest.provider_id == provider_id
        }
        models: list[dict[str, Any]] = []
        for provider_model_id in sorted(visible_model_ids):
            manifest = trusted.get(provider_model_id)
            if manifest is None:
                models.append(
                    {
                        "model_ref": f"{provider_id}:{provider_model_id}",
                        "provider_model_id": provider_model_id,
                        "display_name": provider_model_id,
                        "capability": "text",
                        "capability_metadata": {},
                        "source": "discovered",
                        "availability": "unsupported",
                        "unavailable_reason": "model_not_supported",
                    }
                )
                continue
            if manifest.model_ref in _RETIRED_MODEL_REFS:
                models.append(
                    {
                        **_trusted_projection(manifest, available=False),
                        "availability": "deprecated",
                        "unavailable_reason": "model_retired",
                    }
                )
                continue
            models.append(
                _trusted_projection(
                    manifest,
                    available=self._capability_is_available(
                        manifest.provider_id,
                        manifest.capability,
                    )
                    or manifest.model_ref in _CREDENTIAL_INDEPENDENT_SELECTION_REFS,
                )
            )
        previously_known = {
            model.provider_model_id
            for model in self._repository.list_models(provider_id=provider_id)
            if model.source == "built_in"
        }
        for provider_model_id in sorted(previously_known.difference(visible_model_ids)):
            manifest = trusted.get(provider_model_id)
            if manifest is None:
                model_ref = f"{provider_id}:{provider_model_id}"
                if model_ref in _RETIRED_MODEL_REFS:
                    previous = self._repository.get_model(model_ref)
                    models.append(
                        {
                            "model_ref": model_ref,
                            "provider_model_id": provider_model_id,
                            "display_name": previous.display_name,
                            "capability": previous.capability,
                            "capability_metadata": previous.capability_metadata,
                            "source": "built_in",
                            "availability": "deprecated",
                            "unavailable_reason": "model_retired",
                        }
                    )
                continue
            if manifest.model_ref in _RETIRED_MODEL_REFS:
                models.append(
                    {
                        **_trusted_projection(manifest, available=False),
                        "availability": "deprecated",
                        "unavailable_reason": "model_retired",
                    }
                )
                continue
            models.append(
                _trusted_projection(
                    manifest,
                    available=False,
                    unavailable_reason="provider_model_not_visible",
                )
            )
        return models

    def list_models(
        self,
        *,
        provider_id: str | None = None,
        capability: str | None = None,
        node_type: str | None = None,
        purpose: str | None = None,
        include_unavailable: bool = False,
    ) -> tuple[ProviderModelRecord, ...]:
        required_capability = _required_capability(
            node_type=node_type, purpose=purpose, capability=capability
        )
        if node_type == "editing":
            return ()
        models = self._repository.list_models(
            provider_id=provider_id,
            capability=required_capability,
            availability=None,
        )
        models = tuple(self._with_current_credential_availability(model) for model in models)
        if not include_unavailable:
            models = tuple(
                model
                for model in models
                if model.availability == "available" and _is_execution_conformant(model)
            )
        if node_type == "script" or purpose == "agent":
            models = tuple(
                model for model in models if bool(model.capability_metadata.get("agent_compatible"))
            )
        return models

    def get_model(self, model_ref: str) -> ProviderModelRecord:
        """Return one model with current capability credential availability."""

        return self._with_current_credential_availability(self._repository.get_model(model_ref))

    def current_conformance(
        self,
        *,
        model_ref: str,
        operation: str,
    ) -> ProviderModelConformanceRunRecord | None:
        return self._repository.current_conformance(
            model_ref=model_ref,
            operation=operation,
        )

    def set_defaults(
        self,
        defaults: Mapping[str, str],
        *,
        modes: Mapping[str, str] | None = None,
        now: str,
    ) -> dict[str, ModelDefaultRecord]:
        mode_updates = dict(modes or {})
        if not defaults and not mode_updates:
            raise ValueError("model_default_update_invalid")
        for default_key, model_ref in defaults.items():
            try:
                model = self.get_model(model_ref)
            except ValueError as exc:
                raise ValueError("model_not_found") from exc
            if model.availability != "available":
                raise ValueError("model_unavailable")
            if not _model_matches_default(default_key, model):
                raise ValueError("model_capability_mismatch")
        for default_key, selection_mode in mode_updates.items():
            if selection_mode not in {"automatic", "explicit"}:
                raise ValueError("model_default_mode_invalid")
            if selection_mode == "automatic" and default_key != "audio":
                raise ValueError("model_automatic_policy_unsupported")
        try:
            return self._repository.set_defaults(defaults, modes=mode_updates, updated_at=now)
        except ValueError as exc:
            if str(exc) == "model_default_capability_invalid":
                raise ValueError("model_capability_mismatch") from exc
            raise

    def get_defaults(self) -> dict[str, str]:
        return {key: record.model_ref for key, record in self._repository.get_defaults().items()}

    def get_default_records(self) -> dict[str, ModelDefaultRecord]:
        """Return the public default references with their monotonic revisions."""

        return self._repository.get_defaults()

    def _capability_is_available(self, provider_id: str, capability: str) -> bool:
        return provider_id == "fake" or self._capability_available(provider_id, capability)

    def _repository_capability_available(self, provider_id: str, capability: str) -> bool:
        try:
            connection = self._repository.get_connection(provider_id)
        except ValueError:
            return False
        status = connection.credential_status.get(capability)
        return isinstance(status, Mapping) and status.get("configured") is True

    def _with_current_credential_availability(
        self,
        model: ProviderModelRecord,
    ) -> ProviderModelRecord:
        if model.provider_id == "fake":
            return model
        credential_managed = model.availability == "available" or (
            model.availability == "unavailable"
            and model.unavailable_reason == "provider_credentials_missing"
        )
        if not credential_managed:
            return model
        available = (
            model.model_ref in _CREDENTIAL_INDEPENDENT_SELECTION_REFS
            or self._capability_is_available(model.provider_id, model.capability)
        )
        availability = "available" if available else "unavailable"
        unavailable_reason = None if available else "provider_credentials_missing"
        if model.availability == availability and model.unavailable_reason == unavailable_reason:
            return model
        return replace(
            model,
            availability=availability,
            unavailable_reason=unavailable_reason,
        )


def _is_execution_conformant(model: ProviderModelRecord) -> bool:
    raw_profile = model.capability_metadata.get("adapter_profile")
    if raw_profile is None:
        return True
    try:
        profile = ProviderAdapterProfileV1.model_validate(raw_profile)
    except Exception:
        return False
    return profile.conformance_status in {"compatible", "certified"}


def _required_capability(
    *,
    node_type: str | None,
    purpose: str | None,
    capability: str | None,
) -> str | None:
    if capability is not None:
        return capability
    if node_type in {"text", "script"}:
        return "text"
    if node_type in {"image", "video", "audio"}:
        return node_type
    if purpose in {"agent", "text", "image", "video", "audio"}:
        return "text" if purpose == "agent" else purpose
    return None


def _model_matches_default(default_key: str, model: ProviderModelRecord) -> bool:
    if default_key == "agent":
        return model.capability == "text" and bool(
            model.capability_metadata.get("agent_compatible")
        )
    return model.capability == default_key


def _trusted_projection(
    manifest: TrustedModelManifest,
    *,
    available: bool,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    capability_metadata = dict(manifest.capability_metadata)
    if manifest.adapter_profile is not None:
        capability_metadata["adapter_profile"] = dict(manifest.adapter_profile)
    return {
        "model_ref": manifest.model_ref,
        "provider_model_id": manifest.provider_model_id,
        "display_name": manifest.display_name,
        "capability": manifest.capability,
        "capability_metadata": capability_metadata,
        "source": "built_in",
        "availability": "available" if available else "unavailable",
        "unavailable_reason": (
            None if available else unavailable_reason or "provider_credentials_missing"
        ),
    }


def _trusted_projection_changed(
    existing: ProviderModelRecord | None,
    projected: Mapping[str, Any],
) -> bool:
    if existing is None:
        return True
    if existing.source != "built_in":
        return False
    return any(
        current != projected[key]
        for key, current in (
            ("display_name", existing.display_name),
            ("capability", existing.capability),
            ("capability_metadata", existing.capability_metadata),
            ("availability", existing.availability),
            ("unavailable_reason", existing.unavailable_reason),
        )
    )
