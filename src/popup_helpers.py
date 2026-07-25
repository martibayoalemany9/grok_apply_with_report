"""Shared popup dismiss helpers for job apply automation.

Always skip NordVPN prompts by pressing Continue / Continue to website.
Never navigate to privacy policy / Terms of Use pages — archive offline instead.
"""
from __future__ import annotations

import asyncio
import re

_DIALOG_HOOKED: set[int] = set()

from privacy_offer_store import archive_privacy_url, filter_href_skip_privacy, is_privacy_url


def should_skip_legal_link(href: str = "", name: str = "") -> bool:
    """True for privacy policy, Terms of Use, cookie policy, /legal/ URLs."""
    return filter_href_skip_privacy(href or "") or is_privacy_url(href or "", name or "")


async def leave_legal_page(page, log_fn=None, source_offer_url: str = "") -> bool:
    """If the tab landed on a legal/privacy page, archive it and go back."""
    try:
        url = page.url or ""
        title = await page.title()
        if not is_privacy_url(url, title):
            return False
        archive_privacy_url(url, source_offer_url=source_offer_url, title=title)
        if log_fn:
            log_fn(f"  legal page not opened → back ({title[:40] or url[:50]})")
        try:
            await page.go_back(timeout=12000)
            await page.wait_for_timeout(700)
        except Exception:
            pass
        return True
    except Exception:
        return False


async def skip_nordvpn(page) -> bool:
    """If NordVPN threat-protection / interstitial is showing, press Continue.

    Returns True if a NordVPN control was clicked.
    """
    try:
        url = (page.url or "").lower()
    except Exception:
        url = ""

    nord_visible = "nordvpn" in url or "nord-vpn" in url
    if not nord_visible:
        try:
            # extension interstitials / overlays often include brand text
            loc = page.locator("text=/Nord\\s*VPN/i")
            if await loc.count():
                nord_visible = True
        except Exception:
            pass
    if not nord_visible:
        try:
            body = (await page.inner_text("body", timeout=800)).lower()
            if "nordvpn" in body or "threat protection" in body or "nord security" in body:
                nord_visible = True
        except Exception:
            pass

    # Even without brand text, try highly-specific Nord-style continue CTAs first
    continue_pats = [
        r"Continue to (the )?website",
        r"Continue to site",
        r"Visit (this )?website",
        r"Proceed to (the )?website",
        r"Proceed anyway",
        r"Access website",
        r"^Continue$",
    ]

    async def _click_pat(pat: str) -> bool:
        for role in ("button", "link", "a"):
            try:
                if role in ("button", "link"):
                    loc = page.get_by_role(role, name=re.compile(pat, re.I))
                else:
                    loc = page.locator(f'a:has-text("Continue"), button:has-text("Continue")')
                n = await loc.count()
                for i in range(min(n, 4)):
                    el = loc.nth(i)
                    if await el.is_visible(timeout=350):
                        await el.click(timeout=900)
                        try:
                            await page.wait_for_timeout(600)
                        except Exception:
                            pass
                        return True
            except Exception:
                continue
        # CSS fallbacks
        for sel in [
            'button:has-text("Continue to website")',
            'button:has-text("Continue to the website")',
            'a:has-text("Continue to website")',
            'button:has-text("Continue")',
            'a:has-text("Continue")',
            '[data-testid*="continue" i]',
            'button.continue',
            "#continue-button",
        ]:
            try:
                loc = page.locator(sel)
                if await loc.count() and await loc.first.is_visible(timeout=300):
                    # Only use bare "Continue" if NordVPN is visible (avoid job form Next/Continue)
                    if sel in ('button:has-text("Continue")', 'a:has-text("Continue")') and not nord_visible:
                        continue
                    await loc.first.click(timeout=900)
                    try:
                        await page.wait_for_timeout(600)
                    except Exception:
                        pass
                    return True
            except Exception:
                continue
        return False

    # Prefer specific website-continue phrases always (safe on job forms)
    for pat in continue_pats[:-1]:  # all except bare ^Continue$
        if await _click_pat(pat):
            return True

    # Bare Continue only when NordVPN context detected
    if nord_visible:
        if await _click_pat(r"^Continue$"):
            return True
        # also try Escape then Continue once more
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

    return False


