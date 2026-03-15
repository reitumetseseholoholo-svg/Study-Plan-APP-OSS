#!/usr/bin/env bash
# Deploy script for ACCA Study Plan app. Copy to ~/.local/bin/studyplan-update and
# ensure REPO_DIR/DEST_DIR suit your system. Smoke gate: only fails when smoke
# actually failed; exit 124 (timeout) with valid passed report is treated as pass.
# For fish: source scripts/studyupdate.fish to get studyupdate/study-update with clean exit.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# When run from repo: scripts/studyplan-update.sh -> repo root = SCRIPT_DIR/..
DEFAULT_REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
if [[ -n "${STUDYPLAN_REPO:-}" ]]; then
  REPO_DIR="${STUDYPLAN_REPO}"
elif [[ -f "${PWD}/studyplan_app.py" && -f "${PWD}/studyplan_engine.py" ]]; then
  REPO_DIR="${PWD}"
elif [[ -f "${DEFAULT_REPO_DIR}/studyplan_app.py" && -f "${DEFAULT_REPO_DIR}/studyplan_engine.py" ]]; then
  REPO_DIR="${DEFAULT_REPO_DIR}"
else
  REPO_DIR="${DEFAULT_REPO_DIR}"
fi
DEST_DIR="${STUDYPLAN_DEST:-/opt/studyplan-app}"
WRAPPER_PATH="${STUDYPLAN_WRAPPER:-/usr/local/bin/studyplan}"
SMOKE_TIMEOUT="${STUDYPLAN_SMOKE_TIMEOUT:-300}"
SMOKE_ARG="${STUDYPLAN_SMOKE_ARG:---dialog-smoke-strict}"
SMOKE_REPORT_PATH="${HOME}/.config/studyplan/smoke_last.json"
SKIP_SMOKE=0
SKIP_WRAPPER=0
KEEP_VENV_BACKUPS=0
DRY_RUN=0
PULL_REPO=0
VERBOSE=0
LOCK_DIR="/tmp/studyplan-update.lock"

print_usage() {
  cat <<'EOF'
Usage: studyplan-update [options]

Options:
  --repo <path>           Source repo directory (default: env/current/default repo)
  --dest <path>           Destination app directory (default: /opt/studyplan-app)
  --wrapper <path>        Wrapper path (default: /usr/local/bin/studyplan)
  --smoke-timeout <sec>   Smoke test timeout seconds (default: 300)
  --smoke-arg <arg>       Smoke test argument (default: --dialog-smoke-strict)
  --smoke-report <path>   Smoke report JSON path (default: ~/.config/studyplan/smoke_last.json)
  --pull                  Run git pull --ff-only in repo before deploy
  --verbose               Print full smoke output
  --skip-smoke            Skip smoke test
  --no-wrapper            Do not update wrapper
  --keep-venv-backups     Keep /opt .venv.bak-* directories (default: remove)
  --dry-run               Print actions without executing
  -h, --help              Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO_DIR="${2:-}"
      shift 2
      ;;
    --dest)
      DEST_DIR="${2:-}"
      shift 2
      ;;
    --wrapper)
      WRAPPER_PATH="${2:-}"
      shift 2
      ;;
    --smoke-timeout)
      SMOKE_TIMEOUT="${2:-}"
      shift 2
      ;;
    --smoke-arg)
      SMOKE_ARG="${2:-}"
      shift 2
      ;;
    --smoke-report)
      SMOKE_REPORT_PATH="${2:-}"
      shift 2
      ;;
    --pull)
      PULL_REPO=1
      shift
      ;;
    --verbose)
      VERBOSE=1
      shift
      ;;
    --skip-smoke)
      SKIP_SMOKE=1
      shift
      ;;
    --no-wrapper)
      SKIP_WRAPPER=1
      shift
      ;;
    --keep-venv-backups)
      KEEP_VENV_BACKUPS=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      print_usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "${REPO_DIR}/studyplan_app.py" || ! -f "${REPO_DIR}/studyplan_engine.py" ]]; then
  echo "Repository path does not look valid: ${REPO_DIR}" >&2
  exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required but not found in PATH." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but not found in PATH." >&2
  exit 1
