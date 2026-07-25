"""Fill US-style EEO / voluntary self-ID + EU work-auth fields from candidate prefs.

Defaults (user 2026-07-25):
  - Gender: Male / Man
  - Race/ethnicity: White
  - Protected veteran: No / I am not a protected veteran
  - Disability: No
  - EU work authorization: Yes
"""
from __future__ import annotations

import json
import re
from pathlib import Path

W = Path(__file__).resolve().parent
PREFS = W / "candidate_prefs.json"

# Gender option text that must never be chosen (Female contains "male" as substring).
_GENDER_REJECT = re.compile(
    r"female|woman|non[- ]?binary|intersex|prefer not|decline|refuse|"
    r"self.?identif|other|trans|diverse|divers",
    re.I,
)
_GENDER_ACCEPT = re.compile(
    r"^(male|man|m|männlich|maennlich|homme|masculino|"
    r"male\s*\(?m\)?|male\s*/\s*man|i am a man)$",
    re.I,
)


def _prefs() -> dict:
    try:
        return json.loads(PREFS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _eeo() -> dict:
    return (_prefs().get("eeo") or {})


def _gender_aliases() -> list[str]:
    p = _prefs()
    return list(
        p.get("gender_aliases")
        or ["Male", "Man", "Männlich", "Homme", "Masculino"]
    )


def _work_auth() -> dict:
    return (_prefs().get("work_authorization") or {})


def _is_male_option(text: str) -> bool:
    t = (text or "").strip()
    if not t or _GENDER_REJECT.search(t):
        return False
    if _GENDER_ACCEPT.search(t):
        return True
    # Alias list (exact / contained carefully)
    low = t.lower()
    for a in _gender_aliases():
        al = (a or "").strip().lower()
        if not al:
            continue
        if low == al:
            return True
        # avoid Female matching Male
        if al == "male" and low != "male":
            continue
        if al in low and "female" not in low and "woman" not in low:
            # only accept short exact-ish matches
            if low in ("male", "man", "m", "männlich", "maennlich", "homme", "masculino"):
                return True
    return False


async def _select_matching(page, patterns: list[str], log_fn=None, limit_selects: int = 25) -> int:
    """Pick first matching option across selects (label or value text)."""
    n = 0
    if not patterns:
        return 0
    rx = re.compile("|".join(f"(?:{p})" for p in patterns), re.I)
    try:
        sels = page.locator("select")
        count = min(await sels.count(), limit_selects)
        for i in range(count):
            s = sels.nth(i)
            try:
                opts = await s.locator("option").all_inner_texts()
                for o in opts:
                    if o and rx.search(o.strip()):
                        await s.select_option(label=o)
                        n += 1
                        if log_fn:
                            log_fn(f"  ✓ EEO select: {o.strip()[:70]}")
                        break
            except Exception:
                continue
    except Exception:
        pass
    # role=option clicks (custom dropdowns)
    for pat in patterns[:6]:
        try:
            opt = page.get_by_role("option", name=re.compile(pat, re.I))
            if await opt.count():
                await opt.first.click(timeout=800)
                n += 1
                if log_fn:
                    log_fn(f"  ✓ EEO option: {pat[:50]}")
                break
        except Exception:
            continue
    # radio by label
    for pat in patterns[:8]:
        try:
            lab = page.get_by_label(re.compile(pat, re.I))
            if await lab.count():
                el = lab.first
                tag = (await el.evaluate("e => (e.tagName||'').toLowerCase()")).lower()
                typ = (await el.get_attribute("type") or "").lower()
                if tag == "input" and typ in ("radio", "checkbox"):
                    await el.check(timeout=600)
                    n += 1
                    if log_fn:
                        log_fn(f"  ✓ EEO radio/check: {pat[:50]}")
                    break
        except Exception:
            continue
    return n


async def _fill_gender_male(page, log_fn=None) -> int:
    """Select Male/Man carefully (never Female)."""
    n = 0
    try:
        sels = page.locator("select")
        for i in range(min(await sels.count(), 25)):
            s = sels.nth(i)
            try:
                opts = await s.locator("option").all_inner_texts()
                for o in opts:
                    if _is_male_option(o):
                        await s.select_option(label=o)
                        n += 1
                        if log_fn:
                            log_fn(f"  ✓ gender select: {o.strip()[:50]}")
                        break
            except Exception:
                continue
    except Exception:
        pass

    # Custom dropdown options
    for label in _gender_aliases() + ["Male", "Man", "Männlich", "Homme", "Masculino"]:
        try:
            opt = page.get_by_role("option", name=re.compile(rf"^{re.escape(label)}$", re.I))
            if await opt.count():
                txt = (await opt.first.inner_text()).strip()
                if _is_male_option(txt) or _is_male_option(label):
                    await opt.first.click(timeout=800)
                    n += 1
                    if log_fn:
                        log_fn(f"  ✓ gender option: {label}")
                    break
        except Exception:
            continue

    # Radios / labels
    for pat in [
        r"^Male$",
        r"^Man$",
        r"^Männlich$",
        r"^Homme$",
        r"^Masculino$",
        r"I am a man",
    ]:
        try:
            lab = page.get_by_label(re.compile(pat, re.I))
            if await lab.count():
                el = lab.first
                tag = (await el.evaluate("e => (e.tagName||'').toLowerCase()")).lower()
                typ = (await el.get_attribute("type") or "").lower()
                if tag == "input" and typ in ("radio", "checkbox"):
                    await el.check(timeout=600)
                    n += 1
                    if log_fn:
                        log_fn(f"  ✓ gender radio: {pat}")
                    break
        except Exception:
            continue
    return n


async def _fill_eu_work_auth(page, log_fn=None) -> int:
    """Answer Yes to EU / authorized-to-work questions; No to EU sponsorship when asked."""
    n = 0
    wa = _work_auth()
    if (wa.get("eu") or "Yes").lower() not in ("yes", "y", "true", "1"):
        return 0

    # Authorized to work in EU / Germany / EEA — prefer Yes
    auth_labels = [
        r"authorized to work (in )?(the )?(eu|eea|european|germany|deutschland|europe)",
        r"legally (authorized|entitled|permitted) to work",
        r"right to work (in )?(the )?(eu|eea|germany|europe)",
        r"work authorization",
        r"do you have (the )?(legal )?permission to work",
        r"eligible to work",
        r"arbeitserlaubnis|berechtigt.*arbeiten|aufenthalts",
    ]
    for lab in auth_labels:
        try:
            # Prefer Yes radio near the label
            group = page.get_by_label(re.compile(lab, re.I))
            if await group.count():
                el = group.first
                typ = (await el.get_attribute("type") or "").lower()
                # if it's a yes/no select
                tag = (await el.evaluate("e => (e.tagName||'').toLowerCase()")).lower()
                if tag == "select":
                    for opt_label in ["Yes", "Ja", "Oui", "Sí", "Si"]:
                        try:
                            await el.select_option(label=opt_label)
                            n += 1
                            if log_fn:
                                log_fn(f"  ✓ work auth select Yes ({lab[:40]})")
                            break
                        except Exception:
                            continue
                elif typ in ("radio", "checkbox"):
                    # if label itself is the Yes control
                    name = (await el.get_attribute("name") or "")
                    val = (await el.get_attribute("value") or "").lower()
                    if val in ("yes", "true", "1", "y", "ja"):
                        await el.check(timeout=600)
                        n += 1
                        if log_fn:
                            log_fn(f"  ✓ work auth radio Yes")
                    elif name:
                        yes = page.locator(
                            f'input[type=radio][name="{name}"][value="Yes"], '
                            f'input[type=radio][name="{name}"][value="yes"], '
                            f'input[type=radio][name="{name}"][value="true"]'
                        )
                        if await yes.count():
                            await yes.first.check(timeout=600)
                            n += 1
                            if log_fn:
                                log_fn(f"  ✓ work auth radio Yes (name={name[:30]})")
        except Exception:
            continue

    # Also scan selects whose hint mentions authorization
    try:
        for i in range(min(await page.locator("select").count(), 25)):
            s = page.locator("select").nth(i)
            hint = (
                (await s.get_attribute("name") or "")
                + (await s.get_attribute("id") or "")
                + (await s.get_attribute("aria-label") or "")
            )
            if not re.search(
                r"authoriz|work.?permit|right.?to.?work|eligible.?to.?work|"
                r"sponsorship|visa|arbeits",
                hint,
                re.I,
            ):
                continue
            opts = await s.locator("option").all_inner_texts()
            # sponsorship questions: No for EU (user has permission)
            if re.search(r"sponsor", hint, re.I) and (wa.get("require_sponsorship_eu") or "No").lower() in (
                "no",
                "n",
                "false",
                "0",
            ):
                for o in opts:
                    if re.search(r"^no\b|do not require|not require|keine", o or "", re.I):
                        try:
                            await s.select_option(label=o)
                            n += 1
                            if log_fn:
                                log_fn(f"  ✓ sponsorship EU: {o.strip()[:50]}")
                            break
                        except Exception:
                            continue
            else:
                for o in opts:
                    if re.search(r"^yes\b|^ja\b|authorized|eligible", o or "", re.I) and not re.search(
                        r"not |no ", o or "", re.I
                    ):
                        try:
                            await s.select_option(label=o)
                            n += 1
                            if log_fn:
                                log_fn(f"  ✓ work auth: {o.strip()[:50]}")
                            break
                        except Exception:
                            continue
    except Exception:
        pass

    return n


async def fill_eeo(page, log_fn=None) -> int:
    """Fill gender Male, race, veteran No, disability No, EU work auth Yes. Returns fields touched."""
    eeo = _eeo()
    n = 0

    # Gender — Male / Man (user 2026-07-25)
    n += await _fill_gender_male(page, log_fn=log_fn)

    # Race / ethnicity — White
    race_pats = list(eeo.get("race_aliases") or []) + [
        r"^White$",
        r"White \(Not Hispanic",
        r"White \(Not Hispanic or Latino\)",
        r"Caucasian",
    ]
    n += await _select_matching(
        page,
        [re.escape(x) if x and x[0].isalnum() else x for x in race_pats if x],
        log_fn=log_fn,
    )
    n += await _select_matching(page, [r"White \(Not Hispanic or Latino\)", r"^White$"], log_fn=log_fn)

    # Hispanic/Latino — No when present
    n += await _select_matching(
        page,
        [r"No,?\s*I am not Hispanic", r"^No$", r"Not Hispanic or Latino"],
        log_fn=log_fn,
    )

    # Protected veteran — NOT a veteran
    n += await _select_matching(
        page,
        [
            r"I am not a protected veteran",
            r"I am not a protected veteran \(I have never served",
            r"Not a Protected Veteran",
            r"I am not a veteran",
            r"I have never served",
        ],
        log_fn=log_fn,
    )
    if n == 0:
        vet_pats = list(eeo.get("veteran_aliases") or [])
        n += await _select_matching(
            page,
            [re.escape(x) if x and x[0].isalnum() else x for x in vet_pats if x],
            log_fn=log_fn,
        )

    # Disability — No
    n += await _select_matching(
        page,
        [
            r"No, I do not have a disability and have not had one in the past",
            r"No, I don'?t have a disability",
            r"I do not have a disability",
            r"No disability",
            r"^No$",
        ],
        log_fn=log_fn,
    )

    # EU work authorization — Yes
    n += await _fill_eu_work_auth(page, log_fn=log_fn)

    return n
