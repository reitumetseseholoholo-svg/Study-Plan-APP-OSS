"""
Path and atomic file helpers used by StudyPlanGUI.
Extracted so tests can run without importing studyplan_app (GTK/gi).
"""
from __future__ import annotations

import csv
import io
import os
import tempfile
from typing import Any

from studyplan_file_safety import secure_path_permissions
from studyplan.platform_compat import extra_allowed_import_roots


def normalize_user_file_path(file_path: str, label: str) -> str:
    raw = str(file_path or "").strip()
    if not raw:
        raise ValueError(f"{label} path is empty.")
    path = os.path.abspath(os.path.expanduser(raw))
    if not path:
        raise ValueError(f"{label} path is invalid.")
    return path


def validate_import_source_path(
    file_path: str,
    label: str,
    allowed_extensions: tuple[str, ...] | None = None,
) -> str:
    path = normalize_user_file_path(file_path, label)
    # Prevent path traversal: resolve symlinks and ensure under permitted roots
    try:
        real = os.path.realpath(path)
        home = os.path.realpath(os.path.expanduser("~"))
        tmp = os.path.realpath(tempfile.gettempdir())
        under_home = real == home or real.startswith(home + os.sep)
        under_tmp = real.startswith(tmp + os.sep)
        under_extra = any(
            real.startswith(os.path.realpath(root) + os.sep) for root in extra_allowed_import_roots()
        )
        if not (under_home or under_tmp or under_extra):
            raise ValueError(f"{label} path must be under your home directory, temp directory, or a removable drive.")
    except (OSError, ValueError):
        raise ValueError(f"{label} path is not allowed (path traversal or invalid).")
    if allowed_extensions:
        lower = path.lower()
        allowed = tuple(str(ext).lower() for ext in allowed_extensions if str(ext).strip())
        if allowed and not any(lower.endswith(ext) for ext in allowed):
            pretty = ", ".join(allowed)
            raise ValueError(f"{label} must use one of: {pretty}.")
    if not os.path.exists(path):
        raise FileNotFoundError(f"{label} file not found.")
    if not os.path.isfile(path):
        raise ValueError(f"{label} path is not a regular file.")
    if not os.access(path, os.R_OK):
        raise ValueError(f"{label} file is not readable.")
    return path


def prepare_export_target_path(
    file_path: str,
    label: str,
    *,
    default_extension: str | None = None,
    allowed_extensions: tuple[str, ...] | None = None,
) -> str:
    path = normalize_user_file_path(file_path, label)
    if default_extension:
        ext = str(default_extension).strip().lower()
        if ext and not ext.startswith("."):
            ext = f".{ext}"
        if ext and not os.path.splitext(path)[1]:
            path = f"{path}{ext}"
    if allowed_extensions:
        lower = path.lower()
        allowed = tuple(str(ext).lower() for ext in allowed_extensions if str(ext).strip())
        if allowed and not any(lower.endswith(ext) for ext in allowed):
            pretty = ", ".join(allowed)
            raise ValueError(f"{label} must use one of: {pretty}.")
    parent = os.path.dirname(path) or "."
    if not os.path.isdir(parent):
        raise FileNotFoundError(f"{label} directory does not exist.")
    if not os.access(parent, os.W_OK):
        raise PermissionError(f"{label} directory is not writable.")
    if os.path.exists(path):
        if os.path.islink(path):
            raise ValueError(f"{label} cannot overwrite a symbolic link.")
        if not os.path.isfile(path):
            raise ValueError(f"{label} target is not a regular file.")
        if not os.access(path, os.W_OK):
            raise PermissionError(f"{label} target is not writable.")
    return path


def atomic_write_bytes_file(file_path: str, payload: bytes, mode: int = 0o600) -> None:
    path = normalize_user_file_path(file_path, "Write target")
    parent = os.path.dirname(path) or "."
    fd = -1
    tmp_path = ""
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".studyplan-tmp-", dir=parent)
        with os.fdopen(fd, "wb") as tmp:
            fd = -1
            tmp.write(bytes(payload))
            tmp.flush()
            try:
                os.fsync(tmp.fileno())
            except Exception:
                pass
        # Set permissions on the temp file *before* replacing the destination so
        # the file is never briefly visible with wrong (e.g. world-readable) permissions.
        secure_path_permissions(tmp_path, mode)
        os.replace(tmp_path, path)
    except Exception:
        if fd >= 0:
            try:
                os.close(fd)
            except Exception:
                pass
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise


def atomic_write_text_file(
    file_path: str,
    text: str,
    *,
    encoding: str = "utf-8",
    mode: int = 0o600,
) -> None:
    payload = str(text or "").encode(str(encoding or "utf-8"), "replace")
    atomic_write_bytes_file(file_path, payload, mode=mode)


def atomic_write_csv_rows(
    file_path: str,
    rows: list[list[Any]],
    *,
    mode: int = 0o600,
) -> None:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    for row in rows:
        writer.writerow(row)
    atomic_write_text_file(file_path, stream.getvalue(), mode=mode)
