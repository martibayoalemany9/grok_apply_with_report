"""Fill place of residence / city / country fields — always City, Germany."""
from __future__ import annotations

import re

from candidate_profile import PROFILE

RESIDENCE_CITY = PROFILE.get("residence") or PROFILE["city"]
RESIDENCE_COUNTRY = PROFILE.get("residence_country") or PROFILE["country"]

_CITY_HINT = re.compile(
    r"residence|wohnort|domicile|wohnstadt|current\s*city|city\s*of\s*residence|"
    r"place\s*of\s*residence|where\s*do\s*you\s*live|home\s*city|"
    r"stadt|ort|ville|town|city|address.*city",
    re.I,
)

_COUNTRY_HINT = re.compile(
    r"country\s*of\s*residence|residence\s*country|wohnland|domicile|"
    r"nationality|country|land|pays",
    re.I,
)

_SKIP_CITY = re.compile(r"job|work|employer|company|office|posting|vacancy", re.I)


async def fill_residence(page, log_fn=None) -> int:
    """Set place of residence to City (and Germany for country fields)."""
    n = 0

    def _log(msg: str):
        if log_fn:
            log_fn(msg)

    try:
        inputs = page.locator("input:visible, textarea:visible")
        for i in range(min(await inputs.count(), 45)):
            el = inputs.nth(i)
            try:
                typ = (await el.get_attribute("type") or "text").lower()
                if typ in ("hidden", "submit", "button", "checkbox", "radio", "file", "image"):
                    continue
                hint = (
                    (await el.get_attribute("name") or "")
                    + (await el.get_attribute("id") or "")
                    + (await el.get_attribute("placeholder") or "")
                    + (await el.get_attribute("aria-label") or "")
                )
                low = hint.lower()
                if any(x in low for x in ["phone", "tel", "mobile", "handy"]):
                    continue
                if _COUNTRY_HINT.search(hint) and "city" not in low and "ort" not in low:
                    await el.fill(RESIDENCE_COUNTRY, timeout=800)
                    n += 1
                    _log(f"  ✓ residence country: {RESIDENCE_COUNTRY}")
                    continue
                if _CITY_HINT.search(hint) and not _SKIP_CITY.search(hint):
                    await el.fill(RESIDENCE_CITY, timeout=800)
                    n += 1
                    _log(f"  ✓ place of residence: {RESIDENCE_CITY}")
            except Exception:
                continue
    except Exception:
        pass

    for lab_pat, val in [
        (r"place of residence", RESIDENCE_CITY),
        (r"city of residence", RESIDENCE_CITY),
        (r"current residence", RESIDENCE_CITY),
        (r"residence city", RESIDENCE_CITY),
        (r"wohnort", RESIDENCE_CITY),
        (r"^City$|^Town$|^Ort$|^Ville$|^Stadt$", RESIDENCE_CITY),
        (r"country of residence", RESIDENCE_COUNTRY),
        (r"^Country$|^Land$|^Pays$", RESIDENCE_COUNTRY),
    ]:
        try:
            el = page.get_by_label(re.compile(lab_pat, re.I))
            if await el.count():
                await el.first.fill(val, timeout=800)
                n += 1
                _log(f"  ✓ {lab_pat}: {val}")
        except Exception:
            continue

    # Country <select>
    try:
        for i in range(min(await page.locator("select").count(), 20)):
            sel = page.locator("select").nth(i)
            hint = (
                (await sel.get_attribute("name") or "")
                + (await sel.get_attribute("id") or "")
                + (await sel.get_attribute("aria-label") or "")
            )
            low = hint.lower()
            if any(x in low for x in ["phone", "tel", "mobile", "handy", "countryphonecode"]):
                continue
            if not _COUNTRY_HINT.search(hint):
                continue
            for label in [RESIDENCE_COUNTRY, "Germany", "DE", "Deutschland"]:
                try:
                    await sel.select_option(label=label)
                    n += 1
                    _log(f"  ✓ residence country select: {label}")
                    break
                except Exception:
                    continue
    except Exception:
        pass

    return n