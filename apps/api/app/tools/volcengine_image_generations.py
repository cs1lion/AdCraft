from __future__ import annotations

from typing import Any

from app.services.agnes_image_contract import (
    AGNES_IMAGE_MODEL_IDS,
    AGNES_IMAGE_UNSUPPORTED_FIELDS,
    is_agnes_image_model,
    normalize_agnes_image_size,
)
from app.services.stepfun_image_contract import (
    clamp_stepfun_image_prompt,
    normalize_stepfun_image_size,
)
from app.services.v2_provider_reference_input_delivery import (
    V2ProviderReferenceWireAudit,
    is_provider_compatible_model_input,
)

# The image endpoint this deployment is configured against
# (``IMAGE_GENERATION_ENDPOINT``) is StepFun's step_plan gateway, not
# Volcengine Ark -- so the models that actually execute are StepFun's
# ``step-image-edit-2`` / ``step-2x-large``.  Both take the
# ``sequential_image_generation="disabled"`` branch below, which is why this
# module keeps its historical Volcengine name while serializing for StepFun.
# The Volcengine name is historical, but the *body* is not: size and prompt are
# reconciled against StepFun's documented contract by
# ``stepfun_image_contract`` before validation, because the two providers do not
# accept the same values and this one is the gateway that actually answers.
_SEEDREAM_PRO_MODEL_ID = "doubao-seedream-5-0-pro-260628"
_STEPFUN_IMAGE_MODEL_IDS = frozenset({"step-image-edit-2", "step-2x-large"})
# The image endpoint this deployment is configured against is StepFun's
# step_plan gateway, not Volcengine Ark -- so these are the models that
# actually execute.  They DO take the ``sequential_image_generation="disabled"``
# branch (the gateway answers 400 without it, 503 with it), which is the same
# branch every non-Pro model has always taken.  Named here only so the set is
# assertable in tests, not to change the branch.
_EXECUTABLE_IMAGE_MODEL_IDS = frozenset(_STEPFUN_IMAGE_MODEL_IDS) | frozenset(
    AGNES_IMAGE_MODEL_IDS
)


class V2ProviderRequestContractError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        stage: str,
        message: str,
        audit: V2ProviderReferenceWireAudit,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.audit = audit


def serialize_volcengine_image_generation_request(
    *,
    model: str,
    canonical_prompt: str,
    size: str,
    references: list[dict[str, Any]],
    required_reference_asset_ids: list[str],
    response_format: str = "url",
    watermark: bool = False,
) -> tuple[dict[str, Any], V2ProviderReferenceWireAudit]:
    required_asset_ids = _ordered_unique(required_reference_asset_ids)
    audit = V2ProviderReferenceWireAudit(
        requested_reference_asset_ids=required_asset_ids,
        request_schema="volcengine-image-generations",
    )
    # Reconcile the request with the provider's contract *before* the body is
    # built, so the anti-tamper checks below compare against what is actually
    # sent.  StepFun accepts five sizes and a 512-character prompt, while the
    # configured default was ``2048x2048``, this deployment's ``.env`` says
    # ``1920x1920``, and the guided-parameter table advertised Volcengine Ark
    # sizes.  Every one of those is a refusal waiting to happen the moment the
    # gateway stops answering 503 for reasons of its own.  Agnes is a different
    # contract again -- see ``agnes_image_contract`` -- so the two are branched
    # rather than merged.
    canonical_prompt, prompt_normalization = clamp_stepfun_image_prompt(model, canonical_prompt)
    if is_agnes_image_model(model):
        size, size_normalization = normalize_agnes_image_size(model, size)
    else:
        size, size_normalization = normalize_stepfun_image_size(model, size)
    for normalization in (size_normalization, prompt_normalization):
        if normalization is not None:
            audit.warnings.append(normalization)
    body: dict[str, Any] = {
        "model": model,
        "prompt": canonical_prompt,
        "response_format": response_format,
        "size": size,
    }
    if is_agnes_image_model(model):
        # Agnes answers HTTP 400 ``invalid_request`` to both of these, and it
        # reports ``watermark`` first -- so a body carrying both surfaces only
        # the watermark and hides the second failure.  Dropping them here is the
        # only way to keep an Agnes request deliverable; the StepFun models need
        # ``sequential_image_generation="disabled"`` (the gateway answers 400
        # without it), which is why the two bodies cannot be merged.
        body = {key: value for key, value in body.items() if key not in AGNES_IMAGE_UNSUPPORTED_FIELDS}
    else:
        body["watermark"] = watermark
        if model != _SEEDREAM_PRO_MODEL_ID:
            body["sequential_image_generation"] = "disabled"
    _validate_base_body(body, canonical_prompt=canonical_prompt, audit=audit)

    serialized_values: list[str] = []
    serialized_asset_ids: list[str] = []
    seen_asset_ids: set[str] = set()
    for reference in references:
        asset_id = str(reference.get("asset_id") or "").strip()
        if not asset_id or asset_id in seen_asset_ids:
            if asset_id:
                audit.warnings.append("duplicate_reference_asset_id_deduplicated")
            continue
        seen_asset_ids.add(asset_id)
        value = _reference_input_value(reference)
        if not value or not is_provider_compatible_model_input(value):
            audit.warnings.append(
                "required_reference_value_invalid"
                if asset_id in required_asset_ids
                else "optional_reference_value_invalid"
            )
            continue
        serialized_asset_ids.append(asset_id)
        serialized_values.append(value)

    audit = audit.model_copy(update={"delivered_reference_asset_ids": list(serialized_asset_ids)})
    missing_required = [
        asset_id for asset_id in required_asset_ids if asset_id not in serialized_asset_ids
    ]
    if missing_required:
        raise _reference_error(
            "A required prepared reference is missing from the provider request.",
            audit,
        )

    audit = audit.model_copy(
        update={
            "serialized_reference_asset_ids": list(serialized_asset_ids),
            "provider_request_field": "image" if serialized_values else None,
            "provider_request_reference_count": len(serialized_values),
        }
    )
    if len(serialized_values) == 1:
        body["image"] = serialized_values[0]
    elif serialized_values:
        body["image"] = serialized_values
    _validate_final_body(
        body,
        canonical_prompt=canonical_prompt,
        required_reference_asset_ids=required_asset_ids,
        audit=audit,
    )
    return body, audit


