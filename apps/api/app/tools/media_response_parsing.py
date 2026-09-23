from __future__ import annotations

import json
from typing import Any
from urllib import error as urllib_error

from app.services.v2_provider_error_classification import provider_error_type_from_body
from app.tools.media_provider_protocol import MediaApiError

# The image endpoint is configurable and this deployment points it at StepFun's
# ``step_plan`` gateway (``IMAGE_GENERATION_ENDPOINT``), which proxies the same
# upstream engine.  Hardcoding "volcengine" therefore made a correctly-routed
# StepFun request look like it had gone to the wrong provider: during the
# 2026-09-20 run the node error read ``provider=volcengine`` while the payload
# model was ``step-image-edit-2`` on ``api.stepfun.com``, which reads as "the
# StepFun migration did not take effect" and sends the reader hunting a routing
# bug that does not exist.
_ENDPOINT_PROVIDER_LABELS: tuple[tuple[str, str], ...] = (
    ("agnes-ai.cn", "agnes"),
    ("stepfun", "stepfun"),
    ("volces.com", "volcengine"),
    ("volcengine", "volcengine"),
)

#: The step_plan gateway states its own retry verdict in a header.  On
#: 2026-09-21 every image request answered ``X-Should-Retry: false`` while a
#: successful TTS request on the same key carried no such header at all
#: (``e2e_output/rose/probe_retry_semantics.py``), so the gateway was saying the
#: refusal would not clear by itself -- the opposite of what the 503 body
#: ("please try again later") implies.  Reading it keeps the hint honest instead
#: of promising a retry that cannot help, and the trace id gives the operator
#: something to quote when reporting the outage.
_SHOULD_RETRY_HEADER = "X-Should-Retry"
_TRACE_ID_HEADER = "X-Trace-Id"


