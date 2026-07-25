#!/usr/bin/env python3
"""Complete applications in YOUR Chrome — announce each SUCCESS by name before next.

Focus: actually finish forms (upload CV, fill fields, submit), not just open pages.

Sources: applications_jobboards.csv (eurotechjobs / space-careers / euroengineerjobs)
Docs: 0021_cc CV + certificates compressed | €70.4k–€120k professional (no Praktikum/facility) | NordVPN Continue skip
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright

from candidate_profile import CERTS, CV, PROFILE, pick_first_name
from role_filter import is_never_apply, is_target_role, skip_reason
from form_availability import fill_availability
from form_residence import fill_residence
from personio_helpers import personio_submit
from popup_helpers import leave_legal_page, should_skip_legal_link
from privacy_offer_store import archive_privacy_url, install_privacy_blocker, is_privacy_url
from upload_helpers import attach_documents, clear_upload_state

OFFER_URL_HOLDER: dict[str, str] = {"url": ""}

W = Path.home() / "deepline/data/karlsruhe-public-co-job-apps"
PAUSE = W / ".APPLICATIONS_PAUSED"
SHOT = W / "screenshots"
SHOT.mkdir(exist_ok=True)

# Default: dedicated Playwright Chromium on :9223 (not personal Gmail Chrome :9222)
try:
    from cdp_helpers import default_cdp_url as _default_cdp_url

    CDP = __import__("os").environ.get("CDP_URL", "").strip() or _default_cdp_url()
except Exception:
    CDP = __import__("os").environ.get("CDP_URL", "http://127.0.0.1:9223").strip()
_QUEUE_OVERRIDE = __import__("os").environ.get("COMPLETE_QUEUE_CSV", "").strip()
QUEUE_CSV = W / "applications_jobboards.csv"
RESOLVED_CSV = (
    Path(_QUEUE_OVERRIDE)
    if _QUEUE_OVERRIDE and Path(_QUEUE_OVERRIDE).is_absolute()
    else (W / _QUEUE_OVERRIDE if _QUEUE_OVERRIDE else W / "applications_resolved_ats.csv")
)
OUT_JSON = W / "complete_apply_results.json"
OUT_CSV = W / "applications_complete_apply.csv"
SUCCESS_MD = W / "succeeded_applications.md"
# One application at a time by default (user 2026-07-25) — raise COMPLETE_MAX only with multi-window fullscreen
MAX = int(__import__("os").environ.get("COMPLETE_MAX", "1"))
SKIP_WORKDAY = __import__("os").environ.get("SKIP_WORKDAY", "").lower() in ("1", "true", "yes")
RETRY_UNCLOSED = __import__("os").environ.get("RETRY_UNCLOSED", "").lower() in ("1", "true", "yes")
APPLY_ALL = __import__("os").environ.get("APPLY_ALL", "").lower() in ("1", "true", "yes")
ONE_PER_COMPANY = __import__("os").environ.get("ONE_PER_COMPANY", "").lower() in ("1", "true", "yes")
DWELL_SEC = int(__import__("os").environ.get("DWELL_SEC", "60"))
COMMIT_SEC = int(__import__("os").environ.get("COMMIT_SEC", "45"))
# Hard cap per application (user: skip if more than 5 minutes)
PER_APP_MAX_SEC = int(__import__("os").environ.get("PER_APP_MAX_SEC", "300"))
# After stuck is detected, keep trying this many more seconds before giving up
GIVE_UP_GRACE_SEC = int(__import__("os").environ.get("GIVE_UP_GRACE_SEC", "60"))
# Pause before navigating / reopening the next application URL
REOPEN_GAP_SEC = int(__import__("os").environ.get("REOPEN_GAP_SEC", "10"))
# Same website behaviour with zero progress → skip after N consecutive identical rounds
STUCK_SAME_BEHAVIOUR = int(__import__("os").environ.get("STUCK_SAME_BEHAVIOUR", "2"))
_FORCE = __import__("os").environ.get("FORCE_RETRY", "") or __import__("os").environ.get(
    "STRATEGY_FORCE_RETRY", ""
)
FORCE_RETRY = _FORCE.lower() in ("1", "true", "yes")
CV_RETRY_ONLY = __import__("os").environ.get("CV_RETRY_ONLY", "").lower() in ("1", "true", "yes")
# Default ON: never re-open companies/URLs that already failed (open_only / exception / …)
_SPF = __import__("os").environ.get("SKIP_PRIOR_FAILS", "1")
SKIP_PRIOR_FAILS = _SPF.lower() in ("1", "true", "yes")
# Default OFF: user asked to remove chatbots from applications (2026-07-18)
_UCB = __import__("os").environ.get("USE_CHATBOT", "0")
USE_CHATBOT = _UCB.lower() in ("1", "true", "yes")
GOOD_ATS_RE = re.compile(
    r"ashbyhq|greenhouse|grnh\.se|job-boards\.(eu\.)?greenhouse|personio|"
    r"teamtailor|gestmax|workable\.com|lever\.co|smartrecruiters|bamboohr|"
    r"icims\.com",
    re.I,
)
# Hosts that repeatedly stuck with zero success (measured 2026-07-25) — skip unless FORCE_RETRY
# Also user URI/company blacklist (abacus-nachhilfe hard-banned in role_filter.NEVER_APPLY too)
DEAD_HOST_RE = re.compile(
    r"www\.basf\.com|careers\.db\.com|career\.heidelbergmaterials\.com|"
    r"www\.mercedes-benz\.com|www\.bechtle\.com|p3-group\.com|"
    r"www\.enbw\.com|www\.initse\.com|www\.grenke\.com|www\.durr\.com|"
    r"www\.daimlertruck\.com|www\.porsche\.com|shoplevers\.com|"
    r"careers\.criteo\.com|www\.mozilla\.org|"
    r"(?:www\.)?abacus-nachhilfe\.de|abacus[- ]?nachhilfe",
    re.I,
)
# Fail-fast: no form elements + no progress → treat as stuck after this many rounds
STUCK_NO_FORM_ROUNDS = int(__import__("os").environ.get("STUCK_NO_FORM_ROUNDS", "1"))
_SKIP = __import__("os").environ.get("SKIP_ATTEMPTED", "")
SKIP_ATTEMPTED = (
    _SKIP.lower() in ("1", "true", "yes")
    if _SKIP
    else ONE_PER_COMPANY
)

BOARD_RE = re.compile(
    r"eurotechjobs|space-careers|euroengineerjobs|europharmajobs|eurosciencejobs|"
    r"efinancialcareers|spmailtechnolo\.com",
    re.I,
)
JOB_CLOSED_RE = re.compile(
    r"job not found|no longer (available|accepting)|position (has been )?(filled|closed)|"
    r"this (job|position|posting) (is )?(closed|filled|expired)|"
    r"not accepting applications|vacancy (closed|filled)|"
    r"requisition (is )?closed|offre pourvue",
    re.I,
)
SUCCESS_RE = re.compile(
    r"(application has been sent|successfully applied|thank you for applying|"
    r"thanks for applying|application received|application submitted|"
    r"we('ve| have) received your application|already applied|"
    r"your application has been|application complete|thanks for your application|"
    r"bewerbung eingegangen|vielen dank für ihre bewerbung|"
    r"merci pour votre candidature|candidatura enviada|we received your application)",
    re.I,
)


def log(msg: str = ""):
    print(msg, flush=True)


async def dismiss(page):
    try:
        from popup_helpers import dismiss_cookies_and_vpn

        await dismiss_cookies_and_vpn(page)
    except Exception:
        for sel in [
            'button:has-text("Continue to website")',
            'button:has-text("Continue to the website")',
            'button:has-text("Continue")',
            "#onetrust-accept-btn-handler",
            'button:has-text("Accept all")',
            'button:has-text("Accept All")',
        ]:
            try:
                loc = page.locator(sel)
                if await loc.count() and await loc.first.is_visible(timeout=300):
                    # bare Continue only if nordvpn likely
                    if sel.endswith('"Continue")'):
                        try:
                            b = (await page.inner_text("body", timeout=300)).lower()
                            if "nordvpn" not in b and "threat" not in b:
                                continue
                        except Exception:
                            continue
                    await loc.first.click(timeout=700)
            except Exception:
                pass


def _skip_field_name(name: str) -> bool:
    low = (name or "").lower()
    return any(
        x in low
        for x in (
            "recaptcha",
            "g-recaptcha",
            "captcha-response",
            "honeypot",
            "bot-field",
            "turnstile",
        )
    )


async def consolidate_work_page(ctx, work_page, ats_page):
    """Keep one stable Chrome tab — navigate work_page to the ATS form URL."""
    target = ""
    try:
        target = (ats_page.url or "").strip()
    except Exception:
        target = ""
    if target and not is_board(target):
        try:
            if work_page.is_closed():
                work_page = await ensure_work_page(ctx)
            if ats_page != work_page:
                await goto(work_page, target)
            elif work_page.url != target:
                await goto(work_page, target)
        except Exception as e:
            log(f"  consolidate goto: {e}")
    # Close only blank / ephemeral apply tabs — never close the work tab
    for pg in list(ctx.pages):
        if pg == work_page:
            continue
        try:
            if pg.is_closed():
                continue
            u = pg.url or ""
            if u in ("about:blank", "chrome://newtab/", ""):
                await pg.close()
        except Exception:
            pass
    return work_page


async def goto(page, url, t=35000):
    if is_privacy_url(url or ""):
        archive_privacy_url(url, source_offer_url=OFFER_URL_HOLDER.get("url") or "", title="")
        log("  legal URL not opened in browser → archived offline")
        return
    try:
        if page is None or page.is_closed():
            raise RuntimeError("goto: page already closed")
    except Exception as e:
        if "closed" in str(e).lower():
            raise
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=t)
    except Exception as e:
        # External ATS redirects often raise ERR_ABORTED while still landing
        err = str(e)
        if "closed" in err.lower() or "target" in err.lower():
            raise
        if "ERR_ABORTED" in err or "interrupted" in err.lower() or "net::" in err:
            log(f"  goto interrupted (redirect?) — continue on current page: {err[:100]}")
            try:
                if not page.is_closed():
                    await page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
        else:
            raise
    try:
        if page.is_closed():
            raise RuntimeError("goto: page closed after navigation")
        await page.wait_for_timeout(900)
        await dismiss(page)
        await leave_legal_page(page, log_fn=log, source_offer_url=OFFER_URL_HOLDER.get("url") or "")
        if not is_privacy_url(page.url or ""):
            OFFER_URL_HOLDER["url"] = page.url or ""
    except Exception as e:
        if "closed" in str(e).lower() or "target" in str(e).lower():
            raise
        log(f"  goto post-nav: {e}")


def is_board(url: str) -> bool:
    """True only on job-board host/path — ignore utm_source=space-careers on employer ATS URLs."""
    try:
        p = urlparse(url or "")
        host_path = f"{p.netloc}{p.path}"
        return bool(BOARD_RE.search(host_path))
    except Exception:
        return bool(BOARD_RE.search(url or ""))


def is_success(
    body: str,
    title: str,
    *,
    uploaded_cv: bool = False,
    submitted: bool = False,
    final_url: str = "",
) -> bool:
    """True only for a real application confirmation — not contact-us / marketing pages.

    Requires CV uploaded OR a clear thank-you confirmation after a submit click.
    Never treats eFC company profiles or contact pages as success.
    """
    blob = f"{body or ''} {title or ''}"
    url = (final_url or "").lower()
    if re.search(r"contact-us|/about/|companies/[^/]+$|/en/companies$", url):
        return False
    # eFC board pages are never a real employer thank-you
    if re.search(r"efinancialcareers|spmailtechnolo", url):
        return False
    if not SUCCESS_RE.search(blob):
        return False
    # Confirmation text alone is weak without apply action
    if uploaded_cv or submitted:
        return True
    return False


async def click_text(page, patterns, roles=("button", "link"), t=2000) -> bool:
    for pat in patterns:
        for role in roles:
            try:
                loc = page.get_by_role(role, name=re.compile(pat, re.I))
                n = await loc.count()
                for i in range(min(n, 5)):
                    el = loc.nth(i)
                    if await el.is_visible(timeout=350):
                        href = ""
                        name = ""
                        try:
                            href = await el.get_attribute("href") or ""
                            name = (await el.inner_text(timeout=300)) or ""
                        except Exception:
                            pass
                        if role == "link" and should_skip_legal_link(href, name):
                            if href:
                                archive_privacy_url(
                                    href if href.startswith("http") else page.url,
                                    source_offer_url=page.url,
                                    title=name.strip()[:80],
                                )
                                log(f"  legal link not clicked → archived ({name.strip()[:40]})")
                            continue
                        try:
                            await el.click(timeout=t)
                        except Exception:
                            # Modal / cookie overlay often intercepts eFC Apply Now
                            try:
                                await dismiss(page)
                            except Exception:
                                pass
                            try:
                                await el.click(timeout=min(t, 2500), force=True)
                            except Exception:
                                continue
                        await page.wait_for_timeout(1000)
                        await dismiss(page)
                        await leave_legal_page(page, log_fn=log, source_offer_url=page.url)
                        return True
            except Exception:
                continue
    return False


async def wait_off_board(page, seconds=12) -> str:
    """Wait until URL leaves job-board trackers."""
    deadline = asyncio.get_event_loop().time() + seconds
    last = page.url
    while asyncio.get_event_loop().time() < deadline:
        await dismiss(page)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=2000)
        except Exception:
            pass
        u = page.url or ""
        if u and not is_board(u) and "track_click" not in u:
            return u
        if "track_click" in u:
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                await page.wait_for_timeout(800)
        else:
            await page.wait_for_timeout(500)
        last = page.url
    return last


async def open_employer(ctx, page, board_url: str):
    """Board page → employer ATS page (handles Apply Now modal + new tab)."""
    if (
        board_url
        and not is_board(board_url)
        and "track_click" not in board_url
        and re.search(
            r"gestmax|greenhouse|personio|ashby|lever\.co|teamtailor|smartrecruiters|"
            r"icims|workable|careers\.|jobs\.|apply\.",
            board_url,
            re.I,
        )
    ):
        await goto(page, board_url)
        return page

    await goto(page, board_url)

    # 1) If page already exposes employer href in DOM (rare)
    try:
        hrefs = await page.eval_on_selector_all(
            "a[href]",
            "els => els.map(a => ({t:(a.innerText||'').trim(), h:a.href}))",
        )
    except Exception:
        hrefs = []
    for L in hrefs:
        h, t = L.get("h") or "", L.get("t") or ""
        if not h.startswith("http") or is_board(h):
            continue
        if re.search(
            r"greenhouse|lever\.co|ashby|myworkday|gestmax|teamtailor|personio|"
            r"smartrecruiters|icims|workdayjobs|job-boards",
            h,
            re.I,
        ):
            if re.search(r"greenhouse|job-boards", h, re.I) and "/jobs/" not in h:
                continue
            if "teamtailor" in h and "/jobs/" not in h:
                continue
            if "ashby" in h and len(h.rstrip("/").split("/")) < 5:
                continue
            log(f"  direct ATS href: {h[:100]}")
            await goto(page, h)
            return page

    # 2) Click Apply Now — may open modal or new tab
    before = list(ctx.pages)
    clicked = await click_text(
        page,
        [
            r"^Apply Now$",
            r"^Apply$",
            r"Apply for this job",
            r"Apply externally",
            r"Continue to application",
            r"I'm interested",
            r"Start application",
            r"Jetzt bewerben",
        ],
    )
    if not clicked:
        # bootstrap modal button
        try:
            btn = page.locator("button.callToAction, button[data-bs-target*='Application'], button[data-job-url]")
            if await btn.count():
                await btn.first.click(timeout=2000)
                clicked = True
                await page.wait_for_timeout(800)
        except Exception:
            pass

    # Modal: look for Apply / Continue inside modal that opens track_click
    try:
        modal = page.locator("#jobApplicationModal, .modal.show, .modal")
        if await modal.count():
            # button inside modal linking to track_click
            mbtn = modal.locator("a[href*='track_click'], a.btn, button.btn, a[target=_blank]")
            if await mbtn.count():
                async with ctx.expect_page(timeout=10000) as pi:
                    await mbtn.first.click(timeout=2000)
                try:
                    np = await pi.value
                    await np.wait_for_load_state("domcontentloaded", timeout=30000)
                    await wait_off_board(np, 15)
                    await dismiss(np)
                    log(f"  modal → {np.url[:110]}")
                    return np
                except Exception:
                    pass
    except Exception:
        pass

    # New tab after Apply Now
    after = list(ctx.pages)
    for p2 in after:
        if p2 not in before:
            try:
                await p2.wait_for_load_state("domcontentloaded", timeout=25000)
                await wait_off_board(p2, 15)
                await dismiss(p2)
                log(f"  new tab → {p2.url[:110]}")
                return p2
            except Exception:
                continue

    # Same-tab track_click / navigation
    # Click any track_click link directly
    try:
        tc = page.locator("a[href*='track_click'], button[data-job-url]")
        if await tc.count():
            href = await tc.first.get_attribute("href")
            data = await tc.first.get_attribute("data-job-url")
            target = href or data
            if target:
                target = urljoin(board_url, target)
                log(f"  track_click goto {target[:100]}")
                await goto(page, target, t=40000)
                await wait_off_board(page, 15)
                log(f"  after track → {page.url[:110]}")
                return page
    except Exception as e:
        log(f"  track_click err {e}")

    await wait_off_board(page, 8)
    log(f"  stay → {page.url[:110]}")
    return page


async def upload_cv(page) -> tuple[bool, bool]:
    """Attach at most one CV and one certificate (idempotent per job page).

    Careers sites: force set_input_files on hidden inputs after clicking
    Upload/Apply/Resume controls.
    """
    # Reveal common career-site upload CTAs first
    try:
        await click_text(
            page,
            [
                r"Upload (a )?(resume|CV|file)",
                r"Attach (resume|CV)",
                r"Autofill with Resume",
                r"Choose file",
                r"Select Files?",
                r"Drop files",
                r"Add resume",
                r"Curriculum",
            ],
            roles=("button", "link"),
        )
    except Exception:
        pass

    up_cv, up_cert = await attach_documents(
        page, reveal=True, click_fn=click_text, log_fn=log
    )

    # Brute-force: every file input on page (hidden OK) — CV from candidate_profile (0020_raw default)
    if not up_cv:
        try:
            loc = page.locator("input[type=file]")
            n = await loc.count()
            for i in range(min(n, 6)):
                try:
                    await loc.nth(i).set_input_files(CV, timeout=5000)
                    up_cv = True
                    log("  ✓ CV forced onto careers file input")
                    break
                except Exception:
                    continue
        except Exception:
            pass

    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            if await frame.locator("input[type=file]").count() == 0:
                continue
            c1, c2 = await attach_documents(
                frame, reveal=True, click_fn=click_text, log_fn=log
            )
            up_cv = up_cv or c1
            up_cert = up_cert or c2
            if not up_cv:
                try:
                    floc = frame.locator("input[type=file]")
                    await floc.first.set_input_files(CV, timeout=5000)
                    up_cv = True
                    log("  ✓ CV forced onto iframe file input")
                except Exception:
                    pass
        except Exception:
            pass
    if up_cv or up_cert:
        await page.wait_for_timeout(600)
    return up_cv, up_cert


async def fill(page) -> int:
    n = 0
    page_ctx = page.url or ""
    first = pick_first_name(page_ctx)
    last = PROFILE["last"]
    street = PROFILE.get("address_street") or "Street 1"
    postal = PROFILE.get("address_postal") or "00000"
    gpa = PROFILE.get("gpa") or "2.6/4.0"
    title_prof = PROFILE.get("title") or "Telecommunications Engineer"
    # Brute-force: fill all visible text-like inputs by name/placeholder heuristics
    try:
        inputs = page.locator("input:visible, textarea:visible")
        count = await inputs.count()
        for i in range(min(count, 50)):
            el = inputs.nth(i)
            try:
                typ = (await el.get_attribute("type") or "text").lower()
                if typ in ("hidden", "submit", "button", "checkbox", "radio", "file", "image"):
                    continue
                name = ((await el.get_attribute("name")) or "" + (await el.get_attribute("id") or "") + (await el.get_attribute("placeholder") or "") + (await el.get_attribute("aria-label") or "")).lower()
                if _skip_field_name(name):
                    continue
                val = None
                if any(k in name for k in ["apellido", "apellidos", "lastname", "last_name", "nachname", "surname", "family"]) and "first" not in name and "nombre" not in name:
                    val = last
                elif any(k in name for k in ["first", "vorname", "prenom", "given", "nombre", "fname"]) and "last" not in name and "apellido" not in name:
                    val = first
                elif any(k in name for k in ["last", "nachname", "surname", "family"]) and "first" not in name:
                    val = last
                elif "email" in name or "e-mail" in name or typ == "email":
                    val = PROFILE["email"]
                elif any(k in name for k in ["phone", "tel", "mobile", "handy"]):
                    val = PROFILE["phone"]
                elif any(k in name for k in ["street", "address1", "address_line", "strasse", "straße", "addr1"]):
                    val = street
                elif any(k in name for k in ["postal", "zip", "plz"]):
                    val = postal
                elif any(
                    k in name
                    for k in [
                        "residence",
                        "wohnort",
                        "domicile",
                        "wohnstadt",
                        "place_of_residence",
                    ]
                ):
                    val = PROFILE.get("address_full") or PROFILE["residence"]
                elif any(k in name for k in ["city", "ort", "ville", "town", "stadt"]):
                    if not any(x in name for x in ["job", "work", "employer", "company"]):
                        val = PROFILE["city"]
                elif any(k in name for k in ["country", "land", "pays"]):
                    if "birth" not in name and "nationality" not in name:
                        val = PROFILE["country"]
                elif any(k in name for k in ["school", "university", "college", "uni", "hochschule"]):
                    val = PROFILE["school"]
                elif any(
                    k in name
                    for k in [
                        "graduation_year",
                        "grad_year",
                        "year_of_graduation",
                        "degree_year",
                        "end_year",
                        "abschlussjahr",
                        "year_completed",
                        "date_graduated",
                    ]
                ):
                    val = PROFILE.get("degree_year") or PROFILE.get("graduation_year") or "2003"
                elif any(k in name for k in ["start_year", "from_year", "year_started", "begin_year"]):
                    # university degree notes: 2003
                    val = PROFILE.get("degree_year_start") or "2003"
                elif any(k in name for k in ["gpa", "grade_point", "notendurchschnitt"]):
                    val = gpa
                elif any(k in name for k in ["degree", "qualification", "abschluss"]) and "field" not in name and "year" not in name:
                    val = title_prof
                elif any(k in name for k in ["job_title", "current_title", "headline"]) and "desired" not in name:
                    val = title_prof
                elif any(
                    k in name
                    for k in [
                        "salary",
                        "compensation",
                        "gehalt",
                        "expect",
                        "remuneration",
                        "pay_rate",
                        "annual_pay",
                        "desired_pay",
                        "wage",
                        "sueldo",
                        "salario",
                        "rémunération",
                        "pretention",
                    ]
                ):
                    from candidate_profile import salary_for_field

                    val = salary_for_field(name)
                elif any(k in name for k in ["infosys"]) or (
                    "employer" in name and "experience" in name
                ):
                    from candidate_profile import employment_textbox

                    val = employment_textbox("Infosys")[:4500] or None
                elif "accenture" in name:
                    from candidate_profile import employment_textbox

                    val = employment_textbox("Accenture")[:4500] or None
                elif typ == "text" and not name:
                    continue
                if val:
                    await el.fill(val, timeout=800)
                    n += 1
            except Exception:
                continue
        # Experience free-text: single Infosys + single Accenture blocks when labels match
        try:
            from candidate_profile import employment_textbox

            for label_rx, emp in (
                (r"Infosys|current employer|most recent employer", "Infosys"),
                (r"Accenture|previous employer|prior employer", "Accenture"),
            ):
                blob = employment_textbox(emp)
                if not blob:
                    continue
                try:
                    el = page.get_by_label(re.compile(label_rx, re.I))
                    if await el.count():
                        await el.first.fill(blob[:4500], timeout=2000)
                        n += 1
                        log(f"  ✓ {emp} single-textbox experience filled")
                except Exception:
                    pass
            # Generic large textareas for work history when empty-ish
            tas = page.locator("textarea:visible")
            for i in range(min(await tas.count(), 8)):
                ta = tas.nth(i)
                try:
                    ph = (
                        (await ta.get_attribute("placeholder") or "")
                        + (await ta.get_attribute("name") or "")
                        + (await ta.get_attribute("aria-label") or "")
                    ).lower()
                    cur = (await ta.input_value()) if True else ""
                    if cur and len(cur) > 40:
                        continue
                    if any(k in ph for k in ("experience", "work history", "beschreibung", "duties", "responsibilities", "summary")):
                        # Prefer Infosys consolidated (current role)
                        blob = employment_textbox("Infosys")[:4500]
                        if blob:
                            await ta.fill(blob, timeout=2000)
                            n += 1
                            log("  ✓ experience textarea ← Infosys consolidated")
                            break
                except Exception:
                    continue
        except Exception:
            pass
    except Exception:
        pass
    pairs = [
        (["#first_name", "input[name=first_name]", "input[name='job_application[first_name]']", "input[autocomplete=given-name]"], first),
        (["#last_name", "input[name=last_name]", "input[name='job_application[last_name]']", "input[autocomplete=family-name]"], last),
        (["input[name=apellidos]", "input[name=apellido]", "input#apellidos"], last),
        (["#email", "input[type=email]", "input[name=email]", "input[name='job_application[email]']"], PROFILE["email"]),
        (["#phone", "input[type=tel]", "input[name=phone]", "input[name='job_application[phone]']"], PROFILE["phone"]),
        (["#city", "input[name=city]"], PROFILE["city"]),
        (["input[name=school]", "input[name=university]", "#school"], PROFILE["school"]),
        (["input[name=address]", "input[name=street]", "input[autocomplete=street-address]"], street),
        (["input[name=postal_code]", "input[name=zip]", "input[autocomplete=postal-code]"], postal),
        (["input[name=gpa]", "input[id=gpa]"], gpa),
        (
            [
                "input[name*=graduation_year i]",
                "input[name*=grad_year i]",
                "input[name*=degree_year i]",
                "input[id*=graduation i]",
            ],
            PROFILE.get("degree_year") or "2003",
        ),
    ]
    for sels, val in pairs:
        for sel in sels:
            try:
                loc = page.locator(sel)
                if await loc.count():
                    await loc.first.fill(val, timeout=1500)
                    n += 1
                    break
            except Exception:
                continue
    for lab, val in [
        (r"^First name|^Nombre|^Prénom|^Vorname", first),
        (r"^Last name|^Apellidos|^Apellido|^Nachname|^Surname", last),
        (r"^Email", PROFILE["email"]),
        (r"^Phone", PROFILE["phone"]),
        (r"City|Town|Ort|Ville|Stadt", PROFILE["city"]),
        (r"Place of residence|City of residence|Wohnort|Residence", PROFILE["residence"]),
        (r"Country|Land", PROFILE["country"]),
    ]:
        try:
            el = page.get_by_label(re.compile(lab, re.I))
            if await el.count():
                await el.first.fill(val, timeout=1200)
                n += 1
        except Exception:
            pass
    # cover letter
    try:
        for sel in ["#cover_letter_text", "textarea#cover_letter", "textarea[name*='cover' i]", "textarea[name*='letter' i]"]:
            loc = page.locator(sel)
            if await loc.count():
                try:
                    await loc.first.fill(PROFILE["cover"], timeout=1500)
                    n += 1
                    break
                except Exception:
                    continue
    except Exception:
        pass
    # place of residence: City, Germany
    try:
        n += await fill_residence(page, log_fn=log)
    except Exception:
        pass

    # availability: from today onwards
    try:
        n += await fill_availability(page, log_fn=log)
    except Exception:
        pass

    # Optional second-pass: accessibility/label-graph filler (FORM_FILL_OPTIONS.md)
    if os.environ.get("FILL_A11Y", "0").lower() in ("1", "true", "yes"):
        try:
            from form_fill_a11y import fill_a11y

            m = await fill_a11y(page, log_fn=log)
            n += int(m.get("fields_filled") or 0)
            log(f"  a11y pass filled≈{m.get('fields_filled')} total_controls={m.get('fields_total')}")
        except Exception as e:
            log(f"  a11y fill err: {e}")

    # EEO: Male; race White; not veteran; no disability; EU work auth Yes
    try:
        from form_eeo import fill_eeo

        n += await fill_eeo(page, log_fn=log)
    except Exception as e:
        log(f"  eeo fill err: {e}")
        # fallback gender Male only (never Female — substring trap)
        try:
            for pat in [r"^Male$", r"^Man$", r"^Männlich$", r"^Homme$", r"^Masculino$"]:
                opt = page.get_by_role("option", name=re.compile(pat, re.I))
                if await opt.count():
                    await opt.first.click()
                    n += 1
                    break
                for i in range(min(await page.locator("select").count(), 15)):
                    s = page.locator("select").nth(i)
                    opts = await s.locator("option").all_inner_texts()
                    for o in opts:
                        ot = (o or "").strip()
                        if re.match(r"^(Male|Man|Männlich|Homme|Masculino)$", ot, re.I):
                            await s.select_option(label=o)
                            n += 1
                            break
        except Exception:
            pass
    # consents — check boxes only; never open Terms of Use / privacy policy links
    for pat in [r"I agree", r"I consent", r"I acknowledge", r"I confirm", r"I have read"]:
        try:
            labs = page.get_by_label(re.compile(pat, re.I))
            for i in range(min(await labs.count(), 5)):
                el = labs.nth(i)
                try:
                    tag = await el.evaluate("e => e.tagName")
                    if tag == "A" or should_skip_legal_link(await el.get_attribute("href") or "", pat):
                        href = await el.get_attribute("href")
                        if href:
                            archive_privacy_url(href, source_offer_url=page.url, title=pat)
                        continue
                    await el.check(timeout=400)
                    n += 1
                except Exception:
                    pass
        except Exception:
            pass
    try:
        boxes = page.locator('input[type="checkbox"]')
        for i in range(min(await boxes.count(), 12)):
            el = boxes.nth(i)
            try:
                lab = await el.evaluate(
                    """e => (e.closest('label')||e.parentElement||e).innerText||''"""
                )
                if re.search(r"privacy|terms|consent|agree|gdpr", lab or "", re.I):
                    if not await el.is_checked():
                        await el.check(timeout=400)
                        n += 1
            except Exception:
                pass
    except Exception:
        pass
    return n


async def workday_steps(page):
    if "myworkdayjobs" not in (page.url or "").lower() and "workday" not in (page.url or "").lower():
        return
    log("  [Workday]")
    for sel in [
        '[data-automation-id="adventureButton"]',
        'a[data-automation-id="adventureButton"]',
        'button:has-text("Apply")',
    ]:
        try:
            loc = page.locator(sel)
            if await loc.count() and await loc.first.is_visible(timeout=800):
                await loc.first.click(timeout=2500)
                log(f"  click {sel[:40]}")
                await page.wait_for_timeout(2500)
                await dismiss(page)
                break
        except Exception:
            pass
    for sel in [
        '[data-automation-id="applyManually"]',
        'div[data-automation-id="applyManually"]',
        'button:has-text("Apply Manually")',
        'button:has-text("Autofill with Resume")',
        '[data-automation-id="autofillWithResume"]',
    ]:
        try:
            loc = page.locator(sel)
            if await loc.count() and await loc.first.is_visible(timeout=1000):
                await loc.first.click(timeout=2500)
                log(f"  mode {sel[:40]}")
                await page.wait_for_timeout(3000)
                await dismiss(page)
                break
        except Exception:
            pass
    await upload_cv(page)


APPLY_ENTRY_PATTERNS = [
    r"Apply for this job",
    r"Apply for this position",
    r"^Apply$",
    r"Apply Now",
    r"Start application",
    r"Apply Manually",
    r"Autofill with Resume",
    r"I'm interested",
    r"Easy Apply",
    r"Bewerben",
    r"Jetzt bewerben",
    r"Postuler",
    r"Continue to application",
    r"Begin application",
    r"Register and apply",
]

APPLY_CSS_SELECTORS = [
    'a[data-testid="apply-button"]',
    'button[data-testid="apply-button"]',
    '[data-qa="apply-button"]',
    '[data-automation-id="adventureButton"]',
    "a.postings-btn",
    "button.postings-btn",
    "a.apply-button",
    "button.apply-button",
    'a[href*="/apply"]',
    'button[class*="apply" i]',
    'a[class*="apply" i]',
]


async def _click_apply_selectors(page) -> bool:
    """CSS fallbacks when role/name Apply buttons are hidden or non-standard."""
    for sel in APPLY_CSS_SELECTORS:
        try:
            loc = page.locator(sel)
            n = await loc.count()
            for i in range(min(n, 4)):
                el = loc.nth(i)
                if await el.is_visible(timeout=350):
                    await el.click(timeout=2000)
                    await page.wait_for_timeout(1000)
                    log(f"  apply css → {sel[:45]}")
                    return True
        except Exception:
            continue
    return False


async def ats_platform_boost(page) -> bool:
    """Open the real application form from a job-description landing page."""
    url = (page.url or "").lower()
    patterns: list[str] = []
    if "lever.co" in url:
        patterns = [r"Apply for this job", r"^Apply$", r"Apply Now"]
    elif "tesla.com" in url:
        patterns = [r"^Apply$", r"Apply now", r"Apply for job", r"Continue", r"^Next$"]
    elif "bmwgroup.jobs" in url or "bmw.com/careers" in url:
        patterns = [r"^Apply$", r"Apply now", r"Bewerben", r"Jetzt bewerben"]
    elif "jobs.uber.com" in url:
        patterns = [r"^Apply$", r"Apply now", r"Apply for this job"]
    elif "careers.cisco.com" in url or "cisco.com/global/en/job" in url:
        patterns = [r"^Apply$", r"Apply now", r"Apply for this job"]
    elif "google.com/about/careers" in url:
        patterns = [r"^Apply$", r"Apply now"]
    elif "renesas.com" in url or "jobs.renesas" in url:
        patterns = [r"^Apply$", r"Apply now"]
    elif "axon.com/careers" in url:
        patterns = [r"^Apply$", r"Apply now"]
    elif "careers.bakerhughes.com" in url:
        patterns = [r"^Apply$", r"Apply now"]
    elif "careers.eutelsat" in url or "eutelsat.com" in url:
        patterns = [r"^Apply$", r"Apply now", r"Postuler"]
    elif "embention" in url:
        patterns = [r"^Apply$", r"Apply now", r"Aplicar"]
    elif "greenhouse" in url or "job-boards" in url:
        patterns = [r"Apply for this job", r"^Apply$", r"Apply Now"]
    elif "personio" in url:
        patterns = [r"^Apply$", r"Apply now", r"Jetzt bewerben"]
    elif "teamtailor" in url or "gestmax" in url:
        patterns = [r"^Apply$", r"Apply now", r"Postuler", r"Bewerben"]
    elif "ashbyhq" in url:
        try:
            from ashby_helpers import ashby_open_application

            if await ashby_open_application(page, click_fn=click_text, log_fn=log):
                return True
        except Exception:
            pass
        patterns = [r"^Apply$", r"Apply for this job", r"Apply Now", r"Start application"]
    else:
        patterns = list(APPLY_ENTRY_PATTERNS)

    clicked = False
    for pat in patterns:
        if await click_text(page, [pat], roles=("button", "link")):
            clicked = True
            await page.wait_for_timeout(1200)
            break
    if not clicked:
        clicked = await _click_apply_selectors(page)
    if not clicked and hasattr(page, "frames"):
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            for pat in patterns[:4]:
                try:
                    if await click_text(frame, [pat], roles=("button", "link")):
                        clicked = True
                        await page.wait_for_timeout(1000)
                        break
                except Exception:
                    pass
            if clicked:
                break
    return clicked


async def _discover_apply_entry(page) -> bool:
    """Click any visible path into the application form (main page + frames)."""
    clicked = await ats_platform_boost(page)
    targets = [page, *page.frames]
    for target in targets:
        try:
            if await click_text(
                target,
                APPLY_ENTRY_PATTERNS,
                roles=("button", "link"),
            ):
                clicked = True
        except Exception:
            pass
    if not clicked:
        clicked = await _click_apply_selectors(page)
    return clicked


async def _try_submit(page) -> bool:
    if await click_text(
        page,
        [
            r"^Submit$",
            r"Submit application",
            r"Submit my application",
            r"Send application",
            r"Send application now",
            r"Send$",
            r"Envoyer",
            r"Soumettre",
            r"Postuler",
            r"Absenden",
            r"Senden",
            r"Bewerbung absenden",
            r"Enviar",
            r"Validate",
            r"Confirm",
            r"Finish",
            r"Complete application",
        ],
        roles=("button", "link"),
    ):
        await page.wait_for_timeout(3500)
        return True
    try:
        sub = page.locator('button[type=submit], input[type=submit]')
        if await sub.count() and await sub.first.is_visible(timeout=400):
            await sub.first.click(timeout=2000)
            await page.wait_for_timeout(3000)
            log("  type=submit")
            return True
    except Exception:
        pass
    return False


async def _page_success(page) -> bool:
    try:
        body = await page.inner_text("body")
        title = await page.title()
        if is_success(body, title):
            return True
    except Exception:
        pass
    try:
        from greenhouse_helpers import greenhouse_success_text

        if await greenhouse_success_text(page, is_success):
            return True
    except Exception:
        pass
    return False


async def _timed(coro, sec: float, label: str):
    """Cap slow ATS widgets so the dwell loop always reaches DWELL_SEC."""
    try:
        return await asyncio.wait_for(coro, timeout=sec)
    except asyncio.TimeoutError:
        log(f"  timeout ({int(sec)}s): {label}")
        return None


async def _try_chatbot_channel(page, *, title: str = "", company: str = "", url: str = "") -> dict:
    """If a careers chatbot exists, send CV + application message through it."""
    empty = {
        "present": False,
        "opened": False,
        "uploaded_cv": False,
        "messaged": False,
        "sent": False,
    }
    if not USE_CHATBOT:
        return empty
    try:
        from chatbot_helpers import try_chatbot_apply

        log("  chatbot: scanning for careers chat widget…")
        res = await try_chatbot_apply(
            page,
            title=title,
            company=company,
            url=url,
            log_fn=log,
        )
        if res.get("present") or res.get("opened") or res.get("sent"):
            log(
                f"  chatbot result present={res.get('present')} opened={res.get('opened')} "
                f"cv={res.get('uploaded_cv')} msg={res.get('messaged')} sent={res.get('sent')}"
            )
        return res
    except Exception as e:
        log(f"  chatbot err: {e}")
        return empty


def _prior_fail_keys() -> tuple[set[str], set[str]]:
    """Companies and URLs that already failed a soft attempt — do not re-open."""
    from application_ledger import all_records, CLOSED_STATUSES, _norm_company, _norm_url

    fail_st = {
        "open_only",
        "exception",
        "login_required",
        "stuck_on_board",
        "partial_form_filled",
        "cv_uploaded_only",
        "failed",
        "failed_no_submit",
        "ats_opened",
        "ats_opened_incomplete",
        "job_closed",
    }
    cos: set[str] = set()
    urls: set[str] = set()
    for r in all_records():
        st = (r.get("status") or "").strip()
        if st in CLOSED_STATUSES:
            continue
        if st not in fail_st and not st.startswith("blocked"):
            continue
        c = _norm_company(r.get("company", ""))
        if c:
            cos.add(c)
        u = _norm_url(r.get("url") or r.get("apply_url") or r.get("final_url") or "")
        if u:
            urls.add(u)
    return cos, urls


async def open_first_target_job(page, preferred_query: str = "") -> bool:
    """From a careers hub, open a matching software/engineer/lead job posting.

    Lesson: open_only often means we stayed on the careers landing page.
    Prefer job detail URLs (Greenhouse/Lever/Workday job links) before filling.
    NEVER treats eFinancialCareers as a job detail destination.
    """
    from role_filter import is_never_apply

    url0 = (page.url or "").lower()
    # Refuse to stay on job boards — always leave eFC / Indeed / etc.
    if re.search(
        r"efinancialcareers|spmailtechnolo|eurotechjobs|euroengineerjobs|"
        r"space-careers|stepstone\.|indeed\.|glassdoor",
        url0,
        re.I,
    ):
        log("  open_first_target_job: still on job board — refuse")
        return False

    # Already on a specific employer job post
    if re.search(
        r"/job/|/jobs/\d|/jobs/[a-z0-9-]{8,}|gh_jid=|lever\.co/.+/|/position/|"
        r"myworkdayjobs\.com/.+/job/|personio\.[^/]+/job/|"
        r"smartrecruiters\.com/.+/\d|ashbyhq\.com/.+/.+",
        url0,
        re.I,
    ):
        return False

    # Search boxes — prefer the real job title keywords from the alert
    queries = []
    if preferred_query and preferred_query.strip():
        queries.append(preferred_query.strip())
        # shorter variant: first 3–4 tokens
        toks = preferred_query.strip().split()
        if len(toks) > 4:
            queries.append(" ".join(toks[:4]))
    queries += ["software engineer", "software", "engineer"]
    searched = False
    for q in queries:
        for sel in (
            'input[type=search]',
            'input[placeholder*="Search" i]',
            'input[name*="search" i]',
            'input[name*="keyword" i]',
            'input[aria-label*="Search" i]',
            'input[placeholder*="keyword" i]',
            'input[data-test*="search" i]',
        ):
            try:
                loc = page.locator(sel)
                if await loc.count() and await loc.first.is_visible(timeout=400):
                    await loc.first.fill(q, timeout=1200)
                    await loc.first.press("Enter")
                    await page.wait_for_timeout(1800)
                    log(f"  careers search: {q}")
                    searched = True
                    break
            except Exception:
                continue
        if searched:
            break

    # Click filter chips if present
    for pat in (
        r"^Engineering$",
        r"^Technology$",
        r"^IT$",
        r"Software",
        r"Technik",
        r"IT & Engineering",
    ):
        try:
            if await click_text(page, [pat], roles=("button", "link", "tab")):
                await page.wait_for_timeout(800)
                break
        except Exception:
            pass

    role_rx = re.compile(
        r"software|engineer|developer|architect|technology\s*lead|tech\s*lead|"
        r"engineering\s*manager|platform|backend|fullstack|full[- ]stack|"
        r"cloud|devops|SRE|telecommunications",
        re.I,
    )
    ban_rx = re.compile(
        r"praktikum|intern\b|internship|werkstudent|working\s*student|"
        r"\bstudent\b|studierend|duales?\s*studium|facility|hausmeister|"
        r"apprentice|ausbildung|graduate\s+(programme|program|scheme)|"
        r"stagiaire|becario|campus\s+hire|new\s+graduate|"
        r"\bjunior\b|\bjr\.?\b|entry[- ]level|early\s*career",
        re.I,
    )
    senior_rx = re.compile(
        r"senior|staff|principal|\blead\b|architect|director|manager|head\s+of",
        re.I,
    )

    candidates: list[tuple[int, str, object]] = []
    try:
        links = page.locator(
            "a[href*='/job'], a[href*='/jobs/'], a[href*='greenhouse'], "
            "a[href*='lever.co'], a[href*='myworkday'], a[href*='personio'], "
            "a[href*='ashby'], a[href*='smartrecruiters'], a[href*='icims'], "
            "a[href*='teamtailor'], a[href*='workable'], a[href*='/careers/'], "
            "a[href*='/karriere/'], a[href*='/stellen'], a[href*='position']"
        )
        n = min(await links.count(), 40)
        for i in range(n):
            el = links.nth(i)
            try:
                if not await el.is_visible(timeout=200):
                    continue
                text = ((await el.inner_text(timeout=300)) or "").strip()
                href = (await el.get_attribute("href")) or ""
                blob = f"{text} {href}"
                if ban_rx.search(blob) or is_never_apply(text, "", href):
                    continue
                score = 0
                if ban_rx.search(blob):
                    continue
                if role_rx.search(blob):
                    score += 5
                if senior_rx.search(blob):
                    score += 6  # prefer senior/professional titles
                if re.search(r"lead|principal|staff|senior|architect", blob, re.I):
                    score += 3
                if re.search(
                    r"greenhouse|lever\.co|myworkday|personio|ashby|smartrecruiters",
                    href,
                    re.I,
                ):
                    score += 4
                if re.search(r"/job/|/jobs/", href, re.I):
                    score += 2
                # Require senior/professional signal when title text exists
                if text and not senior_rx.search(text) and not re.search(
                    r"software|engineer|architect|technology", text, re.I
                ):
                    continue
                if score > 0:
                    candidates.append((score, text[:80], el))
            except Exception:
                continue
    except Exception as e:
        log(f"  job scan err: {e}")

    candidates.sort(key=lambda x: -x[0])
    for score, text, el in candidates[:8]:
        try:
            await el.click(timeout=2500)
            await page.wait_for_timeout(1200)
            log(f"  open job (score={score}): {text[:70]}")
            await ats_platform_boost(page)
            return True
        except Exception:
            continue

    # Text fallback: first matching job title link
    for pat in (
        r"Software Engineer",
        r"Technology Lead",
        r"Tech Lead",
        r"Software Architect",
        r"Engineering Manager",
        r"Cloud Engineer",
        r"Platform Engineer",
        r"Softwareentwickler",
        r"IT Engineer",
    ):
        try:
            if await click_text(page, [pat], roles=("link",)):
                await page.wait_for_timeout(1200)
                log(f"  open job by title: {pat}")
                await ats_platform_boost(page)
                return True
        except Exception:
            continue
    return False


def _progress_fingerprint(
    page,
    *,
    up_cv: bool = False,
    up_cert: bool = False,
    filled: int = 0,
    submitted: bool = False,
    chatbot_sent: bool = False,
) -> str:
    """Compact signature of page + apply progress for stuck detection."""
    try:
        url = page.url or ""
    except Exception:
        url = ""
    try:
        p = urlparse(url)
        host_path = f"{p.netloc}{p.path}".lower().rstrip("/")
    except Exception:
        host_path = (url or "")[:120].lower()
    # Drop tracking noise from path identity
    host_path = re.sub(r"/+$", "", host_path)
    return (
        f"{host_path}|cv={int(bool(up_cv))}|cert={int(bool(up_cert))}|"
        f"fill={int(filled or 0)}|sub={int(bool(submitted))}|"
        f"chat={int(bool(chatbot_sent))}"
    )


def _progress_score(
    *,
    up_cv: bool = False,
    up_cert: bool = False,
    filled: int = 0,
    submitted: bool = False,
    chatbot_sent: bool = False,
) -> int:
    """Monotonic progress metric — higher is better."""
    return (
        int(bool(up_cv)) * 100
        + int(bool(up_cert)) * 20
        + int(filled or 0) * 3
        + int(bool(submitted)) * 50
        + int(bool(chatbot_sent)) * 5
    )


async def drive_form(
    page,
    *,
    title: str = "",
    company: str = "",
    job_url: str = "",
) -> dict:
    up_cv = up_cert = False
    filled = 0
    submit_click = False
    chatbot_sent = False
    chatbot_cv = False
    stuck_no_progress = False
    stuck_detail = ""
    start = time.monotonic()
    deadline = start + DWELL_SEC
    prev_fp = ""
    same_fp_streak = 0
    best_score = -1
    grace_until: float | None = None  # extra GIVE_UP_GRACE_SEC before abandon

    # Drill into a concrete job from careers hub (search by alert title keywords)
    try:
        from company_careers import search_query_from_title

        q = search_query_from_title(title) if title else "software engineer"
        await open_first_target_job(page, preferred_query=q)
    except Exception as e:
        log(f"  open_first_target_job: {e}")

    await workday_steps(page)
    cur = page.url or ""
    if re.search(r"ashbyhq", cur, re.I):
        try:
            from ashby_helpers import ashby_open_application

            await ashby_open_application(page, click_fn=click_text, log_fn=log)
        except Exception:
            pass
    else:
        await ats_platform_boost(page)
    if re.search(r"personio", cur, re.I) and "?apply" not in cur:
        await click_text(page, [r"^Apply$", r"Apply now", r"Jetzt bewerben", r"Apply for this position"])
        if "?apply" not in (page.url or ""):
            base = cur.split("#")[0].split("?")[0].rstrip("/")
            try:
                await goto(page, f"{base}?apply")
            except Exception:
                pass

    if USE_CHATBOT:
        log(f"  apply {DWELL_SEC}s — upload CV on form + chatbot if present…")
    else:
        log(f"  apply {DWELL_SEC}s — upload CV on form (chatbot disabled)…")
    rnd = 0
    # Early chatbot pass (user: upload resume via chatbot)
    if USE_CHATBOT and not chatbot_sent:
        chat = await _timed(
            _try_chatbot_channel(
                page, title=title, company=company, url=job_url or (page.url or "")
            ),
            25,
            "chatbot early",
        )
        if chat:
            chatbot_cv = chatbot_cv or bool(chat.get("uploaded_cv"))
            chatbot_sent = chatbot_sent or bool(
                chat.get("sent") and (chat.get("messaged") or chat.get("uploaded_cv"))
            )
            up_cv = up_cv or chatbot_cv
            if chatbot_sent:
                submit_click = True
                log("  chatbot application channel used (early)")

    while time.monotonic() < deadline:
        rnd += 1
        remaining = max(0, int(deadline - time.monotonic()))
        await dismiss(page)
        log(f"  round {rnd} ({remaining}s left) @ {(page.url or '')[:85]}")

        await _timed(workday_steps(page), 8, "workday")
        if not up_cv:
            if re.search(r"ashbyhq", page.url or "", re.I):
                try:
                    from ashby_helpers import ashby_open_application

                    await _timed(
                        ashby_open_application(page, click_fn=click_text, log_fn=log),
                        6,
                        "ashby apply",
                    )
                except Exception:
                    pass
            await _timed(_discover_apply_entry(page), 6, "apply entry")

        # Careers form: always try CV upload every round until it sticks
        upload_res = await _timed(upload_cv(page), 18, "upload")
        if upload_res:
            c1, c2 = upload_res
            up_cv = up_cv or c1
            up_cert = up_cert or c2
        fill_n = await _timed(_fill_all_contexts(page), 18, "fill")
        if fill_n is not None:
            filled = max(filled, fill_n)
        log(f"  cv={up_cv} cert={up_cert} filled={filled} chat={chatbot_sent}")

        # Stuck detection: same website behaviour 2x with no progress → skip
        fp = _progress_fingerprint(
            page,
            up_cv=up_cv,
            up_cert=up_cert,
            filled=filled,
            submitted=submit_click,
            chatbot_sent=chatbot_sent,
        )
        score = _progress_score(
            up_cv=up_cv,
            up_cert=up_cert,
            filled=filled,
            submitted=submit_click,
            chatbot_sent=chatbot_sent,
        )
        if score > best_score:
            best_score = score
            same_fp_streak = 0
            prev_fp = fp
            if grace_until is not None:
                log("  progress during grace — cancel give-up timer")
            grace_until = None
        else:
            # No progress: same or churning site without better apply state
            same_fp_streak += 1
            same_site = fp == prev_fp or (
                prev_fp and fp.split("|")[0] == prev_fp.split("|")[0]
            )
            log(
                f"  no progress #{same_fp_streak}/{STUCK_SAME_BEHAVIOUR} "
                f"{'same-site' if same_site else 'churn'} fp={fp[:85]}"
            )
            prev_fp = fp
            # Fail-fast: marketing hub with zero form widgets → 1 empty round is enough
            no_form = False
            try:
                n_file = await page.locator("input[type=file]").count()
                n_text = await page.locator(
                    "input[type=text], input[type=email], textarea"
                ).count()
                no_form = (n_file == 0 and n_text < 2) and not GOOD_ATS_RE.search(
                    page.url or ""
                )
            except Exception:
                no_form = False
            stuck_limit = (
                STUCK_NO_FORM_ROUNDS
                if (no_form and not up_cv and filled == 0)
                else STUCK_SAME_BEHAVIOUR
            )
            if same_fp_streak >= stuck_limit:
                # Already have CV (+ form work) → not a dead end; keep going / commit
                if up_cv and (submit_click or filled >= 6 or up_cert):
                    log(
                        f"  progress plateau after CV fill={filled} "
                        f"sub={submit_click} cert={up_cert} — continue (likely_submitted if no thank-you)"
                    )
                    same_fp_streak = 0  # don't abort filled applications
                    grace_until = None
                else:
                    now = time.monotonic()
                    # 1-minute (GIVE_UP_GRACE_SEC) gap before actually giving up
                    if GIVE_UP_GRACE_SEC > 0 and grace_until is None:
                        grace_until = now + GIVE_UP_GRACE_SEC
                        if deadline < grace_until:
                            deadline = grace_until
                        log(
                            f"  stuck detected — grace {GIVE_UP_GRACE_SEC}s "
                            f"before give up (keep trying)…"
                        )
                    elif GIVE_UP_GRACE_SEC > 0 and now < grace_until:
                        log(
                            f"  grace remaining {int(grace_until - now)}s "
                            f"before give up — keep trying"
                        )
                    else:
                        stuck_no_progress = True
                        stuck_detail = (
                            f"stuck {same_fp_streak}x same website behaviour without progress: {fp[:160]}"
                            + ("; no_form_fail_fast" if no_form else "")
                            + (
                                f"; after {GIVE_UP_GRACE_SEC}s grace"
                                if GIVE_UP_GRACE_SEC > 0
                                else ""
                            )
                        )
                        log(
                            f"  SKIP stuck — close tab, protocol, next offer — "
                            f"{stuck_detail[:100]}"
                        )
                        break

        if await _page_success(page):
            submit_click = True
            log("  success text detected")
            break

        if re.search(r"personio", page.url or "", re.I):
            if await _timed(personio_submit(page, log_fn=log), 8, "personio submit"):
                submit_click = True
                if await _page_success(page):
                    log("  success after personio submit")
                    break

        if await _timed(_try_submit(page), 8, "submit"):
            submit_click = True
            if await _page_success(page):
                log("  success after submit click")
                break

        if hasattr(page, "frames"):
            try:
                from greenhouse_helpers import greenhouse_try_submit

                if await _timed(
                    greenhouse_try_submit(page, click_fn=click_text, log_fn=log),
                    8,
                    "gh submit",
                ):
                    submit_click = True
                    if await _page_success(page):
                        log("  success after greenhouse submit")
                        break
            except Exception:
                pass

        if await _timed(
            click_text(
                page,
                [r"Save and Continue", r"Save and continue", r"^Next$", r"^Continue$", r"Review"],
                roles=("button",),
            ),
            5,
            "continue",
        ):
            await page.wait_for_timeout(1200)

        # Mid-dwell chatbot: send CV via chat if form still has no CV
        if USE_CHATBOT and not chatbot_sent and (not up_cv or rnd >= 2):
            chat = await _timed(
                _try_chatbot_channel(
                    page, title=title, company=company, url=job_url or (page.url or "")
                ),
                22,
                "chatbot",
            )
            if chat:
                chatbot_cv = chatbot_cv or bool(chat.get("uploaded_cv"))
                chatbot_sent = chatbot_sent or bool(
                    chat.get("sent") and (chat.get("messaged") or chat.get("uploaded_cv"))
                )
                up_cv = up_cv or chatbot_cv
                if chatbot_sent:
                    submit_click = True
                    log("  chatbot application channel used")
                    break

        # scroll to reveal more controls
        try:
            await page.evaluate("window.scrollBy(0, 400)")
        except Exception:
            pass

        await page.wait_for_timeout(min(2500, max(800, remaining * 200)))

    elapsed = int(time.monotonic() - start)
    upload_res = await _timed(upload_cv(page), 18, "upload final")
    if upload_res:
        c1, c2 = upload_res
        up_cv = up_cv or c1
        up_cert = up_cert or c2
    fill_n = await _timed(_fill_all_contexts(page), 18, "fill final")
    if fill_n is not None:
        filled = max(filled, fill_n)
    if hasattr(page, "frames"):
        try:
            from greenhouse_helpers import greenhouse_try_submit

            if not submit_click:
                submit_click = bool(
                    await _timed(
                        greenhouse_try_submit(page, click_fn=click_text, log_fn=log),
                        8,
                        "gh submit final",
                    )
                )
        except Exception:
            pass
    if not submit_click:
        submit_click = bool(await _timed(_try_submit(page), 8, "submit final"))
    # End of dwell: last-chance chatbot if still no CV/submit
    if USE_CHATBOT and not chatbot_sent and (not up_cv or not submit_click):
        chat = await _timed(
            _try_chatbot_channel(
                page, title=title, company=company, url=job_url or (page.url or "")
            ),
            22,
            "chatbot final",
        )
        if chat:
            chatbot_cv = chatbot_cv or bool(chat.get("uploaded_cv"))
            chatbot_sent = chatbot_sent or bool(chat.get("sent") and chat.get("messaged"))
            up_cv = up_cv or chatbot_cv
            if chatbot_sent:
                submit_click = True
                log("  chatbot application channel used (final)")
    if submit_click and await _page_success(page):
        log("  success confirmed at dwell end")
    log(
        f"  apply phase done ({elapsed}s) cv={up_cv} filled={filled} "
        f"sub={submit_click} chat={chatbot_sent}"
        f"{' STUCK' if stuck_no_progress else ''}"
    )
    return {
        "up_cv": up_cv,
        "up_cert": up_cert,
        "filled": filled,
        "submitted": submit_click,
        "chatbot_sent": chatbot_sent,
        "chatbot_cv": chatbot_cv,
        "stuck_no_progress": stuck_no_progress,
        "stuck_detail": stuck_detail,
    }


async def _fill_all_contexts(page) -> int:
    """Fill main page + ATS embed iframes (Greenhouse, Lever, etc.)."""
    n = await fill(page)
    if not hasattr(page, "frames"):
        return n
    try:
        from greenhouse_helpers import greenhouse_fill_frames

        n = max(n, await greenhouse_fill_frames(page, fill, log_fn=log))
    except Exception:
        pass
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        fr_url = (frame.url or "").lower()
        if "greenhouse.io" in fr_url:
            continue
        try:
            has_form = await frame.locator(
                "input:visible, textarea:visible, select:visible"
            ).count()
            if not has_form:
                continue
            fn = await fill(frame)
            if fn:
                n += fn
                log(f"  ✓ frame filled {fn} @ {fr_url[:70]}")
        except Exception:
            continue
    return n


async def commit_application(
    page,
    *,
    title: str = "",
    company: str = "",
    job_url: str = "",
    skip_if_stuck: bool = False,
) -> dict:
    """Second phase: keep working the form until submit or timeout — do not leave early."""
    up_cv = up_cert = False
    filled = 0
    submit_click = False
    chatbot_sent = False
    chatbot_cv = False
    stuck_no_progress = False
    stuck_detail = ""
    if skip_if_stuck:
        log("  COMMIT skipped — already stuck in apply phase")
        return {
            "up_cv": False,
            "up_cert": False,
            "filled": 0,
            "submitted": False,
            "chatbot_sent": False,
            "chatbot_cv": False,
            "stuck_no_progress": True,
            "stuck_detail": "skipped_commit_after_stuck_apply",
        }
    start = time.monotonic()
    deadline = start + COMMIT_SEC
    prev_fp = ""
    same_fp_streak = 0
    best_score = -1
    grace_until: float | None = None
    log(f"  COMMIT {COMMIT_SEC}s — complete form and submit…")
    await workday_steps(page)
    await ats_platform_boost(page)

    while time.monotonic() < deadline:
        remaining = max(0, int(deadline - time.monotonic()))
        await dismiss(page)
        await _discover_apply_entry(page)
        await workday_steps(page)

        c1, c2 = await upload_cv(page)
        up_cv = up_cv or c1
        up_cert = up_cert or c2
        filled = max(filled, await _fill_all_contexts(page))
        log(f"  commit ({remaining}s) cv={up_cv} filled={filled}")

        fp = _progress_fingerprint(
            page,
            up_cv=up_cv,
            up_cert=up_cert,
            filled=filled,
            submitted=submit_click,
            chatbot_sent=chatbot_sent,
        )
        score = _progress_score(
            up_cv=up_cv,
            up_cert=up_cert,
            filled=filled,
            submitted=submit_click,
            chatbot_sent=chatbot_sent,
        )
        if score > best_score:
            best_score = score
            same_fp_streak = 0
            prev_fp = fp
            if grace_until is not None:
                log("  COMMIT progress during grace — cancel give-up timer")
            grace_until = None
        else:
            same_fp_streak += 1
            log(
                f"  COMMIT no progress #{same_fp_streak}/{STUCK_SAME_BEHAVIOUR} "
                f"fp={fp[:80]}"
            )
            prev_fp = fp
            if same_fp_streak >= STUCK_SAME_BEHAVIOUR:
                now = time.monotonic()
                if GIVE_UP_GRACE_SEC > 0 and grace_until is None:
                    grace_until = now + GIVE_UP_GRACE_SEC
                    if deadline < grace_until:
                        deadline = grace_until
                    log(
                        f"  COMMIT stuck — grace {GIVE_UP_GRACE_SEC}s "
                        f"before give up (keep trying)…"
                    )
                elif GIVE_UP_GRACE_SEC > 0 and now < grace_until:
                    log(
                        f"  COMMIT grace remaining {int(grace_until - now)}s "
                        f"before give up — keep trying"
                    )
                else:
                    stuck_no_progress = True
                    stuck_detail = (
                        f"commit stuck {same_fp_streak}x same behaviour without progress: {fp[:160]}"
                        + (
                            f"; after {GIVE_UP_GRACE_SEC}s grace"
                            if GIVE_UP_GRACE_SEC > 0
                            else ""
                        )
                    )
                    log(f"  SKIP stuck COMMIT — {stuck_detail[:110]}")
                    break

        if await _page_success(page):
            submit_click = True
            log("  COMMIT success confirmed")
            break

        if re.search(r"personio", page.url or "", re.I):
            if await personio_submit(page, log_fn=log):
                submit_click = True
                await page.wait_for_timeout(3500)
                if await _page_success(page):
                    break

        if await _try_submit(page):
            submit_click = True
            await page.wait_for_timeout(4000)
            if await _page_success(page):
                log("  COMMIT success after submit")
                break

        if hasattr(page, "frames"):
            try:
                from greenhouse_helpers import greenhouse_try_submit

                if await greenhouse_try_submit(page, click_fn=click_text, log_fn=log):
                    submit_click = True
                    await page.wait_for_timeout(4000)
                    if await _page_success(page):
                        log("  COMMIT success after greenhouse submit")
                        break
            except Exception:
                pass

        if await click_text(
            page,
            [r"Save and Continue", r"Save and continue", r"^Next$", r"^Continue$", r"Review"],
            roles=("button",),
        ):
            await page.wait_for_timeout(1500)

        # Commit-phase chatbot if still stuck
        if USE_CHATBOT and not chatbot_sent and not up_cv and remaining < COMMIT_SEC - 10:
            chat = await _try_chatbot_channel(
                page, title=title, company=company, url=job_url or (page.url or "")
            )
            chatbot_cv = chatbot_cv or bool(chat.get("uploaded_cv"))
            chatbot_sent = chatbot_sent or bool(chat.get("sent") and chat.get("messaged"))
            up_cv = up_cv or chatbot_cv
            if chatbot_sent:
                submit_click = True
                log("  COMMIT chatbot application sent")
                break

        try:
            await page.evaluate("window.scrollBy(0, 500)")
        except Exception:
            pass
        await page.wait_for_timeout(2000)

    elapsed = int(time.monotonic() - start)
    log(
        f"  COMMIT done ({elapsed}s) cv={up_cv} filled={filled} "
        f"sub={submit_click} chat={chatbot_sent}"
        f"{' STUCK' if stuck_no_progress else ''}"
    )
    return {
        "up_cv": up_cv,
        "up_cert": up_cert,
        "filled": filled,
        "submitted": submit_click,
        "chatbot_sent": chatbot_sent,
        "chatbot_cv": chatbot_cv,
        "stuck_no_progress": stuck_no_progress,
        "stuck_detail": stuck_detail,
    }


def _merge_apply_meta(primary: dict, extra: dict) -> dict:
    return {
        "up_cv": primary.get("up_cv") or extra.get("up_cv"),
        "up_cert": primary.get("up_cert") or extra.get("up_cert"),
        "filled": max(int(primary.get("filled") or 0), int(extra.get("filled") or 0)),
        "submitted": bool(primary.get("submitted") or extra.get("submitted")),
        "chatbot_sent": bool(primary.get("chatbot_sent") or extra.get("chatbot_sent")),
        "chatbot_cv": bool(primary.get("chatbot_cv") or extra.get("chatbot_cv")),
        "stuck_no_progress": bool(
            primary.get("stuck_no_progress") or extra.get("stuck_no_progress")
        ),
        "stuck_detail": (primary.get("stuck_detail") or extra.get("stuck_detail") or ""),
    }


async def announce_success(title: str, company: str, status: str, url: str, final: str):
    log("")
    log("*" * 72)
    log("SUCCESS — APPLICATION COMPLETED")
    log(f"  JOB:     {title}")
    log(f"  COMPANY: {company}")
    log(f"  STATUS:  {status}")
    log(f"  FINAL:   {final[:110]}")
    log("*" * 72)
    log(
        f">>> Next application will wait {REOPEN_GAP_SEC}s before reopening "
        f"(REOPEN_GAP_SEC)…"
    )
    log("")
    with SUCCESS_MD.open("a", encoding="utf-8") as f:
        f.write(
            f"- **SUCCESS** {datetime.now().isoformat(timespec='seconds')} | "
            f"**{company}** | {title} | {status} | {url}\n"
        )
    # Gap before next open is applied in process_one (REOPEN_GAP_SEC)


async def process_one(ctx, page, row, idx, total) -> dict:
    title = (row.get("title") or "Unknown role").strip()
    company = (row.get("company") or "Unknown").strip()
    board = row.get("board") or ""
    url = (row.get("apply_url") or row.get("url") or "").strip()
    app_id = row.get("app_id") or f"A-{idx}"

    if SKIP_ATTEMPTED and not FORCE_RETRY:
        from application_ledger import is_already_attempted

        for k in ("employer_url", "apply_url", "url", "ats_url"):
            u = (row.get(k) or "").strip()
            if not u:
                continue
            hit, why = is_already_attempted(company, u, app_id)
            if hit:
                log(f"  SKIP [{why}] — already on record")
                return {
                    "app_id": app_id,
                    "title": title,
                    "company": company,
                    "board": board,
                    "url": url,
                    "status": "skipped_already_done",
                    "detail": why,
                    "succeeded": False,
                }
        hit, why = is_already_attempted(company, "", app_id)
        if hit:
            log(f"  SKIP [{why}] — already on record")
            return {
                "app_id": app_id,
                "title": title,
                "company": company,
                "board": board,
                "url": url,
                "status": "skipped_already_done",
                "detail": why,
                "succeeded": False,
            }

    # Do not re-open pages that already failed (yesterday's open_only / exception / …)
    if SKIP_PRIOR_FAILS and not FORCE_RETRY:
        from application_ledger import _norm_company, _norm_url

        fail_cos, fail_urls = _prior_fail_keys()
        c_norm = _norm_company(company)
        u_norm = _norm_url(
            (row.get("employer_url") or row.get("apply_url") or row.get("url") or "").strip()
        )
        if c_norm and c_norm in fail_cos:
            log(f"  SKIP [prior_fail company] — already failed earlier, not repeating: {company}")
            return {
                "app_id": app_id,
                "title": title,
                "company": company,
                "board": board,
                "url": url,
                "status": "skipped_prior_fail",
                "detail": "company already failed open/exception — user asked not to repeat",
                "succeeded": False,
            }
        if u_norm and u_norm in fail_urls:
            log(f"  SKIP [prior_fail url] — page already failed earlier")
            return {
                "app_id": app_id,
                "title": title,
                "company": company,
                "board": board,
                "url": url,
                "status": "skipped_prior_fail",
                "detail": "url already failed open/exception — user asked not to repeat",
                "succeeded": False,
            }

    # Absolute bans — always, even with APPLY_ALL=1
    # No chatbots (USE_CHATBOT default off). No student/junior tracks.
    # Technical PhD / doctoral positions are ALLOWED (user request).
    # Target: senior / professional + PhD research. Keyword software + 0020 CV fit required.
    from role_filter import (
        is_student_or_academic,
        is_junior_or_student_track,
        is_phd_role,
    )

    _is_phd = is_phd_role(title, url, company)
    if _is_phd:
        log(f"  PhD track allowed: {title[:80]}")
    elif (
        is_never_apply(title, company, url)
        or is_student_or_academic(title, url, company)
        or is_junior_or_student_track(title, url, company)
    ):
        why = skip_reason(title, company, url) or "excluded_student_or_junior_never_apply"
        log(f"  SKIP [never_apply] student/junior/facility banned: {title[:80]} ({why})")
        return {
            "app_id": app_id,
            "title": title,
            "company": company,
            "board": board,
            "url": url,
            "status": "skipped_role_filter",
            "detail": why,
            "succeeded": False,
        }

    # Prefer software / tech-lead / architect titles (not only the word "software").
    # PhD technical fields may omit "software".
    _blob_kw = f"{title} {company} {url}"
    _preferred_kw = bool(
        re.search(
            r"\bsoftware\b|"
            r"technology\s*lead|tech(?:nical)?\s*lead|"
            r"software\s*architect|solution[s]?\s*architect|systems?\s*architect|"
            r"enterprise\s*architect|application\s*architect|cloud\s*architect|"
            r"platform\s*architect|technical\s*architect|"
            r"engineering\s*manager|head\s*of\s*(?:engineering|software|technology)|"
            r"staff\s*(?:software\s*)?engineer|principal\s*(?:software\s*)?(?:engineer|architect)|"
            r"(java|kotlin|rust|python|devops|backend|fullstack|full[- ]stack|"
            r"platform|cloud)\s*(engineer|developer|architect)|"
            r"(engineer|developer|architect).{0,20}(java|kotlin|rust|python|devops|backend)",
            _blob_kw,
            re.I,
        )
    )
    if not _is_phd and not _preferred_kw:
        log(f"  SKIP [no_software_keyword]: {title[:80]}")
        return {
            "app_id": app_id,
            "title": title,
            "company": company,
            "board": board,
            "url": url,
            "status": "skipped_no_software_keyword",
            "detail": "title/url not software/tech-lead/architect-related",
            "succeeded": False,
        }

    # Fit check against 0020_raw CV before applying
    try:
        from cv_fit import job_fit_score

        fits, score, reason = job_fit_score(title, "", company, min_score=3)
        if not fits:
            log(f"  SKIP [cv_fit] {title[:60]} — {reason}")
            return {
                "app_id": app_id,
                "title": title,
                "company": company,
                "board": board,
                "url": url,
                "status": "skipped_cv_fit",
                "detail": reason,
                "succeeded": False,
            }
        log(f"  CV fit OK (0020_raw): {reason}")
    except Exception as e:
        log(f"  cv_fit check err (continue cautiously): {e}")

    reason = skip_reason(title, company) if not CV_RETRY_ONLY and not APPLY_ALL else None
    if reason:
        log(f"  SKIP [{reason}] — needs software + lead in title: {title[:80]}")
        return {
            "app_id": app_id,
            "title": title,
            "company": company,
            "board": board,
            "url": url,
            "status": "skipped_role_filter",
            "detail": reason,
            "succeeded": False,
        }

    from application_ledger import explain_repeat_open

    repeat_meta = explain_repeat_open(
        company,
        (row.get("employer_url") or row.get("apply_url") or row.get("url") or "").strip(),
        app_id,
    )

    log("=" * 72)
    log(f"[{idx}/{total}] START")
    log(f"  {title}")
    log(f"  @ {company}  [{board}]")
    log(f"  {url[:110]}")
    if repeat_meta.get("is_repeat"):
        log(
            f"  REPEAT OPEN #{repeat_meta.get('attempt_n')} — "
            f"prior {repeat_meta.get('prior_status') or '?'} "
            f"({repeat_meta.get('prior_ts') or '?'})"
        )
        if repeat_meta.get("prior_detail"):
            log(f"  prior detail: {repeat_meta['prior_detail'][:110]}")
        log(f"  why again: {repeat_meta.get('repeat_reason', '')[:200]}")
    log("=" * 72)

    res = {
        "app_id": app_id,
        "title": title,
        "company": company,
        "board": board,
        "url": url,
        "status": "failed",
        "succeeded": False,
        "detail": "",
        "repeat_meta": repeat_meta,
    }
    if not url:
        res["status"] = "no_url"
        log("  RESULT: no_url")
        return res

    # Effectiveness: skip hosts that never produce CV uploads after many stucks
    probe_url = " ".join(
        [
            url,
            (row.get("employer_url") or ""),
            (row.get("careers_url") or ""),
        ]
    )
    if DEAD_HOST_RE.search(probe_url) and not FORCE_RETRY and not GOOD_ATS_RE.search(probe_url):
        res["status"] = "skipped_dead_host"
        res["detail"] = "host previously stuck ≥3× with zero success (effectiveness skip)"
        log("  RESULT: skipped_dead_host — measured unproductive careers hub")
        return res

    # Gap before navigating / reopening the application page
    if REOPEN_GAP_SEC > 0:
        log(f"  reopen gap {REOPEN_GAP_SEC}s before opening application…")
        await asyncio.sleep(REOPEN_GAP_SEC)

    ats = page
    try:
        clear_upload_state(page)
        # --- Resolve company careers site (NEVER apply on eFinancialCareers) ---
        careers_url = (row.get("careers_url") or row.get("employer_url") or "").strip()
        search_q = (row.get("search_query") or "").strip()
        try:
            from company_careers import (
                is_board_url as _is_board_url,
                resolve_careers_url,
                search_query_from_title,
                careers_search_url,
            )

            if not careers_url or _is_board_url(careers_url) or is_board(careers_url):
                cu, src = resolve_careers_url(company, title, use_web=True, probe=False)
                if cu:
                    careers_url = cu
                    log(f"  careers resolve ({src}): {careers_url[:100]}")
            if not search_q:
                search_q = search_query_from_title(title)
        except Exception as e:
            log(f"  careers resolve err: {e}")

        # Prefer company careers (+ search); never use eFC/job-board as target
        # Prefer direct apply_url when it is already a good ATS job link
        direct = (row.get("employer_url") or "").strip()
        apply_direct = (row.get("apply_url") or url or "").strip()
        if apply_direct and GOOD_ATS_RE.search(apply_direct) and not is_board(apply_direct):
            target = apply_direct
            log(f"  prefer good-ATS apply_url: {target[:110]}")
        elif careers_url and not is_board(careers_url):
            try:
                from company_careers import careers_search_url as _csu

                target = _csu(careers_url, search_q) if search_q else careers_url
            except Exception:
                target = careers_url
        else:
            target = direct or url

        if target and (is_board(target) or "efinancialcareers" in target.lower() or "spmailtechnolo" in target.lower()):
            if careers_url and not is_board(careers_url):
                target = careers_url
                log(f"  refuse board URL — use careers hub: {target[:100]}")
            else:
                res["status"] = "skipped_no_company_careers"
                res["detail"] = "no employer careers URL; will not apply on eFinancialCareers"
                log("  RESULT: skipped_no_company_careers — refuse eFC apply")
                return res

        if target and DEAD_HOST_RE.search(target) and not GOOD_ATS_RE.search(target) and not FORCE_RETRY:
            res["status"] = "skipped_dead_host"
            res["detail"] = f"resolved to dead host: {target[:120]}"
            log("  RESULT: skipped_dead_host after resolve")
            return res

        if target and not is_board(target) and "track_click" not in target:
            log(f"  company careers → {target[:110]}")
            await goto(page, target)
            ats = page
        else:
            # Last resort: open_employer may follow external apply off the board
            ats = await open_employer(ctx, page, url)
            try:
                if is_board(ats.url or "") or "efinancialcareers" in (ats.url or "").lower():
                    res["status"] = "skipped_stuck_on_board"
                    res["detail"] = f"still on board after open: {(ats.url or '')[:120]}"
                    log("  RESULT: skipped_stuck_on_board — refuse eFC form fill")
                    return res
            except Exception:
                pass
        page = await consolidate_work_page(ctx, page, ats)
        ats = page
        # If still on job board after navigation — abort (never fill eFC forms)
        ats_url = ""
        try:
            ats_url = ats.url or ""
        except Exception:
            ats_url = ""
        stuck_board = is_board(ats_url) or "track_click" in ats_url or "efinancialcareers" in ats_url.lower()
        if stuck_board:
            if careers_url and not is_board(careers_url):
                log(f"  board escape → company careers {careers_url[:100]}")
                await goto(ats, careers_url)
                try:
                    ats_url = ats.url or ""
                except Exception:
                    pass
            if is_board(ats_url) or "efinancialcareers" in (ats_url or "").lower():
                res["status"] = "skipped_stuck_on_board"
                res["detail"] = f"could not leave job board: {ats_url[:120]}"
                log("  RESULT: skipped_stuck_on_board — refuse eFC")
                return res
        try:
            res["ats_url"] = ats.url or direct
        except Exception:
            res["ats_url"] = direct

        try:
            body_early = await ats.inner_text("body")
            title_early = await ats.title()
            if JOB_CLOSED_RE.search(f"{body_early} {title_early}"):
                res["status"] = "job_closed"
                res["detail"] = "posting closed or not found"
                log("  RESULT: job_closed — skipping")
                return res
        except Exception:
            pass

        if re.search(r"greenhouse|gh_jid", (res.get("ats_url") or "") + url, re.I):
            try:
                from greenhouse_helpers import wait_greenhouse_frame

                await wait_greenhouse_frame(ats, timeout_ms=12000)
            except Exception:
                pass

        # login wall early — reuse Apple Keychain company secrets when present
        if re.search(r"sign.?in|log.?in|auth0|okta|accounts\.google|myworkdayjobs", ats.url, re.I):
            try:
                from keychain_secrets import get_secret_for_company

                cred = get_secret_for_company(company, ask_sudo=False)
            except PermissionError as e:
                log("  KEYCHAIN access denied — need your permission for sudo / Keychain allow")
                log(f"  {str(e).splitlines()[0]}")
                cred = None
            except Exception:
                cred = None
            if cred and cred.get("username") and cred.get("password"):
                log(
                    f"  reusing Keychain secret for {company} "
                    f"(service={cred.get('service')}, user={cred.get('username')})"
                )
                try:
                    # common login fields
                    for sel in [
                        'input[type=email]',
                        'input[name*=email i]',
                        'input[name*=user i]',
                        'input[autocomplete=username]',
                        'input[data-automation-id="email"]',
                    ]:
                        loc = ats.locator(sel)
                        if await loc.count() and await loc.first.is_visible(timeout=400):
                            await loc.first.fill(cred["username"])
                            break
                    for sel in [
                        'input[type=password]',
                        'input[name*=pass i]',
                        'input[data-automation-id="password"]',
                    ]:
                        loc = ats.locator(sel)
                        if await loc.count() and await loc.first.is_visible(timeout=400):
                            await loc.first.fill(cred["password"])
                            break
                    if await click_text(
                        ats,
                        [r"^Sign In$", r"^Log In$", r"^Log in$", r"^Continue$", r"^Next$"],
                        roles=("button",),
                    ):
                        await ats.wait_for_timeout(2500)
                        log("  login submitted with Keychain secret")
                except Exception as e:
                    log(f"  keychain login fill err: {e}")

        # Workday often requires SSO/account — fail fast if no upload UI after apply steps
        if re.search(r"myworkdayjobs|workday", ats.url or "", re.I):
            await workday_steps(ats)
            files = await ats.locator("input[type=file]").count()
            body_l = ""
            try:
                body_l = (await ats.inner_text("body")).lower()
            except Exception:
                pass
            if files == 0 and any(x in body_l for x in ["sign in", "create account", "email address", "password", "verify your identity"]):
                # one more secret attempt already done above
                res["status"] = "login_required"
                res["detail"] = "Workday requires account/login (no keychain secret or login failed)"
                res["final_url"] = ats.url
                log("  RESULT: login_required (Workday SSO) — skipping")
                log(
                    f"  Tip: store secret → python3 keychain_secrets.py set {company!r} "
                    f"--user EMAIL --password-env COMPANY_PW"
                )
                try:
                    if ats is not page and not ats.is_closed():
                        await ats.close()
                except Exception:
                    pass
                return res

        # eFinancialCareers: stay on job page — do not open related listings
        try:
            u_now = (ats.url or "").lower()
            # Hard stop: never run form fill while still on a job board
            if is_board(u_now) or "efinancialcareers" in u_now:
                res["status"] = "skipped_stuck_on_board"
                res["detail"] = f"refuse form fill on board: {u_now[:120]}"
                log("  RESULT: skipped_stuck_on_board — before drive_form")
                return res
            await dismiss(ats)
        except Exception:
            pass
        dwell_meta = await drive_form(
            ats, title=title, company=company, job_url=url
        )
        commit_meta = await commit_application(
            ats,
            title=title,
            company=company,
            job_url=url,
            skip_if_stuck=bool(dwell_meta.get("stuck_no_progress")),
        )
        meta = _merge_apply_meta(dwell_meta, commit_meta)
        res.update(
            {
                "uploaded_cv": meta["up_cv"],
                "uploaded_certs": meta["up_cert"],
                "filled": meta["filled"],
                "submitted_click": meta["submitted"],
                "chatbot_sent": meta.get("chatbot_sent"),
                "chatbot_cv": meta.get("chatbot_cv"),
                "stuck_no_progress": meta.get("stuck_no_progress"),
                "final_url": ats.url,
            }
        )
        try:
            res["final_title"] = await ats.title()
        except Exception:
            res["final_title"] = ""
        try:
            body = await ats.inner_text("body")
        except Exception:
            body = ""

        # Honest success: CV must land on a form (or explicit thank-you after submit).
        # Stuck 2x same behaviour without progress → skip (close tab + protocol + next).
        # Exception: CV + certs + multi-field fill + submit click already happened → likely_submitted
        # (e.g. Merck form completed; page stays on /apply without thank-you text).
        if meta.get("stuck_no_progress"):
            if meta.get("up_cv") and (
                meta.get("submitted")
                or int(meta.get("filled") or 0) >= 6
                or meta.get("up_cert")
            ):
                res["status"] = "likely_submitted"
                res["succeeded"] = True
                res["detail"] = (
                    f"stuck after CV fill={meta.get('filled')} "
                    f"sub={meta.get('submitted')} cert={meta.get('up_cert')} "
                    f"(no thank-you page): {meta.get('stuck_detail') or ''}"
                )[:300]
                log(
                    "  RESULT: likely_submitted — CV already on form "
                    f"(fill={meta.get('filled')} cert={meta.get('up_cert')}) despite stuck page"
                )
            else:
                res["status"] = "skipped_stuck_same_behaviour"
                res["succeeded"] = False
                res["detail"] = meta.get("stuck_detail") or "stuck twice without progress"
                log(f"  RESULT: skipped_stuck_same_behaviour — next offer")
        elif is_success(
            body,
            res.get("final_title") or "",
            uploaded_cv=bool(meta["up_cv"]),
            submitted=bool(meta["submitted"]),
            final_url=ats.url or "",
        ):
            res["status"] = "submitted_or_confirmed"
            res["succeeded"] = True
        elif meta["up_cv"] and meta["submitted"]:
            res["status"] = "likely_submitted"
            res["succeeded"] = True
        elif meta["up_cv"] and meta["filled"] >= 3:
            res["status"] = "partial_form_filled"
            res["detail_extra"] = "cv_on_form_no_confirm"
        elif meta["up_cv"]:
            res["status"] = "cv_uploaded_only"
        elif meta.get("chatbot_sent"):
            res["status"] = "open_only"
            res["detail_extra"] = "chatbot_ignored_not_real_apply"
        elif re.search(r"sign.?in|log.?in|auth0|okta", ats.url, re.I):
            res["status"] = "login_required"
        elif is_board(ats.url) or "efinancialcareers" in (ats.url or "").lower() and "/companies/" in (ats.url or "").lower():
            res["status"] = "stuck_on_listing_not_form"
        elif "efinancialcareers" in (ats.url or "").lower() and "/jobs-" in (ats.url or "").lower():
            res["status"] = "open_only"
            res["detail_extra"] = "efc_job_page_no_cv_form"
        else:
            res["status"] = "open_only"
        if not res.get("detail"):
            res["detail"] = (
                f"cv={meta['up_cv']} certs={meta['up_cert']} "
                f"filled={meta['filled']} sub={meta['submitted']} "
                f"chat={meta.get('chatbot_sent')}"
            )

        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", app_id)[:40]
        try:
            await ats.screenshot(path=str(SHOT / f"complete_{safe}.png"))
        except Exception:
            pass

        if res["succeeded"]:
            await announce_success(
                title,
                company,
                res["status"],
                url,
                res.get("final_url") or res.get("ats_url") or "",
            )
        else:
            log(f"  RESULT: {res['status']} | {res['detail']}")
            log("  (not success — continuing)")

    except Exception as e:
        res["status"] = "exception"
        res["detail"] = str(e)[:200]
        log(f"  EXC {e}")

    # Do not close ATS tabs — closing them often kills the shared work page on CDP Chrome
    return res


def _prior_by_app_id() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not OUT_JSON.exists():
        return out
    try:
        for r in json.loads(OUT_JSON.read_text(encoding="utf-8")):
            aid = (r.get("app_id") or "").strip()
            if aid:
                out[aid] = r
    except Exception:
        pass
    return out


def _succeeded_keys() -> set[str]:
    """URLs and app_ids already submitted — skip on resume."""
    keys: set[str] = set()
    if OUT_JSON.exists():
        try:
            for r in json.loads(OUT_JSON.read_text()):
                if not r.get("succeeded"):
                    continue
                if FORCE_RETRY and not r.get("uploaded_cv"):
                    continue
                if r.get("app_id"):
                    keys.add(r["app_id"])
                for k in ("url", "apply_url", "ats_url", "final_url"):
                    u = (r.get(k) or "").strip()
                    if u:
                        keys.add(u)
        except Exception:
            pass
    # SUCCESS_MD is a human log and may list false "likely_submitted" without CV.
    # With FORCE_RETRY we only trust OUT_JSON entries that uploaded a CV.
    if SUCCESS_MD.exists() and not FORCE_RETRY:
        for line in SUCCESS_MD.read_text(encoding="utf-8").splitlines():
            if "http" in line:
                m = re.search(r"https?://\S+", line)
                if m:
                    keys.add(m.group(0).rstrip(")"))
    return keys


def _already_done(row: dict, done: set[str]) -> bool:
    if FORCE_RETRY:
        prior = _prior_by_app_id().get((row.get("app_id") or "").strip(), {})
        if prior and not prior.get("uploaded_cv"):
            return False
    st = (row.get("status") or "").lower()
    if st in (
        "done",
        "submitted",
        "succeeded",
        "likely_submitted",
        "submitted_or_confirmed",
    ):
        if FORCE_RETRY:
            prior = _prior_by_app_id().get((row.get("app_id") or "").strip(), {})
            if prior and not prior.get("uploaded_cv"):
                return False
        return True
    if st.startswith("blocked"):
        return True
    res = (row.get("resolve") or "").strip()
    if res and res != "ok":
        return True
    aid = (row.get("app_id") or "").strip()
    if aid and aid in done:
        return True
    for k in ("apply_url", "url", "employer_url"):
        u = (row.get(k) or "").strip()
        if u and u in done:
            return True
    return False


def _norm_url_key(u: str) -> str:
    return (u or "").strip().rstrip("/").split("?")[0].lower()


def load_cv_retry_queue(limit=MAX) -> list[dict]:
    """Direct ATS URLs where CV was not attached yet — skip role filter."""
    prior = _prior_by_app_id()
    rows: list[dict] = []
    if not RESOLVED_CSV.exists():
        return rows
    with RESOLVED_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            res = (r.get("resolve") or "").strip()
            if res and res != "ok":
                continue
            u = (r.get("employer_url") or r.get("apply_url") or r.get("url") or "").strip()
            if not u or not GOOD_ATS_RE.search(u):
                continue
            if SKIP_WORKDAY and "myworkdayjobs" in u.lower():
                continue
            aid = (r.get("app_id") or "").strip()
            if prior.get(aid, {}).get("uploaded_cv"):
                continue
            row = dict(r)
            if row.get("employer_url"):
                row["apply_url"] = row["employer_url"]
            rows.append(row)
    return rank_queue(rows)[:limit]


def load_queue(limit=MAX):
    if CV_RETRY_ONLY:
        return load_cv_retry_queue(limit)
    if RETRY_UNCLOSED:
        from unclosed_queue import build_unclosed, one_per_company, rank_unclosed

        rows = rank_unclosed(
            build_unclosed(skip_workday=SKIP_WORKDAY, include_all=APPLY_ALL)
        )
        if ONE_PER_COMPANY:
            rows = one_per_company(rows)
        if SKIP_ATTEMPTED and not FORCE_RETRY:
            from application_ledger import filter_not_attempted

            rows, skipped = filter_not_attempted(rows)
            if skipped:
                log(f"Ledger skip: {len(skipped)} already attempted (not re-applying)")
        return rows[:limit]

    rows = []
    done = _succeeded_keys()
    sources = [p for p in (RESOLVED_CSV, QUEUE_CSV) if p.exists()]
    for src in sources:
        with src.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if _already_done(r, done):
                    continue
                u = (r.get("employer_url") or r.get("apply_url") or r.get("url") or "").strip()
                if SKIP_WORKDAY and "myworkdayjobs" in u.lower():
                    continue
                # Skip measured-dead marketing hubs unless URL is a known good ATS
                if (
                    DEAD_HOST_RE.search(u)
                    and not GOOD_ATS_RE.search(u)
                    and not FORCE_RETRY
                ):
                    continue
                if u:
                    r = dict(r)
                    # Prefer apply_url when it is already a good ATS deep link
                    if r.get("apply_url") and GOOD_ATS_RE.search(r.get("apply_url") or ""):
                        pass  # keep apply_url
                    elif r.get("employer_url") and not GOOD_ATS_RE.search(
                        r.get("apply_url") or ""
                    ):
                        # only override weak apply_url with employer when apply isn't ATS
                        if not re.search(r"/job", (r.get("apply_url") or ""), re.I):
                            r["apply_url"] = r["employer_url"]
                    if not APPLY_ALL and not is_target_role(
                        r.get("title") or "", r.get("company") or ""
                    ):
                        continue
                    rows.append(r)
        if rows:
            break
    if not rows and (W / "jobboards_discovered.json").exists():
        data = json.loads((W / "jobboards_discovered.json").read_text())
        for i, j in enumerate(data, 1):
            u = j.get("apply_url") or j.get("url") or ""
            if not u and j.get("base") and j.get("job_id") and j.get("slug"):
                u = f"{j['base']}/job_display/{j['job_id']}/{j['slug']}"
            if not u:
                continue
            title = j.get("title", "")
            company = j.get("company", "")
            if not is_target_role(title, company):
                continue
            rows.append(
                {
                    "app_id": f"JB-{i:03d}",
                    "board": j.get("board", ""),
                    "company": company,
                    "title": title,
                    "apply_url": u,
                }
            )
    return rows[:limit]


def rank_queue(rows: list[dict]) -> list[dict]:
    """Prefer Technology Lead / Software Architect, then good ATS, then Senior SWE.

    Title tier (primary sort — user 2026-07-25):
      3 = Technology Lead / Software|Solutions Architect
      2 = Staff / Principal / Engineering Manager
      1 = Senior Software Engineer (and similar)
      0 = other

    Within a tier, prefer completable ATS URLs over marketing hubs.
    """
    from role_filter import (
        title_preference_score,
        is_preferred_title,
        is_plain_senior_swe,
        STAFF_PRINCIPAL_SIGNAL,
    )

    def title_tier(r) -> int:
        t = r.get("title") or ""
        c = r.get("company") or ""
        if is_preferred_title(t, c):
            return 3
        if STAFF_PRINCIPAL_SIGNAL.search(f"{t} {c}") or re.search(
            r"engineering\s+manager|head\s+of\s+(?:software|engineering)", t, re.I
        ):
            return 2
        if is_plain_senior_swe(t) or re.search(
            r"\bsenior\b.*\b(software|engineer|developer)\b", t, re.I
        ):
            return 1
        return 0

    def ats_score(r) -> int:
        u = (r.get("employer_url") or r.get("apply_url") or r.get("url") or "").lower()
        t = (r.get("title") or "")
        s = 0
        if GOOD_ATS_RE.search(u):
            s += 200
        if re.search(
            r"/jobs?/\d|/job/|/jobs/[^?]+|gh_jid=|ashbyhq\.com/[^/]+/[^/?]+|"
            r"smartrecruiters\.com/.+/\d|personio\.[^/]+/.+|gestmax\.|/apply\?",
            u,
        ):
            s += 120  # deep job URL beats careers homepage
        if re.search(r"\?q=|/careers/?$|/career/?$|/jobs/?$", u) and not GOOD_ATS_RE.search(u):
            s -= 90  # marketing hub — low convert (measured stuck-heavy)
        board = (r.get("board") or "").lower()
        if board in ("etoro_rings", "company_careers") and not GOOD_ATS_RE.search(u):
            if not re.search(r"/job", u):
                s -= 50  # generic public-co careers seeds
        if DEAD_HOST_RE.search(u):
            s -= 300
        if "efinancialcareers" in u or "spmailtechnolo" in u:
            s -= 150  # board only — resolve to employer
        if "myworkdayjobs" in u or "workday" in u:
            s -= 40  # SSO risk — still try real job paths later
        if "linkedin.com" in u:
            s -= 100  # login wall
        if "cisco.com" in u or "jobs.ea.com" in u or "embention" in u or "aerospacelab" in u:
            s += 30
        if "jobs.sap.com" in u and "/job/" in u:
            s += 80  # real SAP requisitions convert better than hubs
        if "esrf" in t.lower() or "gestmax" in u:
            s += 50
        # fine-grained title score within tier
        s += title_preference_score(t, r.get("company") or "")
        st = (r.get("status") or "").lower()
        if st in ("partial_form_filled", "cv_uploaded_only"):
            s += 180  # finish nearly-done apps first
        if st == "open_only":
            s += 20
        try:
            if int(r.get("filled") or 0) >= 3:
                s += 40
        except Exception:
            pass
        if r.get("submitted_click"):
            s += 30
        try:
            s += min(15, int(float(r.get("match_score") or 0)) // 10)
        except Exception:
            pass
        return s

    return sorted(rows, key=lambda r: (-title_tier(r), -ats_score(r)))


def _merge_results(batch: list[dict]) -> list[dict]:
    """Persist latest attempt per URL across runs."""
    by_key: dict[str, dict] = {}
    if OUT_JSON.exists():
        try:
            for r in json.loads(OUT_JSON.read_text(encoding="utf-8")):
                key = _norm_url_key(
                    r.get("url") or r.get("final_url") or r.get("ats_url") or r.get("app_id") or ""
                )
                if key:
                    by_key[key] = r
        except Exception:
            pass
    for r in batch:
        key = _norm_url_key(
            r.get("url") or r.get("final_url") or r.get("ats_url") or r.get("app_id") or ""
        )
        if key:
            by_key[key] = r
    return list(by_key.values())


def _wire_page(page):
    from popup_helpers import install_dialog_handler

    try:
        page.set_default_timeout(15000)
        page.set_default_navigation_timeout(40000)
    except Exception:
        pass
    try:
        install_dialog_handler(page)
    except Exception:
        pass


def _session_is_cloud(holder_or_mode=None) -> bool:
    if isinstance(holder_or_mode, dict) and holder_or_mode.get("mode") == "cloud_mobile":
        return True
    if holder_or_mode == "cloud_mobile":
        return True
    b = (os.environ.get("APPLY_BROWSER") or "").strip().lower()
    return b in ("cloud_mobile", "appium", "mobile_cloud", "s26", "galaxy_s26")


def _session_is_non_cdp(holder_or_mode=None) -> bool:
    """Safari / Firefox / cloud — no Chromium CDP helpers."""
    if _session_is_cloud(holder_or_mode):
        return True
    if isinstance(holder_or_mode, dict) and holder_or_mode.get("mode") in (
        "safari",
        "safari_system",
        "firefox",
    ):
        return True
    b = (os.environ.get("APPLY_BROWSER") or "").strip().lower()
    return b in (
        "safari",
        "webkit",
        "pw_safari",
        "safari_system",
        "safari_app",
        "safaridriver",
        "firefox",
        "chromium_isolated",
        "pw_chromium",
        "playwright_chromium",
        "isolated",
    ) or os.environ.get("APPLY_LAUNCH", "").lower() in ("persistent", "isolated", "1")


async def ensure_work_page(ctx, page=None):
    """Return an open page; create one if the current page was closed."""
    try:
        if page is not None and not page.is_closed():
            return page
    except Exception:
        pass
    try:
        for pg in ctx.pages:
            try:
                if not pg.is_closed():
                    _wire_page(pg)
                    return pg
            except Exception:
                continue
    except Exception:
        pass
    # Context may be dead — open a CDP tab via HTTP then try new_page
    if not _session_is_non_cdp():
        try:
            from cdp_helpers import ensure_cdp_tab

            ensure_cdp_tab(CDP)
        except Exception:
            pass
    try:
        np = await ctx.new_page()
        _wire_page(np)
        return np
    except Exception as e:
        log(f"  ensure_work_page new_page failed: {e}")
        raise


async def reconnect_cdp(p, holder: dict):
    """Reconnect browser session (CDP Chromium/Chrome or Firefox persistent)."""
    from browser_session import reconnect_session

    browser, ctx, page = await reconnect_session(p, holder)
    try:
        await install_privacy_blocker(ctx, OFFER_URL_HOLDER)
    except Exception:
        pass
    ctx.on("page", lambda pg: _wire_page(pg))
    page = await ensure_work_page(ctx, page)
    _wire_page(page)
    log(f"  browser reconnected (mode={holder.get('mode')}) — fresh work page")
    return browser, ctx, page


async def recycle_work_tab(ctx, page):
    """Close the current work tab after a failed/impossible apply and open a fresh one.

    User request: if a test failed and application was not possible, close the tab
    and open a new tab for the next company (avoids stuck ATS/error pages).
    """
    try:
        if page is not None and not page.is_closed():
            log("  recycle tab — close failed page, open new tab")
            try:
                await page.close()
            except Exception:
                pass
    except Exception:
        pass
    if not _session_is_non_cdp():
        try:
            from cdp_helpers import ensure_cdp_tab

            ensure_cdp_tab(CDP)
        except Exception:
            pass
    np = await ctx.new_page()
    _wire_page(np)
    # close extras beyond a few to avoid tab storms (keep new page)
    # cloud_mobile / safari_system are limited multi-tab — skip cleanup
    if _session_is_non_cdp():
        return np
    try:
        pages = [pg for pg in ctx.pages if not pg.is_closed()]
        for pg in pages:
            if pg == np:
                continue
            try:
                u = (pg.url or "").lower()
            except Exception:
                u = ""
            # keep Gmail / auth if open; close job debris
            if any(x in u for x in ("mail.google", "accounts.google", "login", "okta", "auth0")):
                continue
            if len([p for p in pages if not p.is_closed()]) <= 3:
                break
            try:
                await pg.close()
            except Exception:
                pass
    except Exception:
        pass
    return np


async def cleanup_tabs(ctx, keep_page=None):
    """Close only blank tabs at startup — never close real job/ATS pages."""
    for pg in list(ctx.pages):
        if keep_page is not None and pg == keep_page:
            continue
        try:
            u = pg.url or ""
            if u in ("about:blank", "chrome://newtab/", ""):
                await pg.close()
        except Exception:
            pass


async def main():
    from cdp_lock import acquire, release

    if PAUSE.exists():
        log("PAUSED — .APPLICATIONS_PAUSED present; exiting without browser apply")
        return

    if not acquire():
        log("CDP lock held — another apply script is running. Exit.")
        return
    try:
        await _main_apply()
    finally:
        release()


async def _main_apply():
    assert Path(CV).exists(), CV
    queue = rank_queue(load_queue()) if not RETRY_UNCLOSED else load_queue()
    # Optional offset so parallel Chrome/Safari workers pick different companies
    _q_off = int(os.environ.get("QUEUE_OFFSET", "0") or "0")
    if _q_off > 0 and len(queue) > _q_off:
        log(f"QUEUE_OFFSET={_q_off} — skipping first {_q_off} ranked rows for this worker")
        queue = queue[_q_off:]
    mode = (
        "cv_retry_ats"
        if CV_RETRY_ONLY
        else ("retry_unclosed" if RETRY_UNCLOSED else "normal")
    )
    from application_ledger import (
        bootstrap_from_complete_apply,
        bootstrap_from_strategy,
        attempted_sets,
        record_attempt,
        summarize_queue_repeats,
    )

    n_boot = bootstrap_from_strategy() + bootstrap_from_complete_apply()
    att = attempted_sets()
    _browser_name = __import__("os").environ.get("APPLY_BROWSER", "chromium")
    log(
        f"Complete apply | mode={mode} | n={len(queue)} | dwell={DWELL_SEC}s | "
        f"commit={COMMIT_SEC}s | give_up_grace={GIVE_UP_GRACE_SEC}s | "
        f"reopen_gap={REOPEN_GAP_SEC}s | "
        f"skip_attempted={SKIP_ATTEMPTED and not FORCE_RETRY} | "
        f"skip_prior_fails={SKIP_PRIOR_FAILS and not FORCE_RETRY} | "
        f"use_chatbot={USE_CHATBOT} | "
        f"ledger={len(att[0])} cos | browser={_browser_name} | CDP={CDP}"
    )
    if n_boot:
        log(f"Ledger bootstrap: +{n_boot} rows from prior results")
    repeats = summarize_queue_repeats(queue)
    if repeats:
        log(f"Repeat opens in queue: {len(repeats)} (see REPEAT_OPENS.md)")
        for r in repeats[:8]:
            log(
                f"  ↻ {r.get('company', '')[:40]} "
                f"#{r.get('attempt_n')} — {r.get('repeat_reason', '')[:90]}"
            )
        if len(repeats) > 8:
            log(f"  … and {len(repeats) - 8} more")
    log(f"CV={CV}")
    log(f"CERTS={CERTS}")
    log("On each SUCCESS the job name is printed before the next application.")
    if not SUCCESS_MD.exists():
        SUCCESS_MD.write_text(
            f"# Succeeded applications\n\nStarted {datetime.now().isoformat(timespec='seconds')}\n\n",
            encoding="utf-8",
        )

    from browser_session import APPLY_BROWSER as _APPLY_BROWSER
    from browser_session import open_session, reconnect_session

    cloud = _session_is_cloud()

    async def _session_body(p):
        holder: dict = {}
        try:
            browser, ctx, page, sess_mode = await open_session(p)
        except Exception as e:
            log(f"Browser session failed ({_APPLY_BROWSER}): {e}")
            return [], 0
        try:
            await install_privacy_blocker(ctx, OFFER_URL_HOLDER)
        except Exception as pe:
            log(f"  privacy_blocker skip ({pe})")
        try:
            ctx.on("page", lambda pg: _wire_page(pg))
        except Exception:
            pass
        page = await ensure_work_page(ctx, page)
        if not cloud:
            await cleanup_tabs(ctx, keep_page=page)
        _wire_page(page)
        holder.update(
            {"browser": browser, "ctx": ctx, "page": page, "mode": sess_mode}
        )
        log(f"Connected via {_APPLY_BROWSER} (mode={sess_mode}).\n")
        # Local CDP: full-screen the browser window (separate from Grok chat/TUI)
        if sess_mode == "cdp" and not cloud:
            try:
                from cdp_helpers import bring_browser_fullscreen

                if bring_browser_fullscreen(CDP):
                    log("  browser full-screen (separate window from this prompt)")
            except Exception as fe:
                log(f"  fullscreen skip: {fe}")
        if MAX <= 1:
            log("  mode: ONE application at a time (COMPLETE_MAX=1)")

        results = []
        ok = 0
        for i, row in enumerate(queue, 1):
            try:
                page = await ensure_work_page(ctx, page)
            except Exception as e:
                log(f"  ensure_work_page failed → reconnect: {e}")
                try:
                    _, ctx, page = await reconnect_session(p, holder)
                    try:
                        await install_privacy_blocker(ctx, OFFER_URL_HOLDER)
                    except Exception:
                        pass
                    try:
                        ctx.on("page", lambda pg: _wire_page(pg))
                    except Exception:
                        pass
                    _wire_page(page)
                except Exception as e2:
                    log(f"  fatal reconnect: {e2}")
                    break
            holder["page"] = page
            holder["ctx"] = ctx
            res = None
            t0 = time.time()
            for attempt in range(3):
                try:
                    res = await asyncio.wait_for(
                        process_one(ctx, page, row, i, len(queue)),
                        timeout=float(PER_APP_MAX_SEC),
                    )
                    break
                except asyncio.TimeoutError:
                    res = {
                        "app_id": row.get("app_id"),
                        "title": row.get("title"),
                        "company": row.get("company"),
                        "board": row.get("board"),
                        "url": row.get("apply_url") or row.get("url"),
                        "status": "skipped_time_budget",
                        "detail": f"exceeded {PER_APP_MAX_SEC}s — skip to next",
                        "succeeded": False,
                    }
                    log(
                        f"  SKIP [time_budget] >{PER_APP_MAX_SEC}s — "
                        f"{row.get('company')} — next application"
                    )
                    break
                except Exception as e:
                    err = str(e).lower()
                    if attempt < 2 and any(
                        x in err
                        for x in (
                            "closed",
                            "disconnect",
                            "target",
                            "connection closed",
                            "protocol error",
                            "reading from the driver",
                            "pipe closed",
                            "browser has been closed",
                            "session",
                            "invalid session",
                        )
                    ):
                        log(f"  reconnect after: {e}")
                        try:
                            _, ctx, page = await reconnect_cdp(p, holder)
                            holder["page"] = page
                            continue
                        except Exception as e2:
                            log(f"  reconnect failed: {e2}")
                    res = {
                        "app_id": row.get("app_id"),
                        "title": row.get("title"),
                        "company": row.get("company"),
                        "board": row.get("board"),
                        "url": row.get("apply_url") or row.get("url"),
                        "status": "exception",
                        "detail": str(e)[:200],
                        "succeeded": False,
                    }
                    log(f"  EXC {e}")
                    break
            if res is None:
                continue
            res["duration_s"] = round(time.time() - t0, 1)
            if cloud:
                res["source_browser"] = "cloud_mobile"
            fail_recycle = {
                "open_only",
                "exception",
                "login_required",
                "skipped_time_budget",
                "skipped_stuck_same_behaviour",
                "skipped_cv_fit",
                "skipped_no_software_keyword",
                "job_closed",
                "failed",
                "failed_no_submit",
                "partial_form_filled",
                "cv_uploaded_only",
                "stuck_on_board",
                "stuck_on_listing_not_form",
                "ats_opened",
                "ats_opened_incomplete",
                "no_url",
            }
            st = (res.get("status") or "").strip()
            if not res.get("succeeded") and st in fail_recycle:
                try:
                    page = await recycle_work_tab(ctx, page)
                    holder["page"] = page
                except Exception as re_err:
                    log(f"  recycle tab err: {re_err}")
                    try:
                        _, ctx, page = await reconnect_cdp(p, holder)
                        holder["page"] = page
                    except Exception:
                        try:
                            page = await ensure_work_page(ctx, None)
                            holder["page"] = page
                        except Exception:
                            pass
            try:
                from application_protocol import (
                    detect_ats,
                    record_protocol,
                    secrets_for_company,
                    _auto_lesson,
                )

                ats_name = detect_ats(
                    res.get("final_url") or res.get("ats_url") or res.get("url") or ""
                )
                secrets = secrets_for_company(res.get("company") or "")
                fill_imps = []
                if res.get("uploaded_cv"):
                    fill_imps.append("cv_upload")
                if res.get("uploaded_certs"):
                    fill_imps.append("certs_upload")
                if res.get("chatbot_sent"):
                    fill_imps.append("chatbot_channel")
                if res.get("filled"):
                    fill_imps.append(f"fields_filled={res.get('filled')}")
                lesson = _auto_lesson(
                    res.get("status") or "",
                    ats_name,
                    res.get("detail") or "",
                )
                record_protocol(
                    {
                        "app_id": res.get("app_id"),
                        "company": res.get("company"),
                        "title": res.get("title"),
                        "status": res.get("status"),
                        "succeeded": res.get("succeeded"),
                        "detail": res.get("detail"),
                        "url": res.get("url"),
                        "final_url": res.get("final_url") or res.get("ats_url"),
                        "ats": ats_name,
                        "cv": CV,
                        "uploaded_cv": res.get("uploaded_cv"),
                        "uploaded_certs": res.get("uploaded_certs"),
                        "secrets_used": secrets or "none",
                        "duration_s": res.get("duration_s"),
                        "fill_improvements": fill_imps,
                        "lesson": lesson,
                        "board": res.get("board"),
                        "browser": "cloud_mobile" if cloud else _APPLY_BROWSER,
                        "automation": os.environ.get("APPLY_AUTOMATION")
                        or os.environ.get("APPLY_BROWSER")
                        or "unknown",
                        "worker_id": os.environ.get("APPLY_WORKER_ID") or "",
                    }
                )
                res["ats"] = ats_name
                res["lesson"] = lesson
            except Exception as pe:
                log(f"  protocol log err: {pe}")
            results.append(res)
            st = res.get("status") or ""
            if st not in ("skipped_role_filter", "skipped_already_done"):
                repeat_meta = res.get("repeat_meta") or {}
                _auto = (
                    os.environ.get("APPLY_AUTOMATION")
                    or os.environ.get("APPLY_BROWSER")
                    or "unknown"
                )
                record_attempt(
                    company=res.get("company") or "",
                    title=res.get("title") or "",
                    url=res.get("final_url") or res.get("ats_url") or res.get("url") or "",
                    status=st,
                    detail=res.get("detail") or "",
                    app_id=res.get("app_id") or "",
                    source="complete_apply_cloud" if cloud else "complete_apply",
                    uploaded_cv=res.get("uploaded_cv"),
                    uploaded_certs=res.get("uploaded_certs"),
                    extra={
                        "submitted_click": res.get("submitted_click"),
                        "filled": res.get("filled"),
                        "board": res.get("board"),
                        "repeat_open": repeat_meta.get("is_repeat"),
                        "repeat_reason": repeat_meta.get("repeat_reason"),
                        "attempt_n": repeat_meta.get("attempt_n"),
                        "prior_status": repeat_meta.get("prior_status"),
                        "prior_detail": repeat_meta.get("prior_detail"),
                        "prior_ts": repeat_meta.get("prior_ts"),
                        "prior_url": repeat_meta.get("prior_url"),
                        "same_url": repeat_meta.get("same_url"),
                        "retry_policy": repeat_meta.get("retry_policy"),
                        "browser": "cloud_mobile" if cloud else _APPLY_BROWSER,
                        "automation": _auto,
                        "worker_id": os.environ.get("APPLY_WORKER_ID") or "",
                        "fill_a11y": os.environ.get("FILL_A11Y", "0"),
                    },
                )
            if res.get("succeeded"):
                ok += 1
            merged = _merge_results(results)
            OUT_JSON.write_text(json.dumps(merged, indent=2, ensure_ascii=False))
            # Between applications: short settle (main gap is REOPEN_GAP_SEC before next open)
            await asyncio.sleep(0.5 if REOPEN_GAP_SEC > 0 else 0.3)

        try:
            if cloud:
                await ctx.close()
            else:
                await page.close()
        except Exception:
            pass
        return results, ok

    if cloud:
        results, ok = await _session_body(None)
    else:
        async with async_playwright() as p:
            results, ok = await _session_body(p)

    fields = [
        "app_id",
        "company",
        "title",
        "board",
        "url",
        "status",
        "detail",
        "succeeded",
        "ats_url",
        "final_url",
        "uploaded_cv",
        "filled",
        "submitted_click",
    ]
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow(r)

    results = _merge_results(results)
    c = Counter(r.get("status") for r in results)
    log("\n==== COMPLETE APPLY SUMMARY ====")
    for k, v in c.most_common():
        log(f"  {v:3d} {k}")
    log(f"  SUCCEEDED: {ok}")
    log(f"  Success list: {SUCCESS_MD}")
    if ok:
        log("\nSucceeded applications:")
        for r in results:
            if r.get("succeeded"):
                log(f"  ✓ {r.get('company')} — {r.get('title')}")
    from application_ledger import rebuild_views

    rebuild_views()
    with (W / "apply_log.md").open("a") as f:
        f.write(f"\n\n## Complete apply {datetime.now().isoformat(timespec='seconds')}\n")
        for k, v in c.most_common():
            f.write(f"- {k}: {v}\n")
        f.write(f"succeeded: {ok}\n")
        for r in results:
            if r.get("succeeded"):
                f.write(f"- SUCCESS: {r.get('company')} | {r.get('title')}\n")
    log("done")


if __name__ == "__main__":
    asyncio.run(main())
