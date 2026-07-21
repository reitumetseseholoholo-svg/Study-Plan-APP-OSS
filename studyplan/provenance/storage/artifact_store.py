"""Simple content-addressable ArtifactStore for CIR fragments.

Provides a best-effort API to save/load compiled fragments keyed by a
sha256 of their serialized payload and environment metadata.

This is intentionally minimal and conservative: store metadata as JSON
and pickle the fragment object for fast restore when compatible.
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import tempfile
from typing import Any


def _base_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".local", "share", "studyplan", "artifacts")


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def compute_key(payload: dict[str, Any]) -> str:
    j = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(j).hexdigest()


def _fragment_path(key: str) -> tuple[str, str]:
    base = _base_dir()
    _ensure_dir(base)
    meta = os.path.join(base, f"{key}.json")
    blob = os.path.join(base, f"{key}.pkl")
    return meta, blob


def save_fragment(payload: dict[str, Any], fragment_obj: Any) -> str:
    """Save metadata and fragment object; returns the content key."""
    key = compute_key(payload)
    meta_path, blob_path = _fragment_path(key)
    tmp_meta = None
    tmp_blob = None
    try:
        # write metadata atomically
        fdm, tmp_meta = tempfile.mkstemp(dir=os.path.dirname(meta_path))
        with os.fdopen(fdm, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_meta, meta_path)
        # write blob
        fdg, tmp_blob = tempfile.mkstemp(dir=os.path.dirname(blob_path))
        with os.fdopen(fdg, "wb") as f:
            pickle.dump(fragment_obj, f)
        os.replace(tmp_blob, blob_path)
    finally:
        for p in (tmp_meta, tmp_blob):
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
    return key


def load_fragment(key: str) -> tuple[dict[str, Any] | None, Any | None]:
    meta_path, blob_path = _fragment_path(key)
    meta = None
    obj = None
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r") as f:
                meta = json.load(f)
        except Exception:
            meta = None
    if os.path.exists(blob_path):
        try:
            with open(blob_path, "rb") as f:
                obj = pickle.load(f)
        except Exception:
            obj = None
    return meta, obj


def has_fragment(key: str) -> bool:
    meta_path, blob_path = _fragment_path(key)
    return os.path.exists(meta_path) and os.path.exists(blob_path)
