"""Real-shaped HTTP errors must survive native executor and Canvas projection."""

from __future__ import annotations

import io
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from app.core.config import Settings
from app.services.agent_canvas_execution_state import safe_execution_error
from app.services.v2_provider_error_classification import classify_provider_error
from app.services.v2_provider_executor import V2ProviderExecutor
from app.tools.media_response_parsing import _media_api_error

pytestmark = pytest.mark.integration


def media_error(status: int):
    # Chinese response contains no English classifier markers. Real metadata and
    # status=429 envelope must suffice; mutating status to 400 must turn red.
    body = '{"detail":"请求频率超过限制"}' if status == 429 else '{"detail":"输入无效"}'
    return _media_api_error(
        exc=HTTPError(
            "https://api.agnes-ai.cn/v1/videos", status, "refused", {}, io.BytesIO(body.encode())
        ),
        endpoint="https://api.agnes-ai.cn/v1/videos",
        payload={"model": "agnes-video-2.5-flash", "prompt": "test"},
    )


@pytest.mark.parametrize(
    "status,expected",
    [(429, ("provider_rate_limited", True)), (400, (None, False)), (401, (None, False))],
)
def test_legacy_media_error_envelope(status, expected):
    assert classify_provider_error(response_body=str(media_error(status))) == expected


@pytest.mark.parametrize(
    "body",
    [
        "prompt mentions status=429",
        'response_body={"status":429}',
        "media_api_failed:\nstatus=400\nresponse_body=\nstatus=429",
    ],
)
def test_no_arbitrary_status_inference(body):
    assert classify_provider_error(response_body=body) == (None, False)


@pytest.mark.parametrize("phase", ["submit", "poll"])
@pytest.mark.parametrize("status", [429, 400])
def test_native_video_http_error_projects_to_canvas(tmp_path, monkeypatch, phase, status):
    error = media_error(status)
    calls = []

    def fail(*args):
        calls.append(phase)
        raise error

    adapter = SimpleNamespace(
        active_profile=SimpleNamespace(supports_remote_task_lookup=True),
        compile=lambda *_: SimpleNamespace(audit={}),
        submit=fail,
        poll=fail,
    )
    executor = V2ProviderExecutor(settings=Settings(media_mode="real"), data_dir=tmp_path)
    monkeypatch.setattr(executor, "_native_adapter_for_payload", lambda *_, **__: (adapter, None))
    import app.services.v2_provider_executor as module

    monkeypatch.setattr(
        module,
        "_native_request_from_payload",
        lambda *_, **__: SimpleNamespace(provider_model_id="agnes-video-2.5-flash"),
    )
    monkeypatch.setattr(module, "_native_resolution_from_payload", lambda *_: None)
    payload = {"provider_id": "agnes", "provider_model_id": "agnes-video-2.5-flash"}
    if phase == "submit":
        result = executor._execute_native_minimal(
            workflow_id="test",
            slot_type="shot_video_segment",
            media_type="video",
            provider_payload=payload,
        )
    else:
        result = executor._poll_native_minimal(
            media_type="video",
            remote_task_id="existing-task",
            provider_payload=payload,
            result_descriptor={"native_adapter_audit": {"request_fingerprint": "test"}},
        )
    assert calls == [phase]  # Classification never resubmits a paid request.
    assert result.status == "failed"
    assert result.metadata["provider_http_status"] == status
    expected = "provider_rate_limited" if status == 429 else "provider_generation_failed"
    assert result.error_code == expected
    assert bool(result.metadata.get("retryable")) is (status == 429)
    projected_error = RuntimeError(result.error_message)
    projected_error.code = result.error_code
    projected_error.details = {"retryable": bool(result.metadata.get("retryable"))}
    projected = safe_execution_error(projected_error, default_code="provider_generation_failed")
    assert projected.code == expected
    assert projected.retryable is (status == 429)
