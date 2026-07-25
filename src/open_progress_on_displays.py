#!/usr/bin/env python3
"""Open the progress report in Playwright Chromium on every Mac display.

Uses separate Playwright Chromium instances (not your daily Chrome profile),
positioned on each screen so they run in parallel without taking over the OS.

  # Ensure report server is up, then:
  python3 -u open_progress_on_displays.py

  # One-shot: start server + open browsers
  python3 -u open_progress_on_displays.py --with-server

Env:
  PROGRESS_URL=http://127.0.0.1:8790/
  PROGRESS_RELOAD_SEC=600     # page.reload interval (10 min)
  PROGRESS_PORT=8790
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

W = Path(__file__).resolve().parent
LOG = W / "progress_displays.log"
URL = os.environ.get("PROGRESS_URL", "http://127.0.0.1:8790/").rstrip("/") + "/"
RELOAD_SEC = int(os.environ.get("PROGRESS_RELOAD_SEC", "600"))
PORT = int(os.environ.get("PROGRESS_PORT", "8790"))


def log(msg: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


@dataclass
class Display:
    index: int
    display_id: int
    x: int
    y: int
    width: int
    height: int
    is_main: bool


def list_displays() -> list[Display]:
    """macOS CoreGraphics display bounds (logical points)."""
    try:
        cg = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )

        class CGPoint(ctypes.Structure):
            _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

        class CGSize(ctypes.Structure):
            _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]

        class CGRect(ctypes.Structure):
            _fields_ = [("origin", CGPoint), ("size", CGSize)]

        CGDirectDisplayID = ctypes.c_uint32
        max_d = 16
        ids = (CGDirectDisplayID * max_d)()
        count = ctypes.c_uint32(0)
        cg.CGGetActiveDisplayList(max_d, ids, ctypes.byref(count))
        cg.CGDisplayBounds.restype = CGRect
        cg.CGDisplayBounds.argtypes = [CGDirectDisplayID]
        cg.CGDisplayIsMain.restype = ctypes.c_uint32

        out: list[Display] = []
        for i in range(count.value):
            b = cg.CGDisplayBounds(ids[i])
            out.append(
                Display(
                    index=i,
                    display_id=int(ids[i]),
                    x=int(b.origin.x),
                    y=int(b.origin.y),
                    width=int(b.size.width),
                    height=int(b.size.height),
                    is_main=bool(cg.CGDisplayIsMain(ids[i])),
                )
            )
        if out:
            return out
    except Exception as e:
        log(f"display detect fallback: {e}")
    # Single synthetic display
    return [
        Display(
            index=0, display_id=0, x=0, y=0, width=1440, height=900, is_main=True
        )
    ]


def wait_server(timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(URL, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def ensure_server() -> subprocess.Popen | None:
    if wait_server(timeout=2):
        log(f"server already up {URL}")
        return None
    log("starting serve_progress_report.py …")
    proc = subprocess.Popen(
        [sys.executable, "-u", str(W / "serve_progress_report.py")],
        cwd=str(W),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env={
            **os.environ,
            "PROGRESS_PORT": str(PORT),
            "PROGRESS_REGEN_SEC": str(RELOAD_SEC),
            "PROGRESS_REFRESH_SEC": str(RELOAD_SEC),
        },
    )
    if not wait_server(timeout=25):
        log("server failed to start")
        return proc
    log(f"server pid={proc.pid} {URL}")
    return proc


async def run_viewer(display: Display, stop: asyncio.Event) -> None:
    from playwright.async_api import async_playwright

    # Leave a margin so windows don't fully cover menu bar / dock
    margin = 24
    w = max(800, display.width - margin * 2)
    h = max(600, display.height - margin * 2 - 40)
    x = display.x + margin
    y = display.y + margin + 22  # below menu bar

    profile = W / f".progress-browser-profile-{display.index}"
    profile.mkdir(exist_ok=True)

    log(
        f"display[{display.index}] id={display.display_id} "
        f"{display.width}x{display.height}+{display.x}+{display.y} "
        f"window={w}x{h}+{x}+{y} main={display.is_main}"
    )

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=False,
            viewport={"width": w, "height": h},
            args=[
                f"--window-position={x},{y}",
                f"--window-size={w},{h}",
                "--disable-infobars",
                "--no-default-browser-check",
                "--disable-session-crashed-bubble",
                # Do not steal focus aggressively
                "--new-window",
            ],
            ignore_default_args=["--enable-automation"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            await page.title()
            log(f"display[{display.index}] loaded {URL}")
        except Exception as e:
            log(f"display[{display.index}] goto err: {e}")

        # Reload loop (HTML also meta-refreshes; this forces regen-friendly reload)
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=RELOAD_SEC)
            except asyncio.TimeoutError:
                pass
            if stop.is_set():
                break
            try:
                await page.reload(wait_until="domcontentloaded", timeout=60000)
                log(f"display[{display.index}] reloaded")
            except Exception as e:
                log(f"display[{display.index}] reload err: {e}")
                try:
                    await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
                except Exception:
                    pass
        await ctx.close()


async def main_async(with_server: bool) -> int:
    server_proc = None
    if with_server:
        server_proc = ensure_server()
    elif not wait_server(timeout=5):
        log(f"No server at {URL} — start with --with-server or serve_progress_report.py")
        return 2

    displays = list_displays()
    log(f"found {len(displays)} display(s)")
    for d in displays:
        log(
            f"  [{d.index}] {d.width}x{d.height} @ ({d.x},{d.y}) "
            f"{'MAIN' if d.is_main else ''}"
        )

    stop = asyncio.Event()
    tasks = [asyncio.create_task(run_viewer(d, stop)) for d in displays]

    log(
        f"Playwright viewers running on {len(displays)} screen(s). "
        f"Reload every {RELOAD_SEC}s. Ctrl+C to stop."
    )
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        stop.set()
        for t in tasks:
            t.cancel()
        if server_proc and server_proc.poll() is None:
            log(f"leaving report server running (pid={server_proc.pid})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Progress report on all Mac displays")
    ap.add_argument(
        "--with-server",
        action="store_true",
        help="Start serve_progress_report.py if not already running",
    )
    args = ap.parse_args()
    try:
        return asyncio.run(main_async(with_server=args.with_server))
    except KeyboardInterrupt:
        log("interrupted")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