fi

if [[ ! "${SMOKE_TIMEOUT}" =~ ^[0-9]+$ ]]; then
  echo "--smoke-timeout must be an integer number of seconds." >&2
  exit 2
fi

if [[ -z "${SMOKE_ARG}" ]]; then
  echo "--smoke-arg cannot be empty." >&2
  exit 2
fi

# Dialog smoke needs enough time (startup + GTK + steps). Enforce minimum so old copies exit cleanly.
if [[ "${SMOKE_ARG}" == *dialog-smoke* ]] && [[ "${SMOKE_TIMEOUT}" -lt 300 ]]; then
  SMOKE_TIMEOUT=300
fi

run_cmd() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    printf '[dry-run] '
    printf '%q ' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

run_sudo_cmd() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    printf '[dry-run] sudo '
    printf '%q ' "$@"
    printf '\n'
    return 0
  fi
  sudo "$@"
}

validate_smoke_report() {
  local report_path="$1"
  python3 - "$report_path" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1]).expanduser()
if not path.exists():
    print(f"smoke report missing: {path}", file=sys.stderr)
    raise SystemExit(1)
try:
    report = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"smoke report unreadable: {exc}", file=sys.stderr)
    raise SystemExit(1)
status = str(report.get("status", "")).strip().lower()
if status != "passed":
    reason = str(report.get("reason", "")).strip() or "unknown"
    print(f"smoke report status={status or 'missing'} reason={reason}", file=sys.stderr)
    raise SystemExit(1)
failures = report.get("kpi_failures") or []
if failures:
    print(f"smoke report has {len(failures)} KPI failure(s)", file=sys.stderr)
    raise SystemExit(1)
PY
}

run_smoke_gate() {
  local smoke_log smoke_rc report_mtime_before report_mtime_after smoke_started_at
  smoke_log="$(mktemp /tmp/studyplan-smoke.XXXXXX.log)"
  smoke_started_at="$(date +%s)"
  report_mtime_before=0
  if [[ -f "${SMOKE_REPORT_PATH}" ]]; then
    report_mtime_before="$(stat -c %Y "${SMOKE_REPORT_PATH}" 2>/dev/null || echo 0)"
  fi

  if timeout "${SMOKE_TIMEOUT}"s python3 "${DEST_DIR}/studyplan_app.py" "${SMOKE_ARG}" >"${smoke_log}" 2>&1; then
    smoke_rc=0
  else
    smoke_rc=$?
  fi

  if [[ "${VERBOSE}" -eq 1 ]]; then
    cat "${smoke_log}"
  fi

  # Only treat as failure when smoke actually failed. If process got 124 (timeout)
  # but the report exists, was updated this run, and passes validation, smoke completed.
  check_report_and_pass() {
    [[ "${SMOKE_ARG}" != *dialog-smoke* ]] && return 1
    [[ ! -f "${SMOKE_REPORT_PATH}" ]] && return 1
    report_mtime_after="$(stat -c %Y "${SMOKE_REPORT_PATH}" 2>/dev/null || echo 0)"
    [[ "${report_mtime_after}" -lt "${smoke_started_at}" ]] && return 1
    validate_smoke_report "${SMOKE_REPORT_PATH}"
  }

  if [[ "${smoke_rc}" -ne 0 ]]; then
    if [[ "${smoke_rc}" -eq 124 ]] && check_report_and_pass; then
      rm -f "${smoke_log}"
      echo "smoke ok"
      return 0
    fi
    echo "Smoke test failed (exit ${smoke_rc})." >&2
    tail -n 40 "${smoke_log}" >&2 || true
    rm -f "${smoke_log}"
    return 1
  fi

  if grep -qiE "already running" "${smoke_log}"; then
    echo "Smoke test did not run: app instance already running. Close it and retry." >&2
    rm -f "${smoke_log}"
    return 1
  fi

  if grep -qiE "No display available" "${smoke_log}"; then
    echo "Smoke test did not run: no display available for GTK." >&2
    rm -f "${smoke_log}"
    return 1
  fi

  if [[ "${SMOKE_ARG}" == *dialog-smoke* ]]; then
    if [[ ! -f "${SMOKE_REPORT_PATH}" ]]; then
      echo "Smoke report missing: ${SMOKE_REPORT_PATH}" >&2
      rm -f "${smoke_log}"
      return 1
    fi
    report_mtime_after="$(stat -c %Y "${SMOKE_REPORT_PATH}" 2>/dev/null || echo 0)"
    # Report must be from this run (mtime >= start). Avoid false fail on same-second mtime.
    if [[ "${report_mtime_after}" -lt "${smoke_started_at}" ]]; then
      echo "Smoke report was not updated by this run: ${SMOKE_REPORT_PATH}" >&2
      rm -f "${smoke_log}"
      return 1
    fi
    if ! validate_smoke_report "${SMOKE_REPORT_PATH}"; then
      rm -f "${smoke_log}"
      return 1
    fi
  fi

  rm -f "${smoke_log}"
  echo "smoke ok"
}

