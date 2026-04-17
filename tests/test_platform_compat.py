"""Tests for studyplan.platform_compat cross-platform helpers."""
from __future__ import annotations

import os
import sys
import tempfile

import pytest


def test_platform_flags_consistent():
    from studyplan.platform_compat import IS_LINUX, IS_MACOS, IS_WINDOWS

    # Exactly one of the major platforms should be True on any given OS
    active = [IS_WINDOWS, IS_LINUX, IS_MACOS]
    assert sum(active) <= 1, "At most one platform flag should be True"
    if sys.platform == "win32":
        assert IS_WINDOWS
    elif sys.platform.startswith("linux"):
        assert IS_LINUX
    elif sys.platform == "darwin":
        assert IS_MACOS


def test_lock_unlock_roundtrip():
    """lock + unlock should not raise on a real temp file."""
    from studyplan.platform_compat import lock_file_exclusive_nb, unlock_file

    fd = -1
    path = ""
    try:
        fd, path = tempfile.mkstemp(prefix="compat-test-lock-")
        lock_file_exclusive_nb(fd)
        unlock_file(fd)
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except Exception:
                pass
        if path:
            try:
                os.remove(path)
            except Exception:
                pass


def test_lock_exclusive_blocks_second_lock():
    """A second non-blocking lock on the same file should fail with OSError."""
    from studyplan.platform_compat import lock_file_exclusive_nb, unlock_file

    fd1 = fd2 = -1
    path = ""
    try:
        fd1, path = tempfile.mkstemp(prefix="compat-test-excl-")
        lock_file_exclusive_nb(fd1)

        fd2 = os.open(path, os.O_RDWR)
        with pytest.raises(OSError):
            lock_file_exclusive_nb(fd2)

        unlock_file(fd1)
    finally:
        for fd in (fd1, fd2):
            if fd >= 0:
                try:
                    os.close(fd)
                except Exception:
                    pass
        if path:
            try:
                os.remove(path)
            except Exception:
                pass


def test_truncate_fd():
    from studyplan.platform_compat import truncate_fd

    fd = -1
    path = ""
    try:
        fd, path = tempfile.mkstemp(prefix="compat-test-trunc-")
        os.write(fd, b"hello world")
        truncate_fd(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        data = os.read(fd, 1024)
        assert data == b"", f"Expected empty file after truncate, got {data!r}"
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except Exception:
                pass
        if path:
            try:
                os.remove(path)
            except Exception:
                pass


def test_extra_allowed_import_roots_returns_list():
    from studyplan.platform_compat import extra_allowed_import_roots

    roots = extra_allowed_import_roots()
    assert isinstance(roots, list)
    assert len(roots) >= 1
    for r in roots:
        assert isinstance(r, str)
        assert r  # non-empty


def test_open_path_functions_exist():
    """Smoke-check that the open-path helpers are importable (no crash)."""
    from studyplan.platform_compat import open_path_in_os, open_path_in_os_sync

    # Just ensure they are callable
    assert callable(open_path_in_os)
    assert callable(open_path_in_os_sync)


def test_focus_tracking_returns_bool():
    from studyplan.platform_compat import is_focus_tracking_available, is_tiling_wm_session

    assert isinstance(is_focus_tracking_available(), bool)
    assert isinstance(is_tiling_wm_session(), bool)
