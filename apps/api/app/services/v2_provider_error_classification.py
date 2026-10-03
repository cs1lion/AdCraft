"""Shared classification of provider HTTP failures.

Media providers report transient overload (Volcengine Ark answers an image
request with HTTP 503 ``engine_overloaded`` and the literal text "please try
again later").  Those responses used to be flattened into a single opaque
``provider_generation_failed`` / ``provider_request_failed`` code, which is not
in :data:`app.services.workflow_v2.RETRYABLE_PROVIDER_ERROR_CODES`, so neither
the V2 polling loop nor the Agent Canvas media executor ever retried them and
the user was left waiting for the provider to recover on its own.

Every code returned here is already a member of that retryable set, so both the
existing polling path and the canvas-side backoff agree on one definition of
"transient" instead of maintaining two.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Response bodies that describe a transient overload even when the provider
# reports it under a non-5xx status.
#
# The queue entries were added after a real one: the video provider answered a
# full render queue with ``{"code":"video_queue_full","message":"视频队列已满,
# 请稍后重试"}`` under a status the native adapter path discards, so the body is
# the only witness left.  "overload" is deliberately unqualified -- Ark spells it
# ``engine_overloaded``, other vendors "server overloaded", and neither is a
# contract error.
_TRANSIENT_BODY_MARKERS = (
    "engine_overloaded",
    "overload",
    "try again later",
    "服务繁忙",
    "rate limit",
    "too many requests",
    "temporarily unavailable",
    "queue_full",
    "queue full",
    "队列已满",
    "稍后重试",
    "稍后再试",
)

_RATE_LIMIT_BODY_MARKERS = (
    "rate limit",
    "too many requests",
    "quota",
)

#: Every code :func:`classify_provider_http_status` can return.
#:
#: Callers that must decide "is this transient?" without re-deriving it from a
#: status code test membership here instead of restating the list.  Two such
#: callers matter: :data:`app.services.workflow_v2.RETRYABLE_PROVIDER_ERROR_CODES`
#: gates the V2 poll retry, and
#: :data:`app.services.agent_canvas_execution_state.APPROVED_TRANSIENT_ERROR_CODES`
#: gates whether a failed canvas node is projected as ``retryable`` at all.
#: Before this set existed the second gate had its own shorter list, so a 503
#: the classifier had already called transient still reached the user as a
#: permanently red node.
CLASSIFIED_RETRYABLE_PROVIDER_ERROR_CODES = frozenset(
    {
        "provider_timeout",
        "provider_rate_limited",
        "provider_temporary_unavailable",
        "provider_server_error",
    }
)


def classify_provider_http_status(status_code: int | None) -> tuple[str | None, bool]:
    """Map a provider HTTP status to ``(error_code, retryable)``.

    Returns ``(None, False)`` for statuses that carry no transient meaning, so
    callers keep their existing non-retryable error code.
    """

    if not isinstance(status_code, int) or isinstance(status_code, bool):
        return None, False
    if status_code in {408, 504}:
        return "provider_timeout", True
    if status_code == 429:
        return "provider_rate_limited", True
    if 500 <= status_code < 600:
        if status_code in {500, 502, 503, 599}:
            return "provider_temporary_unavailable", True
        return "provider_server_error", True
    return None, False


def classify_provider_error(
    *,
    status_code: int | None = None,
    response_body: str | None = None,
) -> tuple[str | None, bool]:
    """Classify a provider failure from its status and response body.

    The body is checked first: a provider that reports overload as a 400 must
    still be treated as transient, otherwise the user sees a permanent failure
    for a condition the provider itself calls temporary.
    """

    # Legacy/native transports sometimes retain only MediaApiError's envelope.
    # Read its explicit header, never an arbitrary status mentioned in a prompt
    # or response payload. Structured status supplied by the caller wins.
    if status_code is None and response_body and response_body.startswith("media_api_failed:\n"):
        envelope_headers = response_body.split("\nresponse_body=", 1)[0]
        match = re.search(r"(?m)^status=([1-5][0-9]{2})$", envelope_headers)
        if match:
            status_code = int(match.group(1))
    if status_code == 429:
        return "provider_rate_limited", True
    lowered = (response_body or "").casefold()
    if lowered and any(marker in lowered for marker in _TRANSIENT_BODY_MARKERS):
        if any(marker in lowered for marker in _RATE_LIMIT_BODY_MARKERS):
            return "provider_rate_limited", True
        return "provider_temporary_unavailable", True
    return classify_provider_http_status(status_code)


def provider_error_type_from_body(response_body: str | None) -> str | None:
    """Extract ``error.type`` (e.g. ``engine_overloaded``) from a JSON body."""

    if not response_body:
        return None
    try:
        parsed: Any = json.loads(response_body)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    error = parsed.get("error")
    if not isinstance(error, dict):
        return None
    value = error.get("type")
    return value.strip() if isinstance(value, str) and value.strip() else None