def install_dialog_handler(page) -> None:
    """Accept JS alerts/confirms so Playwright does not crash on race dismiss."""
    pid = id(page)
    if pid in _DIALOG_HOOKED:
        return
    _DIALOG_HOOKED.add(pid)

    async def _accept(dialog):
        try:
            await dialog.accept()
        except Exception:
            try:
                await dialog.dismiss()
            except Exception:
                pass

    def _on_dialog(dialog):
        asyncio.create_task(_accept(dialog))

    try:
        page.on("dialog", _on_dialog)
    except Exception:
        pass


async def _dismiss_usercentrics(page) -> bool:
    """Usercentrics CMP (#usercentrics-cmp-ui) often intercepts Apply clicks."""
    # 1) Click accept in light DOM / frames
    for sel in [
        '#usercentrics-cmp-ui button',
        'button[data-testid*="uc-accept" i]',
        'button[id*="uc-btn" i]',
        '[data-action="consent"] button',
        'button:has-text("Accept All")',
        'button:has-text("Accept all")',
        'button:has-text("Allow all")',
        'button:has-text("Alles akzeptieren")',
    ]:
        try:
            loc = page.locator(sel)
            if await loc.count() and await loc.first.is_visible(timeout=250):
                await loc.first.click(timeout=800, force=True)
                await page.wait_for_timeout(300)
                return True
        except Exception:
            continue

    # 2) Shadow-DOM walk + hard remove/disable overlay (CMP re-injects otherwise)
    try:
        acted = await page.evaluate(
            """() => {
              const labels = /accept all|allow all|alles akzeptieren|tout accepter|aceptar todas|agree|zustimmen|einverstanden|save settings|confirm/i;
              let clicked = false;
              const walk = (node, depth) => {
                if (!node || depth > 12) return;
                if (node.shadowRoot) walk(node.shadowRoot, depth + 1);
                let els = [];
                try { els = node.querySelectorAll ? [...node.querySelectorAll('button, [role="button"], a')] : []; } catch (e) {}
                for (const el of els) {
                  const t = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
                  if (labels.test(t)) {
                    try { el.click(); clicked = true; } catch (e) {}
                  }
                }
                try {
                  for (const c of (node.children || [])) walk(c, depth + 1);
                } catch (e) {}
              };
              walk(document, 0);
              // Always neuter CMP overlays so they cannot steal clicks
              const kill = (sel) => {
                document.querySelectorAll(sel).forEach((el) => {
                  try {
                    el.style.setProperty('display', 'none', 'important');
                    el.style.setProperty('pointer-events', 'none', 'important');
                    el.style.setProperty('visibility', 'hidden', 'important');
                    el.setAttribute('aria-hidden', 'true');
                  } catch (e) {}
                });
              };
              kill('#usercentrics-cmp-ui');
              kill('[id*="usercentrics"]');
              kill('[class*="usercentrics"]');
              kill('#usercentrics-root');
              kill('aside[data-nosnippet]');
              kill('[class*="cookie"][class*="banner"]');
              kill('[id*="cookie"][class*="banner"]');
              kill('#onetrust-banner-sdk');
              kill('.osano-cm-window');
              return clicked || true;
            }"""
        )
        if acted:
            await page.wait_for_timeout(250)
            return True
    except Exception:
        pass
    return False


