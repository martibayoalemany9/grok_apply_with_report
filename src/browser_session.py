#!/usr/bin/env python3
"""Browser session factory for job-apply automation.

Supported stacks
----------------
| APPLY_BROWSER | Engine              | How it attaches              |
|---------------|---------------------|------------------------------|
| chromium      | Playwright Chromium | CDP :9223 (default)          |
| chrome        | Google Chrome       | CDP :9222                    |
| edge          | Microsoft Edge      | CDP :9224                    |
| safari        | Playwright WebKit   | launch_persistent_context    |
| webkit        | Playwright WebKit   | same as safari               |
| safari_system | macOS Safari        | Selenium safaridriver        |
| firefox       | Playwright Firefox  | launch_persistent_context    |
| cloud_mobile  | Appium (real phone) | LambdaTest / BrowserStack /  |
|               | Chrome on Android   | Sauce / generic Appium hub   |

Notes
-----
- **safari / webkit**: reliable automation via Playwright WebKit (Safari engine).
- **safari_system**: real Safari.app — requires Develop → Allow Remote Automation
  and `safaridriver --enable` (one-time). Falls back to webkit if session fails.
- Chrome uses your real Chrome with CDP (Gmail profile on :9222 by default).

Robot Framework suites set APPLY_BROWSER and call complete_apply.py.
Cloud mobile: see CLOUD_MOBILE.md and cloud_device.env.example.
"""
from __future__ import annotations

import os
from pathlib import Path

HOME = Path.home()
APPLY_BROWSER = (os.environ.get("APPLY_BROWSER") or "chromium").strip().lower()

# Aliases accepted for rented-device mode
_CLOUD_ALIASES = frozenset(
    {"cloud_mobile", "appium", "mobile_cloud", "s26", "galaxy_s26"}
)
_SAFARI_ALIASES = frozenset({"safari", "webkit", "pw_safari"})
_SAFARI_SYSTEM_ALIASES = frozenset({"safari_system", "safari_app", "safaridriver"})


def is_cloud_mobile_browser(name: str | None = None) -> bool:
    b = (name or APPLY_BROWSER).strip().lower()
    return b in _CLOUD_ALIASES


def is_safari_browser(name: str | None = None) -> bool:
    b = (name or APPLY_BROWSER).strip().lower()
    return b in _SAFARI_ALIASES or b in _SAFARI_SYSTEM_ALIASES


def is_persistent_browser(name: str | None = None) -> bool:
    """True when session is launch_persistent_context (not CDP)."""
    b = (name or APPLY_BROWSER).strip().lower()
    return (
        b in _SAFARI_ALIASES
        or b == "firefox"
        or b in _SAFARI_SYSTEM_ALIASES
        or b in ("chromium_isolated", "pw_chromium", "playwright_chromium", "isolated")
        or os.environ.get("APPLY_LAUNCH", "").lower() in ("persistent", "isolated", "1")
    )


async def open_session(playwright=None):
    """Return (browser_or_none, context, page, mode).

    mode: 'cdp' | 'chromium_isolated' | 'firefox' | 'safari' | 'safari_system' | 'cloud_mobile'
    For CDP, browser is the Browser object; for persistent, browser is None
    and context is BrowserContext from launch_persistent_context.
    For cloud_mobile, browser/context/page are Appium shims (Playwright-like API).
    playwright may be None when mode is cloud_mobile.
    """
    if is_cloud_mobile_browser():
        return await _open_cloud_mobile()
    if APPLY_BROWSER in _SAFARI_SYSTEM_ALIASES:
        try:
            return await _open_safari_system()
        except Exception as e:
            print(f"[safari_system] failed ({e}); falling back to Playwright WebKit", flush=True)
            return await _open_safari_webkit(playwright)
    if APPLY_BROWSER in _SAFARI_ALIASES:
        return await _open_safari_webkit(playwright)
    if APPLY_BROWSER == "firefox":
        return await _open_firefox(playwright)
    # Isolated Chromium (parallel workers — no shared CDP)
    if APPLY_BROWSER in (
        "chromium_isolated",
        "pw_chromium",
        "playwright_chromium",
        "isolated",
    ) or os.environ.get("APPLY_LAUNCH", "").lower() in ("persistent", "isolated", "1"):
        return await _open_chromium_isolated(playwright)
    return await _open_cdp(playwright)


async def _open_cloud_mobile():
    import asyncio

    from appium_playwright_shim import create_appium_session
    from cloud_device import load_config, redacted_hub

    cfg = load_config()

    def _start():
        return create_appium_session(cfg.hub_url, cfg.capabilities)

    browser, ctx, page = await asyncio.to_thread(_start)
    # Stash config on context for logs / reconnect
    ctx._cloud_cfg = cfg  # type: ignore[attr-defined]
    print(
        f"[cloud_mobile] provider={cfg.provider} device={cfg.device_name!r} "
        f"browser={cfg.browser} hub={redacted_hub(cfg.hub_url)}",
        flush=True,
    )
    return browser, ctx, page, "cloud_mobile"


