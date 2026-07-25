#!/usr/bin/env python3
"""One command: regenerate report, serve on localhost, open on all displays.

  python3 -u run_progress_report.py

- HTML progress: http://127.0.0.1:8790/
- Rebuilds every 10 minutes
- Playwright Chromium window per Mac screen (separate profiles, not your Chrome)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

W = Path(__file__).resolve().parent


def main() -> int:
    env = os.environ.copy()
    env.setdefault("PROGRESS_PORT", "8790")
    env.setdefault("PROGRESS_REGEN_SEC", "600")
    env.setdefault("PROGRESS_REFRESH_SEC", "600")
    env.setdefault("PROGRESS_RELOAD_SEC", "600")
    env.setdefault("PROGRESS_URL", f"http://127.0.0.1:{env['PROGRESS_PORT']}/")

    # Generate once
    subprocess.run(
        [sys.executable, str(W / "generate_progress_report.py")],
        cwd=str(W),
        check=False,
        env=env,
    )
    # Open viewers + server
    return subprocess.call(
        [sys.executable, "-u", str(W / "open_progress_on_displays.py"), "--with-server"],
        cwd=str(W),
        env=env,
    )


if __name__ == "__main__":
    raise SystemExit(main())
