#!/usr/bin/env python3
import os


def secure_path_permissions(path: str, mode: int) -> None:
    try:
        os.chmod(path, int(mode))
    except Exception:
        pass


def enforce_file_size_limit(
    file_path: str,
    max_bytes: int,
    label: str,
    *,
    human_readable: bool = False,
    punctuate_simple_errors: bool = False,
) -> int:
    suffix = "." if punctuate_simple_errors else ""
    if not isinstance(file_path, str) or not file_path.strip():
        raise ValueError(f"{label} file path is empty{suffix}")
    path = os.path.abspath(file_path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"{label} file not found{suffix}")
    if not os.path.isfile(path):
        raise ValueError(f"{label} path is not a regular file{suffix}")
    if not os.access(path, os.R_OK):
        raise ValueError(f"{label} file is not readable{suffix}")
    try:
        size = int(os.path.getsize(path))
    except Exception as exc:
        raise ValueError(f"{label} file could not be accessed: {exc}") from exc
    limit = max(1024, int(max_bytes or 0))
    if size > limit:
        if human_readable:
            size_mb = size / (1024.0 * 1024.0)
            limit_mb = limit / (1024.0 * 1024.0)
            raise ValueError(
                f"{label} file is too large ({size_mb:.1f}MB). Maximum allowed is {limit_mb:.1f}MB."
            )
        raise ValueError(
            f"{label} file is too large ({size} bytes). Maximum allowed is {limit} bytes."
        )
    return size