async def _open_cdp(playwright):
    from cdp_helpers import default_cdp_url, ensure_cdp_tab, launch_browser_cdp

    cdp = os.environ.get("CDP_URL", "").strip() or default_cdp_url()
    if not ensure_cdp_tab(cdp):
        if not launch_browser_cdp(cdp) or not ensure_cdp_tab(cdp):
            raise RuntimeError(f"CDP offline and launch failed ({APPLY_BROWSER} @ {cdp})")
    browser = await playwright.chromium.connect_over_cdp(cdp)
    if not browser.contexts:
        raise RuntimeError("CDP connected but no browser context — open a tab")
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    return browser, ctx, page, "cdp"


async def _open_chromium_isolated(playwright):
    """Playwright Chromium persistent profile — safe for parallel apply workers."""
    worker = (os.environ.get("APPLY_WORKER_ID") or os.environ.get("CDP_LOCK_NAME") or "0").strip()
    profile = Path(
        os.environ.get("APPLY_USER_DATA_DIR")
        or (HOME / f".browser-job-apply-chromium-w{worker}")
    ).expanduser()
    profile.mkdir(parents=True, exist_ok=True)
    headless = os.environ.get("HEADLESS", "").lower() in ("1", "true", "yes")
    # Position window if coordinates provided (multi-display parallel)
    args = ["--disable-infobars", "--no-default-browser-check"]
    wx = os.environ.get("APPLY_WINDOW_X")
    wy = os.environ.get("APPLY_WINDOW_Y")
    ww = os.environ.get("APPLY_WINDOW_W", "1100")
    wh = os.environ.get("APPLY_WINDOW_H", "800")
    if wx is not None and wy is not None:
        args.append(f"--window-position={int(wx)},{int(wy)}")
        args.append(f"--window-size={int(ww)},{int(wh)}")
    ctx = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile),
        headless=headless,
        viewport={"width": int(ww), "height": int(wh)},
        args=args,
        accept_downloads=True,
        locale="en-US",
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    print(f"[chromium_isolated] worker={worker} profile={profile}", flush=True)
    return None, ctx, page, "chromium_isolated"


async def _open_firefox(playwright):
    profile = Path(
        os.environ.get("APPLY_USER_DATA_DIR")
        or (HOME / ".browser-job-apply-firefox")
    ).expanduser()
    profile.mkdir(parents=True, exist_ok=True)
    headless = os.environ.get("HEADLESS", "").lower() in ("1", "true", "yes")
    ctx = await playwright.firefox.launch_persistent_context(
        user_data_dir=str(profile),
        headless=headless,
        viewport={"width": 1400, "height": 900},
        accept_downloads=True,
        locale="en-US",
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    return None, ctx, page, "firefox"


async def _open_safari_webkit(playwright):
    """Playwright WebKit — Safari rendering engine (reliable automation on macOS)."""
    profile = Path(
        os.environ.get("APPLY_USER_DATA_DIR")
        or (HOME / ".browser-job-apply-safari")
    ).expanduser()
    profile.mkdir(parents=True, exist_ok=True)
    headless = os.environ.get("HEADLESS", "").lower() in ("1", "true", "yes")
    ctx = await playwright.webkit.launch_persistent_context(
        user_data_dir=str(profile),
        headless=headless,
        viewport={"width": 1400, "height": 900},
        accept_downloads=True,
        locale="en-US",
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    print(f"[safari] Playwright WebKit profile={profile}", flush=True)
    return None, ctx, page, "safari"


async def _open_safari_system():
    """Real Safari.app via Selenium safaridriver (shimmed to Playwright-like API)."""
    import asyncio

    from safari_selenium_shim import create_safari_session

    browser, ctx, page = await asyncio.to_thread(create_safari_session)
    print("[safari_system] Safari.app via safaridriver", flush=True)
    return browser, ctx, page, "safari_system"


async def reconnect_session(playwright, holder: dict):
    """Rebuild session after disconnect. Updates holder in place."""
    if holder.get("mode"):
        mode = holder["mode"]
    elif is_cloud_mobile_browser():
        mode = "cloud_mobile"
    elif APPLY_BROWSER in _SAFARI_SYSTEM_ALIASES:
        mode = "safari_system"
    elif APPLY_BROWSER in _SAFARI_ALIASES:
        mode = "safari"
    elif APPLY_BROWSER == "firefox":
        mode = "firefox"
    elif is_persistent_browser():
        mode = "chromium_isolated"
    else:
        mode = "cdp"
    # close old if possible
    try:
        old_ctx = holder.get("ctx")
        if old_ctx and mode in (
            "firefox",
            "safari",
            "safari_system",
            "chromium_isolated",
            "cloud_mobile",
        ):
            try:
                await old_ctx.close()
            except Exception:
                pass
        old_browser = holder.get("browser")
        if old_browser and mode in ("cloud_mobile", "safari_system"):
            try:
                await old_browser.close()
            except Exception:
                pass
    except Exception:
        pass
    browser, ctx, page, mode = await open_session(playwright)
    holder["browser"] = browser
    holder["ctx"] = ctx
    holder["page"] = page
    holder["mode"] = mode
    return browser, ctx, page
