from __future__ import annotations

import contextlib
import threading
import time
from dataclasses import dataclass, field


class ShutdownInProgressError(RuntimeError):
    pass


@dataclass
class ShutdownBarrier:
    """Prevent new work from starting while shutdown is in progress."""

    _shutting_down: bool = False
    _active_work: set[str] = field(default_factory=set)
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _cv: threading.Condition = field(init=False)

    def __post_init__(self) -> None:
        self._cv = threading.Condition(self._lock)

    def is_shutting_down(self) -> bool:
        with self._lock:
            return bool(self._shutting_down)

    def start_work(self, work_id: str) -> bool:
        wid = str(work_id or "").strip()
        if not wid:
            wid = f"work-{time.monotonic_ns()}"
        with self._lock:
            if self._shutting_down:
                return False
            self._active_work.add(wid)
            return True

    def finish_work(self, work_id: str) -> None:
        wid = str(work_id or "").strip()
        with self._cv:
            if wid:
                self._active_work.discard(wid)
            self._cv.notify_all()

    @contextlib.contextmanager
    def work_scope(self, work_id: str):
        wid = str(work_id or "").strip() or f"work-{time.monotonic_ns()}"
        if not self.start_work(wid):
            raise ShutdownInProgressError(wid)
        try:
            yield wid
        finally:
            self.finish_work(wid)

    def active_work_ids(self) -> list[str]:
        with self._lock:
            return sorted(str(item) for item in self._active_work if str(item))

    def initiate_shutdown(self, timeout_sec: float = 30.0) -> bool:
        try:
            timeout = float(timeout_sec)
        except Exception:
            timeout = 30.0
        timeout = max(0.0, timeout)
        deadline = time.monotonic() + timeout
        with self._cv:
            self._shutting_down = True
            while self._active_work:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cv.wait(timeout=remaining)
            return True

