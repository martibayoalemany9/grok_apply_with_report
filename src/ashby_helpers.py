"""Ashby HQ application form helpers."""
from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse


ASHBY_APPLY_PATTERNS = [
    r"^Apply$",
    r"Apply for this job",
    r"Apply for this position",
    r"Apply for role",
    r"Apply Now",
    r"Start application",
    r"Submit application",
    r"I'm interested",
]


def ashby_application_url(url: str) -> str | None:
    """Build Ashby /application URL from a job posting link."""
    u = (url or "").strip()
    if "ashbyhq" not in u.lower():
        return None
    if "/application" in u.lower():
        return u.split("#")[0]
    parsed = urlparse(u)
    path = parsed.path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    # jobs.ashbyhq.com/{org}/{jobId}
    if len(parts) >= 2:
        app_path = path + "/application"
        return urlunparse(parsed._replace(path=app_path, fragment=""))
    return None


async def ashby_navigate_to_application(page, log_fn=None) -> bool:
    """Open the Ashby application form — direct /application URL or Apply CTA."""
    url = page.url or ""
    if "ashbyhq" not in url.lower():
        return False

    def _log(msg: str):
        if log_fn:
            log_fn(msg)

    app_url = ashby_application_url(url)
    if app_url and "/application" not in url.lower():
        try:
            await page.goto(app_url, wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(1500)
            _log(f"  ashby → {app_url[:90]}")
            return True
        except Exception:
            pass

    # Already on application page — wait for form widgets
    if "/application" in url.lower():
        try:
            await page.wait_for_selector(
                'input[type="file"], input[name], textarea, form',
                timeout=8000,
            )
        except Exception:
            pass
        return True

    return False


async def ashby_open_application(page, click_fn=None, log_fn=None) -> bool:
    """Click Ashby apply CTA and wait for the application form."""
    url = page.url or ""
    if "ashbyhq" not in url.lower():
        return False

    def _log(msg: str):
        if log_fn:
            log_fn(msg)

    if await ashby_navigate_to_application(page, log_fn=log_fn):
        cur = page.url or ""
        if "/application" in cur.lower():
            return True

    clicked = False
    if click_fn:
        for pat in ASHBY_APPLY_PATTERNS:
            try:
                if await click_fn(page, [pat], roles=("button", "link")):
                    clicked = True
                    _log(f"  ashby apply → {pat[:40]}")
                    break
            except Exception:
                continue
    if not clicked:
        for pat in ASHBY_APPLY_PATTERNS:
            for role in ("button", "link"):
                try:
                    loc = page.get_by_role(role, name=re.compile(pat, re.I))
                    if await loc.count() and await loc.first.is_visible(timeout=500):
                        await loc.first.click(timeout=2500)
                        clicked = True
                        _log(f"  ashby apply → {pat[:40]}")
                        break
                except Exception:
                    continue
            if clicked:
                break

    if not clicked:
        for sel in (
            'a[href*="/application"]',
            'button[class*="ashby"]',
            '[data-testid*="apply"]',
        ):
            try:
                loc = page.locator(sel)
                if await loc.count() and await loc.first.is_visible(timeout=400):
                    await loc.first.click(timeout=2500)
                    clicked = True
                    _log(f"  ashby apply css → {sel[:40]}")
                    break
            except Exception:
                continue

    if clicked:
        try:
            await page.wait_for_timeout(2000)
        except Exception:
            pass
        if "/application" not in (page.url or "").lower():
            await ashby_navigate_to_application(page, log_fn=log_fn)

    return clicked or "/application" in (page.url or "").lower()


async def ashby_attach_files(page, cv_path: str, cert_path: str, log_fn=None) -> tuple[bool, bool]:
    """Force-attach CV/certs on Ashby forms (inputs are often hidden until Apply is clicked)."""
    up_cv = up_cert = False

    def _log(msg: str):
        if log_fn:
            log_fn(msg)

    await ashby_open_application(page, log_fn=log_fn)

    try:
        inputs = page.locator('input[type="file"]')
        n = await inputs.count()
        for i in range(n):
            el = inputs.nth(i)
            try:
                if not up_cv:
                    await el.set_input_files(cv_path, timeout=5000)
                    up_cv = True
                    _log("  ✓ Ashby CV attached")
                elif not up_cert:
                    await el.set_input_files(cert_path, timeout=5000)
                    up_cert = True
                    _log("  ✓ Ashby cert attached")
            except Exception:
                continue
        if not up_cv and n >= 1:
            try:
                await inputs.first.set_input_files([cv_path, cert_path], timeout=5000)
                up_cv = up_cert = True
                _log("  ✓ Ashby CV + cert (multi)")
            except Exception:
                pass
    except Exception:
        pass

    if not up_cv:
        try:
            from mac_file_picker import click_upload_and_fill_mac

            if await click_upload_and_fill_mac(page, cv_path, log_fn=log_fn):
                up_cv = True
                _log("  ✓ Ashby CV via Mac picker")
        except Exception:
            pass

    if up_cv and not up_cert:
        try:
            from mac_file_picker import click_upload_and_fill_mac

            if await click_upload_and_fill_mac(page, cert_path, log_fn=log_fn):
                up_cert = True
                _log("  ✓ Ashby cert via Mac picker")
        except Exception:
            pass

    return up_cv, up_cert