"""macOS native Open panel helper for job-application uploads.

When a form opens the Mac file picker (NSOpenPanel) instead of a hookable
<input type=file>, Playwright's file chooser may not fire. This module uses
Cmd+Shift+G ("Go to the folder") and types the absolute file path.

Documents (absolute paths — from candidate_profile):
  CV:       .../0020_raw_marti__bayo_alemany_curriculum.pdf
  Work:     .../First__Bayo_Alemany_certificates_2020_compressed.pdf
  Academic: .../etsetb_with_equivalences_and_government_register.pdf

Requires macOS Accessibility permission for the terminal/Python process.
"""
from __future__ import annotations

import asyncio
import platform
import subprocess
from pathlib import Path

from candidate_profile import CERTS, CV

try:
    from candidate_profile import ACADEMIC_CERTS
except Exception:
    ACADEMIC_CERTS = ""

CV_ABS = CV
CERT_ABS = CERTS
ACADEMIC_ABS = ACADEMIC_CERTS

BROWSER_APPS = ("Google Chrome", "Chromium", "Microsoft Edge", "Brave Browser", "Arc")

_UPLOAD_BTN = (
    r"Upload (a )?(resume|CV|file|document)",
    r"Attach (a )?(resume|CV|file)",
    r"Choose [Ff]ile",
    r"Select [Ff]ile",
    r"Browse",
    r"Add (a )?(resume|CV|document)",
    r"^Upload$",
    r"Curriculum [Vv]itae",
)


def is_macos() -> bool:
    return platform.system() == "Darwin"


def _resolve_path(path: str) -> str | None:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return None
    return str(p)


def _run_osascript(*args: str) -> tuple[bool, str]:
    lines = list(args)
    try:
        proc = subprocess.run(
            ["osascript", *lines],
            capture_output=True,
            text=True,
            timeout=15,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode == 0:
            return True, out
        return False, err or out or f"exit {proc.returncode}"
    except Exception as exc:
        return False, str(exc)


def detect_browser_app() -> str:
    """Best-effort front browser process name for System Events."""
    ok, out = _run_osascript(
        "-e",
        'tell application "System Events" to get name of first process '
        'whose frontmost is true and name contains "Chrome"',
    )
    if ok and out:
        for app in BROWSER_APPS:
            if app.lower() in out.lower():
                return app
        if "Chrome" in out:
            return "Google Chrome"
    for app in BROWSER_APPS:
        ok, _ = _run_osascript("-e", f'tell application "System Events" to exists process "{app}"')
        if ok:
            return app
    return "Google Chrome"


def mac_fill_open_dialog_sync(abs_path: str, browser_app: str | None = None) -> bool:
    """Type an absolute file path into the macOS Open panel via Go to Folder."""
    if not is_macos():
        return False
    resolved = _resolve_path(abs_path)
    if not resolved:
        return False
    app = browser_app or detect_browser_app()

    script = [
        "-e",
        "on run argv",
        "-e",
        "set filePath to item 1 of argv",
        "-e",
        "set appName to item 2 of argv",
        "-e",
        'tell application appName to activate',
        "-e",
        "delay 0.35",
        "-e",
        'tell application "System Events"',
        "-e",
        "tell process appName",
        "-e",
        "set frontmost to true",
        "-e",
        "delay 0.25",
        "-e",
        'keystroke "G" using {command down, shift down}',
        "-e",
        "delay 0.6",
        "-e",
        'keystroke "a" using {command down}',
        "-e",
        "delay 0.08",
        "-e",
        "keystroke filePath",
        "-e",
        "delay 0.15",
        "-e",
        "keystroke return",
        "-e",
        "delay 0.5",
        "-e",
        "keystroke return",
        "-e",
        "end tell",
        "-e",
        "end tell",
        "-e",
        'return "ok"',
        "-e",
        "end run",
        "--",
        resolved,
        app,
    ]
    ok, _ = _run_osascript(*script)
    return ok


async def mac_fill_open_dialog(abs_path: str, browser_app: str | None = None) -> bool:
    return await asyncio.to_thread(mac_fill_open_dialog_sync, abs_path, browser_app)


async def click_upload_and_fill_mac(
    page,
    abs_path: str,
    *,
    log_fn=None,
    browser_app: str | None = None,
) -> bool:
    """Click an upload button, then fill the native Mac Open panel with abs_path."""
    import re

    if not is_macos():
        return False
    resolved = _resolve_path(abs_path)
    if not resolved:
        return False

    for pat in _UPLOAD_BTN:
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=re.compile(pat, re.I))
                if not await loc.count():
                    continue
                el = loc.first
                if not await el.is_visible(timeout=400):
                    continue
                await el.click(timeout=2000)
                await asyncio.sleep(0.55)
                ok = await mac_fill_open_dialog(resolved, browser_app)
                if ok:
                    if log_fn:
                        log_fn(f"  ✓ Mac Open panel → {Path(resolved).name}")
                    await asyncio.sleep(1.2)
                    return True
            except Exception:
                continue
    return False