#!/usr/bin/env python3
"""Local website to track job applications + screenshots.

  python3 serve_applications_dashboard.py
  → http://127.0.0.1:8765/

Serves:
  /                     applications_dashboard.html (auto-regenerated)
  /screenshots/*        apply attempt screenshots
  /offer_screenshots/*  job-offer screenshots
  /api/summary.json     lightweight status JSON
  /api/regenerate       force rebuild dashboard (POST or GET)

Env:
  PORT=8765
  REGEN_SEC=30   auto-regenerate interval (0 = only on request)
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
PORT = int(os.environ.get("PORT", "8765"))
REGEN_SEC = int(os.environ.get("REGEN_SEC", "30"))
DASH = W / "applications_dashboard.html"
GEN = W / "generate_applications_dashboard.py"
PID_FILE = W / ".dashboard_server.pid"
LOG = W / "dashboard_server.log"

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
        if not force and _last_gen and (now - _last_gen) < 5:
            return True
        try:
            subprocess.run(
                [sys.executable, str(GEN)],
                cwd=str(W),
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            _last_gen = time.time()
            log(f"dashboard regenerated → {DASH.name}")
            return True
        except Exception as exc:
            log(f"regenerate failed: {exc}")
            return False


def summary() -> dict:
    ledger = W / "applications_ledger.jsonl"
    n = 0
    by_status: dict[str, int] = {}
    last_ts = ""
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            n += 1
            st = o.get("status") or "unknown"
            by_status[st] = by_status.get(st, 0) + 1
            last_ts = o.get("ts") or last_ts
    shots = 0
    for sub in ("screenshots", "offer_screenshots"):
        d = W / sub
        if d.is_dir():
            shots += len(list(d.glob("*.png")))
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ledger_rows": n,
        "by_status": dict(sorted(by_status.items(), key=lambda x: -x[1])[:20]),
        "screenshot_pngs": shots,
        "dashboard": str(DASH),
        "docs": {
            "cv": "0020_raw_marti__bayo_alemany_curriculum.pdf",
            "academic": "etsetb_with_equivalences_and_government_register.pdf",
            "work_certs": "First__Bayo_Alemany_certificates_2020_compressed.pdf",
            "degree_year": "2003",
        },
        "last_ledger_ts": last_ts,
        "url": f"http://127.0.0.1:{PORT}/",
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(W), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        # quieter access log
        if args and str(args[0]).startswith("GET /api/"):
            return
        log(f"http {self.address_string()} {fmt % args}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html", "/dashboard"):
            regenerate(force=False)
            self.path = "/applications_dashboard.html"
            return super().do_GET()
        if path == "/api/summary.json":
            body = json.dumps(summary(), indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/regenerate":
            ok = regenerate(force=True)
            body = json.dumps({"ok": ok, "ts": datetime.now().isoformat()}).encode()
            self.send_response(200 if ok else 500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/regenerate":
            return self.do_GET()
        self.send_error(404)


def regen_loop(stop: threading.Event) -> None:
    while not stop.wait(REGEN_SEC if REGEN_SEC > 0 else 3600):
        if REGEN_SEC > 0:
            regenerate(force=True)


def main() -> None:
    regenerate(force=True)
    stop = threading.Event()
    if REGEN_SEC > 0:
        t = threading.Thread(target=regen_loop, args=(stop,), daemon=True)
        t.start()
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    log(f"serving tracker at http://127.0.0.1:{PORT}/  (cwd={W})")
    log(f"screenshots: {W / 'screenshots'} + {W / 'offer_screenshots'}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        httpd.server_close()
        if PID_FILE.exists():
            PID_FILE.unlink(missing_ok=True)
        log("dashboard server stopped")


if __name__ == "__main__":
    main()
