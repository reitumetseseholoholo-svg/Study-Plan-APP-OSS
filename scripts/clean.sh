#!/usr/bin/env bash
# Remove Python/test/build caches and artifacts from the repo (keeps .venv intact).
# Run from repo root: bash scripts/clean.sh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT}"

rm -rf .pytest_cache
rm -rf .ruff_cache
rm -rf .mypy_cache
find . -type d -name __pycache__ -not -path "./.venv/*" -not -path "./.git/*" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name "*.egg-info" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
rm -rf build dist
echo "Cleaned .pytest_cache, .ruff_cache, .mypy_cache, __pycache__, *.egg-info, build, dist."