async def _dismiss_blocking_modals(page) -> bool:
    """Close overlays that steal clicks (eFC application-status, generic modals).

    eFinancialCareers often shows modal-container.application-status over Apply Now;
    Playwright then times out on click. Close via button / Escape / pointer-events kill.
    """
    acted = False
    # Prefer explicit close controls first
    for sel in [
        'modal-container.modal.show button.close',
        'modal-container.modal.show [aria-label="Close"]',
        'modal-container.modal.show [aria-label="close"]',
        'modal-container.modal.show button[class*="close" i]',
        '.modal.show button.close',
        '.modal.show [data-dismiss="modal"]',
        '.modal.show [data-bs-dismiss="modal"]',
        '[class*="application-status"] button.close',
        'button:has-text("Close")',
        'button:has-text("Not now")',
        'button:has-text("No thanks")',
        'button:has-text("Maybe later")',
        'button:has-text("Dismiss")',
        'button:has-text("OK")',
        'button:has-text("Got it")',
    ]:
        try:
            loc = page.locator(sel)
            n = await loc.count()
            for i in range(min(n, 3)):
                el = loc.nth(i)
                if await el.is_visible(timeout=200):
                    await el.click(timeout=700, force=True)
                    acted = True
                    await page.wait_for_timeout(200)
                    break
            if acted:
                break
        except Exception:
            continue

    # Escape often closes bootstrap/ng-bootstrap modals
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(150)
        await page.keyboard.press("Escape")
    except Exception:
        pass

    # Hard-disable remaining modal backdrops so Apply can receive clicks
    try:
        await page.evaluate(
            """() => {
              const kill = (sel) => {
                document.querySelectorAll(sel).forEach((el) => {
                  try {
                    el.style.setProperty('pointer-events', 'none', 'important');
                    // keep visible status text if any, but do not intercept
                    if (el.matches && (
                      el.matches('modal-container') ||
                      el.matches('.modal-backdrop') ||
                      el.classList.contains('modal-backdrop') ||
                      (el.className && String(el.className).includes('application-status'))
                    )) {
                      el.style.setProperty('display', 'none', 'important');
                      el.setAttribute('aria-hidden', 'true');
                      el.classList.remove('show');
                    }
                  } catch (e) {}
                });
              };
              kill('modal-container.modal.show');
              kill('modal-container');
              kill('.modal-backdrop');
              kill('.modal.show');
              kill('[class*="application-status"]');
              document.body && document.body.classList.remove('modal-open');
              document.documentElement && document.documentElement.classList.remove('modal-open');
              return true;
            }"""
        )
        acted = True
    except Exception:
        pass
    return acted


async def dismiss_cookies_and_vpn(page) -> None:
    """Dismiss cookie banners and always try to skip NordVPN."""
    # NordVPN first — it blocks the whole page
    try:
        await skip_nordvpn(page)
    except Exception:
        pass

    try:
        await _dismiss_usercentrics(page)
    except Exception:
        pass

    try:
        await _dismiss_blocking_modals(page)
    except Exception:
        pass

    for sel in [
        "#onetrust-accept-btn-handler",
        "#didomi-notice-agree-button",
        "#usercentrics-root",
        'button:has-text("Accept all")',
        'button:has-text("Accept All")',
        'button:has-text("Accept cookies")',
        'button:has-text("Allow all")',
        'button:has-text("I agree")',
        'button:has-text("Agree")',
        'button:has-text("Got it")',
        'button:has-text("Only necessary")',
        'button:has-text("Alles akzeptieren")',
        'button:has-text("Tout accepter")',
        'button:has-text("Aceptar todas")',
        'button:has-text("Accepteren")',
        'button:has-text("Alle akzeptieren")',
        'button:has-text("Zustimmen")',
    ]:
        try:
            loc = page.locator(sel)
            if await loc.count() and await loc.first.is_visible(timeout=350):
                await loc.first.click(timeout=600, force=True)
                break
        except Exception:
            pass

    # Second NordVPN / modal pass after cookies (overlay order varies)
    try:
        await skip_nordvpn(page)
    except Exception:
        pass
    try:
        await _dismiss_blocking_modals(page)
    except Exception:
        pass
