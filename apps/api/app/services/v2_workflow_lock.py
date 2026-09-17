from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys
import threading
from typing import Iterator, TextIO

if sys.platform == "win32":
    import msvcrt

    def _flock_exclusive(file_object: TextIO) -> None:
        file_object.seek(0)
        msvcrt.locking(file_object.fileno(), msvcrt.LK_LOCK, 1)

    def _flock_release(file_object: TextIO) -> None:
        file_object.seek(0)
        msvcrt.locking(file_object.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _flock_exclusive(file_object: TextIO) -> None:
        fcntl.flock(file_object.fileno(), fcntl.LOCK_EX)

    def _flock_release(file_object: TextIO) -> None:
        fcntl.flock(file_object.fileno(), fcntl.LOCK_UN)

from app.services.v2_data_boundary import validate_v2_data_path


_LOCKS_GUARD = threading.Lock()
_WORKFLOW_LOCKS: dict[tuple[str, str], threading.RLock] = {}
_THREAD_STATE = threading.local()


def _held_workflow_locks() -> dict[tuple[str, str], tuple[int, TextIO]]:
    held = getattr(_THREAD_STATE, "held_workflow_locks", None)
    if held is None:
        held = {}
        _THREAD_STATE.held_workflow_locks = held
    return held


@contextmanager
def v2_workflow_lock(data_dir: Path, workflow_id: str) -> Iterator[None]:
    key = (str(data_dir.resolve()), workflow_id)
    with _LOCKS_GUARD:
        lock = _WORKFLOW_LOCKS.setdefault(key, threading.RLock())
    with lock:
        held = _held_workflow_locks()
        nested = held.get(key)
        if nested is not None:
            depth, handle = nested
            held[key] = (depth + 1, handle)
            try:
                yield
            finally:
                current_depth, current_handle = held[key]
                held[key] = (current_depth - 1, current_handle)
            return
        workflow_root = validate_v2_data_path(
            data_dir,
            data_dir / "v2" / "workflows" / workflow_id,
            operation="v2-workflow-lock",
        )
        workflow_root.mkdir(parents=True, exist_ok=True)
        lock_path = workflow_root / ".workflow.lock"
        handle = lock_path.open("a+", encoding="utf-8")
        _flock_exclusive(handle)
        held[key] = (1, handle)
        try:
            yield
        finally:
            _, outer_handle = held.pop(key)
            _flock_release(outer_handle)
            outer_handle.close()
