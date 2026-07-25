#!/usr/bin/env python3
"""Store privacy-policy pages to disk; screenshot job offers — do NOT keep reading policies in-browser.

Usage:
  # One-shot: archive open CDP tabs (privacy text + offer screenshots), close privacy tabs
  python privacy_offer_store.py --archive-cdp

  # Import helpers from apply scripts:
  from privacy_offer_store import is_privacy_url, archive_privacy_url, screenshot_offer, install_privacy_blocker
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

W = Path.home() / "deepline/data/karlsruhe-public-co-job-apps"
PRIVACY_DIR = W / "privacy_policies"
OFFER_DIR = W / "offer_screenshots"
INDEX = PRIVACY_DIR / "index.jsonl"

PRIVACY_URL_RE = re.compile(
    r"(privacy|candidate.?privacy|applicant.?privacy|/legal/|"
    r"terms.?of.?use|terms.?and.?conditions|cookie.?policy|"
    r"datenschutz|confidentialit|politique.?de.?confidentialit)",
    re.I,
)
OFFER_URL_RE = re.compile(
    r"(job|career|workday|greenhouse|lever|apply|gestmax|requisition|/jobs?/)",
    re.I,
)


def ensure_dirs():
    PRIVACY_DIR.mkdir(parents=True, exist_ok=True)
    OFFER_DIR.mkdir(parents=True, exist_ok=True)


def is_privacy_url(url: str, title: str = "") -> bool:
    blob = f"{url or ''} {title or ''}"
    return bool(PRIVACY_URL_RE.search(blob))


def is_offer_url(url: str, title: str = "") -> bool:
    if is_privacy_url(url, title):
        return False
    blob = f"{url or ''} {title or ''}"
    return bool(OFFER_URL_RE.search(blob))


def _slug(url: str) -> str:
    host = urlparse(url).netloc.replace("www.", "")[:40]
    h = hashlib.sha1(url.encode()).hexdigest()[:10]
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", f"{host}_{h}")[:80]


def archive_privacy_url(url: str, source_offer_url: str = "", title: str = "") -> Path | None:
    """Fetch privacy policy HTML/text once and save under privacy_policies/. No browser reading."""
    ensure_dirs()
    if not url or not url.startswith("http"):
        return None
    slug = _slug(url)
    txt_path = PRIVACY_DIR / f"{slug}.txt"
    meta_path = PRIVACY_DIR / f"{slug}.meta.json"
    # already stored
    if txt_path.exists() and txt_path.stat().st_size > 200:
        _index_append(
            {
                "url": url,
                "title": title,
                "source_offer_url": source_offer_url,
                "file": str(txt_path),
                "status": "already_cached",
                "ts": datetime.now().isoformat(timespec="seconds"),
            }
        )
        return txt_path
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8", errors="ignore")
            final = r.geturl()
    except Exception as e:
        txt_path.write_text(f"FETCH_FAILED\nurl={url}\nerror={e}\n", encoding="utf-8")
        _index_append(
            {
                "url": url,
                "title": title,
                "source_offer_url": source_offer_url,
                "file": str(txt_path),
                "status": f"fetch_failed: {e}",
                "ts": datetime.now().isoformat(timespec="seconds"),
            }
        )
        return txt_path

    # crude HTML → text (no full browser)
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", raw)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    header = (
        f"URL: {url}\nFINAL: {final}\nTITLE: {title}\n"
        f"SOURCE_OFFER: {source_offer_url}\n"
        f"SAVED: {datetime.now().isoformat(timespec='seconds')}\n"
        f"{'='*72}\n\n"
    )
    txt_path.write_text(header + text[:200000], encoding="utf-8")
    meta_path.write_text(
        json.dumps(
            {
                "url": url,
                "final_url": final,
                "title": title,
                "source_offer_url": source_offer_url,
                "chars": len(text),
                "saved": datetime.now().isoformat(timespec="seconds"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _index_append(
        {
            "url": url,
            "title": title,
            "source_offer_url": source_offer_url,
            "file": str(txt_path),
            "status": "saved",
            "chars": len(text),
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
    )
    return txt_path


def _index_append(row: dict):
    ensure_dirs()
    with INDEX.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


async def screenshot_offer(page, company: str = "", title: str = "") -> Path | None:
    """Screenshot current page as the job offer (not a privacy page)."""
    ensure_dirs()
    url = page.url or ""
    if is_privacy_url(url, await page.title()):
        return None
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", f"{company}_{title}")[:50] or "offer"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OFFER_DIR / f"{safe}_{ts}.png"
    try:
        await page.screenshot(path=str(path), full_page=False)
        meta = {
            "url": url,
            "title": await page.title(),
            "company": company,
            "job_title": title,
            "screenshot": str(path),
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        (path.with_suffix(".json")).write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return path
    except Exception:
        return None


async def install_privacy_blocker(context, offer_url_holder: dict | None = None):
    """On new pages: if privacy/legal URL → archive to disk and close tab; do not leave open for reading.

    offer_url_holder: optional dict with key 'url' updated by apply code for cross-ref.
    """
    ensure_dirs()

    async def on_page(page):
        async def check(_=None):
            try:
                url = page.url or ""
                title = ""
                try:
                    title = await page.title()
                except Exception:
                    pass
                if not is_privacy_url(url, title):
                    return
                # Never kill real job / ATS pages — only pure privacy/legal URLs
                if is_offer_url(url, title) or re.search(
                    r"job|career|apply|greenhouse|lever|workday|personio|"
                    r"efinancialcareers|ashby|smartrecruiters|icims",
                    url or "",
                    re.I,
                ):
                    return
                offer = (offer_url_holder or {}).get("url") or ""
                path = archive_privacy_url(url, source_offer_url=offer, title=title)
                print(f"  [privacy stored] {path}  (closing tab, not reading)", flush=True)
                try:
                    await page.close()
                except Exception:
                    pass
            except Exception as e:
                print(f"  [privacy handler] {e}", flush=True)

        def _schedule(_=None):
            asyncio.ensure_future(check())

        page.on("load", _schedule)
        page.on("framenavigated", _schedule)
        try:
            await page.wait_for_timeout(500)
            await check()
        except Exception:
            pass

    context.on("page", lambda p: asyncio.ensure_future(on_page(p)))


async def archive_cdp_now(cdp: str = "http://127.0.0.1:9222") -> dict:
    """One-shot: for open CDP tabs — save privacy text, screenshot offers, close privacy tabs."""
    from playwright.async_api import async_playwright

    ensure_dirs()
    stats = {"privacy_saved": 0, "privacy_closed": 0, "offers_shot": 0, "errors": []}
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp)
        ctx = browser.contexts[0] if browser.contexts else None
        if not ctx:
            return {"error": "no browser context"}
        pages = list(ctx.pages)
        # map offer urls first for cross-ref
        offer_urls = []
        for page in pages:
            try:
                u = page.url or ""
                t = await page.title()
                if is_offer_url(u, t):
                    offer_urls.append(u)
            except Exception:
                pass
        source_offer = offer_urls[0] if offer_urls else ""

        for page in pages:
            try:
                u = page.url or ""
                t = await page.title()
                if is_privacy_url(u, t):
                    archive_privacy_url(u, source_offer_url=source_offer, title=t)
                    stats["privacy_saved"] += 1
                    try:
                        await page.close()
                        stats["privacy_closed"] += 1
                    except Exception:
                        pass
                elif is_offer_url(u, t):
                    path = await screenshot_offer(page, company=urlparse(u).netloc, title=t[:40])
                    if path:
                        stats["offers_shot"] += 1
                        print(f"  [offer screenshot] {path}", flush=True)
            except Exception as e:
                stats["errors"].append(str(e)[:120])
    return stats


def filter_href_skip_privacy(href: str) -> bool:
    """Return True if apply code should NOT navigate to this href."""
    return is_privacy_url(href or "")


if __name__ == "__main__":
    import asyncio
    import sys

    if "--archive-cdp" in sys.argv:
        print("Archiving privacy tabs + screenshotting offers via CDP…", flush=True)
        stats = asyncio.run(archive_cdp_now())
        print(json.dumps(stats, indent=2), flush=True)
        print(f"Privacy dir: {PRIVACY_DIR}", flush=True)
        print(f"Offer screenshots: {OFFER_DIR}", flush=True)
    else:
        print("Usage: python privacy_offer_store.py --archive-cdp")