def _header_value(exc: urllib_error.HTTPError, name: str) -> str | None:
    """Read a response header, tolerating an HTTPError built without any."""

    headers = getattr(exc, "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except Exception:  # noqa: BLE001 - a malformed header bag must not mask the error
        return None
    return value if value is None else str(value)


def _gateway_retry_directive(exc: urllib_error.HTTPError) -> bool | None:
    """The gateway's own retry verdict, or None when it does not state one."""

    value = _header_value(exc, _SHOULD_RETRY_HEADER)
    if value is None or not value.strip():
        return None
    return value.strip().lower() not in {"false", "0", "no"}


def _provider_label_for_endpoint(endpoint: str) -> str:
    """Name the gateway the request actually went to, not the one it used to."""

    lowered = (endpoint or "").casefold()
    for needle, label in _ENDPOINT_PROVIDER_LABELS:
        if needle in lowered:
            return label
    return "volcengine" if not lowered.strip() else "unknown"


def _media_api_error(
    *,
    exc: urllib_error.HTTPError,
    endpoint: str,
    payload: dict[str, Any] | None,
) -> MediaApiError:
    response_body = exc.read().decode("utf-8", errors="replace")
    sanitized_payload = _sanitize_secret_values(payload)
    provider_error_type = provider_error_type_from_body(response_body)
    provider_label = _provider_label_for_endpoint(endpoint)
    should_retry = _gateway_retry_directive(exc)
    trace_id = _header_value(exc, _TRACE_ID_HEADER)
    metadata: dict[str, Any] = {
        "provider": provider_label,
        "endpoint": endpoint,
        "status": exc.code,
        "response_body": response_body,
        "payload": sanitized_payload,
    }
    if provider_error_type is not None:
        # Preserve the provider's own machine-readable reason (e.g.
        # "engine_overloaded") so callers can classify the failure instead of
        # collapsing every status into one opaque code.
        metadata["provider_error_code"] = provider_error_type
    if should_retry is not None:
        # Kept separate from ``retryable``: that flag is *our* classification of
        # the status, this one is the gateway's own instruction, and when the two
        # disagree the operator needs to see both.
        metadata["provider_should_retry"] = should_retry
    if trace_id:
        metadata["provider_trace_id"] = trace_id
    payload_json = json.dumps(sanitized_payload, ensure_ascii=False, indent=2, sort_keys=True)
    message = "\n".join(
        [
            "media_api_failed:",
            *(
                [f"user_action={hint}"]
                if (hint := _provider_user_action_hint(
                    response_body, exc.code, should_retry=should_retry
                ))
                is not None
                else []
            ),
            f"provider={provider_label}",
            f"endpoint={endpoint}",
            f"status={exc.code}",
            *([f"provider_should_retry={should_retry}"] if should_retry is not None else []),
            *([f"provider_trace_id={trace_id}"] if trace_id else []),
            f"response_body={response_body}",
            f"payload={payload_json}",
        ]
    )
    return MediaApiError(message=message, metadata=metadata)


def _overload_hint(should_retry: bool | None) -> str:
    """What to tell the operator about an overload refusal.

    The body says "try again later"; the gateway's header may say the opposite.
    When it does, promising a retry would send the operator in circles, so the
    hint names the header and points at the trace id instead.
    """

    if should_retry is False:
        return (
            "The provider gateway refused this request and marked it "
            "X-Should-Retry: false, so retrying will not clear it. "
            "Report the provider_trace_id from this error to the provider."
        )
    return (
        "The provider engine is temporarily overloaded. "
        "This is transient - the request is safe to retry as-is."
    )


def _provider_user_action_hint(
    response_body: str,
    status: int,
    *,
    should_retry: bool | None = None,
) -> str | None:
    """Return a short English fix-it hint for well-known provider rejections."""

    lowered = response_body.lower()
    if "modelnotopen" in lowered or "has not activated the model" in lowered:
        return (
            "This model is not activated on your Volcengine Ark account. "
            "Open the Ark Console -> Activation Management, activate this model, "
            "then retry. Alternatively, pick a model that is already activated."
        )
    if "invalidendpointormodel" in lowered:
        return (
            "This model id does not exist on Volcengine Ark (it may be deprecated "
            "or a wrong version). Select a different model and retry."
        )
    if "invalid api key" in lowered or (status == 401 and "unauthorized" in lowered):
        return (
            "The provider rejected the API key. "
            "Check the API key configured in the API Space."
        )
    if status == 429:
        return (
            "The provider rate limit or quota was hit. "
            "Wait a moment and retry, or check your plan quota."
        )
    if status == 503:
        return _overload_hint(should_retry)
    if status in {500, 502, 504}:
        return (
            "The provider reported a temporary server error. "
            "This is transient - the request is safe to retry as-is."
        )
    if "engine_overloaded" in lowered or "try again later" in lowered:
        return _overload_hint(should_retry)
    return None


def _sanitize_secret_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redacted_value(key, item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_secret_values(item) for item in value]
    return value


def _redacted_value(key: str, value: Any) -> Any:
    lowered_key = key.lower()
    if any(secret_key in lowered_key for secret_key in ("api_key", "apikey", "token", "secret")):
        return _redact_secret(str(value)) if value is not None else None
    if lowered_key == "authorization":
        return _redact_authorization(str(value)) if value is not None else None
    return _sanitize_secret_values(value)


def _redact_authorization(value: str) -> str:
    parts = value.split(maxsplit=1)
    if len(parts) == 2:
        return f"{parts[0]} {_redact_secret(parts[1])}"
    return _redact_secret(value)


def _redact_secret(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def _video_generation_task_id_from_response(response: dict[str, Any]) -> str:
    task_id = response.get("id") or response.get("task_id")
    if isinstance(task_id, str) and task_id.strip():
        return task_id
    video_id = response.get("video_id")
    if isinstance(video_id, str) and video_id.strip():
        return video_id

    data = response.get("data")
    if isinstance(data, dict):
        task_id = data.get("id") or data.get("task_id")
        if isinstance(task_id, str) and task_id.strip():
            return task_id
        video_id = data.get("video_id")
        if isinstance(video_id, str) and video_id.strip():
            return video_id

    raise ValueError("Volcengine video generation response did not include task id.")


def _optional_video_generation_task_id_from_response(response: dict[str, Any]) -> str | None:
    try:
        return _video_generation_task_id_from_response(response)
    except ValueError:
        return None


def _video_url_from_response(response: dict[str, Any]) -> str | None:
    if isinstance(response.get("url"), str):
        return response["url"]
    if isinstance(response.get("video_url"), str):
        return response["video_url"]
    metadata = response.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("url"), str):
        return metadata["url"]
    output = response.get("output")
    if isinstance(output, dict) and isinstance(output.get("url"), str):
        return output["url"]
    data = response.get("data")
    if isinstance(data, dict) and isinstance(data.get("url"), str):
        return data["url"]
    content = response.get("content")
    if isinstance(content, dict):
        if isinstance(content.get("video_url"), str):
            return content["video_url"]
        if isinstance(content.get("url"), str):
            return content["url"]
    return None


def _video_resolution_from_response(response: dict[str, Any]) -> str | None:
    return _string_response_value(response, "resolution")


def _video_ratio_from_response(response: dict[str, Any]) -> str | None:
    return _string_response_value(response, "ratio") or _string_response_value(
        response,
        "aspect_ratio",
    )


def _video_duration_from_response(response: dict[str, Any]) -> int | None:
    value = _response_value(response, "duration") or _response_value(response, "duration_seconds")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _string_response_value(response: dict[str, Any], key: str) -> str | None:
    value = _response_value(response, key)
    return value if isinstance(value, str) and value.strip() else None


def _response_value(response: dict[str, Any], key: str) -> Any:
    if key in response:
        return response[key]
    for nested_key in ("content", "output", "data", "result"):
        nested = response.get(nested_key)
        if isinstance(nested, dict) and key in nested:
            return nested[key]
    return None


def _image_url_from_response(response: dict[str, Any]) -> str | None:
    if isinstance(response.get("url"), str):
        return response["url"]
    data = response.get("data")
    if isinstance(data, list) and data:
        first_item = data[0]
        if isinstance(first_item, dict) and isinstance(first_item.get("url"), str):
            return first_item["url"]
    if isinstance(data, dict) and isinstance(data.get("url"), str):
        return data["url"]
    return None


def _image_base64_from_response(response: dict[str, Any]) -> str | None:
    if isinstance(response.get("b64_json"), str):
        return response["b64_json"]
    if isinstance(response.get("base64"), str):
        return response["base64"]

    data = response.get("data")
    if isinstance(data, list) and data:
        first_item = data[0]
        if isinstance(first_item, dict):
            if isinstance(first_item.get("b64_json"), str):
                return first_item["b64_json"]
            if isinstance(first_item.get("base64"), str):
                return first_item["base64"]
    if isinstance(data, dict):
        if isinstance(data.get("b64_json"), str):
            return data["b64_json"]
        if isinstance(data.get("base64"), str):
            return data["base64"]
    return None
