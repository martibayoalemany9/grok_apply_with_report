"""Idempotent CV + certificate upload — at most one of each per application page.

Handles:
  - Playwright set_input_files on <input type=file>
  - Playwright file chooser events
  - macOS native Open panel (Cmd+Shift+G + absolute path) when forms use Mac picker
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from mac_file_picker import CERT_ABS, CV_ABS, click_upload_and_fill_mac, mac_fill_open_dialog

try:
    from candidate_profile import ACADEMIC_CERTS, EXTRA_CERTS
except Exception:
    ACADEMIC_CERTS = ""
    EXTRA_CERTS = []

W = Path.home() / "deepline/data/karlsruhe-public-co-job-apps"
CV = CV_ABS
CERTS = CERT_ABS
CV_NAME = Path(CV).name.lower()
CERT_NAME = Path(CERTS).name.lower()
ACADEMIC_NAME = Path(ACADEMIC_CERTS).name.lower() if ACADEMIC_CERTS else ""
# Multi-file attach order: work certs 2020 first, then ETSETB academic
CERT_PATHS = [CERTS] + [p for p in (EXTRA_CERTS or []) if p and Path(p).is_file() and p != CERTS]

_STATE: dict[int, dict] = {}

FILE_SELECTORS = [
    'input[data-automation-id="file-upload-input-ref"]',
    'input[data-automation-id*="file" i]',
    "input[type=file]",
]

REVEAL_PATTERNS = [
    r"Upload (a )?(resume|CV|file)",
    r"Attach",
    r"Select Files?",
    r"Choose file",
    r"Browse",
    r"Add (a )?(resume|CV)",
    r"Autofill with Resume",
    r"Drop files",
    r"Select file",
]

UPLOAD_BUTTON_PATTERNS = [
    r"Upload (a )?(resume|CV|file|document)",
    r"Attach (a )?(resume|CV|file)",
    r"Choose [Ff]ile",
    r"Select [Ff]ile",
    r"Browse",
    r"Add (a )?(resume|CV|document)",
    r"^Upload$",
    r"Curriculum [Vv]itae",
]

CERT_BUTTON_PATTERNS = [
    r"upload.*cert",
    r"attach.*cert",
    r"cover letter",
    r"additional (file|document)",
    r"supporting document",
    r"other document",
]


def clear_upload_state(page=None) -> None:
    if page is None:
        _STATE.clear()
    else:
        _STATE.pop(id(page), None)


def _state(page) -> dict:
    return _STATE.setdefault(
        id(page),
        {"cv": False, "cert": False, "academic": False, "inputs": set(), "combined": False},
    )


def _all_cert_files() -> list[str]:
    """Work certs 2020 + ETSETB academic (existing files only)."""
    out: list[str] = []
    for p in CERT_PATHS:
        if p and Path(p).is_file() and p not in out:
            out.append(p)
    return out


async def _filenames_visible(page) -> tuple[bool, bool]:
    cv = cert = False
    try:
        body = (await page.inner_text("body", timeout=800)).lower()
        if CV_NAME in body or "0021_cc_marti" in body or "0020_raw_marti" in body:
            cv = True
        if (
            CERT_NAME in body
            or "certificates_2020" in body
            or "certificates compressed" in body
            or (ACADEMIC_NAME and ACADEMIC_NAME in body)
            or "etsetb_with" in body
        ):
            cert = True
    except Exception:
        pass
    return cv, cert


async def _default_reveal(page, patterns) -> None:
    for pat in patterns:
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=re.compile(pat, re.I))
                if await loc.count() and await loc.first.is_visible(timeout=300):
                    await loc.first.click(timeout=700)
                    return
            except Exception:
                continue


async def _reveal_uploaders(page, click_fn) -> None:
    fn = click_fn or _default_reveal
    for pat in REVEAL_PATTERNS:
        try:
            await fn(page, [pat])
        except Exception:
            pass


async def _collect_file_inputs(page) -> list[tuple[str, object]]:
    """Collect file inputs — include hidden ones (careers sites often hide them)."""
    found: list[tuple[str, object]] = []
    seen: set[str] = set()
    for sel in FILE_SELECTORS:
        try:
            loc = page.locator(sel)
            n = await loc.count()
            for i in range(n):
                key = f"{sel}#{i}"
                if key in seen:
                    continue
                el = loc.nth(i)
                # Prefer visible, but still keep hidden (set_input_files works)
                try:
                    vis = await el.is_visible(timeout=200)
                except Exception:
                    vis = False
                seen.add(key)
                found.append((key, el) if vis else (f"{key}:hidden", el))
        except Exception:
            continue
    # Always also sweep any remaining type=file (hidden)
    try:
        loc = page.locator("input[type=file]")
        n = await loc.count()
        for i in range(n):
            key = f"input[type=file]#all#{i}"
            if key in seen:
                continue
            seen.add(key)
            found.append((key, loc.nth(i)))
    except Exception:
        pass
    return found


async def _click_button_patterns(page, patterns) -> bool:
    for pat in patterns:
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=re.compile(pat, re.I))
                if await loc.count() and await loc.first.is_visible(timeout=400):
                    await loc.first.click(timeout=2000)
                    return True
            except Exception:
                continue
    return False


async def _upload_path_via_chooser(page, abs_path: str, patterns, log_fn) -> bool:
    """Click upload button; use Playwright file chooser or Mac Open panel."""
    for pat in patterns:
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=re.compile(pat, re.I))
                if not await loc.count():
                    continue
                el = loc.first
                if not await el.is_visible(timeout=400):
                    continue
                # Playwright hook (preferred)
                try:
                    async with page.expect_file_chooser(timeout=2500) as fc_info:
                        await el.click(timeout=2000)
                    chooser = await fc_info.value
                    await chooser.set_files(abs_path)
                    if log_fn:
                        log_fn(f"  ✓ file chooser → {Path(abs_path).name}")
                    await asyncio.sleep(0.8)
                    return True
                except Exception:
                    pass
                # Native macOS Open panel
                try:
                    await el.click(timeout=2000)
                    await asyncio.sleep(0.5)
                    if await mac_fill_open_dialog(abs_path):
                        if log_fn:
                            log_fn(f"  ✓ Mac Open panel → {Path(abs_path).name}")
                        await asyncio.sleep(1.0)
                        return True
                except Exception:
                    continue
            except Exception:
                continue
    return False


async def _attach_via_pickers(page, need_cv: bool, need_cert: bool, log_fn) -> tuple[bool, bool]:
    up_cv = not need_cv
    up_cert = not need_cert

    if need_cv:
        if await _upload_path_via_chooser(page, CV, UPLOAD_BUTTON_PATTERNS, log_fn):
            up_cv = True
        elif await click_upload_and_fill_mac(page, CV, log_fn=log_fn):
            up_cv = True

    if need_cert:
        pats = CERT_BUTTON_PATTERNS + UPLOAD_BUTTON_PATTERNS
        if await _upload_path_via_chooser(page, CERTS, pats, log_fn):
            up_cert = True
        elif await click_upload_and_fill_mac(page, CERTS, log_fn=log_fn):
            up_cert = True

    return up_cv, up_cert


async def attach_documents(
    page,
    *,
    reveal: bool = True,
    click_fn=None,
    log_fn=None,
) -> tuple[bool, bool]:
    """Attach exactly one CV and one certificate file to the current form.

    Safe to call multiple times per page — will not re-upload or duplicate files.
    """
    st = _state(page)
    url = ""
    try:
        url = page.url or ""
    except Exception:
        pass

    has_embed = False
    try:
        has_embed = any("greenhouse.io" in (fr.url or "").lower() for fr in page.frames)
    except AttributeError:
        has_embed = "greenhouse.io" in url.lower()
    if hasattr(page, "frames") and (
        re.search(r"greenhouse\.io|gh_jid=|job-boards\.eu\.greenhouse", url, re.I) or has_embed
    ):
        try:
            from greenhouse_helpers import greenhouse_attach

            gcv, gce = await greenhouse_attach(page, CV, CERTS, click_fn=click_fn, log_fn=log_fn)
            st["cv"] = st["cv"] or gcv
            st["cert"] = st["cert"] or gce
            if st["cv"] and st["cert"]:
                return True, True
        except Exception as exc:
            if log_fn:
                log_fn(f"  Greenhouse upload: {exc}")

    if re.search(r"ashbyhq\.com", url, re.I):
        try:
            from ashby_helpers import ashby_attach_files, ashby_open_application

            if not st["cv"] or not st["cert"]:
                await ashby_open_application(page, click_fn=click_fn, log_fn=log_fn)
            acv, ace = await ashby_attach_files(page, CV, CERTS, log_fn=log_fn)
            st["cv"] = st["cv"] or acv
            st["cert"] = st["cert"] or ace
            if st["cv"] and st["cert"]:
                return True, True
        except Exception as exc:
            if log_fn:
                log_fn(f"  Ashby upload: {exc}")

    if re.search(r"jobs\.apple\.com|idmsa\.apple\.com", url, re.I):
        if st["cv"]:
            return st["cv"], st["cert"]
        try:
            from apple_upload import apple_attach_documents

            up_cv, up_cert = await apple_attach_documents(page, log_fn=log_fn)
            st["cv"] = st["cv"] or up_cv
            st["cert"] = st["cert"] or up_cert
            return st["cv"], st["cert"]
        except Exception as exc:
            if log_fn:
                log_fn(f"  Apple upload fallback: {exc}")

    if st["cv"] and st["cert"]:
        return True, True

    dom_cv, dom_cert = await _filenames_visible(page)
    if re.search(r"personio", url, re.I):
        try:
            from personio_helpers import personio_files_on_page

            pcv, pce = await personio_files_on_page(page)
            dom_cv = dom_cv or pcv
            dom_cert = dom_cert or pce
        except Exception:
            pass
    st["cv"] = st["cv"] or dom_cv
    st["cert"] = st["cert"] or dom_cert
    if st["cv"] and st["cert"]:
        return True, True

    def _log(msg: str):
        if log_fn:
            log_fn(msg)

    if reveal:
        if click_fn:
            await _reveal_uploaders(page, click_fn)
        else:
            await _reveal_uploaders(page, None)

    inputs = await _collect_file_inputs(page)
    unused = [(k, el) for k, el in inputs if k not in st["inputs"]]

    cert_files = _all_cert_files()

    # Single multi-file input: CV + work certs 2020 + ETSETB academic
    if len(unused) == 1 and not st["combined"] and (not st["cv"] or not st["cert"]):
        key, el = unused[0]
        try:
            await el.set_input_files([CV, *cert_files] if cert_files else [CV, CERTS])
            st["cv"] = st["cert"] = True
            st["academic"] = len(cert_files) > 1
            st["combined"] = True
            st["inputs"].add(key)
            names = ", ".join(Path(p).name for p in ([CV] + cert_files))
            _log(f"  ✓ multi-attach (single field): {names}")
            return True, True
        except Exception:
            try:
                await el.set_input_files([CV, CERTS])
                st["cv"] = st["cert"] = True
                st["combined"] = True
                st["inputs"].add(key)
                _log("  ✓ CV + work cert attached (single field)")
                return True, True
            except Exception:
                pass

    # Separate <input type=file> fields
    for key, el in unused:
        if st["cv"] and st["cert"] and (st.get("academic") or len(cert_files) <= 1):
            break
        try:
            if not st["cv"]:
                await el.set_input_files(CV)
                st["cv"] = True
                st["inputs"].add(key)
                _log("  ✓ CV attached")
            elif not st["cert"]:
                await el.set_input_files(CERTS)
                st["cert"] = True
                st["inputs"].add(key)
                _log("  ✓ work cert 2020 attached")
            elif not st.get("academic") and len(cert_files) > 1:
                acad = cert_files[1]
                await el.set_input_files(acad)
                st["academic"] = True
                st["inputs"].add(key)
                _log(f"  ✓ academic cert attached ({Path(acad).name})")
        except Exception:
            continue

    # Hidden inputs (force attach even if not visible)
    if not st["cv"] or not st["cert"] or (not st.get("academic") and len(cert_files) > 1):
        try:
            all_inputs = page.locator('input[type=file]')
            n = await all_inputs.count()
            for i in range(n):
                key = f"hidden#{i}"
                if key in st["inputs"]:
                    continue
                el = all_inputs.nth(i)
                try:
                    if not st["cv"]:
                        await el.set_input_files(CV, timeout=4000)
                        st["cv"] = True
                        st["inputs"].add(key)
                        _log("  ✓ CV attached (hidden input)")
                    elif not st["cert"]:
                        await el.set_input_files(CERTS, timeout=4000)
                        st["cert"] = True
                        st["inputs"].add(key)
                        _log("  ✓ work cert 2020 attached (hidden input)")
                    elif not st.get("academic") and len(cert_files) > 1:
                        acad = cert_files[1]
                        await el.set_input_files(acad, timeout=4000)
                        st["academic"] = True
                        st["inputs"].add(key)
                        _log(f"  ✓ academic cert attached (hidden): {Path(acad).name}")
                except Exception:
                    continue
        except Exception:
            pass

    # Upload buttons → Playwright chooser or Mac Open panel with absolute paths
    if not st["cv"] or not st["cert"]:
        pcv, pce = await _attach_via_pickers(page, not st["cv"], not st["cert"], _log)
        st["cv"] = st["cv"] or pcv
        st["cert"] = st["cert"] or pce
    # Try academic as extra supporting doc if work cert already on form
    if st["cert"] and not st.get("academic") and len(cert_files) > 1:
        acad = cert_files[1]
        pats = CERT_BUTTON_PATTERNS + [
            r"education",
            r"degree",
            r"diploma",
            r"transcript",
            r"academic",
        ]
        if await _upload_path_via_chooser(page, acad, pats, _log):
            st["academic"] = True
        elif await click_upload_and_fill_mac(page, acad, log_fn=_log):
            st["academic"] = True

    dom_cv, dom_cert = await _filenames_visible(page)
    st["cv"] = st["cv"] or dom_cv
    st["cert"] = st["cert"] or dom_cert

    return st["cv"], st["cert"]