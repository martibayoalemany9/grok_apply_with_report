#!/usr/bin/env python3
"""Localhost HTML report: succeeded vs failed applications.

  python3 serve_progress_report.py
  → http://127.0.0.1:8790/

Regenerates the report every PROGRESS_REGEN_SEC (default 600 = 10 minutes).
HTML also auto-refreshes every 10 minutes.

Env:
  PROGRESS_PORT=8790
  PROGRESS_REGEN_SEC=600
  PROGRESS_REFRESH_SEC=600
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

W = Path(__file__).resolve().parent
PORT = int(os.environ.get("PROGRESS_PORT", "8790"))
REGEN_SEC = int(os.environ.get("PROGRESS_REGEN_SEC", "600"))
GEN = W / "generate_progress_report.py"
REPORT = W / "applications_progress_report.html"
PID_FILE = W / ".progress_report_server.pid"
LOG = W / "progress_report_server.log"

_lock = threading.Lock()
_last_gen = 0.0


def log(msg: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def regenerate(force: bool = False) -> bool:
    global _last_gen
    with _lock:
        now = time.time()
        if not force and _last_gen and (now - _last_gen) < 10:
            return True
        try:
            env = os.environ.copy()
            env["PROGRESS_REFRESH_SEC"] = str(
                int(os.environ.get("PROGRESS_REFRESH_SEC", "600"))
            )
            subprocess.run(
                [sys.executable, str(GEN)],
                cwd=str(W),
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
            _last_gen = time.time()
            log(f"progress report regenerated → {REPORT.name}")
            return True
        except Exception as e:
            log(f"regenerate failed: {e}")
            return False


def summary() -> dict:
    ledger = W / "applications_ledger.jsonl"
    by_status: dict[str, int] = {}
    n = 0
    success = fail = 0
    SUCCESS = {
        "submitted",
        "submitted_or_confirmed",
        "likely_submitted",
        "succeeded",
        "done",
        "skipped_already_done",
    }
    if ledger.exists():
        seen = {}
        for line in ledger.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                o = json.loads(line)
            except Exception:
                continue
            key = (o.get("url") or "") + "|" + (o.get("company") or "")
            seen[key] = o
        for o in seen.values():
            n += 1
            st = (o.get("status") or "unknown").lower()
            by_status[st] = by_status.get(st, 0) + 1
            if st in SUCCESS or "submit" in st:
                success += 1
            elif "fail" in st or "stuck" in st or st == "exception":
                fail += 1
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "unique_roles": n,
        "success": success,
        "fail_or_stuck": fail,
        "by_status": dict(sorted(by_status.items(), key=lambda x: -x[1])[:25]),
        "report_url": f"http://127.0.0.1:{PORT}/applications_progress_report.html",
        "refresh_sec": REGEN_SEC,
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(W), **k)

    def log_message(self, fmt, *args):
        log("http " + (fmt % args))

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/progress", "/progress.html"):
            regenerate(force=False)
            self.send_response(302)
            self.send_header("Location", "/applications_progress_report.html")
            self.end_headers()
            return
        if path == "/api/summary.json":
            body = json.dumps(summary(), indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("/api/regenerate", "/regenerate"):
            regenerate(force=True)
            self.send_response(302)
            self.send_header("Location", "/applications_progress_report.html")
            self.end_headers()
            return
        return super().do_GET()


def regen_loop():
    while True:
        time.sleep(max(30, REGEN_SEC))
        regenerate(force=True)


def main() -> int:
    regenerate(force=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    t = threading.Thread(target=regen_loop, daemon=True)
    t.start()
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    log(f"Progress report http://127.0.0.1:{PORT}/  regen every {REGEN_SEC}s")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("stopped")
    finally:
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
