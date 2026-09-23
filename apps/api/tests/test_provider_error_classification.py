"""Provider HTTP failure classification (ISSUE-12).

Volcengine Ark answers an image request with HTTP 503 ``engine_overloaded``
("please try again later"). That used to be flattened into
``provider_request_failed``, which is not in ``RETRYABLE_PROVIDER_ERROR_CODES``,
so neither the V2 polling loop nor the canvas media executor retried it and the
user was left waiting for the provider to recover on its own.

The critical invariant is not the individual mapping but that every returned
code is a member of the retryable set — otherwise the canvas backoff would
retry while the V2 poller gives up, i.e. two definitions of "transient".
"""

from __future__ import annotations

import io
from urllib import error as urllib_error

import pytest

from app.services.v2_provider_error_classification import (
    classify_provider_error,
    classify_provider_http_status,
    provider_error_type_from_body,
)
from app.services.workflow_v2 import RETRYABLE_PROVIDER_ERROR_CODES
from app.tools.media_response_parsing import (
    _media_api_error,
    _provider_label_for_endpoint,
)

#: A 503 shaped exactly like the one the step_plan gateway returns.
_OVERLOAD_BODY = (
    '{"error": {"message": "The engine is currently overloaded, '
    'please try again later", "type": "engine_overloaded"}}'
)


class _HTTPError503(urllib_error.HTTPError):
    """An HTTPError that answers ``read()`` with the overload body."""

    def __init__(self, url: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(url, 503, "Service Unavailable", headers or {}, io.BytesIO())  # type: ignore[arg-type]

    def read(self) -> bytes:  # type: ignore[override]
        return _OVERLOAD_BODY.encode("utf-8")


_STEP_PLAN_OVERLOAD_HEADERS = {
    "X-Should-Retry": "false",
    "X-Trace-Id": "70e2d34d70170d972ca3f346011751b5",
    "X-Router-Id": "/step_plan/v1/images",
}


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        (408, "provider_timeout"),
        (504, "provider_timeout"),
        (429, "provider_rate_limited"),
        (500, "provider_temporary_unavailable"),
        (502, "provider_temporary_unavailable"),
        (503, "provider_temporary_unavailable"),
        (599, "provider_temporary_unavailable"),
        (501, "provider_server_error"),
        (507, "provider_server_error"),
    ],
)
def test_transient_statuses_map_to_retryable_codes(status: int, expected_code: str) -> None:
    code, retryable = classify_provider_http_status(status)
    assert code == expected_code
    assert retryable is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
def test_client_errors_stay_non_retryable(status: int) -> None:
    # A 400 must not gain retryability from the status alone; the body is the
    # only thing that can promote it, and that is tested separately.
    assert classify_provider_http_status(status) == (None, False)


@pytest.mark.parametrize("status", [None, 0, -1])
def test_absent_or_nonsense_status_is_not_retryable(status: int | None) -> None:
    assert classify_provider_http_status(status) == (None, False)


def test_every_classified_code_is_in_the_retryable_set() -> None:
    codes = set()
    for status in (408, 429, 500, 502, 503, 501, 507, 599, 504):
        code, _ = classify_provider_http_status(status)
        assert code is not None
        codes.add(code)
    assert codes <= RETRYABLE_PROVIDER_ERROR_CODES, (
        f"codes not understood by the V2 poller: {codes - RETRYABLE_PROVIDER_ERROR_CODES}"
    )


