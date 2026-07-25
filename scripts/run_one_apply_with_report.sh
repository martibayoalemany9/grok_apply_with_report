#!/usr/bin/env bash
# One application + regenerate progress report.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export COMPLETE_MAX="${COMPLETE_MAX:-1}"
export APPLY_BROWSER="${APPLY_BROWSER:-chromium}"
export CDP_URL="${CDP_URL:-http://127.0.0.1:9223}"
export APPLY_BROWSER_FULLSCREEN="${APPLY_BROWSER_FULLSCREEN:-1}"
export JOB_APPLY_WORKDIR="${JOB_APPLY_WORKDIR:-$HOME/deepline/data/karlsruhe-public-co-job-apps}"
PY="${HOME}/.browser-use-env/bin/python3"
if [[ ! -x "$PY" ]]; then PY=python3; fi
exec "$PY" -u "$ROOT/grok_apply_with_report.py" "$@"
