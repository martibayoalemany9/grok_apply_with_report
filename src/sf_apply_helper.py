#!/usr/bin/env python3
"""SuccessFactors apply helpers via Playwright CDP (port 9222).

Candidate defaults (see candidate_prefs.json):
  - gender: Male / Man (user 2026-07-25)
  - school: Universitat Politècnica de Catalunya (UPC / ETSETB / BarcelonaTech)
  - EU work authorization: Yes; not a veteran; no disability
"""
from __future__ import annotations

import json
from pathlib import Path

WORKDIR = Path(__file__).resolve().parent
PREFS_PATH = WORKDIR / "candidate_prefs.json"

DEFAULT_PREFS = {
    "gender": "Male",
    "gender_aliases": [
        "Male",
        "Man",
        "Male (M)",
        "Männlich",
        "Maennlich",
        "Homme",
        "Masculino",
        "M",
    ],
    "university": "Universitat Politècnica de Catalunya",
    "university_aliases": [
        "Universitat Politècnica de Catalunya",
        "Universitat Politecnica de Catalunya",
        "Politecnica de Catalunya",
        "ETSETB",
        "BarcelonaTech",
        "Barcelona Tech",
        "UPC",
    ],
    "school_search_order": [
        "Universitat Politècnica de Catalunya",
        "Universitat Politecnica de Catalunya",
        "Politecnica de Catalunya",
        "ETSETB",
        "BarcelonaTech",
        "UPC",
    ],
}


def load_prefs() -> dict:
    if PREFS_PATH.exists():
        data = json.loads(PREFS_PATH.read_text())
        merged = {**DEFAULT_PREFS, **data}
        return merged
    PREFS_PATH.write_text(json.dumps(DEFAULT_PREFS, indent=2, ensure_ascii=False))
    return dict(DEFAULT_PREFS)


async def pick_combobox(page, aria_substr, option, exact=True):
    """Open SF paginated combobox and click matching role=option."""
    inp = page.locator(f'input[role=combobox][aria-label*="{aria_substr}" i]')
    btn = page.locator(f'button[aria-label*="{aria_substr}" i]')
    if await inp.count() == 0:
        return {"ok": False, "err": f"missing {aria_substr}"}
    await inp.first.scroll_into_view_if_needed()
    cur = (await inp.first.input_value()).strip()
    if exact and cur == option:
        return {"ok": True, "val": cur, "skipped": True}
    if not exact and option.lower() in cur.lower():
        return {"ok": True, "val": cur, "skipped": True}
    if await btn.count():
        await btn.first.click(force=True)
    else:
        await inp.first.click(force=True)
    await page.wait_for_timeout(800)
    opts = page.get_by_role("option", name=option, exact=exact)
    if await opts.count() == 0:
        opts = page.locator("ul.sf-list-select li[role=option], a[title]")
    for i in range(await opts.count()):
        t = (await opts.nth(i).inner_text()).strip()
        if t == option or (not exact and option.lower() in t.lower()):
            # Avoid Male/Female substring trap
            if option.lower() == "male" and t.lower() != "male":
                continue
            await opts.nth(i).click()
            break
    await page.wait_for_timeout(400)
    val = (await inp.first.input_value()).strip()
    return {"ok": val == option or (not exact and option.lower() in val.lower()), "val": val}


async def pick_by_input_id(page, input_id, option):
    prefix = input_id.split(":")[0]
    inp = page.locator(f'[id="{input_id}"]')
    btn = page.locator(f'[id="{prefix}:_selectButton"]')
    await inp.scroll_into_view_if_needed()
    if await btn.count():
        await btn.click(force=True)
    else:
        await inp.click(force=True)
    await page.wait_for_timeout(800)
    opts = page.locator("ul.sf-list-select li[role=option]")
    for i in range(await opts.count()):
        t = (await opts.nth(i).inner_text()).strip()
        if t == option:
            await opts.nth(i).click()
            break
    await page.wait_for_timeout(300)
    return await inp.input_value()


async def pick_first_match(page, aria_substr, option_list, exact=False):
    """Try options in order until one sticks."""
    prefs_options = option_list
    last = None
    for opt in prefs_options:
        last = await pick_combobox(page, aria_substr, opt, exact=exact)
        if last.get("ok"):
            return last
        # type-filter path for long school lists
        inp = page.locator(f'input[role=combobox][aria-label*="{aria_substr}" i]')
        btn = page.locator(f'button[aria-label*="{aria_substr}" i]')
        if await inp.count() == 0:
            continue
        if await btn.count():
            await btn.first.click(force=True)
        else:
            await inp.first.click(force=True)
        await page.wait_for_timeout(500)
        await inp.first.click(force=True)
        await page.keyboard.press("Meta+A")
        await page.keyboard.press("Backspace")
        await page.keyboard.type(opt[:50], delay=30)
        await page.wait_for_timeout(800)
        opts = page.locator("ul.sf-list-select li[role=option]")
        for i in range(await opts.count()):
            t = (await opts.nth(i).inner_text()).strip()
            if opt.lower() in t.lower() or t.lower() in opt.lower():
                if t and t != "No Selection":
                    await opts.nth(i).click()
                    await page.wait_for_timeout(400)
                    val = await inp.first.input_value()
                    return {"ok": True, "val": val, "matched": t, "from": opt}
    return last or {"ok": False}


async def apply_candidate_prefs(page):
    """Set gender + school from candidate_prefs.json on an open SF form/profile."""
    prefs = load_prefs()
    results = {}
    # Gender — Male / Man (exact first to avoid Female substring trap)
    gender_opts = prefs.get("gender_aliases") or [prefs.get("gender") or "Male"]
    results["gender"] = await pick_first_match(
        page,
        "gender",
        gender_opts,
        exact=True,
    )
    if not results["gender"].get("ok"):
        results["gender"] = await pick_first_match(
            page,
            "gender",
            gender_opts,
            exact=False,
        )
    # School / university
    results["school"] = await pick_first_match(
        page,
        "School",
        prefs.get("school_search_order") or prefs.get("university_aliases") or [prefs["university"]],
        exact=False,
    )
    return results
