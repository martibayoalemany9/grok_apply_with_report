"""Per-application protocol log — fail reasons, ATS, secrets, field improvements.

Append-only JSONL + human-readable APPLICATION_PROTOCOL.md
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

W = Path(__file__).resolve().parent
PROTOCOL_JSONL = W / "application_protocol.jsonl"
PROTOCOL_MD = W / "APPLICATION_PROTOCOL.md"
FAIL_REASONS = W / "failure_reasons.json"
IMPROVEMENTS = W / "field_improvements.json"

ATS_PATTERNS = [
    ("greenhouse", re.compile(r"greenhouse|job-boards\.(eu\.)?greenhouse", re.I)),
    ("lever", re.compile(r"lever\.co|jobs\.lever", re.I)),
    ("workday", re.compile(r"myworkdayjobs|workday", re.I)),
    ("personio", re.compile(r"personio", re.I)),
    ("ashby", re.compile(r"ashbyhq|jobs\.ashby", re.I)),
    ("smartrecruiters", re.compile(r"smartrecruiters", re.I)),
    ("icims", re.compile(r"icims", re.I)),
    ("successfactors", re.compile(r"successfactors|sap\.com/job|jobs\.sap", re.I)),
    ("taleo", re.compile(r"taleo", re.I)),
    ("teamtailor", re.compile(r"teamtailor", re.I)),
    ("workable", re.compile(r"workable\.com", re.I)),
    ("gestmax", re.compile(r"gestmax", re.I)),
    ("bamboohr", re.compile(r"bamboohr", re.I)),
    ("jobvite", re.compile(r"jobvite", re.I)),
    ("phenom", re.compile(r"phenom", re.I)),
    ("linkedin", re.compile(r"linkedin\.com", re.I)),
    ("custom", re.compile(r".")),
]


def detect_ats(url: str = "", body_hint: str = "") -> str:
    blob = f"{url or ''} {body_hint or ''}"
    for name, rx in ATS_PATTERNS:
        if name == "custom":
            continue
        if rx.search(blob):
            return name
    return "custom_or_unknown"


def _load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def record_protocol(entry: dict[str, Any]) -> None:
    """Append one application protocol row."""
    row = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        **entry,
    }
    with PROTOCOL_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Maintain failure reasons aggregate for next iteration
    fails = _load_json(FAIL_REASONS, {"by_status": {}, "by_ats": {}, "by_company": {}, "lessons": []})
    status = (entry.get("status") or "unknown").strip()
    ats = entry.get("ats") or "unknown"
    company = entry.get("company") or ""
    if not entry.get("succeeded"):
        fails["by_status"][status] = fails["by_status"].get(status, 0) + 1
        fails["by_ats"][ats] = fails["by_ats"].get(ats, 0) + 1
        if company:
            fails["by_company"][company] = {
                "status": status,
                "detail": (entry.get("detail") or "")[:300],
                "ats": ats,
                "ts": row["ts"],
                "fix_improvements": entry.get("fill_improvements") or [],
            }
        lesson = entry.get("lesson") or _auto_lesson(status, ats, entry.get("detail") or "")
        if lesson and lesson not in fails.get("lessons", []):
            fails.setdefault("lessons", []).append(lesson)
            fails["lessons"] = fails["lessons"][-80:]
        FAIL_REASONS.write_text(json.dumps(fails, indent=2, ensure_ascii=False), encoding="utf-8")

    # Human log
    lines = [
        f"\n### {row['ts']} — {company} — {entry.get('title') or ''}",
        f"- **status:** `{status}` succeeded={entry.get('succeeded')}",
        f"- **ATS / HR system:** `{ats}`",
        f"- **URL:** {entry.get('url') or entry.get('final_url') or ''}",
        f"- **CV:** `{entry.get('cv') or ''}`",
        f"- **certs uploaded:** {entry.get('uploaded_certs')}",
        f"- **CV uploaded:** {entry.get('uploaded_cv')}",
        f"- **secrets used:** {entry.get('secrets_used') or 'none'}",
        f"- **duration_s:** {entry.get('duration_s')}",
        f"- **detail:** {(entry.get('detail') or '')[:400]}",
        f"- **fill improvements:** {entry.get('fill_improvements') or []}",
        f"- **lesson for next iteration:** {entry.get('lesson') or _auto_lesson(status, ats, entry.get('detail') or '')}",
        "",
    ]
    if not PROTOCOL_MD.exists():
        PROTOCOL_MD.write_text(
            "# Application protocol\n\nFail reasons, ATS, secrets, and field-fill improvements.\n",
            encoding="utf-8",
        )
    with PROTOCOL_MD.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _auto_lesson(status: str, ats: str, detail: str) -> str:
    s = f"{status} {detail}".lower()
    if "stuck" in s or "same behaviour" in s or "same website" in s:
        return "Skip after 2x same-site no-progress; close tab and try next offer"
    if "timeout" in s or "5 min" in s or "time_budget" in s:
        return "Skip slow ATS faster; prefer direct job URLs over careers hubs"
    if "login" in s or "sign in" in s or "create account" in s:
        return f"Pre-auth or keychain login for {ats}; mark login_required early"
    if "captcha" in s:
        return "Manual captcha or headed browser dwell; do not spin"
    if "workday" in ats or "workday" in s:
        return "Workday needs account — SKIP_WORKDAY or store creds in keychain job-apps/<slug>"
    if "open_only" in s:
        return "Improve job discovery: click Apply Now into Greenhouse/Lever job post before fill"
    if "cv" in s and ("false" in s or "not" in s):
        return "Force file input + certificates; try Mac file picker on NSOpenPanel"
    if "chat" in s:
        return "Use chatbot with CV attach + ask which roles fit; treat sent chat as channel"
    if status == "exception":
        return "Reconnect CDP; ensure Chrome tab alive before next company"
    return f"Review {ats} form mapping for status={status}"


def lessons_for_iteration() -> list[str]:
    fails = _load_json(FAIL_REASONS, {})
    return list(fails.get("lessons") or [])


def record_field_improvement(ats: str, field: str, strategy: str) -> None:
    data = _load_json(IMPROVEMENTS, {})
    key = f"{ats}:{field}"
    data[key] = {
        "ats": ats,
        "field": field,
        "strategy": strategy,
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    IMPROVEMENTS.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def secrets_for_company(company: str) -> list[str]:
    """List keychain secret labels for company (username only — never password)."""
    used: list[str] = []
    slug = re.sub(r"[^a-z0-9]+", "-", (company or "").lower()).strip("-")
    try:
        from keychain_secrets import get_secret_for_company, list_company_secrets

        try:
            cred = get_secret_for_company(company, ask_sudo=False)
            if cred and cred.get("username"):
                used.append(
                    f"{cred.get('service') or 'job-apps/' + slug} user={cred.get('username')}"
                )
        except Exception:
            pass
        try:
            for item in list_company_secrets() or []:
                svc = str(item.get("service") or item or "")
                if slug and slug in svc.lower():
                    acc = item.get("account") or item.get("username") or ""
                    used.append(f"{svc}" + (f" user={acc}" if acc else " (present)"))
        except Exception:
            pass
    except Exception:
        pass
    # de-dupe
    out = []
    for u in used:
        if u not in out:
            out.append(u)
    return out
