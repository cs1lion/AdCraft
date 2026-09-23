"""Transient provider retry in the canvas media executor (ISSUE-12).

A Volcengine 503 ``engine_overloaded`` is answered with the literal text
"please try again later", but the failure was flattened into
``provider_request_failed``, which is not retryable, so the node went red and
stayed red until the provider recovered on its own.

Two contracts matter here:
* a result flagged ``retryable`` is submitted again (and the eventual outcome
  records how many attempts it took, so a late success is not confused with a
  first-try one);
* a failure the provider does *not* call transient fails immediately, so a bad
  prompt or an unsupported model still costs exactly one request.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pytest

from app.core.config import Settings
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_runtime import ResolvedModelExecutionV1
from app.schemas.workflow_v2 import V2ProviderResult
from app.services.agent_canvas_execution_state import (
    APPROVED_TRANSIENT_ERROR_CODES,
    safe_execution_error,
)
from app.services.agent_canvas_node_execution import (
    MediaNodeExecutor,
    NodeExecutionContext,
)
from app.services.v2_provider_error_classification import (
    CLASSIFIED_RETRYABLE_PROVIDER_ERROR_CODES,
)
from app.services.v2_provider_executor import (
    _native_provider_failure,
    _native_status_error_text,
)
from app.services.workflow_v2 import RETRYABLE_PROVIDER_ERROR_CODES


class _ScriptedProvider:
    """Returns queued results in order, then repeats the last one."""

    def __init__(self, results: list[V2ProviderResult]) -> None:
        self._results = list(results)
        self.calls = 0

    def execute_minimal(self, **_: Any) -> V2ProviderResult:
        index = min(self.calls, len(self._results) - 1)
        self.calls += 1
        return self._results[index]


def _result(status: str, *, retryable: bool = False, code: str | None = None) -> V2ProviderResult:
    return V2ProviderResult(
        status=status,  # type: ignore[arg-type]
        media_type="image",
        error_code=code,
        error_message="provider refused the request",
        metadata={"retryable": retryable} if retryable else {},
    )


def _executor(
    tmp_path: Path,
    provider: _ScriptedProvider,
    *,
    attempts: int,
    base_delay: float = 0.0,
) -> MediaNodeExecutor:
    settings = Settings(
        provider_transient_retry_attempts=attempts,
        provider_transient_retry_base_delay_seconds=base_delay,
    )
    return MediaNodeExecutor(
        provider,  # type: ignore[arg-type]
        data_dir=tmp_path,
        settings=settings,
        seedance_inputs=None,
    )


def _submit(
    executor: MediaNodeExecutor,
) -> V2ProviderResult:
    return executor._submit_with_transient_retry(
        workflow_id="wf_retry",
        slot_type="scene",
        media_type="image",
        provider_payload={"prompt": "a teahouse"},
        intent=None,
    )


def _make_node() -> CanvasNodeV2:
    from datetime import datetime, timezone

    return CanvasNodeV2(
        node_id="node-image",
        workflow_id="wf_retry",
        node_type="image",  # type: ignore[arg-type]
        creative_role="storyboard_sequence",  # type: ignore[arg-type]
        title="Retry node",
        status="draft",
        generation_prompt="a teahouse at dusk",
        structured_content={},
        position={"x": 0.0, "y": 0.0},
        revision=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _model_resolution() -> ResolvedModelExecutionV1:
    return ResolvedModelExecutionV1(
        model_ref="stepfun:step-image-edit-2",
        provider_id="stepfun",
        provider_model_id="step-image-edit-2",
        capability="image",
        provider_protocol="stepfun_image",
        credential_revision=1,
        catalog_revision=4,
    )


def _context() -> NodeExecutionContext:
    return NodeExecutionContext(
        execution_id="exec-retry",
        node=_make_node(),
        inputs=(),
        model_resolution=_model_resolution(),
    )


class TestTransientRetry:
    def test_retryable_failure_is_retried_until_success(self, tmp_path: Path) -> None:
        provider = _ScriptedProvider(
            [
                _result("failed", retryable=True, code="provider_temporary_unavailable"),
                _result("failed", retryable=True, code="provider_temporary_unavailable"),
                _result("completed"),
            ]
        )
        result = _submit(_executor(tmp_path, provider, attempts=3))
        assert provider.calls == 3
        assert result.status == "completed"

    def test_attempt_count_rides_on_success_metadata(self, tmp_path: Path) -> None:
        # A node that only succeeded on the third attempt must not be
        # indistinguishable from one that succeeded first try.
        provider = _ScriptedProvider(
            [
                _result("failed", retryable=True),
                _result("failed", retryable=True),
                _result("completed"),
            ]
        )
        result = _submit(_executor(tmp_path, provider, attempts=3))
        assert result.metadata["provider_retry_attempts"] == 3
        assert result.metadata["provider_retry_attempts_total"] == 3

    def test_first_try_success_records_no_retry(self, tmp_path: Path) -> None:
        provider = _ScriptedProvider([_result("completed")])
        result = _submit(_executor(tmp_path, provider, attempts=3))
        assert provider.calls == 1
        assert "provider_retry_attempts" not in result.metadata

    def test_non_retryable_failure_fails_immediately(self, tmp_path: Path) -> None:
        provider = _ScriptedProvider(
            [_result("failed", retryable=False, code="provider_request_failed")]
        )
        result = _submit(_executor(tmp_path, provider, attempts=3))
        assert provider.calls == 1
        assert result.status == "failed"
        assert "provider_retry_attempts" not in result.metadata

    def test_exhausted_retries_return_the_last_failure(self, tmp_path: Path) -> None:
        provider = _ScriptedProvider([_result("failed", retryable=True)])
        result = _submit(_executor(tmp_path, provider, attempts=3))
        assert provider.calls == 3
        assert result.status == "failed"
        assert result.metadata["provider_retry_attempts"] == 3

    def test_attempts_of_one_never_retries(self, tmp_path: Path) -> None:
        provider = _ScriptedProvider([_result("failed", retryable=True)])
        result = _submit(_executor(tmp_path, provider, attempts=1))
        assert provider.calls == 1
        assert result.status == "failed"

    def test_zero_attempts_is_clamped_to_one(self, tmp_path: Path) -> None:
        provider = _ScriptedProvider([_result("failed", retryable=True)])
        _submit(_executor(tmp_path, provider, attempts=0))
        assert provider.calls == 1


class TestBackoffDoesNotRetryTransientStatusWithoutFlag:
    def test_unflagged_5xx_is_not_retried_by_this_layer(self, tmp_path: Path) -> None:
        # Only the executor's own retryable flag drives this layer; the V2
        # poller is the layer that classifies HTTP status. Two classifiers would
        # disagree about what "transient" means.
        provider = _ScriptedProvider([_result("failed", retryable=False, code=None)])
        _submit(_executor(tmp_path, provider, attempts=3))
        assert provider.calls == 1


class TestExhaustedTransientRetryStaysRetryable:
    """The flag must survive the hop from result to node error.

    ``_submit_with_transient_retry`` correctly retries a 503 and returns the
    last failure flagged ``retryable``.  The caller then raised
    ``_error(result.error_code, result.error_message)`` with no ``details``, so
    ``safe_execution_error`` saw ``details.get("retryable") == False`` and
    projected the node as permanently failed.  During the 2026-09-20 E2E run the
    image node sat red with ``code=provider_temporary_unavailable,
    retryable=False`` -- the classifier had already done its job and the last
    hop threw the answer away.
    """

    def test_every_classified_code_is_approved_transient(self) -> None:
        # The second gate: even with the flag carried, safe_execution_error
        # also requires the code to be in APPROVED_TRANSIENT_ERROR_CODES.
        assert CLASSIFIED_RETRYABLE_PROVIDER_ERROR_CODES <= APPROVED_TRANSIENT_ERROR_CODES

    def test_transient_code_with_flag_projects_as_retryable(self) -> None:
        error = V2PersistenceError(
            "provider_temporary_unavailable",
            "media_api_failed: The engine is currently overloaded, please try again later",
            stage="agent_canvas_node_execution",
            details={"retryable": True},
        )
        detail = safe_execution_error(error, default_code="node_execution_failed")
        assert detail.code == "provider_temporary_unavailable"
        assert detail.retryable is True

    def test_transient_code_without_flag_is_not_retryable(self) -> None:
        # Locks in the pre-fix behaviour so the regression is legible: the code
        # alone was never enough, the flag has to travel with it.
        error = V2PersistenceError(
            "provider_temporary_unavailable",
            "media_api_failed: The engine is currently overloaded",
            stage="agent_canvas_node_execution",
        )
        detail = safe_execution_error(error, default_code="node_execution_failed")
        assert detail.retryable is False

    def test_non_transient_code_with_flag_is_not_retryable(self) -> None:
        # A contract error must not become retryable just because something set
        # the flag; otherwise a bad prompt would burn quota on every retry.
        error = V2PersistenceError(
            "provider_request_failed",
            "prompt rejected",
            stage="agent_canvas_node_execution",
            details={"retryable": True},
        )
        assert safe_execution_error(error, default_code="x").retryable is False

    def test_media_executor_carries_the_flag_into_the_raised_error(
        self, tmp_path: Path
    ) -> None:
        # End-to-end through the real raise site: an exhausted backoff must
        # raise an error whose details still say "transient".
        provider = _ScriptedProvider(
            [_result("failed", retryable=True, code="provider_temporary_unavailable")]
        )
        executor = _executor(tmp_path, provider, attempts=1)
        context = _context()
        with pytest.raises(V2PersistenceError) as excinfo:
            executor(context)
        assert excinfo.value.code == "provider_temporary_unavailable"
        assert excinfo.value.details.get("retryable") is True
        assert safe_execution_error(
            excinfo.value, default_code="node_execution_failed"
        ).retryable is True


# ---------------------------------------------------------------------------
# The native adapter path (ISSUE-12, second front)
# ---------------------------------------------------------------------------

_VIDEO_QUEUE_FULL_BODY = (
    "media_api_failed:\n"
    "user_action=The provider engine is temporarily overloaded. "
    "This is transient - the request is safe to retry as-is.\n"
    "provider=agnes\nstatus=503\n"
    'response_body={"code":"video_queue_full",'
    '"message":"视频队列已满，请稍后重试 (request id: 20260921095116397820206zuKcUCgT)",'
    '"data":null}'
)


class _FakePollStatus:
    """A ProviderStatus stand-in: the state plus the vendor's raw body."""

    def __init__(self, state: str, raw: Mapping[str, object]) -> None:
        self.state = state
        self.raw = raw


