#!/usr/bin/env python3
"""Grok apply-with-report — one job application, then regenerate progress report.

Usage (from a private workdir that has CV + queue + prefs, with this repo on PYTHONPATH
or installed next to your data):

  # Point at your private data directory (CVs, ledger, queue — never commit these)
  export JOB_APPLY_WORKDIR=~/deepline/data/karlsruhe-public-co-job-apps

  # One application at a time (default)
  python3 grok_apply_with_report.py

  # Report only (no browser apply)
  python3 grok_apply_with_report.py --report-only

  # Apply only
  python3 grok_apply_with_report.py --apply-only

  # Then open HTML report
  open applications_progress_report.html   # inside WORKDIR

Env (common):
  COMPLETE_MAX=1                 # default 1 — one application per run
  APPLY_BROWSER=chromium         # chromium | chrome | firefox | cloud_mobile
  CDP_URL=http://127.0.0.1:9223
  APPLY_BROWSER_FULLSCREEN=1
  COMPLETE_QUEUE_CSV=applications_eu_all.csv
  APPLY_CV_FILE=cv.pdf
  JOB_APPLY_WORKDIR=/path/to/private/data
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _workdir() -> Path:
    env = (os.environ.get("JOB_APPLY_WORKDIR") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    # If running from inside a data workdir that already has complete_apply
    here = Path.cwd()
    if (here / "complete_apply.py").is_file() or (here / "applications_ledger.jsonl").is_file():
        return here
    # Default: sibling private data path (user-specific; override with JOB_APPLY_WORKDIR)
    candidate = Path.home() / "deepline/data/karlsruhe-public-co-job-apps"
    if candidate.is_dir():
        return candidate
    return here


def _python() -> str:
    venv = Path.home() / ".browser-use-env/bin/python3"
    if venv.is_file():
        return str(venv)
    return sys.executable


def _ensure_path(workdir: Path) -> None:
    """Prefer workdir modules (live data project); fall back to repo src/."""
    root = _repo_root()
    src = root / "src"
    # Workdir first so private complete_apply / prefs win when present
    for p in (str(workdir), str(src), str(root)):
        if p not in sys.path:
            sys.path.insert(0, p)


def run_apply(workdir: Path) -> int:
    os.environ.setdefault("COMPLETE_MAX", "1")
    os.environ.setdefault("APPLY_BROWSER", "chromium")
    os.environ.setdefault("CDP_URL", "http://127.0.0.1:9223")
    os.environ.setdefault("APPLY_BROWSER_FULLSCREEN", "1")
    os.environ.setdefault("ONE_PER_COMPANY", "1")
    os.environ.setdefault("SKIP_ATTEMPTED", "1")
    os.environ.setdefault("USE_CHATBOT", "0")
    os.environ.setdefault("SKIP_WORKDAY", "1")
    os.environ.setdefault("REOPEN_GAP_SEC", "10")
    os.environ.setdefault("GIVE_UP_GRACE_SEC", "60")

    py = _python()
    # Prefer workdir complete_apply if present
    script = workdir / "complete_apply.py"
    if not script.is_file():
        script = _repo_root() / "src" / "complete_apply.py"
    if not script.is_file():
        print("ERROR: complete_apply.py not found in workdir or src/", file=sys.stderr)
        return 2

    print(f"[apply] COMPLETE_MAX={os.environ.get('COMPLETE_MAX')} workdir={workdir}")
    print(f"[apply] script={script}")
    return subprocess.call(
        [py, "-u", str(script)],
        cwd=str(workdir),
        env=os.environ.copy(),
    )


def run_report(workdir: Path) -> int:
    py = _python()
    gen = workdir / "generate_progress_report.py"
    if not gen.is_file():
        gen = _repo_root() / "src" / "generate_progress_report.py"
    if not gen.is_file():
        print("ERROR: generate_progress_report.py not found", file=sys.stderr)
        return 2
    print(f"[report] generating from ledger in {workdir}")
    rc = subprocess.call([py, "-u", str(gen)], cwd=str(workdir), env=os.environ.copy())
    out = workdir / "applications_progress_report.html"
    if out.is_file():
        print(f"[report] wrote {out}")
    # Optional dashboard
    dash = workdir / "generate_applications_dashboard.py"
    if not dash.is_file():
        dash = _repo_root() / "src" / "generate_applications_dashboard.py"
    if dash.is_file():
        subprocess.call([py, "-u", str(dash)], cwd=str(workdir), env=os.environ.copy())
    return rc


def main() -> int:
    parser = argparse.ArgumentParser(description="One apply + progress report")
    parser.add_argument("--apply-only", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="Private data directory (CVs, ledger, queues)",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="After report, serve HTML on PROGRESS_PORT (default 8790)",
    )
    args = parser.parse_args()

    workdir = (args.workdir or _workdir()).expanduser().resolve()
    if not workdir.is_dir():
        print(f"ERROR: workdir not found: {workdir}", file=sys.stderr)
        return 2
    os.environ["JOB_APPLY_WORKDIR"] = str(workdir)
    _ensure_path(workdir)

    print(f"grok_apply_with_report | workdir={workdir}")

    rc = 0
    if not args.report_only:
        rc = run_apply(workdir)
        print(f"[apply] exit={rc}")
    if not args.apply_only:
        rrc = run_report(workdir)
        print(f"[report] exit={rrc}")
        rc = rc or rrc
    if args.serve:
        serve = workdir / "serve_progress_report.py"
        if not serve.is_file():
            serve = _repo_root() / "src" / "serve_progress_report.py"
        if serve.is_file():
            print("[serve] starting progress report server…")
            return subprocess.call(
                [_python(), "-u", str(serve)],
                cwd=str(workdir),
                env=os.environ.copy(),
            )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