if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
  echo "Another studyplan-update appears to be running (lock: ${LOCK_DIR})." >&2
  exit 1
fi
cleanup_lock() {
  rmdir "${LOCK_DIR}" >/dev/null 2>&1 || true
}
trap cleanup_lock EXIT

echo "Deploy source: ${REPO_DIR}"
echo "Deploy target: ${DEST_DIR}"

if [[ "${PULL_REPO}" -eq 1 ]]; then
  if [[ -d "${REPO_DIR}/.git" ]]; then
    run_cmd git -C "${REPO_DIR}" pull --ff-only
  else
    echo "Skipping --pull: ${REPO_DIR} is not a git repo."
  fi
fi

run_sudo_cmd mkdir -p "${DEST_DIR}"
if [[ "${KEEP_VENV_BACKUPS}" -eq 0 ]]; then
  run_sudo_cmd find "${DEST_DIR}" -mindepth 1 -maxdepth 1 -type d -name '.venv.bak-*' -exec rm -rf {} +
fi
run_sudo_cmd rsync -a --delete \
  --delete-after \
  --exclude '.git/' \
  --exclude '.pytest_cache/' \
  --exclude '.venv/' \
  --exclude '.venv.bak-*/' \
  --exclude '__pycache__/' \
  --exclude 'build/' \
  --exclude '.mypy_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '*.pyc' \
  "${REPO_DIR}/" "${DEST_DIR}/"

if [[ "${SKIP_WRAPPER}" -eq 0 ]]; then
  WRAPPER_CONTENT='#!/usr/bin/env bash
APP_DIR="'"${DEST_DIR}"'"
VENV_PY="$APP_DIR/.venv/bin/python"
if [[ -x "$VENV_PY" ]]; then
  exec "$VENV_PY" "$APP_DIR/studyplan_app.py" "$@"
fi
exec python3 "$APP_DIR/studyplan_app.py" "$@"'
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "[dry-run] write wrapper to ${WRAPPER_PATH}"
  else
    printf '%s\n' "${WRAPPER_CONTENT}" | sudo tee "${WRAPPER_PATH}" >/dev/null
    run_sudo_cmd chmod +x "${WRAPPER_PATH}"
  fi
fi

if [[ "${SKIP_SMOKE}" -eq 0 ]]; then
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "[dry-run] timeout ${SMOKE_TIMEOUT}s python3 ${DEST_DIR}/studyplan_app.py ${SMOKE_ARG}"
  else
    run_smoke_gate
  fi
fi

echo "deploy ok"
exit 0
