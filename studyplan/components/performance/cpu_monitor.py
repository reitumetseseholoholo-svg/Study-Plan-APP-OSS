"""
Lightweight CPU diagnostic: samples thread stacks and logs CPU burners.

Toggle at startup via ``STUDYPLAN_PERF_TRACE=1``; output goes to stderr.
"""

import os
import sys
import time
import threading
import traceback
from collections import Counter


_ENABLED = bool(int(os.environ.get("STUDYPLAN_PERF_TRACE", "0")))


def _thread_cpu_time() -> dict[int, float]:
    """Return ``{thread_native_id: user_cpu_seconds}`` for all threads (Linux)."""
    result: dict[int, float] = {}
    try:
        for entry in os.listdir("/proc/self/task"):
            tid = int(entry)
            try:
                with open(f"/proc/self/task/{tid}/stat") as f:
                    parts = f.read().split()
                utime = float(parts[11])
                stime = float(parts[12])
                hertz = float(os.sysconf(os.sysconf_names["SC_CLK_TCK"]))
                result[tid] = (utime + stime) / hertz
            except (OSError, ValueError, IndexError):
                pass
    except OSError:
        pass
    return result


class CPUMonitor:
    """Periodically samples thread stacks and logs the hottest call sites.

    Designed for interactive diagnosis — attach with ``STUDYPLAN_PERF_TRACE=1``.
    """

    def __init__(self, interval_s: float = 5.0) -> None:
        self.interval = max(1.0, float(interval_s))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._sample_count: int = 0
        self._last_cpu: dict[int, float] = {}
        self._stack_counts: Counter[str] = Counter()

    def start(self) -> None:
        if not _ENABLED:
            return
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._last_cpu = _thread_cpu_time()
        self._thread = threading.Thread(
            target=self._loop,
            name="studyplan-cpu-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread = None

    def _loop(self) -> None:
        print("[perf] CPU monitor started — sampling every {:.0f}s".format(self.interval), file=sys.stderr)
        while not self._stop_event.wait(timeout=self.interval):
            self._sample()
        self._report()

    def _sample(self) -> None:
        self._sample_count += 1
        now_cpu = _thread_cpu_time()
        delta: dict[int, float] = {}
        for tid, util in now_cpu.items():
            prev = self._last_cpu.get(tid, util)
            d = util - prev
            if d > self.interval * 0.3:  # at least 30% of wall clock
                delta[tid] = d
        self._last_cpu = now_cpu

        if not delta:
            return  # nothing busy this interval

        # Get thread names and stacks for busy threads
        frames = sys._current_frames()
        for tid, cpu_sec in sorted(delta.items(), key=lambda x: -x[1]):
            name = _thread_name(tid) or f"tid={tid}"
            pct = min(100.0, cpu_sec / self.interval * 100.0)
            frames_for_tid = None
            # Match native TID to Python thread ID (they may differ).
            for py_thread_id, frame in frames.items():
                if py_thread_id == tid:
                    frames_for_tid = frame
                    break
            if frames_for_tid is None:
                # Some TIDs may be non-Python (e.g., GTK worker threads).
                loc = "(non-python thread)"
            else:
                stack_summary = "".join(traceback.format_stack(frames_for_tid))
                loc = _collapse_python_stack(stack_summary)
            self._stack_counts[loc] += 1
            print(
                "[perf] CPU {:.0f}%  thread={}  tid={}  samples={}  top={}".format(
                    pct, name, tid, self._stack_counts[loc], loc
                ),
                file=sys.stderr,
            )

    def _report(self) -> None:
        if not self._stack_counts:
            return
        print("[perf] === CPU Monitor Summary ({} samples) ===".format(self._sample_count), file=sys.stderr)
        for loc, count in self._stack_counts.most_common(15):
            print("[perf]   {:>4}x  {}".format(count, loc), file=sys.stderr)


def _thread_name(tid: int) -> str | None:
    try:
        with open(f"/proc/self/task/{tid}/comm") as f:
            return f.read().strip()
    except OSError:
        return None


def _collapse_python_stack(stack: str) -> str:
    """Keep the most instructive frame from a Python traceback."""
    if not stack:
        return "?"
    lines = [l.strip() for l in stack.strip().splitlines() if l.strip()]
    if not lines:
        return "?"
    # The last meaningful line is usually the innermost call.
    for line in reversed(lines):
        if line.startswith("File "):
            return line[:120]
    return lines[-1][:120]


__all__ = ["CPUMonitor", "_ENABLED"]
