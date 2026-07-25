"""Cooperative lock so apply scripts don't fight the same browser/CDP port.

By default locks are **per browser**:
  - chrome / chromium / edge → shared CDP lock (same Chrome instance family)
  - safari / webkit           → separate Safari lock (can run in parallel with Chrome)
  - firefox                   → separate Firefox lock

Env:
  CDP_LOCK_NAME   force lock file name suffix (e.g. chrome, safari)
  APPLY_BROWSER   used to pick default lock when CDP_LOCK_NAME unset
"""
from __future__ import annotations

import os
import time
from pathlib import Path

W = Path(__file__).resolve().parent
STALE_SEC = 7200

# Browsers that share the same CDP/Chrome process family
_CHROME_FAMILY = frozenset({"chromium", "chrome", "edge", ""})


def _lock_key() -> str:
    forced = (os.environ.get("CDP_LOCK_NAME") or "").strip().lower()
    if forced:
        return forced
    b = (os.environ.get("APPLY_BROWSER") or "chromium").strip().lower()
    if b in _CHROME_FAMILY:
        return "chrome"
    if b in ("safari", "webkit", "pw_safari", "safari_system", "safari_app", "safaridriver"):
        return "safari"
    if b == "firefox":
        return "firefox"
    if b in ("cloud_mobile", "appium", "mobile_cloud", "s26", "galaxy_s26"):
        return "cloud"
    return b or "chrome"


def lock_path() -> Path:
    return W / f".cdp_apply_{_lock_key()}.lock"


# Back-compat alias used by older code
LOCK = W / ".cdp_apply.lock"


def acquire() -> bool:
    path = lock_path()
    # also respect legacy single lock if present and chrome-family
    try:
        if _lock_key() == "chrome" and LOCK.exists() and not path.exists():
            if time.time() - LOCK.stat().st_mtime < STALE_SEC:
                return False
        if path.exists():
            if time.time() - path.stat().st_mtime < STALE_SEC:
                return False
        path.write_text(f"{os.getpid()} {time.time()} key={_lock_key()}\n", encoding="utf-8")
        # legacy touch for chrome so old scripts still see a holder
        if _lock_key() == "chrome":
            try:
                LOCK.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception:
                pass
        return True
    except Exception:
        return True


def release() -> None:
    path = lock_path()
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass
    if _lock_key() == "chrome":
        try:
            LOCK.unlink(missing_ok=True)
        except Exception:
            pass
