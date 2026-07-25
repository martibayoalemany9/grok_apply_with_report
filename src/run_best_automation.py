#!/usr/bin/env python3
"""Best-path job-apply automation (canonical stack).

Stack (AUTOMATION_STACK.md A):
  Robot Framework  →  complete_apply.py  →  Playwright Chromium CDP :9223

Also runs:
  1) efc_job_search.py — refresh software-rings queue (CV-fit 0020_raw)
  2) robot apply_software_rings.robot — CDP + batch with long dwell/commit
  3) iterate_apply.py — fail→lesson→retry iterations on the same queue

Documents (candidate_profile):
  CV 0020_raw · ETSETB academic · work certificates 2020 · degree year 2003

Tracker: http://127.0.0.1:8765/  (serve_applications_dashboard.py)

  python3 run_best_automation.py
  SKIP_SEARCH=1 ITERATIONS=3 COMPLETE_MAX=20 python3 run_best_automation.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

W = Path(__file__).resolve().parent
PYTHON = Path.home() / ".browser-use-env" / "bin" / "python3"
ROBOT = Path.home() / ".browser-use-env" / "bin" / "robot"
LOG = W / "best_automation_run.log"
PAUSE = W / ".APPLICATIONS_PAUSED"

SKIP_SEARCH = os.environ.get("SKIP_SEARCH", "0").lower() in ("1", "true", "yes")
ITERATIONS = int(os.environ.get("ITERATIONS", "3"))
# One application at a time unless user sets COMPLETE_MAX>1 with multi-window
BATCH_MAX = int(os.environ.get("COMPLETE_MAX", "1"))
PER_APP = int(os.environ.get("PER_APP_MAX_SEC", "300"))
QUEUE = os.environ.get(
    "COMPLETE_QUEUE_CSV", "applications_software_rings_cvfit.csv"
).strip()


def log(msg: str = "") -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def base_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "APPLY_BROWSER": "chromium",
            "CDP_URL": "http://127.0.0.1:9223",
            "CDP_PORT": "9223",
            "USE_CHATBOT": "0",
            "SKIP_WORKDAY": "1",
            "APPLY_ALL": "1",
            "ONE_PER_COMPANY": "1",
            "COMPLETE_MAX": str(BATCH_MAX),
            "PER_APP_MAX_SEC": str(PER_APP),
            "DWELL_SEC": "100",
            "COMMIT_SEC": "70",
            "STUCK_SAME_BEHAVIOUR": "2",
            "COMPLETE_QUEUE_CSV": QUEUE,
            # Prefer real ATS over careers hubs when ranking
            "SKIP_ATTEMPTED": "1",
            "SKIP_PRIOR_FAILS": "0",
        }
    )
    return env


def run(cmd: list[str], *, env: dict | None = None, timeout: int | None = None) -> int:
    log(f"$ {' '.join(cmd)}")
    with LOG.open("a", encoding="utf-8") as lf:
        proc = subprocess.run(
            cmd,
            cwd=str(W),
            env=env or base_env(),
            stdout=lf,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    log(f"  exit={proc.returncode}")
    return proc.returncode


def ensure_cdp() -> None:
    log("ensure Chromium CDP :9223")
    run(
        [
            str(PYTHON),
            "-c",
            "from cdp_helpers import ensure_cdp_tab, default_cdp_url; "
            "print(default_cdp_url(), ensure_cdp_tab())",
        ],
        timeout=120,
    )


def ensure_dashboard() -> None:
    import urllib.request

    try:
        urllib.request.urlopen("http://127.0.0.1:8765/api/summary.json", timeout=2)
        log("tracker already up http://127.0.0.1:8765/")
        return
    except Exception:
        pass
    log("starting applications dashboard on :8765")
    subprocess.Popen(
        [str(PYTHON), "-u", str(W / "serve_applications_dashboard.py")],
        cwd=str(W),
        stdout=open(W / "dashboard_server.out", "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    time.sleep(1.5)


def refresh_queue() -> None:
    if SKIP_SEARCH:
        log("SKIP_SEARCH=1 — keep existing queue")
        return
    log("refresh software rings via efc_job_search.py (keyword software, CV-fit 0020)")
    # eFC multi-ring search can take several minutes
    run([str(PYTHON), "-u", str(W / "efc_job_search.py")], timeout=1800)


def robot_suite() -> int:
    """Run Robot suite from robot/ so ${CURDIR}/.. resolves to project root."""
    suite = W / "robot" / "apply_software_rings.robot"
    if not ROBOT.is_file() or not suite.is_file():
        log("robot suite missing — fall back to complete_apply only")
        return -1
    log(f"Robot Framework suite: {suite.name} (cwd=robot/)")
    env = base_env()
    # Search already done by refresh_queue when SKIP_SEARCH=0; suite may re-search
    # for freshness — acceptable. Use SKIP_SEARCH for suite-only apply by patching
    # nothing; efc_job_search is idempotent enough.
    outdir = W / "robot_results"
    outdir.mkdir(exist_ok=True)
    log(f"$ (cd robot && robot --outputdir {outdir} {suite.name})")
    with LOG.open("a", encoding="utf-8") as lf:
        proc = subprocess.run(
            [
                str(ROBOT),
                "--outputdir",
                str(outdir),
                "--loglevel",
                "INFO",
                suite.name,
            ],
            cwd=str(W / "robot"),
            env=env,
            stdout=lf,
            stderr=subprocess.STDOUT,
            timeout=PER_APP * (BATCH_MAX + 3) + 2400,
        )
    log(f"  exit={proc.returncode}")
    return proc.returncode


def complete_apply_fallback() -> int:
    log("complete_apply.py direct (best env: long dwell/commit, ATS helpers)")
    return run(
        [str(PYTHON), "-u", str(W / "complete_apply.py")],
        timeout=PER_APP * (BATCH_MAX + 2) + 600,
    )


def iterate_fail_learn() -> int:
    log(f"iterate_apply.py ×{ITERATIONS} (fail→lesson→retry)")
    env = base_env()
    env["ITERATIONS"] = str(ITERATIONS)
    env["COMPLETE_MAX"] = str(min(BATCH_MAX, 15))
    # iterate_apply defaults queue to etoro; force software rings
    env["COMPLETE_QUEUE_CSV"] = QUEUE
    return run(
        [str(PYTHON), "-u", str(W / "iterate_apply.py")],
        env=env,
        timeout=PER_APP * (BATCH_MAX + 2) * ITERATIONS + 1800,
    )


def regenerate_dashboard() -> None:
    run([str(PYTHON), str(W / "generate_applications_dashboard.py")], timeout=120)


def main() -> int:
    if PAUSE.exists():
        log("PAUSED — .APPLICATIONS_PAUSED present; exiting")
        return 2
    log("==== BEST AUTOMATION START ====")
    log("stack: Robot → complete_apply → Playwright Chromium :9223")
    log(f"queue={QUEUE} max={BATCH_MAX} per_app={PER_APP}s iterations={ITERATIONS}")
    log("docs: 0020_raw + ETSETB academic + work certs 2020 + degree 2003")

    ensure_dashboard()
    ensure_cdp()
    refresh_queue()

    rc_robot = robot_suite()
    if rc_robot != 0:
        log("robot path incomplete or failed — running complete_apply with best env")
        complete_apply_fallback()

    # Multi-iteration learning always (improves stuck/open_only rates)
    iterate_fail_learn()
    regenerate_dashboard()

    log("==== BEST AUTOMATION DONE ====")
    log(f"log: {LOG}")
    log("tracker: http://127.0.0.1:8765/")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.TimeoutExpired as e:
        log(f"TIMEOUT: {e}")
        sys.exit(124)
    except KeyboardInterrupt:
        log("interrupted")
        sys.exit(130)
