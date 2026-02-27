"""llama.cpp-backed secondary generation service.

This module is intentionally stdlib-only so it can run in constrained
environments. It supports:
1) Discovering Ollama models that point to local GGUF blobs.
2) Persisting a lightweight registry for llama.cpp model selection.
3) Calling a running llama.cpp server (OpenAI-compatible HTTP API).
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass

from ..logging_config import get_logger

logger = get_logger(__name__)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = str(os.environ.get(name, "") or "").strip()
    try:
        value = int(raw) if raw else int(default)
    except (TypeError, ValueError):
        value = int(default)
    return max(int(minimum), min(int(maximum), int(value)))


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name, "") or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "on"}


def _registry_default_path() -> str:
    configured = str(os.environ.get("STUDYPLAN_LLAMACPP_REGISTRY_PATH", "") or "").strip()
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    return os.path.expanduser("~/.config/studyplan/llama_cpp_models.json")


def _run_capture(cmd: list[str], timeout_s: int = 20) -> tuple[str, str, int]:
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_s)),
        )
        return str(proc.stdout or ""), str(proc.stderr or ""), int(proc.returncode)
    except (OSError, subprocess.SubprocessError) as exc:
        return "", str(exc), 1


def _parse_ollama_list_names(text: str) -> list[str]:
    names: list[str] = []
    for idx, line in enumerate(str(text or "").splitlines()):
        row = str(line or "").strip()
        if not row:
            continue
        if idx == 0 and "name" in row.lower() and "id" in row.lower():
            continue
        parts = row.split()
        if not parts:
            continue
        name = str(parts[0] or "").strip()
        if name and name.lower() != "name":
            names.append(name)
    return names


def _resolve_ollama_from_value(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith("sha256:"):
        digest = raw.split(":", 1)[1].strip().lower()
        if digest:
            return os.path.expanduser(f"~/.ollama/models/blobs/sha256-{digest}")
    if raw.startswith("sha256-"):
        return os.path.expanduser(f"~/.ollama/models/blobs/{raw}")
    if raw.startswith("/") or raw.startswith("~"):
        return os.path.abspath(os.path.expanduser(raw))
    # Sometimes FROM may include "blob:sha256:..."
    match = re.search(r"sha256:([0-9a-fA-F]{32,128})", raw)
    if match:
        digest = str(match.group(1) or "").lower()
        if digest:
            return os.path.expanduser(f"~/.ollama/models/blobs/sha256-{digest}")
    return None


def _extract_modelfile_from_source(modelfile_text: str) -> str | None:
    for line in str(modelfile_text or "").splitlines():
        row = str(line or "").strip()
        if not row:
            continue
        if row.lower().startswith("from "):
            value = row[5:].strip()
            resolved = _resolve_ollama_from_value(value)
            if resolved:
                return resolved
    return None


def discover_ollama_gguf_models(
    *,
    ollama_bin: str = "ollama",
    max_models: int = 32,
) -> dict[str, str]:
    """Return {ollama_model_name: gguf_path} for locally discoverable models."""
    out: dict[str, str] = {}
    limit = max(1, min(128, int(max_models)))
    if not shutil_which(ollama_bin):
        return out
    stdout, _stderr, rc = _run_capture([ollama_bin, "list"], timeout_s=20)
    if rc != 0:
        return out
    names = _parse_ollama_list_names(stdout)[:limit]
    for model_name in names:
        show_out, _show_err, show_rc = _run_capture([ollama_bin, "show", model_name, "--modelfile"], timeout_s=20)
        if show_rc != 0:
            continue
        resolved = _extract_modelfile_from_source(show_out)
        if not resolved:
            continue
        if not os.path.isfile(resolved):
            continue
        out[str(model_name)] = str(resolved)
    return out


def load_llamacpp_registry(path: str | None = None) -> dict[str, str]:
    reg_path = path or _registry_default_path()
    try:
        text = open(reg_path, "r", encoding="utf-8").read()
    except OSError:
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    models = payload.get("models", {})
    if not isinstance(models, dict):
        return {}
    out: dict[str, str] = {}
    for name, gguf_path in models.items():
        key = str(name or "").strip()
        val = str(gguf_path or "").strip()
        if not key or not val:
            continue
        out[key] = val
    return out


def sync_ollama_models_to_llamacpp_registry(
    *,
    registry_path: str | None = None,
    max_models: int = 32,
    ollama_bin: str = "ollama",
) -> dict[str, int | str]:
    """Discover Ollama models and write llama.cpp model registry."""
    reg_path = registry_path or _registry_default_path()
    existing = load_llamacpp_registry(reg_path)
    discovered = discover_ollama_gguf_models(ollama_bin=ollama_bin, max_models=max_models)

    merged = dict(existing)
    merged.update(discovered)

    parent = os.path.dirname(reg_path) or "."
    os.makedirs(parent, mode=0o700, exist_ok=True)
    payload = {
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "source": "ollama_modelfile_discovery",
        "models": merged,
    }
    tmp_path = f"{reg_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    os.replace(tmp_path, reg_path)

    return {
        "existing": int(len(existing)),
        "discovered": int(len(discovered)),
        "total": int(len(merged)),
        "registry_path": reg_path,
    }


def shutil_which(cmd: str) -> str | None:
    # Local helper to avoid adding a top-level shutil import for one call site.
    import shutil

    return shutil.which(cmd)


@dataclass
class LlamaCppHTTPConfig:
    base_url: str = "http://127.0.0.1:8080"
    timeout_seconds: int = 40
    model: str = ""

    @classmethod
    def from_env(cls) -> "LlamaCppHTTPConfig":
        base_url = str(os.environ.get("STUDYPLAN_LLAMACPP_BASE_URL", "http://127.0.0.1:8080") or "").strip()
        timeout_seconds = _env_int("STUDYPLAN_LLAMACPP_TIMEOUT_SECONDS", 40, 5, 600)
        model = str(os.environ.get("STUDYPLAN_LLAMACPP_MODEL", "") or "").strip()
        return cls(base_url=base_url, timeout_seconds=timeout_seconds, model=model)


class LlamaCppHTTPQGenService:
    """Question generation via a running llama.cpp server."""

    def __init__(self, config: LlamaCppHTTPConfig | None = None):
        self._config = config or LlamaCppHTTPConfig.from_env()

    @property
    def model_name(self) -> str:
        if self._config.model:
            return self._config.model
        registry = load_llamacpp_registry()
        if registry:
            return sorted(registry.keys())[0]
        return "llama.cpp"

    def _chat_completion(self, prompt: str) -> tuple[str, str | None]:
        base = str(self._config.base_url or "").rstrip("/")
        url = f"{base}/v1/chat/completions"
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": "You generate concise ACCA-style practice questions."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 500,
            "stream": False,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=max(1, int(self._config.timeout_seconds))) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            return "", str(exc)
        except OSError as exc:
            return "", str(exc)
        try:
            body = json.loads(raw)
        except Exception as exc:
            return "", f"invalid_json:{exc}"
        try:
            choices = list(body.get("choices", []) or [])
            if not choices:
                return "", "no_choices"
            msg = dict(choices[0].get("message", {}) or {})
            content = str(msg.get("content", "") or "").strip()
            if not content:
                return "", "empty_content"
            return content, None
        except Exception as exc:
            return "", f"parse_error:{exc}"

    @staticmethod
    def _extract_questions(text: str, count: int) -> list[str]:
        raw = str(text or "").strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                rows = [str(item or "").strip() for item in data if str(item or "").strip()]
                return rows[:count]
        except Exception:
            pass
        rows: list[str] = []
        for line in raw.splitlines():
            row = str(line or "").strip()
            if not row:
                continue
            row = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", row).strip()
            if row:
                rows.append(row)
            if len(rows) >= count:
                break
        return rows[:count]

    def generate_questions(
        self,
        *,
        topic: str,
        source_text: str | None = None,
        count: int = 5,
    ) -> list[str]:
        wanted = max(1, min(20, int(count)))
        topic_text = str(topic or "").strip() or "topic"
        base = str(source_text or topic_text).strip()
        prompt = (
            "Return JSON array only.\n"
            f"Generate {wanted} concise ACCA practice questions for: {topic_text}.\n"
            f"Context: {base}\n"
            "No answers, no explanations."
        )
        text, err = self._chat_completion(prompt)
        if err:
            logger.warning("llama.cpp qgen failed", extra={"err": err, "model": self.model_name})
            return [f"[{topic_text}] Auto-generated question {i+1} based on {base}." for i in range(wanted)]
        questions = self._extract_questions(text, wanted)
        if len(questions) < wanted:
            # Pad deterministically to avoid empty outputs in learning flow.
            for idx in range(len(questions), wanted):
                questions.append(f"[{topic_text}] Auto-generated question {idx+1} based on {base}.")
        return questions[:wanted]


def maybe_sync_llamacpp_registry_from_ollama() -> dict[str, int | str] | None:
    if not _env_bool("STUDYPLAN_LLAMACPP_SYNC_OLLAMA", default=True):
        return None
    try:
        return sync_ollama_models_to_llamacpp_registry(
            max_models=_env_int("STUDYPLAN_LLAMACPP_SYNC_MAX_MODELS", 32, 1, 256),
            ollama_bin=str(os.environ.get("STUDYPLAN_OLLAMA_BIN", "ollama") or "ollama").strip() or "ollama",
        )
    except Exception as exc:
        logger.warning("llama.cpp registry sync failed", extra={"err": str(exc)})
        return None

