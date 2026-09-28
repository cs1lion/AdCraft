"""Teardown job manager (D8): cancelable, budget-bounded reference teardown.

The demo-facing problem this solves: teardown is the only step that burns LLM
quota, and the old endpoint blocked the request with no job identity — the
UI's "cancel" only aborted the frontend fetch while the backend kept calling
the model (one misclick = one wasted analysis). This manager makes teardown a
first-class job:

* ``submit`` returns a job id immediately (the request never blocks on LLM);
* ``cancel`` is **cooperative but real**: the worker passes a ``cancel_check``
  into ``analyze_reference_teardown`` which is consulted before every LLM
  call, so a cancelled job issues no further model requests;
* a total ``timeout_seconds`` budget covers the *sum* of the per-call timeouts
  (each call is already bounded by ``DEFAULT_LLM_TIMEOUT_SECONDS``; N frames ×
  120s could still hang the demo) — on expiry the job fails loudly with a
  timeout error instead of waiting forever.

In-memory store, single-instance scope (mirrors
``app.services.scene3d.render_job_manager``); multi-instance deployments would
move the store to the database.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from app.services.replica.teardown import (
    TeardownCancelled,
    analyze_reference_teardown,
)

# 总预算默认值：默认抽帧数 × 单次调用超时 + 综合一次的兜底量。
DEFAULT_TEARDOWN_TIMEOUT_SECONDS = 900


@dataclass
class TeardownJob:
    """A reference-teardown job with its current state."""

    job_id: str
    status: str = "pending"  # pending | running | completed | failed | cancelled
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    # TeardownResult on success（端点层负责序列化成响应，职责不复制）
    result: Any = None
    error: str | None = None
    error_type: str | None = None
    # 调用方拥有的临时源视频路径：终态时由任务回收（端点 finally 不再管）
    cleanup_path: str | None = None


class TeardownJobManager:
    """Thread-safe in-memory teardown job store with a background pool.

    Cancellation sets the job status and is observed by the worker between
    LLM calls (``cancel_check``). A thread that is already inside an httpx
    call finishes that call first — bounded by the per-call timeout — but
    issues no further ones.
    """

    def __init__(self, max_workers: int = 2, job_ttl_seconds: int = 3600):
        self._jobs: dict[str, TeardownJob] = {}
        self._lock = threading.Lock()
        # 取消/超时的原因：cancel_check 返回 True 时记录，worker 据此区分
        # "用户取消"（cancelled）与"总预算耗尽"（failed + timeout）。
        self._cancel_reasons: dict[str, str] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="replica-teardown",
        )
        self._job_ttl = job_ttl_seconds

    # ------------------------------------------------------------------
    # Submission / queries / cancellation
    # ------------------------------------------------------------------

    def submit(
        self,
        *,
        video_path: str,
        num_frames: int,
        user_description: str | None,
        use_cache: bool,
        timeout_seconds: int = DEFAULT_TEARDOWN_TIMEOUT_SECONDS,
        cleanup_path: str | None = None,
    ) -> str:
        """Submit a teardown job. Returns the job id immediately."""
        job_id = str(uuid.uuid4())[:12]
        job = TeardownJob(job_id=job_id, cleanup_path=cleanup_path)
        with self._lock:
            self._jobs[job_id] = job
        self._executor.submit(
            self._execute_job,
            job_id,
            video_path,
            num_frames,
            user_description,
            use_cache,
            timeout_seconds,
        )
        return job_id

    def get(self, job_id: str) -> TeardownJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        """Request cancellation. The worker stops before the next LLM call.

        Returns True when the job existed and was still in flight.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status not in ("pending", "running"):
                return False
            job.status = "cancelled"
            job.completed_at = time.time()
            self._cancel_reasons[job_id] = "cancelled"
            self._cleanup_locked(job)
            return True

    def cleanup(self) -> int:
        """Drop terminal jobs older than the TTL. Returns count removed."""
        now = time.time()
        removed = 0
        with self._lock:
            for job_id in list(self._jobs.keys()):
                job = self._jobs[job_id]
                if job.completed_at and (now - job.completed_at) > self._job_ttl:
                    del self._jobs[job_id]
                    self._cancel_reasons.pop(job_id, None)
                    removed += 1
        return removed

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)

    # ------------------------------------------------------------------
    # Internal: worker
    # ------------------------------------------------------------------

    def _cancel_check_factory(self, job_id: str, deadline: float):
        """Build the cooperative cancel/budget check for one job."""

        def _cancel_check() -> bool:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None or job.status == "cancelled":
                    return True
                if time.monotonic() > deadline:
                    # 总预算耗尽：记明原因，worker 会标成 timeout 失败——
                    # "明确失败"而不是让用户和额度一起干等。
                    self._cancel_reasons.setdefault(job_id, "timeout")
                    return True
            return False

        return _cancel_check

    def _execute_job(
        self,
        job_id: str,
        video_path: str,
        num_frames: int,
        user_description: str | None,
        use_cache: bool,
        timeout_seconds: int,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status == "cancelled":
                return
            job.status = "running"
            job.started_at = time.time()

        deadline = time.monotonic() + max(1, int(timeout_seconds))
        cancel_check = self._cancel_check_factory(job_id, deadline)
        try:
            result = analyze_reference_teardown(
                video_path=video_path,
                num_frames=num_frames,
                user_description=user_description,
                use_cache=use_cache,
                cancel_check=cancel_check,
            )
        except TeardownCancelled:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                if job.status == "cancelled":
                    return  # 用户取消：状态已由 cancel() 落好
                reason = self._cancel_reasons.get(job_id, "timeout")
                job.status = "failed"
                job.error_type = "teardown_timeout"
                job.error = (
                    f"拆解超过总时限 {timeout_seconds} 秒仍未完成，已停止后续 LLM "
                    "调用（未产生完整报告）。可重试，或减少抽帧数后再次拆解。"
                    if reason == "timeout"
                    else "拆解已取消"
                )
                job.completed_at = time.time()
                self._cleanup_locked(job)
            return
        except Exception as exc:  # noqa: BLE001 - 任务错误必须可查询，不吞
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None or job.status == "cancelled":
                    return
                job.status = "failed"
                job.error_type = getattr(exc, "error_type", None) or "teardown_failed"
                job.error = str(exc)[:400]
                job.completed_at = time.time()
                self._cleanup_locked(job)
            return

        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status == "cancelled":
                # 跑完那一刻用户已取消：结果作废，临时文件照收
                self._cleanup_locked(job)
                return
            job.status = "completed"
            job.result = result
            job.completed_at = time.time()
            self._cleanup_locked(job)

    def _cleanup_locked(self, job: TeardownJob) -> None:
        """Remove the caller-owned temp source file once the job is terminal."""
        path = job.cleanup_path
        job.cleanup_path = None
        if not path:
            return
        try:
            import os

            os.unlink(path)
        except Exception:
            pass


_default_manager: TeardownJobManager | None = None


def get_teardown_job_manager() -> TeardownJobManager:
    """Get the module-level singleton teardown job manager."""
    global _default_manager
    if _default_manager is None:
        _default_manager = TeardownJobManager()
    return _default_manager
