#!/usr/bin/env python3
"""File and path safety: permissions, size limits, path-under-base validation."""
import os


def validate_path_under(
    base_dir: str,
    path: str,
    *,
    must_be_file: bool = False,
    must_exist: bool = True,
) -> str:
    """
    Resolve path and ensure it is under base_dir (no escape via ..).
    Returns the resolved absolute path. Raises ValueError if not under base or invalid.

    :param base_dir: Allowed base directory (will be normalized and realpath'd).
    :param path: User or config path to validate.
    :param must_be_file: If True, resolved path must be a regular file.
    :param must_exist: If True, path must exist. If False, only containment is checked.
    """
    if not isinstance(base_dir, str) or not base_dir.strip():
        raise ValueError("Base directory is empty.")
    if not isinstance(path, str) or not path.strip():
        raise ValueError("Path is empty.")
    base = os.path.realpath(os.path.abspath(os.path.expanduser(base_dir.strip())))
    resolved = os.path.realpath(os.path.abspath(os.path.expanduser(path.strip())))
    if not resolved.startswith(base + os.sep) and resolved != base:
        raise ValueError(f"Path is not under the allowed base directory.")
    if must_exist and not os.path.exists(resolved):
        raise FileNotFoundError(f"Path does not exist: {resolved}")
    if must_be_file and os.path.exists(resolved) and not os.path.isfile(resolved):
        raise ValueError("Path is not a regular file.")
    return resolved


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
