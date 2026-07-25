#!/usr/bin/env python3
"""Grok apply-with-report — one job application, then ALWAYS regenerate + open reports.

Reports (always included unless --no-report):
  - applications_progress_report.html
  - applications_dashboard.html
  - automation_comparison.html / AUTOMATION_COMPARISON.md (if generator present)
  - EFFECTIVENESS_REPORT.md (if measure_effectiveness present)

  python3 grok_apply_with_report.py              # apply + all reports + open
  python3 grok_apply_with_report.py --report-only
  python3 grok_apply_with_report.py --serve      # also serve on :8790

Env:
  COMPLETE_MAX=1
  JOB_APPLY_WORKDIR=...
  OPEN_REPORT=1          # open HTML in browser (default on)
  INCLUDE_COMPARISON=1
  INCLUDE_EFFECTIVENESS=1
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import webbrowser
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _workdir() -> Path:
    env = (os.environ.get("JOB_APPLY_WORKDIR") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    here = Path.cwd()
    if (here / "complete_apply.py").is_file() or (here / "applications_ledger.jsonl").is_file():
        return here
    candidate = Path.home() / "deepline/data/karlsruhe-public-co-job-apps"
    if candidate.is_dir():
        return candidate
    return here


def _python() -> str:
    venv = Path.home() / ".browser-use-env/bin/python3"
    if venv.is_file():
        return str(venv)
    return sys.executable


def _find_script(workdir: Path, name: str) -> Path | None:
    for base in (workdir, _repo_root() / "src", _repo_root()):
        p = base / name
        if p.is_file():
            return p
    return None


def _ensure_path(workdir: Path) -> None:
    root = _repo_root()
    for p in (str(workdir), str(root / "src"), str(root)):
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
    script = _find_script(workdir, "complete_apply.py")
    if not script:
        print("ERROR: complete_apply.py not found", file=sys.stderr)
        return 2
    print(f"[apply] COMPLETE_MAX={os.environ.get('COMPLETE_MAX')} workdir={workdir}")
    print(f"[apply] script={script}")
    return subprocess.call([py, "-u", str(script)], cwd=str(workdir), env=os.environ.copy())


def _run_py(workdir: Path, name: str) -> int:
    script = _find_script(workdir, name)
    if not script:
        print(f"[report] skip missing {name}")
        return 0
    print(f"[report] {name}")
    return subprocess.call(
        [_python(), "-u", str(script)],
        cwd=str(workdir),
        env=os.environ.copy(),
    )


def open_reports(workdir: Path) -> None:
    """Open generated HTML reports (separate browser windows from Grok TUI)."""
    flag = (os.environ.get("OPEN_REPORT") or "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return
    files = [
        workdir / "applications_progress_report.html",
        workdir / "applications_dashboard.html",
        workdir / "automation_comparison.html",
    ]
    for f in files:
        if not f.is_file():
            continue
        uri = f.resolve().as_uri()
        print(f"[report] open {f.name}")
        try:
            # macOS: prefer open -a so it is a real window
            if sys.platform == "darwin":
                subprocess.Popen(
                    ["open", str(f)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                webbrowser.open(uri)
        except Exception as e:
            print(f"[report] open failed {f.name}: {e}")


def run_report(workdir: Path) -> int:
    """Always regenerate progress + dashboard (+ comparison / effectiveness)."""
    print(f"[report] generating all reports in {workdir}")
    rc = 0
    # Core progress report (required)
    r = _run_py(workdir, "generate_progress_report.py")
    rc = rc or r
    out = workdir / "applications_progress_report.html"
    if out.is_file():
        print(f"[report] wrote {out}")
    else:
        print("[report] WARNING: progress report HTML missing", file=sys.stderr)
        rc = rc or 1

    # Dashboard always
    r = _run_py(workdir, "generate_applications_dashboard.py")
    rc = rc or r

    # Comparison stack report
    if (os.environ.get("INCLUDE_COMPARISON") or "1").lower() not in ("0", "false", "no"):
        r = _run_py(workdir, "report_automation_comparison.py")
        # non-fatal if missing

    # Effectiveness metrics markdown
    if (os.environ.get("INCLUDE_EFFECTIVENESS") or "1").lower() not in ("0", "false", "no"):
        _run_py(workdir, "measure_effectiveness.py")

    open_reports(workdir)
    return rc


def main() -> int:
    parser = argparse.ArgumentParser(description="One apply + full progress reports")
    parser.add_argument("--apply-only", action="store_true", help="Skip reports (not recommended)")
    parser.add_argument("--report-only", action="store_true", help="Only regenerate + open reports")
    parser.add_argument("--no-report", action="store_true", help="Alias of --apply-only")
    parser.add_argument("--no-open", action="store_true", help="Do not open HTML in browser")
    parser.add_argument("--workdir", type=Path, default=None)
    parser.add_argument(
        "--serve",
        action="store_true",
        help="After report, serve on PROGRESS_PORT (default 8790)",
    )
    args = parser.parse_args()

    if args.no_open:
        os.environ["OPEN_REPORT"] = "0"

    workdir = (args.workdir or _workdir()).expanduser().resolve()
    if not workdir.is_dir():
        print(f"ERROR: workdir not found: {workdir}", file=sys.stderr)
        return 2
    os.environ["JOB_APPLY_WORKDIR"] = str(workdir)
    _ensure_path(workdir)

    print(f"grok_apply_with_report | workdir={workdir}")

    skip_report = args.apply_only or args.no_report
    rc = 0
    if not args.report_only:
        rc = run_apply(workdir)
        print(f"[apply] exit={rc}")

    # Report is included by default after every apply
    if not skip_report:
        rrc = run_report(workdir)
        print(f"[report] exit={rrc}")
        rc = rc or rrc
    else:
        print("[report] skipped (--apply-only / --no-report)")

    if args.serve:
        serve = _find_script(workdir, "serve_progress_report.py")
        if serve:
            print("[serve] progress report server…")
            return subprocess.call(
                [_python(), "-u", str(serve)],
                cwd=str(workdir),
                env=os.environ.copy(),
            )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
