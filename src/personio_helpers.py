"""Personio ATS — submit + upload detection fixes."""
from __future__ import annotations

import re

from upload_helpers import CERT_NAME, CV_NAME


async def personio_files_on_page(page) -> tuple[bool, bool]:
    """True when CV/cert filenames already appear in Personio DOM."""
    cv = cert = False
    try:
        body = (await page.inner_text("body", timeout=1200)).lower()
        if CV_NAME in body or "0021_cc_marti" in body or "0020_raw_marti" in body:
            cv = True
        if CERT_NAME in body or "certificates_2020" in body:
            cert = True
    except Exception:
        pass
    try:
        names = await page.evaluate(
            """() => {
              const out = [];
              for (const el of document.querySelectorAll(
                '.file-name, .filename, [class*="file"], [class*="document"], a[href*=".pdf"]'
              )) {
                const t = (el.innerText || el.textContent || '').trim();
                if (t) out.push(t);
              }
              return out.slice(0, 20);
            }"""
        )
        for n in names or []:
            low = (n or "").lower()
            if CV_NAME in low or "0021_cc_marti" in low or "0020_raw_marti" in low:
                cv = True
            if CERT_NAME in low or "certificates" in low:
                cert = True
    except Exception:
        pass
    return cv, cert


async def personio_submit(page, log_fn=None) -> bool:
    """Click Personio submit — scroll, force-enable, multi-strategy."""
    if not re.search(r"personio", page.url or "", re.I):
        return False

    def _log(msg: str):
        if log_fn:
            log_fn(msg)

    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(400)
    except Exception:
        pass

    selectors = [
        'button[data-test-id="submit-application"]',
        'button[data-testid="submit-application"]',
        'button.application-form__submit',
        'button[type=submit]:has-text("Submit")',
        'button[type=submit]:has-text("Send")',
        'button[type=submit]:has-text("Apply")',
        'button[type=submit]',
        'input[type=submit]',
    ]

    for sel in selectors:
        try:
            loc = page.locator(sel)
            n = await loc.count()
            for i in range(min(n, 3)):
                el = loc.nth(i)
                if not await el.is_visible(timeout=350):
                    continue
                try:
                    await el.scroll_into_view_if_needed(timeout=1000)
                except Exception:
                    pass
                try:
                    await el.click(timeout=2500)
                    _log("  ✓ Personio submit (click)")
                    await page.wait_for_timeout(3000)
                    return True
                except Exception:
                    try:
                        await el.click(force=True, timeout=2000)
                        _log("  ✓ Personio submit (force)")
                        await page.wait_for_timeout(3000)
                        return True
                    except Exception:
                        pass
        except Exception:
            continue

    try:
        clicked = await page.evaluate(
            """() => {
              const sels = [
                'button[data-test-id="submit-application"]',
                'button.application-form__submit',
                'button[type="submit"]',
              ];
              for (const s of sels) {
                const el = document.querySelector(s);
                if (!el) continue;
                el.removeAttribute('disabled');
                el.click();
                return s;
              }
              return null;
            }"""
        )
        if clicked:
            _log(f"  ✓ Personio submit (JS {clicked})")
            await page.wait_for_timeout(3000)
            return True
    except Exception:
        pass

    return False