"""Career-site chatbots — open widget and send CV / application message.

Used when normal ATS forms fail or a chat launcher is visible.
Supports common widgets: Intercom, Drift, HubSpot, Zendesk, Salesforce,
LiveChat, Tidio, Crisp, Genesys, and generic "Chat with us" launchers.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from candidate_profile import CERTS, CV, FULL, PROFILE

W = Path(__file__).resolve().parent
CV_PATH = Path(CV)
CERTS_PATH = Path(CERTS)

# Floating launchers / labels
LAUNCHER_SELECTORS = [
    # Intercom
    "#intercom-container iframe",
    ".intercom-lightweight-app-launcher",
    ".intercom-launcher",
    "div[class*='intercom-launcher']",
    # Drift
    "#drift-frame-controller",
    "button[id*='drift']",
    # HubSpot
    "#hubspot-messages-iframe-container",
    "div#hubspot-messages-iframe-container iframe",
    # Zendesk
    "iframe#webWidget",
    "iframe[title*='Messaging' i]",
    "iframe[title*='Message from' i]",
    "button[data-testid='launcher']",
    # Salesforce Embedded Messaging
    "button.embeddedMessagingConversationButton",
    "button[class*='embeddedMessaging']",
    # LiveChat / Tidio / Crisp / Genesys
    "#chat-widget-container",
    "#tidio-chat",
    "#crisp-chatbox",
    "div[class*='livechat']",
    "button[aria-label*='chat' i]",
    "button[aria-label*='message' i]",
    "button[title*='chat' i]",
    "div[role='button'][aria-label*='chat' i]",
    # Generic floaters
    "#chat-button",
    ".chat-button",
    ".chat-launcher",
    ".open-chat",
    "[data-chat-open]",
    "[class*='ChatWidget']",
    "[class*='chat-widget']",
    "[id*='chat-widget']",
    "[class*='ChatBubble']",
]

LAUNCHER_TEXT = re.compile(
    r"^(chat|chat with us|chat now|live chat|message us|contact us|"
    r"ask a question|talk to us|talk to a recruiter|talk to hr|"
    r"need help|get help|start chat|open chat|hilfe|chatten|"
    r"escribir|hablar|kontakt|fragen|bewerbung per chat)$",
    re.I,
)

COMPOSER_SELECTORS = [
    "textarea[placeholder*='message' i]",
    "textarea[placeholder*='type' i]",
    "textarea[placeholder*='write' i]",
    "textarea[placeholder*='chat' i]",
    "textarea[aria-label*='message' i]",
    "div[contenteditable='true'][role='textbox']",
    "div[contenteditable='true'][data-placeholder]",
    "div[contenteditable='true']",
    "input[placeholder*='message' i]",
    "textarea",
]

FILE_INPUT_SELECTORS = [
    "input[type=file]",
    "input[accept*='pdf' i]",
    "input[accept*='.doc' i]",
]

SEND_TEXT = re.compile(
    r"^(send|submit|envoyer|senden|absenden|enviar|send message|send now)$",
    re.I,
)


def application_chat_message(
    *,
    title: str = "",
    company: str = "",
    url: str = "",
) -> str:
    email = (PROFILE or {}).get("email") or "you@example.com"
    phone = (PROFILE or {}).get("phone") or "+490000000000"
    role = (title or "Software Engineer / Technology Lead").strip()
    co = (company or "your company").strip()
    lines = [
        f"Hello — my name is {FULL}.",
        f"I am a professional candidate (not Praktikum / internship / Werkstudent) "
        f"interested in open roles at {co}.",
        "I have attached / uploaded my CV (0021_cc curriculum) and company certificates 2020.",
        "Based on my CV, which professional job offers currently fit my profile best?",
        "Please include remote, hybrid, onsite, permanent, and short-term / fixed-term "
        "contract roles (software engineering, architecture, technology lead, cloud, platform) "
        "— no internships, Praktikum, or facility management.",
        f"Target interest: {role}. Salary expectation: €70,400–€120,000.",
        f"Email: {email} | Phone: {phone}",
        "Address: Street 1, 00000 City, Germany.",
        "Background: Telecommunications Engineer (Master), UPC / BarcelonaTech; GPA 2.6/4.0.",
        "Thank you — happy to apply to the best-fit professional openings you suggest.",
    ]
    if url:
        lines.insert(2, f"Careers page: {url[:180]}")
    return "\n".join(lines)


async def _visible(loc, timeout: int = 400) -> bool:
    try:
        if not await loc.count():
            return False
        return await loc.first.is_visible(timeout=timeout)
    except Exception:
        return False


async def _click_first_visible(page, selectors: list[str], log_fn=None) -> bool:
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if await _visible(loc):
                await loc.first.click(timeout=1500)
                if log_fn:
                    log_fn(f"  chatbot launcher click: {sel[:60]}")
                await page.wait_for_timeout(900)
                return True
        except Exception:
            continue
    return False


async def _click_text_launcher(page, log_fn=None) -> bool:
    for role in ("button", "link"):
        try:
            loc = page.get_by_role(role, name=LAUNCHER_TEXT)
            if await loc.count() and await loc.first.is_visible(timeout=400):
                await loc.first.click(timeout=1500)
                if log_fn:
                    log_fn(f"  chatbot text launcher ({role})")
                await page.wait_for_timeout(900)
                return True
        except Exception:
            continue
    # broader: any button containing Chat
    try:
        loc = page.locator(
            "button:has-text('Chat'), a:has-text('Chat'), "
            "button:has-text('Message'), a:has-text('Message us')"
        )
        if await loc.count():
            for i in range(min(await loc.count(), 6)):
                el = loc.nth(i)
                try:
                    if await el.is_visible(timeout=300):
                        box = await el.bounding_box()
                        # prefer floating widgets (bottom-right-ish)
                        if box and box.get("y", 0) > 200:
                            await el.click(timeout=1500)
                            if log_fn:
                                log_fn("  chatbot generic Chat control")
                            await page.wait_for_timeout(900)
                            return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


def _iter_targets(page):
    """Main page + all frames (chat often lives in iframe)."""
    yield page
    if hasattr(page, "frames"):
        for fr in page.frames:
            if fr == page.main_frame:
                continue
            yield fr


async def detect_chatbot(page) -> bool:
    """True if a chat launcher / widget is present (may be closed)."""
    for target in _iter_targets(page):
        for sel in LAUNCHER_SELECTORS[:18]:
            try:
                loc = target.locator(sel)
                if await loc.count():
                    return True
            except Exception:
                continue
        try:
            loc = target.get_by_role("button", name=LAUNCHER_TEXT)
            if await loc.count():
                return True
        except Exception:
            pass
    # body text heuristics
    try:
        body = (await page.inner_text("body", timeout=800)).lower()
        if any(
            x in body
            for x in (
                "chat with us",
                "live chat",
                "talk to a recruiter",
                "message us",
                "start a conversation",
            )
        ):
            return True
    except Exception:
        pass
    return False


async def open_chatbot(page, log_fn=None) -> bool:
    """Open the chat widget if closed. Returns True if opened or already open."""
    # Already has a composer?
    if await _find_composer(page) is not None:
        return True

    for target in _iter_targets(page):
        if await _click_first_visible(target, LAUNCHER_SELECTORS, log_fn=log_fn):
            await page.wait_for_timeout(1200)
            if await _find_composer(page) is not None:
                return True
        if await _click_text_launcher(target, log_fn=log_fn):
            await page.wait_for_timeout(1200)
            if await _find_composer(page) is not None:
                return True

    # Shadow / nested: click any visible iframe that looks like a launcher
    try:
        frames = page.frames if hasattr(page, "frames") else []
        for fr in frames:
            fu = (fr.url or "").lower()
            if any(
                k in fu
                for k in (
                    "intercom",
                    "drift",
                    "hubspot",
                    "zendesk",
                    "salesforce",
                    "livechat",
                    "tidio",
                    "crisp",
                    "genesys",
                    "messaging",
                )
            ):
                try:
                    # click inside launcher frame
                    btn = fr.locator("button, [role=button], a").first
                    if await btn.count():
                        await btn.click(timeout=1500)
                        if log_fn:
                            log_fn(f"  chatbot frame click @ {fu[:55]}")
                        await page.wait_for_timeout(1000)
                except Exception:
                    pass
    except Exception:
        pass

    return await _find_composer(page) is not None


async def _find_composer(page):
    """Return (target, locator) for message input, or None."""
    for target in _iter_targets(page):
        for sel in COMPOSER_SELECTORS:
            try:
                loc = target.locator(sel)
                n = await loc.count()
                for i in range(min(n, 5)):
                    el = loc.nth(i)
                    if await el.is_visible(timeout=250):
                        return target, el
            except Exception:
                continue
    return None


async def _type_message(target, el, text: str) -> bool:
    try:
        await el.click(timeout=1200)
        await el.fill("")  # may fail on contenteditable
    except Exception:
        pass
    try:
        tag = await el.evaluate("e => (e.tagName || '').toLowerCase()")
    except Exception:
        tag = ""
    try:
        if tag in ("textarea", "input"):
            await el.fill(text)
        else:
            await el.evaluate(
                """(e, t) => {
                    e.focus();
                    e.innerText = t;
                    e.dispatchEvent(new InputEvent('input', {bubbles: true}));
                }""",
                text,
            )
        return True
    except Exception:
        try:
            await el.type(text[:1200], delay=8)
            return True
        except Exception:
            return False


async def _upload_cv_in_chat(page, log_fn=None) -> bool:
    """Attach CV inside chat widget — hidden file inputs + paperclip + file chooser."""
    if not CV_PATH.exists():
        return False
    cv = str(CV_PATH)
    certs = str(CERTS_PATH) if CERTS_PATH.exists() else ""

    # 1) Any file input in page/frames (visible or hidden) — chat widgets often hide them
    for target in _iter_targets(page):
        for sel in FILE_INPUT_SELECTORS + ["input[type=file]"]:
            try:
                loc = target.locator(sel)
                n = await loc.count()
                for i in range(min(n, 8)):
                    inp = loc.nth(i)
                    try:
                        await inp.set_input_files(cv, timeout=5000)
                        if log_fn:
                            log_fn("  chatbot: CV attached via file input (incl. hidden)")
                        await page.wait_for_timeout(700)
                        if certs and n > 1:
                            try:
                                await loc.nth(min(i + 1, n - 1)).set_input_files(
                                    certs, timeout=3500
                                )
                                if log_fn:
                                    log_fn("  chatbot: certificates attached")
                            except Exception:
                                pass
                        return True
                    except Exception:
                        continue
            except Exception:
                continue

    # 2) Click paperclip / attach and hook file chooser
    attach_sel = (
        "button[aria-label*='attach' i], button[aria-label*='upload' i], "
        "button[aria-label*='file' i], button[title*='attach' i], "
        "button[aria-label*='Add file' i], button[aria-label*='Add attachment' i], "
        "label:has(input[type=file]), [data-testid*='attach' i], "
        "svg[aria-label*='attach' i], button:has(svg)"
    )
    for target in _iter_targets(page):
        try:
            attach = target.locator(attach_sel)
            n = await attach.count()
            for i in range(min(n, 6)):
                el = attach.nth(i)
                try:
                    if not await el.is_visible(timeout=300):
                        continue
                except Exception:
                    continue
                nested = el.locator("input[type=file]")
                try:
                    if await nested.count():
                        await nested.first.set_input_files(cv, timeout=4000)
                        if log_fn:
                            log_fn("  chatbot: CV via nested file input")
                        return True
                except Exception:
                    pass
                # Playwright file chooser
                try:
                    page_obj = page
                    async with page_obj.expect_file_chooser(timeout=2800) as fc_info:
                        await el.click(timeout=1500)
                    chooser = await fc_info.value
                    await chooser.set_files(cv)
                    if log_fn:
                        log_fn("  chatbot: CV via file chooser")
                    await page.wait_for_timeout(700)
                    return True
                except Exception:
                    try:
                        await el.click(timeout=1200)
                        await page.wait_for_timeout(400)
                        # after click, re-scan file inputs
                        for t2 in _iter_targets(page):
                            try:
                                fi = t2.locator("input[type=file]")
                                if await fi.count():
                                    await fi.first.set_input_files(cv, timeout=4000)
                                    if log_fn:
                                        log_fn("  chatbot: CV after attach click")
                                    return True
                            except Exception:
                                continue
                    except Exception:
                        continue
        except Exception:
            continue
    return False


async def _send(page, log_fn=None) -> bool:
    for target in _iter_targets(page):
        try:
            loc = target.get_by_role("button", name=SEND_TEXT)
            if await loc.count() and await loc.first.is_visible(timeout=400):
                await loc.first.click(timeout=2000)
                if log_fn:
                    log_fn("  chatbot: Send clicked")
                await page.wait_for_timeout(1500)
                return True
        except Exception:
            pass
        for sel in (
            "button[type=submit]",
            "button[data-testid*='send' i]",
            "button[aria-label*='send' i]",
            "button[title*='send' i]",
        ):
            try:
                loc = target.locator(sel)
                if await loc.count() and await loc.first.is_visible(timeout=300):
                    await loc.first.click(timeout=2000)
                    if log_fn:
                        log_fn(f"  chatbot: send selector {sel}")
                    await page.wait_for_timeout(1500)
                    return True
            except Exception:
                continue
    # Enter key on composer
    found = await _find_composer(page)
    if found:
        _, el = found
        try:
            await el.press("Enter")
            if log_fn:
                log_fn("  chatbot: Enter to send")
            await page.wait_for_timeout(1200)
            return True
        except Exception:
            pass
    return False


async def _wait_for_composer(page, log_fn=None, timeout_ms: int = 8000):
    """Poll for chat composer after widget animation / iframe load."""
    deadline = asyncio.get_event_loop().time() + timeout_ms / 1000.0
    while asyncio.get_event_loop().time() < deadline:
        found = await _find_composer(page)
        if found:
            return found
        await page.wait_for_timeout(400)
    return None


async def try_chatbot_apply(
    page,
    *,
    title: str = "",
    company: str = "",
    url: str = "",
    log_fn=None,
) -> dict:
    """Open chatbot if present, attach CV when possible, send application message.

    Returns dict: present, opened, uploaded_cv, messaged, sent
    """
    out = {
        "present": False,
        "opened": False,
        "uploaded_cv": False,
        "messaged": False,
        "sent": False,
    }
    try:
        present = await detect_chatbot(page)
    except Exception:
        present = False
    out["present"] = present
    if not present:
        # still try open — some widgets only appear after soft detection miss
        pass

    opened = await open_chatbot(page, log_fn=log_fn)
    # Always wait a bit — Intercom/Drift composers mount after launcher click
    await page.wait_for_timeout(1200)
    found = await _wait_for_composer(page, log_fn=log_fn, timeout_ms=7000)
    out["opened"] = opened or (found is not None)
    if not out["opened"] and not present:
        # one more launcher pass
        await open_chatbot(page, log_fn=log_fn)
        await page.wait_for_timeout(1500)
        found = await _wait_for_composer(page, log_fn=log_fn, timeout_ms=5000)
        out["opened"] = found is not None
    if not out["opened"] and not present and not found:
        return out

    # Upload CV FIRST (user request: send resume via chatbot)
    try:
        out["uploaded_cv"] = await _upload_cv_in_chat(page, log_fn=log_fn)
    except Exception as e:
        if log_fn:
            log_fn(f"  chatbot upload err: {e}")

    msg = application_chat_message(title=title, company=company, url=url)
    if out["uploaded_cv"]:
        msg = (
            "I have attached my CV (0021_cc curriculum) and certificates.\n"
            "Please review it and tell me which open job offers fit my CV best.\n\n"
            + msg
        )
    else:
        msg = (
            "My CV filename is "
            f"{CV_PATH.name} — I am trying to attach it in this chat.\n"
            "Based on my profile, which job offers currently fit my CV best?\n\n"
            + msg
        )

    if not found:
        found = await _wait_for_composer(page, log_fn=log_fn, timeout_ms=4000)
    if not found:
        await open_chatbot(page, log_fn=log_fn)
        found = await _wait_for_composer(page, log_fn=log_fn, timeout_ms=4000)
    if not found:
        if log_fn:
            log_fn("  chatbot: no composer found (CV attach attempted separately)")
        # CV-only success still useful if file landed in widget
        return out

    target, el = found
    typed = await _type_message(target, el, msg)
    out["messaged"] = typed
    if not typed:
        if log_fn:
            log_fn("  chatbot: failed to type message")
        return out
    if log_fn:
        log_fn("  chatbot: application message typed")

    # Attach again after typing (some UIs enable attach only then)
    if not out["uploaded_cv"]:
        try:
            out["uploaded_cv"] = await _upload_cv_in_chat(page, log_fn=log_fn)
        except Exception:
            pass

    out["sent"] = await _send(page, log_fn=log_fn)
    if out["sent"] and log_fn:
        log_fn(
            f"  chatbot: message sent "
            f"(cv_attached={out['uploaded_cv']}) — treat as application channel"
        )
    return out
