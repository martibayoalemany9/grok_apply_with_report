"""Poll Gmail for verification codes / magic links during applications.

Uses local CLI if available; callers can also use Gmail MCP from the agent.
Does not print full email bodies with secrets beyond OTP extraction.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

W = Path(__file__).resolve().parent
VERIFY_LOG = W / "gmail_verify_log.jsonl"

OTP_RE = re.compile(
    r"(?:code|otp|verification|pin|passcode)[^\d]{0,40}(\d{4,8})",
    re.I,
)
OTP_BARE = re.compile(r"\b(\d{6})\b")
LINK_RE = re.compile(
    r"https?://[^\s\"'<>]+(?:verify|confirm|activate|token|magic)[^\s\"'<>]*",
    re.I,
)


def extract_otp(text: str) -> str | None:
    if not text:
        return None
    m = OTP_RE.search(text)
    if m:
        return m.group(1)
    # fallback 6-digit
    m = OTP_BARE.search(text)
    return m.group(1) if m else None


def extract_verify_link(text: str) -> str | None:
    if not text:
        return None
    m = LINK_RE.search(text)
    return m.group(0).rstrip(").,]") if m else None


def log_verify_event(event: dict) -> None:
    event = {"ts": datetime.now().isoformat(timespec="seconds"), **event}
    with VERIFY_LOG.open("a", encoding="utf-8") as f:
        import json

        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def gmail_search_via_cli(query: str, max_results: int = 5) -> list[dict]:
    """Optional: if `gog` or similar not present, return empty (agent uses MCP)."""
    return []


def wait_for_otp_from_snippets(
    snippets: list[str],
    *,
    company: str = "",
    timeout_s: int = 90,
) -> dict:
    """Scan provided snippets (from MCP gmail_search) for OTP/link."""
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        for sn in snippets:
            otp = extract_otp(sn)
            link = extract_verify_link(sn)
            if otp or link:
                last = {"otp": otp, "link": link, "company": company, "source": "snippet"}
                log_verify_event(last)
                return last
        time.sleep(3)
    return {"otp": None, "link": None, "company": company, "timeout": True}
