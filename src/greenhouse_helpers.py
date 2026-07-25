"""Greenhouse embed (job-boards.eu.greenhouse.io) helpers."""
from __future__ import annotations

import re


async def wait_greenhouse_frame(page, timeout_ms: int = 15000):
    """Wait until a Greenhouse embed iframe is present and loaded."""
    deadline = timeout_ms / 1000.0
    import time

    start = time.monotonic()
    while time.monotonic() - start < deadline:
        for fr in page.frames:
            if "greenhouse.io" in (fr.url or "").lower():
                try:
                    if await fr.locator("body").count():
                        return fr
                except Exception:
                    return fr
        try:
            await page.wait_for_timeout(400)
        except Exception:
            break
    return None


async def greenhouse_frames(page) -> list:
    return [fr for fr in page.frames if "greenhouse.io" in (fr.url or "").lower()]


async def greenhouse_open_apply(frame, click_fn=None, log_fn=None) -> bool:
    for pat in [r"Apply for this job", r"^Apply$", r"Apply Now", r"Submit application"]:
        if click_fn:
            try:
                if await click_fn(frame, [pat], roles=("button", "link")):
                    if log_fn:
                        log_fn(f"  greenhouse apply → {pat[:30]}")
                    return True
            except Exception:
                pass
        for role in ("button", "link"):
            try:
                loc = frame.get_by_role(role, name=re.compile(pat, re.I))
                if await loc.count() and await loc.first.is_visible(timeout=500):
                    await loc.first.click(timeout=2500)
                    if log_fn:
                        log_fn(f"  greenhouse apply → {pat[:30]}")
                    return True
            except Exception:
                continue
    return False


async def greenhouse_attach(page, cv_path: str, cert_path: str, click_fn=None, log_fn=None) -> tuple[bool, bool]:
    """Open apply + attach CV/certs inside Greenhouse embed iframes."""
    up_cv = up_cert = False
    await wait_greenhouse_frame(page)
    for frame in await greenhouse_frames(page):
        await greenhouse_open_apply(frame, click_fn=click_fn, log_fn=log_fn)
        try:
            await frame.wait_for_timeout(800)
        except Exception:
            pass
        inputs = frame.locator('input[type="file"]')
        n = await inputs.count()
        for i in range(n):
            el = inputs.nth(i)
            try:
                if not up_cv:
                    await el.set_input_files(cv_path, timeout=5000)
                    up_cv = True
                    if log_fn:
                        log_fn("  ✓ Greenhouse CV attached")
                elif not up_cert:
                    await el.set_input_files(cert_path, timeout=5000)
                    up_cert = True
                    if log_fn:
                        log_fn("  ✓ Greenhouse cert attached")
            except Exception:
                continue
        if not up_cv and n:
            try:
                await inputs.first.set_input_files([cv_path, cert_path], timeout=5000)
                up_cv = up_cert = True
                if log_fn:
                    log_fn("  ✓ Greenhouse CV + cert")
            except Exception:
                pass
    return up_cv, up_cert


async def greenhouse_fill_frames(page, fill_fn, log_fn=None) -> int:
    """Run fill() inside each Greenhouse embed iframe."""
    total = 0
    if not hasattr(page, "frames"):
        return 0
    for frame in await greenhouse_frames(page):
        try:
            n = await fill_fn(frame)
            if n:
                total += n
                if log_fn:
                    log_fn(f"  ✓ Greenhouse filled {n} field(s)")
        except Exception:
            continue
    return total


async def greenhouse_try_submit(page, click_fn=None, log_fn=None) -> bool:
    """Click Submit inside Greenhouse embed iframes."""
    if not hasattr(page, "frames"):
        return False
    pats = [
        r"Submit application",
        r"^Submit$",
        r"Submit$",
        r"Send application",
        r"Apply",
    ]
    for frame in await greenhouse_frames(page):
        if click_fn:
            for pat in pats:
                try:
                    if await click_fn(frame, [pat], roles=("button", "link")):
                        if log_fn:
                            log_fn(f"  greenhouse submit → {pat[:30]}")
                        return True
                except Exception:
                    continue
        for pat in pats:
            for role in ("button", "link"):
                try:
                    loc = frame.get_by_role(role, name=re.compile(pat, re.I))
                    if await loc.count() and await loc.first.is_visible(timeout=400):
                        await loc.first.click(timeout=2500)
                        if log_fn:
                            log_fn(f"  greenhouse submit → {pat[:30]}")
                        try:
                            await frame.wait_for_timeout(2500)
                        except Exception:
                            pass
                        return True
                except Exception:
                    continue
    return False


async def greenhouse_success_text(page, success_fn) -> bool:
    """Check main page + Greenhouse iframe bodies for thank-you text."""
    if not hasattr(page, "frames"):
        return False
    for frame in await greenhouse_frames(page):
        try:
            body = await frame.inner_text("body")
            title = await frame.title()
            if success_fn(body, title):
                return True
        except Exception:
            continue
    return False