"""
Cross-platform compatibility helpers.

Provides platform-aware implementations for:
- File locking (fcntl on POSIX, msvcrt on Windows)
- Opening files/folders in the OS file manager
- Platform detection helpers
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, cast

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform == "darwin"

# ---------------------------------------------------------------------------
# File locking
# ---------------------------------------------------------------------------

if IS_WINDOWS:
    try:
        import msvcrt  # noqa: F401 — Windows-only stdlib module
        _msvcrt_any = cast(Any, msvcrt)

        def lock_file_exclusive_nb(fd: int) -> None:
            """Acquire an exclusive non-blocking lock on *fd* (Windows)."""
            _msvcrt_any.locking(fd, _msvcrt_any.LK_NBLCK, 1)

        def unlock_file(fd: int) -> None:
            """Release the lock on *fd* (Windows)."""
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                _msvcrt_any.locking(fd, _msvcrt_any.LK_UNLCK, 1)
            except Exception:
                pass

    except ImportError:
        # Fallback: no locking support
        def lock_file_exclusive_nb(fd: int) -> None:  # type: ignore[misc]
            pass

        def unlock_file(fd: int) -> None:  # type: ignore[misc]
            pass

else:
    import fcntl

    def lock_file_exclusive_nb(fd: int) -> None:  # type: ignore[misc]
        """Acquire an exclusive non-blocking lock on *fd* (POSIX)."""
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def unlock_file(fd: int) -> None:  # type: ignore[misc]
        """Release the lock on *fd* (POSIX)."""
        fcntl.flock(fd, fcntl.LOCK_UN)


def truncate_fd(fd: int, length: int = 0) -> None:
    """Truncate file descriptor *fd* to *length* bytes (cross-platform)."""
    if IS_WINDOWS:
        # os.ftruncate is not available on Windows; seek + _chsize via os
        try:
            os.lseek(fd, length, os.SEEK_SET)
            # _chsize is available via msvcrt on CPython for Windows
            import msvcrt as _msvcrt  # noqa: F811
            _msvcrt_any = cast(Any, _msvcrt)
            os_any = cast(Any, os)

            _msvcrt_any.setmode(fd, getattr(os_any, "O_BINARY", 0))
            os.write(fd, b"")  # flush position
        except Exception:
            pass
    else:
        os.ftruncate(fd, length)


# ---------------------------------------------------------------------------
# Open file / folder in the platform's default handler
# ---------------------------------------------------------------------------

def open_path_in_os(path: str) -> None:
    """Open *path* (file or directory) in the platform's default handler.

    On Linux uses ``xdg-open``, on macOS ``open``, on Windows ``os.startfile``.
    Errors are silently swallowed — this is a best-effort convenience function.
    """
    try:
        if IS_WINDOWS:
            os.startfile(path)  # type: ignore[attr-defined]  # Windows-only
        elif IS_MACOS:
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def open_path_in_os_sync(path: str, timeout: int = 5) -> None:
    """Like :func:`open_path_in_os` but waits for completion (up to *timeout* seconds)."""
    try:
        if IS_WINDOWS:
            os.startfile(path)  # type: ignore[attr-defined]
        elif IS_MACOS:
            subprocess.run(["open", path], check=False, timeout=timeout)
        else:
            subprocess.run(["xdg-open", path], check=False, timeout=timeout)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Path helpers — allowed import roots
# ---------------------------------------------------------------------------

def extra_allowed_import_roots() -> list[str]:
    """Return additional allowed import-source root paths for the platform.

    On Linux: ``/media`` (removable drives).
    On Windows: all existing drive letter roots (``C:\\``, ``D:\\``, etc.).
    On macOS: ``/Volumes``.
    """
    if IS_WINDOWS:
        # Accept any existing drive root as a permitted import source
        roots: list[str] = []
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = f"{letter}:\\"
            if os.path.isdir(drive):
                roots.append(drive)
        return roots
    if IS_MACOS:
        return ["/Volumes"]
    # Linux / other POSIX
    return [os.path.join(os.sep, "media")]


# ---------------------------------------------------------------------------
# Focus-tracking availability
# ---------------------------------------------------------------------------

def is_focus_tracking_available() -> bool:
    """Return True if focus-tracking tools are available on this platform.

    Currently only supported on Linux (Hyprland via ``hyprctl``).
    Returns False on Windows and macOS.
    """
    if IS_WINDOWS or IS_MACOS:
        return False
    import shutil

    return bool(shutil.which("hyprctl"))


def is_tiling_wm_session() -> bool:
    """Return True when the desktop session appears to be a tiling WM.

    Always False on Windows and macOS.
    """
    if IS_WINDOWS or IS_MACOS:
        return False
    markers = ("HYPRLAND_INSTANCE_SIGNATURE", "SWAYSOCK", "I3SOCK")
    for name in markers:
        if str(os.environ.get(name, "") or "").strip():
            return True
    session_name = str(os.environ.get("XDG_CURRENT_DESKTOP", "") or "").strip().lower()
    return session_name in {"hyprland", "sway", "i3"}
