"""Unified GGUF model registry.

Scans GPT4All model directory, Ollama manifest→blob mappings, and optional
extra directories to produce a deduplicated catalog of locally-available
GGUF files that llama-server can load directly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

log = logging.getLogger(__name__)

_GGUF_MAGIC = b"GGUF"
_PARTIAL_HASH_BYTES = 8192


@dataclass(frozen=True)
class GgufModel:
    """A single discovered GGUF model."""

    name: str
    path: str
    size_bytes: int
    source: str  # "gpt4all" | "ollama" | "extra"
    architecture: str  # inferred from filename: "llama", "qwen", "phi", "gemma", etc.
    param_billions: float  # estimated from filename, 0.0 if unknown
    quant_tag: str  # "q4_0", "q4_k_m", "q8_0", etc.
    is_instruct: bool
    content_hash: str  # partial hash for dedup


@dataclass
class GgufRegistryConfig:
    gpt4all_dir: str = field(
        default_factory=lambda: os.path.expanduser("~/.local/share/nomic.ai/GPT4All")
    )
    ollama_manifests_dir: str = field(
        default_factory=lambda: os.path.expanduser(
            "~/.ollama/models/manifests/registry.ollama.ai/library"
        )
    )
    ollama_blobs_dir: str = field(
        default_factory=lambda: os.path.expanduser("~/.ollama/models/blobs")
    )
    extra_dirs: list[str] = field(default_factory=list)
    ttl_seconds: float = 120.0


@dataclass
class GgufRegistry:
    """Discovers and deduplicates GGUF models from multiple local sources."""

    config: GgufRegistryConfig = field(default_factory=GgufRegistryConfig)
    _catalog: list[GgufModel] = field(default_factory=list, init=False, repr=False)
    _catalog_ts: float = field(default=0.0, init=False, repr=False)

    def catalog(self, *, force_refresh: bool = False) -> list[GgufModel]:
        now = time.monotonic()
        ttl = max(5.0, min(3600.0, self.config.ttl_seconds))
        if self._catalog and not force_refresh and (now - self._catalog_ts) <= ttl:
            return list(self._catalog)
        self._catalog = self._scan_all()
        self._catalog_ts = now
        return list(self._catalog)

    def find_by_name(self, name: str) -> GgufModel | None:
        lower = name.strip().lower()
        for m in self.catalog():
            if m.name.lower() == lower:
                return m
        return None

    def find_best_match(self, name_hint: str) -> GgufModel | None:
        """Fuzzy match: find the model whose name best matches a hint string."""
        hint = name_hint.strip().lower()
        if not hint:
            return None
        candidates = self.catalog()
        if not candidates:
            return None
        exact = [m for m in candidates if m.name.lower() == hint]
        if exact:
            return exact[0]
        contained = [m for m in candidates if hint in m.name.lower()]
        if contained:
            return contained[0]
        tokens = set(re.split(r"[^a-z0-9]+", hint))
        tokens.discard("")

        def _overlap(m: GgufModel) -> int:
            m_tokens = set(re.split(r"[^a-z0-9]+", m.name.lower()))
            return len(tokens & m_tokens)

        best = max(candidates, key=_overlap)
        if _overlap(best) > 0:
            return best
        return None

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _scan_all(self) -> list[GgufModel]:
        seen_hashes: dict[str, GgufModel] = {}
        models: list[GgufModel] = []

        for m in self._scan_gpt4all():
            if m.content_hash not in seen_hashes:
                seen_hashes[m.content_hash] = m
                models.append(m)

        for m in self._scan_ollama():
            if m.content_hash not in seen_hashes:
                seen_hashes[m.content_hash] = m
                models.append(m)

        for m in self._scan_extra_dirs():
            if m.content_hash not in seen_hashes:
                seen_hashes[m.content_hash] = m
                models.append(m)

        log.info(
            "GGUF registry: %d unique models from %d total scanned",
            len(models),
            len(seen_hashes),
        )
        return models

    def _scan_gpt4all(self) -> list[GgufModel]:
        d = self.config.gpt4all_dir
        if not d or not os.path.isdir(d):
            return []
        out: list[GgufModel] = []
        try:
            entries = sorted(os.listdir(d))
        except OSError:
            return []
        for fname in entries:
            if not fname.lower().endswith(".gguf"):
                continue
            path = os.path.join(d, fname)
            if not os.path.isfile(path):
                continue
            size = _safe_file_size(path)
            if size < 1024:
                continue
            if not _is_gguf(path):
                continue
            out.append(_build_model_entry(
                path=path,
                filename=fname,
                source="gpt4all",
                size_bytes=size,
            ))
        return out

    def _scan_ollama(self) -> list[GgufModel]:
        manifests_dir = self.config.ollama_manifests_dir
        blobs_dir = self.config.ollama_blobs_dir
        if not manifests_dir or not os.path.isdir(manifests_dir):
            return []
        out: list[GgufModel] = []
        try:
            model_dirs = sorted(os.listdir(manifests_dir))
        except OSError:
            return []
        for model_name in model_dirs:
            model_path = os.path.join(manifests_dir, model_name)
            if not os.path.isdir(model_path):
                continue
            try:
                tags = sorted(os.listdir(model_path))
            except OSError:
                continue
            for tag in tags:
                tag_path = os.path.join(model_path, tag)
                if not os.path.isfile(tag_path):
                    continue
                gguf_path = _resolve_ollama_manifest_to_gguf(
                    tag_path, blobs_dir
                )
                if not gguf_path:
                    continue
                size = _safe_file_size(gguf_path)
                if size < 1024:
                    continue
                display_name = f"{model_name}:{tag}" if tag != "latest" else model_name
                out.append(_build_model_entry(
                    path=gguf_path,
                    filename=display_name,
                    source="ollama",
                    size_bytes=size,
                ))
        return out

    def _scan_extra_dirs(self) -> list[GgufModel]:
        out: list[GgufModel] = []
        for d in self.config.extra_dirs:
            expanded = os.path.expanduser(d)
            if not os.path.isdir(expanded):
                continue
            try:
                entries = sorted(os.listdir(expanded))
            except OSError:
                continue
            for fname in entries:
                if not fname.lower().endswith(".gguf"):
                    continue
                path = os.path.join(expanded, fname)
                if not os.path.isfile(path):
                    continue
                size = _safe_file_size(path)
                if size < 1024:
                    continue
                if not _is_gguf(path):
                    continue
                out.append(_build_model_entry(
                    path=path,
                    filename=fname,
                    source="extra",
                    size_bytes=size,
                ))
        return out


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _safe_file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _is_gguf(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == _GGUF_MAGIC
    except OSError:
        return False


def _partial_content_hash(path: str, size_bytes: int) -> str:
    """Hash first+last N bytes plus file size for fast dedup."""
    h = hashlib.sha256()
    h.update(str(size_bytes).encode())
    try:
        with open(path, "rb") as f:
            h.update(f.read(_PARTIAL_HASH_BYTES))
            if size_bytes > _PARTIAL_HASH_BYTES * 2:
                f.seek(size_bytes - _PARTIAL_HASH_BYTES)
                h.update(f.read(_PARTIAL_HASH_BYTES))
    except OSError:
        pass
    return h.hexdigest()[:24]


def _resolve_ollama_manifest_to_gguf(
    manifest_path: str, blobs_dir: str
) -> str | None:
    """Parse an Ollama manifest JSON and return the GGUF blob path."""
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    layers = data.get("layers")
    if not isinstance(layers, list):
        return None
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        if layer.get("mediaType") != "application/vnd.ollama.image.model":
            continue
        from_path = str(layer.get("from", "") or "").strip()
        if from_path and os.path.isfile(from_path) and _is_gguf(from_path):
            return from_path
        digest = str(layer.get("digest", "") or "").strip()
        if not digest:
            continue
        blob_filename = digest.replace(":", "-")
        blob_path = os.path.join(blobs_dir, blob_filename)
        if os.path.isfile(blob_path) and _is_gguf(blob_path):
            return blob_path
    return None


_ARCH_PATTERNS: list[tuple[str, str]] = [
    (r"deepseek", "deepseek"),
    (r"llama", "llama"),
    (r"qwen", "qwen"),
    (r"phi", "phi"),
    (r"gemma", "gemma"),
    (r"orca", "orca"),
    (r"mistral", "mistral"),
    (r"mamba", "mamba"),
    (r"falcon", "falcon"),
    (r"starcoder", "starcoder"),
]

_QUANT_PATTERN = re.compile(
    r"(q[2345678](?:_[0kms]+(?:_[sml])?)?|fp16|f16|bf16|f32)", re.IGNORECASE
)

_PARAM_PATTERNS = [
    re.compile(r"(?:^|[^0-9])(\d+\.\d+)\s*[bB](?![a-z])"),
    re.compile(r"(?:^|[-_ ])(\d+)[bB](?:[-_ ]|$)"),
]


def _infer_architecture(name: str) -> str:
    lower = name.lower()
    for pattern, arch in _ARCH_PATTERNS:
        if re.search(pattern, lower):
            return arch
    return "unknown"


def _infer_quant(name: str) -> str:
    m = _QUANT_PATTERN.search(name)
    return m.group(1).lower().replace("-", "_") if m else "unknown"


def _infer_param_billions(name: str) -> float:
    normalized = name.replace("_", ".")
    for pattern in _PARAM_PATTERNS:
        m = pattern.search(normalized)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return 0.0


def _infer_instruct(name: str) -> bool:
    lower = name.lower()
    return any(tok in lower for tok in ("instruct", "chat", "it-"))


def _build_model_entry(
    *,
    path: str,
    filename: str,
    source: str,
    size_bytes: int,
) -> GgufModel:
    stem = Path(filename).stem if filename.lower().endswith(".gguf") else filename
    norm_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", stem).strip("-").lower()
    if not norm_name:
        norm_name = os.path.basename(path).lower()

    return GgufModel(
        name=norm_name,
        path=path,
        size_bytes=size_bytes,
        source=source,
        architecture=_infer_architecture(filename),
        param_billions=_infer_param_billions(filename),
        quant_tag=_infer_quant(filename),
        is_instruct=_infer_instruct(filename),
        content_hash=_partial_content_hash(path, size_bytes),
    )
