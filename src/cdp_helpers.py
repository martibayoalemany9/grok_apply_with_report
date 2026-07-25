#!/usr/bin/env python3
"""Browser CDP helpers for job-apply automation.

Default browser (2026-07-19): **Playwright Chromium** on :9223 with a dedicated
profile (`~/.browser-job-apply-chromium`). This replaces the previous personal
Google Chrome profile on :9222 (Gmail browser-use profile), which fought other
sessions and closed tabs unpredictably.

Env:
  APPLY_BROWSER   chromium | chrome | edge   (default: chromium)
  CDP_URL         e.g. http://127.0.0.1:9223 (default by browser)
  CDP_PORT        override port (default 9223 for chromium, 9222 for chrome)
  APPLY_USER_DATA_DIR  override user-data-dir
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

HOME = Path.home()

# --- browser selection -------------------------------------------------------
APPLY_BROWSER = (os.environ.get("APPLY_BROWSER") or "chromium").strip().lower()

_DEFAULT_PORTS = {
    "chromium": 9223,
    "chrome": 9222,
    "edge": 9224,
}
_DEFAULT_PROFILES = {
    "chromium": HOME / ".browser-job-apply-chromium",
    "chrome": HOME / ".browser-use-chrome-profile-with-gmail",
    "edge": HOME / ".browser-job-apply-edge",
}


def _port() -> int:
    if os.environ.get("CDP_PORT"):
        return int(os.environ["CDP_PORT"])
    if os.environ.get("CDP_URL"):
        # parse :port from URL
        try:
            return int(os.environ["CDP_URL"].rstrip("/").rsplit(":", 1)[-1])
        except Exception:
            pass
    return _DEFAULT_PORTS.get(APPLY_BROWSER, 9223)


def default_cdp_url() -> str:
    if os.environ.get("CDP_URL"):
        return os.environ["CDP_URL"].strip()
    return f"http://127.0.0.1:{_port()}"


def user_data_dir() -> Path:
    if os.environ.get("APPLY_USER_DATA_DIR"):
        return Path(os.environ["APPLY_USER_DATA_DIR"]).expanduser()
    return _DEFAULT_PROFILES.get(APPLY_BROWSER, _DEFAULT_PROFILES["chromium"])


def browser_binary() -> str | None:
    """Resolve browser executable for APPLY_BROWSER."""
    if APPLY_BROWSER == "chrome":
        p = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        return str(p) if p.exists() else None
    if APPLY_BROWSER == "edge":
        for p in (
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            Path("/Applications/Edge.app/Contents/MacOS/Microsoft Edge"),
        ):
            if p.exists():
                return str(p)
        return None
    # chromium via Playwright install
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            exe = p.chromium.executable_path
            if exe and Path(exe).exists():
                return exe
    except Exception:
        pass
    # fallback common chromium paths
    for p in (
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        Path.home() / "Library/Caches/ms-playwright",
    ):
        if p.is_file():
            return str(p)
        if p.is_dir():
            # find chromium-*/chrome-mac*/Chromium or chrome
            for cand in sorted(p.glob("chromium-*/chrome-mac*/Chromium")):
                return str(cand)
            for cand in sorted(p.glob("chromium-*/chrome-mac*/Google Chrome for Testing")):
                return str(cand)
    return None


def cdp_alive(cdp: str | None = None) -> bool:
    cdp = cdp or default_cdp_url()
    try:
        urllib.request.urlopen(cdp + "/json/version", timeout=2)
        return True
    except Exception:
        return False


def cdp_tabs(cdp: str | None = None) -> list[dict]:
    cdp = cdp or default_cdp_url()
    try:
        raw = urllib.request.urlopen(cdp + "/json/list", timeout=3).read()
        return json.loads(raw)
    except Exception:
        return []


def launch_browser_cdp(cdp: str | None = None, port: int | None = None) -> bool:
    """Start the selected browser with remote debugging if not already listening."""
    cdp = cdp or default_cdp_url()
    if cdp_alive(cdp):
        return True
    port = port or _port()
    binary = browser_binary()
    if not binary:
        print(f"  [cdp] no binary for APPLY_BROWSER={APPLY_BROWSER}", flush=True)
        return False
    profile = user_data_dir()
    profile.mkdir(parents=True, exist_ok=True)
    cmd = [
        binary,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "about:blank",
    ]
    print(
        f"  [cdp] launching {APPLY_BROWSER} → :{port} profile={profile}",
        flush=True,
    )
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        print(f"  [cdp] launch failed: {e}", flush=True)
        return False
    for _ in range(30):
        time.sleep(0.5)
        if cdp_alive(cdp):
            return True
    return False


# Back-compat aliases
def launch_chrome_cdp(cdp: str | None = None, port: int | None = None) -> bool:
    return launch_browser_cdp(cdp=cdp, port=port)


def ensure_cdp_tab(cdp: str | None = None) -> bool:
    """Launch browser if needed; open about:blank if no page targets."""
    cdp = cdp or default_cdp_url()
    if not cdp_alive(cdp):
        if not launch_browser_cdp(cdp):
            return False
    pages = [t for t in cdp_tabs(cdp) if t.get("type") == "page"]
    if pages:
        return True
    try:
        req = urllib.request.Request(
            cdp + "/json/new?about:blank",
            method="PUT",
        )
        urllib.request.urlopen(req, timeout=5)
        return bool([t for t in cdp_tabs(cdp) if t.get("type") == "page"])
    except Exception:
        return False


def bring_browser_fullscreen(cdp: str | None = None) -> bool:
    """Put the apply Chromium window full-screen on macOS (separate from Grok TUI).

    Uses AppleScript to activate the browser app and send Ctrl+Cmd+F (fullscreen).
    The CDP browser is already a different process/window from the chat prompt.
    Env: APPLY_BROWSER_FULLSCREEN=0 to disable (default on for local CDP).
    """
    flag = (os.environ.get("APPLY_BROWSER_FULLSCREEN") or "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    cdp = cdp or default_cdp_url()
    if not cdp_alive(cdp):
        return False

    # Map APPLY_BROWSER → macOS process/app name
    app_map = {
        "chromium": "Chromium",
        "chrome": "Google Chrome",
        "edge": "Microsoft Edge",
    }
    # Playwright "Google Chrome for Testing" often shows as "Google Chrome for Testing"
    candidates = []
    ab = APPLY_BROWSER
    if ab in app_map:
        candidates.append(app_map[ab])
    candidates.extend(
        [
            "Google Chrome for Testing",
            "Chromium",
            "Google Chrome",
        ]
    )
    # Dedupe preserve order
    seen = set()
    apps = []
    for a in candidates:
        if a not in seen:
            seen.add(a)
            apps.append(a)

    for app in apps:
        script = f'''
        tell application "System Events"
          if exists process "{app}" then
            tell process "{app}"
              set frontmost to true
            end tell
          else
            return "missing"
          end if
        end tell
        tell application "{app}" to activate
        delay 0.4
        tell application "System Events"
          tell process "{app}"
            try
              -- enter full screen if not already
              keystroke "f" using {{control down, command down}}
            end try
          end tell
        end tell
        return "ok"
        '''
        try:
            r = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=8,
            )
            out = (r.stdout or "").strip()
            if r.returncode == 0 and out == "ok":
                print(f"  [cdp] fullscreen via {app}", flush=True)
                return True
        except Exception:
            continue
    # Fallback: maximize via bounds if we can find Chrome window (best-effort)
    try:
        script = '''
        tell application "System Events"
          set procs to name of every process whose background only is false
        end tell
        return procs
        '''
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except Exception:
        pass
    print("  [cdp] fullscreen skipped (app not found or osascript denied)", flush=True)
    return False


if __name__ == "__main__":
    print("APPLY_BROWSER=", APPLY_BROWSER)
    print("CDP=", default_cdp_url())
    print("profile=", user_data_dir())
    print("binary=", browser_binary())
    print("alive=", cdp_alive())
    if not cdp_alive():
        print("launch=", launch_browser_cdp())
    print("tabs=", len(cdp_tabs()))
