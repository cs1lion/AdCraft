"""D8：拆解任务化 —— 真取消、总预算 timeout、任务查询。

锁定的行为（对应 demo 阻断项"拆解的取消是假的"）：

1. POST /replica/teardown 只提交任务并立刻返回 job_id（不再阻塞请求、不再
   把 LLM 调用串在 HTTP 请求上）；
2. 取消是**真的**：fake analyze 在每次"LLM 调用"前咨询 cancel_check（与
   ``analyze_reference_teardown`` 生产路径同构），取消后不再产生新的调用；
3. 总预算耗尽 → 失败**明确**（teardown_timeout + 可读文案），不是无限等待；
4. AnalysisError 的 error_type 随任务可查询；
5. 未知 job id → 404；已终态任务取消 → cancelled=False + 原因。
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from app.services.replica import teardown as _teardown_module
from app.services.replica.teardown import (
    AnalysisError,
    TeardownCancelled,
    TeardownResult,
    analyze_reference_teardown,
)
from app.services.replica.teardown_jobs import TeardownJobManager


def _frame_json() -> str:
    return json.dumps(
        {
            "scene_type": "indoor",
            "environment_description": "bright studio desk",
            "lighting": "soft",
            "camera_angle": "eye-level",
            "shot_size": "closeup",
            "camera_motion_hint": "static",
            "characters": [],
            "props": [],
            "on_screen_text": "",
            "notable_elements": "",
        }
    )


def test_real_analyze_stops_between_llm_calls(monkeypatch, tmp_path) -> None:
    """生产路径锁定（区别于上面的 fake 自管取消）：真实
    ``analyze_reference_teardown`` 必须在每次 LLM 调用前咨询 cancel_check——
    第一帧后取消，就不准再发起后续帧/综合调用。

    mutation：把 ``check_teardown_cancelled`` 改成 no-op，本测试立刻变红。
    """
    calls: list[str] = []

    def fake_llm(*, image_path, **kwargs):
        calls.append(str(image_path))
        return _frame_json() if image_path is not None else "{}"

    monkeypatch.setattr(_teardown_module, "_call_multimodal_llm", fake_llm)
    monkeypatch.setattr(
        _teardown_module,
        "_build_llm_client",
        lambda: (None, "http://llm.test", "key", "test-model"),
    )
    monkeypatch.setattr(
        _teardown_module,
        "extract_metadata",
        lambda path: _teardown_module.VideoMetadata(
            duration_seconds=12.0,
            width=720,
            height=1280,
            frame_rate=30.0,
            frame_count=360,
            codec_name="h264",
            file_size_bytes=1,
        ),
    )
    monkeypatch.setattr(
        _teardown_module,
        "extract_keyframes_from_video",
        lambda video_path, output_dir, num_keyframes: [
            f"keyframe_{i:02d}.png" for i in range(num_keyframes)
        ],
    )
    monkeypatch.setattr(
        _teardown_module, "teardown_cache_dir", lambda media_dir: tmp_path / "cache"
    )

    video = tmp_path / "reference.mp4"
    video.write_bytes(b"fake-video-bytes")

    # 第一次帧调用发生之后即取消：生产路径应在此处停下
    with pytest.raises(TeardownCancelled):
        analyze_reference_teardown(
            video,
            num_frames=4,
            use_cache=False,
            cancel_check=lambda: len(calls) >= 1,
        )
    assert len(calls) == 1, f"取消后仍在发起 LLM 调用（{len(calls)} 次）"


def _fake_result(**overrides) -> TeardownResult:
    payload = dict(
        report=_teardown_module.TeardownReport(format_name="product-comparison"),
        frame_analyses=[],
        video_metadata=_teardown_module.VideoMetadata(
            duration_seconds=12.0,
            width=720,
            height=1280,
            frame_rate=30.0,
            frame_count=360,
            codec_name="h264",
            file_size_bytes=1,
        ),
        num_frames_analyzed=8,
        cached=False,
        cache_key="f" * 64,
    )
    payload.update(overrides)
    return TeardownResult(**payload)


class _RecordingAnalyze:
    """模拟逐帧 LLM 调用：每次"调用"前咨询 cancel_check（与生产同构）。"""

    def __init__(self, *, fail_after: int | None = None, error: Exception | None = None):
        self.calls = 0
        self.fail_after = fail_after
        self.error = error
        self._lock = threading.Lock()

    def __call__(self, **kwargs):
        check = kwargs.get("cancel_check")
        while True:
            if check is not None and check():
                raise TeardownCancelled()
            with self._lock:
                if self.fail_after is not None and self.calls >= self.fail_after:
                    raise self.error or AnalysisError("llm down", error_type="llm")
                self.calls += 1
                current = self.calls
            if current >= 20:
                return _fake_result()
            time.sleep(0.05)


@pytest.fixture
def endpoint_client(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import replica as replica_endpoint
    from app.services.replica import teardown_jobs as teardown_jobs_module

    stored = tmp_path / "reference.mp4"
    stored.write_bytes(b"fake")
    monkeypatch.setattr(replica_endpoint, "get_reference_video_path", lambda asset_id: stored)
    fresh_manager = TeardownJobManager()
    monkeypatch.setattr(replica_endpoint, "get_teardown_job_manager", lambda: fresh_manager)

    app = FastAPI()
    app.include_router(replica_endpoint.router)
    client = TestClient(app)
    yield client, teardown_jobs_module, fresh_manager
    fresh_manager.shutdown(wait=False)


def _submit(endpoint_client, **data) -> str:
    client, _, _ = endpoint_client
    payload = {"asset_id": "abc"}
    payload.update(data)
    response = client.post("/replica/teardown", data=payload)
    assert response.status_code == 200, response.text
    return response.json()["job_id"]


def _poll(endpoint_client, job_id: str) -> dict:
    client, _, _ = endpoint_client
    deadline = time.time() + 10
    body: dict = {}
    while time.time() < deadline:
        response = client.get(f"/replica/teardown/jobs/{job_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] in ("completed", "failed", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"job did not settle: {body}")


def test_submit_returns_job_id_and_completes_with_payload(endpoint_client, monkeypatch) -> None:
    _, jobs_module, _ = endpoint_client
    monkeypatch.setattr(jobs_module, "analyze_reference_teardown", _RecordingAnalyze())

    job_id = _submit(endpoint_client, user_description="换商品")
    body = _poll(endpoint_client, job_id)

    assert body["status"] == "completed"
    assert body["report"]["format_name"] == "product-comparison"
    assert body["num_frames_analyzed"] == 8
    assert body["cached"] is False
    assert body["cache_key"] == "f" * 64


def test_cancel_stops_llm_calls_for_real(endpoint_client, monkeypatch) -> None:
    """点了取消，后端真的停：取消后不再产生新的"LLM 调用"。"""
    client, jobs_module, _ = endpoint_client
    analyze = _RecordingAnalyze()
    monkeypatch.setattr(jobs_module, "analyze_reference_teardown", analyze)

    job_id = _submit(endpoint_client)
    # 等到至少一次"调用"发生再取消
    deadline = time.time() + 5
    while analyze.calls == 0 and time.time() < deadline:
        time.sleep(0.01)
    assert analyze.calls >= 1, "no LLM call observed before cancel"

    response = client.post(f"/replica/teardown/jobs/{job_id}/cancel")
    assert response.status_code == 200, response.text
    assert response.json()["cancelled"] is True

    body = _poll(endpoint_client, job_id)
    assert body["status"] == "cancelled"
    assert body["report"] == {}

    # 取消后冻结：给一个宽限期，调用数不得再增长
    frozen = analyze.calls
    time.sleep(0.4)
    assert analyze.calls == frozen, "backend kept calling the LLM after cancel"


def test_timeout_fails_loudly() -> None:
    """总预算耗尽 → 明确失败（teardown_timeout），不是无限等待。"""
    from app.services.replica import teardown_jobs as jobs_module

    def slow_analyze(**kwargs):
        check = kwargs.get("cancel_check")
        # 与生产同构：每次"调用"前咨询——预算耗尽时自己抛 TeardownCancelled
        while True:
            if check is not None and check():
                raise TeardownCancelled()
            time.sleep(0.05)

    original = jobs_module.analyze_reference_teardown
    jobs_module.analyze_reference_teardown = slow_analyze
    manager = TeardownJobManager()
    try:
        job_id = manager.submit(
            video_path="unused-by-fake",
            num_frames=4,
            user_description=None,
            use_cache=False,
            timeout_seconds=1,
        )
        deadline = time.time() + 10
        job = None
        while time.time() < deadline:
            job = manager.get(job_id)
            if job.status in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.02)
        assert job is not None and job.status == "failed", job
        assert job.error_type == "teardown_timeout"
        assert "总时限" in job.error
    finally:
        jobs_module.analyze_reference_teardown = original
        manager.shutdown(wait=False)


def test_analysis_error_is_queryable_on_the_job(endpoint_client, monkeypatch) -> None:
    _, jobs_module, _ = endpoint_client
    monkeypatch.setattr(
        jobs_module,
        "analyze_reference_teardown",
        _RecordingAnalyze(fail_after=0, error=AnalysisError("llm down", error_type="llm")),
    )

    job_id = _submit(endpoint_client)
    body = _poll(endpoint_client, job_id)

    assert body["status"] == "failed"
    assert body["error_type"] == "llm"
    assert "llm down" in body["error"]


def test_unknown_job_is_404(endpoint_client) -> None:
    client, _, _ = endpoint_client
    assert client.get("/replica/teardown/jobs/nope").status_code == 404
    assert client.post("/replica/teardown/jobs/nope/cancel").status_code == 404


def test_cancel_after_completion_reports_reason(endpoint_client, monkeypatch) -> None:
    client, jobs_module, _ = endpoint_client
    monkeypatch.setattr(jobs_module, "analyze_reference_teardown", _RecordingAnalyze())

    job_id = _submit(endpoint_client)
    body = _poll(endpoint_client, job_id)
    assert body["status"] == "completed"

    response = client.post(f"/replica/teardown/jobs/{job_id}/cancel")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["cancelled"] is False
    assert payload["reason"] == "任务已结束，无需取消"
