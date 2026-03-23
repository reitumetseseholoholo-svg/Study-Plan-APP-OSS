"""Managed llama-server subprocess.

Starts llama-server with a GGUF model, monitors health, supports model
swapping, and shuts down cleanly.  The server exposes an OpenAI-compatible
``/v1/chat/completions`` endpoint that ``LlamaCppTutorService`` already
speaks to.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class LlamaServerConfig:
    binary: str = field(
        default_factory=lambda: os.environ.get(
            "STUDYPLAN_LLAMA_SERVER_BIN",
            shutil.which("llama-server") or "llama-server",
        )
    )
    host: str = "127.0.0.1"
    port: int = field(
        default_factory=lambda: int(os.environ.get("STUDYPLAN_LLAMA_SERVER_PORT", "8090"))
    )
    threads: int = field(
        default_factory=lambda: max(1, min(os.cpu_count() or 4, 6))
    )
    ctx_size: int = 4096
    n_gpu_layers: int = 0
    batch_size: int = 512
    extra_args: list[str] = field(default_factory=list)
    startup_timeout_seconds: float = 60.0
    health_poll_interval: float = 0.5
    shutdown_timeout_seconds: float = 10.0
    # After this many seconds without mark_used / successful ensure_running touch, stop llama-server
    # to drop resident model memory. 0 disables.
    idle_shutdown_seconds: float = 0.0
    idle_poll_interval_seconds: float = 10.0


@dataclass
class LlamaServerManager:
    """Lifecycle manager for a single llama-server subprocess."""

    config: LlamaServerConfig = field(default_factory=LlamaServerConfig)
    _process: subprocess.Popen[bytes] | None = field(default=None, init=False, repr=False)
    _current_model_path: str = field(default="", init=False, repr=False)
    _current_model_name: str = field(default="", init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _registered_atexit: bool = field(default=False, init=False, repr=False)
    _startup_latency_ms: int = field(default=0, init=False, repr=False)
    _last_activity_mono: float = field(default=0.0, init=False, repr=False)
    _idle_watcher_thread: threading.Thread | None = field(default=None, init=False, repr=False)

    @property
    def endpoint(self) -> str:
        return f"http://{self.config.host}:{self.config.port}/v1/chat/completions"

    @property
    def health_url(self) -> str:
        return f"http://{self.config.host}:{self.config.port}/health"

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    @property
    def current_model(self) -> str:
        return self._current_model_name

    @property
    def startup_latency_ms(self) -> int:
        return self._startup_latency_ms

    def ensure_running(self, model_path: str, model_name: str = "") -> bool:
        """Start the server with the given model, or confirm it's already running it.

        Returns True if the server is healthy and ready.
        """
        with self._lock:
            if self._process and self._process.poll() is None:
                if self._current_model_path == model_path:
                    if self._health_check_unlocked():
                        self._last_activity_mono = time.monotonic()
                        return True
                self._stop_unlocked()

            return self._start_unlocked(model_path, model_name or os.path.basename(model_path))

    def stop(self) -> None:
        with self._lock:
            self._stop_unlocked()

    def swap_model(self, model_path: str, model_name: str = "") -> bool:
        """Stop current server and start with a different model."""
        return self.ensure_running(model_path, model_name)

    def mark_used(self) -> None:
        """Record activity so idle shutdown does not stop a busy server."""
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                return
            self._last_activity_mono = time.monotonic()

    def status(self) -> dict[str, Any]:
        return {
            "running": self.is_running,
            "model": self._current_model_name,
            "model_path": self._current_model_path,
            "endpoint": self.endpoint,
            "pid": self._process.pid if self._process else None,
            "startup_latency_ms": self._startup_latency_ms,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _start_unlocked(self, model_path: str, model_name: str) -> bool:
        binary = self.config.binary
        if not binary or not shutil.which(binary):
            log.error("llama-server binary not found: %s", binary)
            return False

        if not os.path.isfile(model_path):
            log.error("GGUF model file not found: %s", model_path)
            return False

        cmd = [
            binary,
            "-m", model_path,
            "--host", self.config.host,
            "--port", str(self.config.port),
            "-t", str(self.config.threads),
            "-c", str(self.config.ctx_size),
            "-ngl", str(self.config.n_gpu_layers),
            "-b", str(self.config.batch_size),
            "--log-disable",
        ]
        cmd.extend(self.config.extra_args)

        log.info("Starting llama-server: %s", " ".join(cmd))
        t0 = time.monotonic()

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                preexec_fn=os.setpgrp,
            )
        except (OSError, FileNotFoundError) as exc:
            log.error("Failed to start llama-server: %s", exc)
            self._process = None
            return False

        self._current_model_path = model_path
        self._current_model_name = model_name

        if not self._registered_atexit:
            atexit.register(self.stop)
            self._registered_atexit = True

        ok = self._wait_for_healthy(self.config.startup_timeout_seconds)
        elapsed = int((time.monotonic() - t0) * 1000)
        self._startup_latency_ms = elapsed

        if ok:
            self._last_activity_mono = time.monotonic()
            self._ensure_idle_watcher_started_unlocked()
            log.info(
                "llama-server ready in %dms (pid=%d, model=%s)",
                elapsed,
                self._process.pid if self._process else -1,
                model_name,
            )
        else:
            log.error(
                "llama-server failed to become healthy within %.1fs, stopping",
                self.config.startup_timeout_seconds,
            )
            self._dump_stderr()
            self._stop_unlocked()

        return ok

    def _ensure_idle_watcher_started_unlocked(self) -> None:
        lim = float(self.config.idle_shutdown_seconds or 0.0)
        if lim <= 0:
            return
        if self._idle_watcher_thread is not None and self._idle_watcher_thread.is_alive():
            return
        thread = threading.Thread(
            target=self._idle_watcher_loop,
            name="studyplan-llama-idle",
            daemon=True,
        )
        self._idle_watcher_thread = thread
        thread.start()

    def _idle_watcher_loop(self) -> None:
        poll = float(self.config.idle_poll_interval_seconds or 10.0)
        poll = max(1.0, min(120.0, poll))
        while True:
            time.sleep(poll)
            lim = float(self.config.idle_shutdown_seconds or 0.0)
            if lim <= 0:
                continue
            to_finalize: subprocess.Popen[bytes] | None = None
            with self._lock:
                proc = self._process
                if proc is None or proc.poll() is not None:
                    continue
                if (time.monotonic() - self._last_activity_mono) <= lim:
                    continue
                log.info(
                    "llama-server idle for %.0fs; stopping to free model memory",
                    lim,
                )
                self._process = None
                self._current_model_path = ""
                self._current_model_name = ""
                to_finalize = proc
            if to_finalize is not None:
                self._finalize_subprocess(to_finalize)

    def _stop_unlocked(self) -> None:
        proc = self._process
        if proc is None:
            return
        self._process = None
        self._current_model_path = ""
        self._current_model_name = ""

        if proc.poll() is not None:
            return

        self._finalize_subprocess(proc)

    def _finalize_subprocess(self, proc: subprocess.Popen[bytes]) -> None:
        log.info("Stopping llama-server (pid=%d)", proc.pid)
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass

        try:
            proc.wait(timeout=self.config.shutdown_timeout_seconds)
        except subprocess.TimeoutExpired:
            log.warning("llama-server did not exit gracefully, sending SIGKILL")
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
            try:
                proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                pass

    def _wait_for_healthy(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        interval = self.config.health_poll_interval
        while time.monotonic() < deadline:
            if self._process is None or self._process.poll() is not None:
                return False
            if self._health_check_unlocked():
                return True
            time.sleep(interval)
        return False

    def _health_check_unlocked(self) -> bool:
        try:
            with urllib.request.urlopen(self.health_url, timeout=2.0) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                if resp.status == 200:
                    try:
                        data = json.loads(body)
                        return data.get("status") == "ok"
                    except (json.JSONDecodeError, AttributeError):
                        return True
                return False
        except Exception:
            return False

    def _dump_stderr(self) -> None:
        proc = self._process
        if proc is None or proc.stderr is None:
            return
        try:
            stderr = proc.stderr.read(4096)
            if stderr:
                log.error("llama-server stderr: %s", stderr.decode("utf-8", errors="replace")[:500])
        except Exception:
            pass