class TestClassifyProviderError:
    def test_engine_overloaded_body_is_transient(self) -> None:
        # The exact Volcengine failure from the 2026-09-19 E2E run.
        body = '{"error": {"code": "engine_overloaded", "message": "please try again later"}}'
        code, retryable = classify_provider_error(status_code=503, response_body=body)
        assert code == "provider_temporary_unavailable"
        assert retryable is True

    def test_overload_body_promotes_non_5xx_status(self) -> None:
        # A provider that reports overload under 400 must still be transient,
        # otherwise the operator sees a permanent failure for a temporary one.
        body = '{"error": {"type": "engine_overloaded"}}'
        code, retryable = classify_provider_error(status_code=400, response_body=body)
        assert code == "provider_temporary_unavailable"
        assert retryable is True

    def test_rate_limit_body_wins_over_temporary(self) -> None:
        body = "too many requests, slow down"
        code, _ = classify_provider_error(status_code=503, response_body=body)
        assert code == "provider_rate_limited"

    def test_plain_400_stays_non_retryable(self) -> None:
        body = '{"error": {"message": "prompt is empty"}}'
        assert classify_provider_error(status_code=400, response_body=body) == (None, False)

    def test_status_alone_is_still_honored_without_body(self) -> None:
        assert classify_provider_error(status_code=503) == (
            "provider_temporary_unavailable",
            True,
        )

    def test_video_queue_full_body_is_transient(self) -> None:
        # The exact video failure from the 2026-09-21 E2E run. The native
        # adapter path discards the HTTP status, so the body is the only
        # witness left -- and it spells the overload as a full queue, not as
        # "engine_overloaded".
        body = (
            "media_api_failed:\n"
            "user_action=The provider engine is temporarily overloaded. "
            "This is transient - the request is safe to retry as-is.\n"
            "provider=agnes\nstatus=503\n"
            'response_body={"code":"video_queue_full",'
            '"message":"视频队列已满，请稍后重试 (request id: 20260921095116397820206zuKcUCgT)",'
            '"data":null}'
        )
        code, retryable = classify_provider_error(response_body=body)
        assert code == "provider_temporary_unavailable"
        assert retryable is True
        assert code in RETRYABLE_PROVIDER_ERROR_CODES

    @pytest.mark.parametrize(
        "body",
        [
            "queue_full",
            "video queue full, retry shortly",
            "队列已满",
            "请稍后重试",
            "server overloaded",
        ],
    )
    def test_overload_spellings_without_a_status_are_transient(self, body: str) -> None:
        # Different vendors spell the same condition differently; the adapter
        # that flattens the status must not need to know each spelling.
        code, retryable = classify_provider_error(response_body=body)
        assert (code, retryable) == ("provider_temporary_unavailable", True)

    def test_unparseable_body_falls_back_to_status(self) -> None:
        assert classify_provider_error(status_code=429, response_body="not json") == (
            "provider_rate_limited",
            True,
        )


class TestProviderErrorTypeFromBody:
    def test_extracts_engine_overloaded(self) -> None:
        body = '{"error": {"type": "engine_overloaded"}}'
        assert provider_error_type_from_body(body) == "engine_overloaded"

    @pytest.mark.parametrize("body", [None, "", "not json", "[]", '{"error": {}}'])
    def test_returns_none_when_unavailable(self, body: str | None) -> None:
        assert provider_error_type_from_body(body) is None


