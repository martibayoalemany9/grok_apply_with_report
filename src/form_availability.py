"""Fill 'available from' / start-date fields with today's date."""
from __future__ import annotations

import re
from datetime import date

TODAY = date.today()
AVAILABLE_FROM = {
    "iso": TODAY.isoformat(),
    "eu": TODAY.strftime("%d/%m/%Y"),
    "us": TODAY.strftime("%m/%d/%Y"),
    "de": TODAY.strftime("%d.%m.%Y"),
}

_AVAIL_HINT = re.compile(
    r"available|availability|start\s*date|earliest|notice\s*period|"
    r"when\s*can\s*you|join\s*date|commence|verfügbar|disponib",
    re.I,
)

_IMMEDIATE = re.compile(
    r"immediately|as soon as possible|right away|now|today|"
    r"sofort|ab sofort|dès que possible",
    re.I,
)


async def fill_availability(page, log_fn=None) -> int:
    """Set availability to today / immediately. Returns fields touched."""
    n = 0

    def _log(msg: str):
        if log_fn:
            log_fn(msg)

    # Dropdowns: prefer Immediately / As soon as possible
    try:
        for i in range(min(await page.locator("select").count(), 20)):
            sel = page.locator("select").nth(i)
            hint = (
                (await sel.get_attribute("name") or "")
                + (await sel.get_attribute("id") or "")
                + (await sel.get_attribute("aria-label") or "")
            )
            if not _AVAIL_HINT.search(hint):
                # also check nearby label text
                try:
                    lab = await sel.evaluate(
                        """e => {
                          const l = e.closest('label') || document.querySelector(`label[for='${e.id}']`);
                          return (l && l.innerText) || '';
                        }"""
                    )
                    if not _AVAIL_HINT.search(lab or ""):
                        continue
                except Exception:
                    continue
            opts = await sel.locator("option").all_inner_texts()
            for opt in opts:
                if _IMMEDIATE.search(opt or ""):
                    await sel.select_option(label=opt)
                    n += 1
                    _log(f"  ✓ availability select: {opt.strip()[:40]}")
                    break
    except Exception:
        pass

    # Date / text inputs
    date_formats = [AVAILABLE_FROM["iso"], AVAILABLE_FROM["de"], AVAILABLE_FROM["eu"], AVAILABLE_FROM["us"]]
    try:
        inputs = page.locator("input:visible")
        for i in range(min(await inputs.count(), 35)):
            el = inputs.nth(i)
            try:
                typ = (await el.get_attribute("type") or "text").lower()
                if typ not in ("text", "date", "tel", ""):
                    continue
                hint = (
                    (await el.get_attribute("name") or "")
                    + (await el.get_attribute("id") or "")
                    + (await el.get_attribute("placeholder") or "")
                    + (await el.get_attribute("aria-label") or "")
                ).lower()
                if not _AVAIL_HINT.search(hint):
                    continue
                val = AVAILABLE_FROM["iso"] if typ == "date" else AVAILABLE_FROM["de"]
                await el.fill(val, timeout=800)
                n += 1
                _log(f"  ✓ availability date: {val}")
            except Exception:
                continue
    except Exception:
        pass

    # get_by_label
    for lab_pat in [
        r"available from",
        r"availability",
        r"start date",
        r"earliest start",
        r"when can you start",
        r"notice period",
    ]:
        try:
            el = page.get_by_label(re.compile(lab_pat, re.I))
            if await el.count():
                field = el.first
                typ = (await field.get_attribute("type") or "text").lower()
                val = AVAILABLE_FROM["iso"] if typ == "date" else AVAILABLE_FROM["de"]
                await field.fill(val, timeout=800)
                n += 1
                _log(f"  ✓ availability ({lab_pat}): {val}")
        except Exception:
            continue

    return n