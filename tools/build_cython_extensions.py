#!/usr/bin/env python3
"""Build Cython extension modules for the current Python version.

Usage:
    python tools/build_cython_extensions.py

Builds all ``.pyx`` files in ``studyplan/cython/`` to ``.so`` files.
Exits 0 on success, 1 on failure (missing Cython, compilation error).
"""

from __future__ import annotations

import os
import sys
import shutil

CYTHON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "studyplan", "cython")


def find_pyx_files() -> list[str]:
    """Return basenames (without .pyx) of all .pyx files in CYTHON_DIR."""
    result: list[str] = []
    if not os.path.isdir(CYTHON_DIR):
        print(f"ERROR: cython directory not found: {CYTHON_DIR}", file=sys.stderr)
        sys.exit(1)
    for entry in sorted(os.listdir(CYTHON_DIR)):
        if entry.endswith(".pyx"):
            result.append(entry[:-4])
    return result


def build_extensions(names: list[str]) -> int:
    """Build each .pyx file using Cython's cythonize + setuptools build_ext.

    Returns 0 on success, 1 on failure.
    """
    try:
        from Cython.Build import cythonize
        from setuptools import Extension, Distribution
    except ImportError as exc:
        print(f"ERROR: Cython not available: {exc}", file=sys.stderr)
        print("Install with: pip install cython setuptools", file=sys.stderr)
        return 1

    # Try to include numpy headers for cimport support
    include_dirs: list[str] = []
    try:
        import numpy as np

        include_dirs.append(np.get_include())
    except ImportError:
        pass

    for name in names:
        pyx_path = os.path.join(CYTHON_DIR, f"{name}.pyx")
        if not os.path.isfile(pyx_path):
            print(f"ERROR: source not found: {pyx_path}", file=sys.stderr)
            return 1

        print(f"Building {name}...")
        include = list(include_dirs) if name == "tfidf_fast" else []
        ext = Extension(name, sources=[pyx_path], include_dirs=include)
        ext_modules = cythonize([ext], language_level="3str", quiet=True)

        dist = Distribution({"ext_modules": ext_modules, "name": name})
        cmd = dist.get_command_obj("build_ext")
        cmd.inplace = True
        cmd.ensure_finalized()
        cmd.run()

        # Copy .so from build/ to CYTHON_DIR
        for output in cmd.get_outputs():
            dest = os.path.join(CYTHON_DIR, os.path.basename(output))
            shutil.copy2(output, dest)
            print(f"  -> {dest}")

    return 0


def main() -> int:
    pyx_names = find_pyx_files()
    if not pyx_names:
        print("No .pyx files found — nothing to build.")
        return 0

    print(f"Found {len(pyx_names)} Cython extension(s): {', '.join(pyx_names)}")
    return build_extensions(pyx_names)


if __name__ == "__main__":
    raise SystemExit(main())