class TestProviderLabelFollowsTheEndpoint:
    """The error must name the gateway that was actually called.

    ``IMAGE_GENERATION_ENDPOINT`` is configurable and points at StepFun's
    ``step_plan`` gateway, which proxies the same upstream engine.  A hardcoded
    ``provider=volcengine`` therefore reported a correctly-routed StepFun request
    as if it had gone to the wrong provider, which reads as "the StepFun
    migration did not take effect" and sends the reader hunting a routing bug
    that does not exist.
    """

    def test_stepfun_gateway_is_labelled_stepfun(self) -> None:
        assert (
            _provider_label_for_endpoint(
                "https://api.stepfun.com/step_plan/v1/images/generations"
            )
            == "stepfun"
        )

    def test_volcengine_gateway_is_labelled_volcengine(self) -> None:
        assert (
            _provider_label_for_endpoint(
                "https://ark.cn-beijing.volces.com/api/v3/images/generations"
            )
            == "volcengine"
        )

    def test_label_is_case_insensitive(self) -> None:
        assert _provider_label_for_endpoint("HTTPS://API.STEPFUN.COM/v1") == "stepfun"

    def test_unknown_host_is_not_claimed_as_volcengine(self) -> None:
        # Claiming a provider we did not call is worse than admitting we do not
        # know; "unknown" at least tells the reader to look at the endpoint.
        assert _provider_label_for_endpoint("https://example.invalid/v1") == "unknown"

    def test_empty_endpoint_keeps_the_legacy_label(self) -> None:
        assert _provider_label_for_endpoint("") == "volcengine"

    def test_raised_error_reports_the_real_gateway(self) -> None:
        # End to end through the real raise site: the label in the message and in
        # the metadata must both come from the endpoint.
        exc = _HTTPError503("https://api.stepfun.com/step_plan/v1/images/generations")
        error = _media_api_error(
            exc=exc,
            endpoint="https://api.stepfun.com/step_plan/v1/images/generations",
            payload={"model": "step-image-edit-2", "prompt": "a teahouse"},
        )
        assert error.metadata["provider"] == "stepfun"
        assert "provider=stepfun" in str(error)
        assert "provider=volcengine" not in str(error)
        assert error.metadata["status"] == 503
        assert error.metadata["provider_error_code"] == "engine_overloaded"


class TestGatewayRetryDirective:
    """The gateway's own retry verdict must survive into the error.

    StepFun's step_plan gateway answers the image 503 with
    ``X-Should-Retry: false`` while the body says "please try again later".  A
    successful TTS request on the same key carries no such header, so the
    directive is real and specific -- but the hint used to promise "safe to
    retry as-is" regardless, which sends the operator in circles.
    """

    def _error(self, headers: dict[str, str] | None = None):
        return _media_api_error(
            exc=_HTTPError503(
                "https://api.stepfun.com/step_plan/v1/images/generations", headers
            ),
            endpoint="https://api.stepfun.com/step_plan/v1/images/generations",
            payload={"model": "step-image-edit-2", "prompt": "a teahouse"},
        )

    def test_should_retry_false_is_recorded(self) -> None:
        error = self._error(_STEP_PLAN_OVERLOAD_HEADERS)
        assert error.metadata["provider_should_retry"] is False
        assert error.metadata["provider_trace_id"] == (
            "70e2d34d70170d972ca3f346011751b5"
        )

    def test_the_hint_stops_promising_a_retry(self) -> None:
        error = self._error(_STEP_PLAN_OVERLOAD_HEADERS)
        assert "X-Should-Retry" in str(error)
        assert "safe to retry as-is" not in str(error)

    def test_should_retry_true_keeps_the_transient_hint(self) -> None:
        error = self._error({"X-Should-Retry": "true"})
        assert error.metadata["provider_should_retry"] is True
        assert "safe to retry as-is" in str(error)

    def test_an_absent_header_keeps_the_transient_hint(self) -> None:
        # Most providers do not send the header at all, and the status alone is
        # still the best evidence available.
        error = self._error()
        assert "provider_should_retry" not in error.metadata
        assert "safe to retry as-is" in str(error)

    def test_trace_id_reaches_the_message(self) -> None:
        error = self._error(_STEP_PLAN_OVERLOAD_HEADERS)
        assert "provider_trace_id=70e2d34d70170d972ca3f346011751b5" in str(error)

    def test_our_retryable_classification_is_untouched(self) -> None:
        """The header changes the hint, not the two-gate contract.

        ``provider_should_retry`` is the gateway's opinion; ``retryable`` is
        ours, derived from the status.  Conflating them would make one provider's
        header able to switch off retry for every caller.
        """

        code, retryable = classify_provider_error(
            status_code=503,
            response_body=_OVERLOAD_BODY,
        )
        assert code == "provider_temporary_unavailable"
        assert retryable is True