class TestNativeFailureClassification:
    """The native path must classify exactly like the request path does.

    ``_execute_native_minimal`` used to hardcode ``provider_generation_failed``
    for every failure, which is not in ``RETRYABLE_PROVIDER_ERROR_CODES``. The
    2026-09-21 video node hit this: Ark's own adapter raised the very 503 the
    ``except MediaApiError`` branch was already classifying as transient, and
    the node still came back red with ``retryable=False``.
    """

    def test_transient_body_becomes_a_retryable_code(self) -> None:
        result = _native_provider_failure(
            media_type="video",
            provider_payload={"provider_id": "volcengine_ark"},
            error_code="provider_generation_failed",
            error_message=_VIDEO_QUEUE_FULL_BODY,
        )
        assert result.error_code == "provider_temporary_unavailable"
        assert result.metadata["retryable"] is True
        # The generic code survives in metadata so the operator can still see
        # what the native adapter itself reported.
        assert result.metadata["native_error_code"] == "provider_generation_failed"
        assert result.error_code in RETRYABLE_PROVIDER_ERROR_CODES

    def test_contract_error_keeps_the_generic_code(self) -> None:
        result = _native_provider_failure(
            media_type="video",
            provider_payload={"provider_id": "volcengine_ark"},
            error_code="provider_generation_failed",
            error_message="duration must be an integer between 3 and 12",
        )
        assert result.error_code == "provider_generation_failed"
        assert result.metadata.get("retryable") in (None, False)

    def test_specific_native_code_is_not_overridden(self) -> None:
        # provider_payload_resolution_mismatch is a contract violation dressed
        # as a provider error; classifying it away would hide a wiring bug.
        result = _native_provider_failure(
            media_type="video",
            provider_payload={"provider_id": "volcengine_ark"},
            error_code="provider_payload_resolution_mismatch",
        )
        assert result.error_code == "provider_payload_resolution_mismatch"
        assert result.metadata.get("retryable") in (None, False)

    def test_poll_status_text_carries_the_vendor_reason(self) -> None:
        status = _FakePollStatus(
            "failed",
            {"code": "video_queue_full", "message": "视频队列已满，请稍后重试"},
        )
        text = _native_status_error_text(status)
        assert "video_queue_full" in text
        assert "队列已满" in text

    def test_poll_failure_is_classified_from_the_vendor_body(self) -> None:
        # The poll branch passes the raw text explicitly: a poll that comes back
        # "failed" with no further detail would otherwise be indistinguishable
        # from a content rejection.
        status = _FakePollStatus(
            "failed",
            {"code": "video_queue_full", "message": "视频队列已满，请稍后重试"},
        )
        result = _native_provider_failure(
            media_type="video",
            provider_payload={"provider_id": "volcengine_ark"},
            error_code="provider_generation_failed",
            raw_body=_native_status_error_text(status),
        )
        assert result.error_code == "provider_temporary_unavailable"
        assert result.metadata["retryable"] is True

    def test_poll_status_without_a_body_is_not_retryable(self) -> None:
        status = _FakePollStatus("failed", {})
        result = _native_provider_failure(
            media_type="video",
            provider_payload={"provider_id": "volcengine_ark"},
            error_code="provider_generation_failed",
            raw_body=_native_status_error_text(status),
        )
        assert result.error_code == "provider_generation_failed"
        assert result.metadata.get("retryable") in (None, False)