def _validate_base_body(
    body: dict[str, Any],
    *,
    canonical_prompt: str,
    audit: V2ProviderReferenceWireAudit,
) -> None:
    if not all(isinstance(body.get(key), str) and body[key].strip() for key in ("model", "size")):
        raise _contract_error("Volcengine image request requires model and size.", audit)
    if not canonical_prompt.strip() or body.get("prompt") != canonical_prompt:
        raise _contract_error(
            "Volcengine image request prompt must match the canonical prompt.", audit
        )
    # Seedream Pro is retired from the catalog (2026-09-20) but its
    # "no group generation" rule is kept so the contract does not silently
    # change for any caller still pinning it.  Every StepFun step_plan model
    # takes the ``"disabled"`` branch below.  Agnes models are exempt from the
    # rule entirely: they take neither branch, because Agnes rejects the field
    # outright -- so "must be disabled" and "must be absent" are both correct
    # answers for different providers, and naming the provider is the only way
    # to tell them apart.
    if body.get("model") == _SEEDREAM_PRO_MODEL_ID:
        if "sequential_image_generation" in body:
            raise _contract_error(
                "Seedream Pro does not accept group generation parameters.", audit
            )
    elif is_agnes_image_model(str(body.get("model") or "")):
        if "sequential_image_generation" in body:
            raise _contract_error(
                "Agnes image models do not accept sequential_image_generation.", audit
            )
    elif body.get("sequential_image_generation") != "disabled":
        raise _contract_error("V2 image slots must disable sequential image generation.", audit)

def _validate_final_body(
    body: dict[str, Any],
    *,
    canonical_prompt: str,
    required_reference_asset_ids: list[str],
    audit: V2ProviderReferenceWireAudit,
) -> None:
    _validate_base_body(body, canonical_prompt=canonical_prompt, audit=audit)
    if "references" in body or "context" in body:
        raise _contract_error("Volcengine image request leaked an internal field.", audit)
    image = body.get("image")
    if image is None:
        if required_reference_asset_ids:
            raise _reference_error(
                "A required prepared reference is missing from the provider request.", audit
            )
        return
    values = [image] if isinstance(image, str) else image if isinstance(image, list) else []
    if not values or any(
        not isinstance(value, str) or not is_provider_compatible_model_input(value)
        for value in values
    ):
        raise _contract_error("Volcengine image request contains an invalid image value.", audit)
    if len(values) != audit.provider_request_reference_count:
        raise _reference_error(
            "Volcengine image request did not serialize every prepared reference exactly once.",
            audit,
        )


def _reference_input_value(reference: dict[str, Any]) -> str:
    for key in ("provider_input_value", "model_input_value"):
        value = reference.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _reference_error(
    message: str,
    audit: V2ProviderReferenceWireAudit,
) -> V2ProviderRequestContractError:
    return V2ProviderRequestContractError(
        code="v2_provider_reference_serialization_failed",
        stage="provider_request_serialization",
        message=message,
        audit=audit,
    )


def _contract_error(
    message: str,
    audit: V2ProviderReferenceWireAudit,
) -> V2ProviderRequestContractError:
    return V2ProviderRequestContractError(
        code="v2_provider_request_contract_invalid",
        stage="provider_request_validation",
        message=message,
        audit=audit,
    )


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in (str(raw).strip() for raw in values) if value))
