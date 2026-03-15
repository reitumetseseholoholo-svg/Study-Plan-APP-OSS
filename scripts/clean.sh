#!/usr/bin/env bash
# Remove Python/test/build caches and artifacts from the repo (keeps .venv intact).
# Optionally clean the same artifacts under an install path (e.g. /opt/studyplan-app).
# Run from repo root: bash scripts/clean.sh [--dest [path]]
#   --dest [path]  Also clean path (default: /opt/studyplan-app). May need sudo for /opt.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
DEST_DIR=""
CLEAN_DEST=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest)
      CLEAN_DEST=1
      if [[ -n "${2:-}" && "${2:0:1}" != "-" ]]; then
        DEST_DIR="$2"
        shift 2
      else
        DEST_DIR="${STUDYPLAN_DEST:-/opt/studyplan-app}"
        shift
      fi
      ;;
    -h|--help)
      echo "Usage: $0 [--dest [path]]"
      echo "  Clean repo caches. With --dest, also clean install path (default: /opt/studyplan-app)."
      echo "  Env: STUDYPLAN_DEST overrides default dest path when --dest is used."
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# Default dest when --dest was given without path
[[ "$CLEAN_DEST" -eq 1 && -z "$DEST_DIR" ]] && DEST_DIR="${STUDYPLAN_DEST:-/opt/studyplan-app}"

clean_under() {
  local base="$1"
  [[ ! -d "$base" ]] && return 0
  rm -rf "${base}/.pytest_cache" "${base}/.ruff_cache" "${base}/.mypy_cache"
  find "$base" -type d -name __pycache__ -not -path "*/.venv/*" -not -path "*/.git/*" -exec rm -rf {} + 2>/dev/null || true
  find "$base" -type d -name "*.egg-info" -not -path "*/.venv/*" -exec rm -rf {} + 2>/dev/null || true
  rm -rf "${base}/build" "${base}/dist"
}

cd "${ROOT}"

clean_under "${ROOT}"
echo "Cleaned repo: .pytest_cache, .ruff_cache, .mypy_cache, __pycache__, *.egg-info, build, dist."

if [[ "$CLEAN_DEST" -eq 1 && -n "$DEST_DIR" ]]; then
  if [[ -d "$DEST_DIR" ]]; then
    clean_under "$DEST_DIR"
    echo "Cleaned dest: ${DEST_DIR}"
  else
    echo "Dest not found (skipped): ${DEST_DIR}"
  fi
fi
