#!/usr/bin/env python3
"""Measure job-apply pipeline effectiveness and write EFFECTIVENESS_REPORT.md.

KPIs:
  - closed rate (submitted / likely_submitted)
  - CV upload rate
  - stuck rate (careers hubs with no form)
  - success by ATS type
  - today's batch vs overall

  python3 measure_effectiveness.py
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

W = Path(__file__).resolve().parent
LEDGER = W / "applications_ledger.jsonl"
OUT_MD = W / "EFFECTIVENESS_REPORT.md"
OUT_JSON = W / "EFFECTIVENESS_REPORT.json"

CLOSED = frozenset(
    {"submitted", "submitted_or_confirmed", "likely_submitted", "succeeded", "done"}
)
PROGRESS = frozenset(
    CLOSED
    | {
        "partial_form_filled",
        "cv_uploaded_only",
    }
)
GOOD_ATS = re.compile(
    r"ashbyhq|greenhouse|grnh\.se|job-boards\.(eu\.)?greenhouse|personio|"
    r"teamtailor|gestmax|workable\.com|lever\.co|smartrecruiters|bamboohr|"
    r"icims\.com|myworkdayjobs",
    re.I,
)


def host(u: str) -> str:
    try:
        return urlparse(u or "").netloc.lower()
    except Exception:
        return ""


def ats_kind(u: str) -> str:
    u = (u or "").lower()
    for name, pat in [
        ("greenhouse", r"greenhouse|grnh\.se|job-boards"),
        ("lever", r"lever\.co"),
        ("ashby", r"ashbyhq"),
        ("smartrecruiters", r"smartrecruiters"),
        ("personio", r"personio"),
        ("workday", r"myworkdayjobs|workday"),
        ("teamtailor", r"teamtailor"),
        ("workable", r"workable"),
        ("gestmax", r"gestmax"),
        ("icims", r"icims"),
        ("efc", r"efinancialcareers"),
    ]:
        if re.search(pat, u):
            return name
    return "custom"


def load_ledger() -> list[dict]:
    rows = []
    if not LEDGER.exists():
        return rows
    for line in LEDGER.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def measure(rows: list[dict]) -> dict:
    n = len(rows) or 1
    by_status = Counter((r.get("status") or "unknown") for r in rows)
    closed = sum(by_status[s] for s in CLOSED)
    progress = sum(by_status[s] for s in PROGRESS)
    stuck = sum(v for k, v in by_status.items() if "stuck" in k)
    cv = sum(1 for r in rows if r.get("uploaded_cv"))
    cert = sum(1 for r in rows if r.get("uploaded_certs"))
    sub = sum(
        1
        for r in rows
        if r.get("submitted_click")
        or r.get("submitted")
        or (r.get("status") or "") in CLOSED
    )

    by_ats_closed = Counter()
    by_ats_all = Counter()
    for r in rows:
        u = r.get("url") or r.get("final_url") or ""
        k = ats_kind(u)
        by_ats_all[k] += 1
        if (r.get("status") or "") in CLOSED:
            by_ats_closed[k] += 1

    stuck_hosts = Counter(
        host(r.get("url") or "")
        for r in rows
        if "stuck" in (r.get("status") or "")
    )
    win_hosts = Counter(
        host(r.get("url") or "")
        for r in rows
        if (r.get("status") or "") in CLOSED
    )
    dead = [
        {"host": h, "stuck": n, "wins": win_hosts.get(h, 0)}
        for h, n in stuck_hosts.most_common(40)
        if n >= 3 and win_hosts.get(h, 0) == 0
    ]

    today = datetime.now().strftime("%Y-%m-%d")
    today_rows = [r for r in rows if (r.get("ts") or "").startswith(today)]
    t_by = Counter((r.get("status") or "unknown") for r in today_rows)
    t_n = len(today_rows) or 1
    t_closed = sum(t_by[s] for s in CLOSED)
    t_stuck = sum(v for k, v in t_by.items() if "stuck" in k)

    # ATS rate: closed / attempts per ATS
    ats_rates = []
    for k, total in by_ats_all.most_common():
        c = by_ats_closed.get(k, 0)
        ats_rates.append(
            {"ats": k, "attempts": total, "closed": c, "rate_pct": round(100 * c / total, 1)}
        )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "overall": {
            "attempts": len(rows),
            "closed": closed,
            "closed_rate_pct": round(100 * closed / n, 2),
            "progress": progress,
            "progress_rate_pct": round(100 * progress / n, 2),
            "stuck": stuck,
            "stuck_rate_pct": round(100 * stuck / n, 2),
            "cv_uploads": cv,
            "cv_rate_pct": round(100 * cv / n, 2),
            "cert_uploads": cert,
            "submitish": sub,
            "submitish_rate_pct": round(100 * sub / n, 2),
            "by_status": dict(by_status.most_common()),
        },
        "today": {
            "date": today,
            "attempts": len(today_rows),
            "closed": t_closed,
            "closed_rate_pct": round(100 * t_closed / t_n, 2),
            "stuck": t_stuck,
            "stuck_rate_pct": round(100 * t_stuck / t_n, 2),
            "by_status": dict(t_by.most_common()),
        },
        "ats_rates": ats_rates,
        "dead_hosts": dead,
        "win_hosts": [{"host": h, "wins": n} for h, n in win_hosts.most_common(20)],
        "recommendations": [
            "Prefer direct ATS job URLs (Greenhouse/Lever/Ashby/Personio/SmartRecruiters/Gestmax) over corporate careers hubs.",
            "Skip dead hosts that stuck ≥3 times with zero CV upload/success.",
            "Treat careers marketing pages without file inputs as fail-fast (1 stuck round).",
            "Do not count eFC contact-us / company profile pages as success.",
            "Retry partial_form_filled / cv_uploaded_only before new companies.",
        ],
    }


def render_md(m: dict) -> str:
    o = m["overall"]
    t = m["today"]
    lines = [
        f"# Effectiveness report — {m['generated_at']}",
        "",
        "## KPIs (overall ledger)",
        "",
        f"| Metric | Value |",
        f"|--------|------:|",
        f"| Attempts | {o['attempts']} |",
        f"| **Closed** (submitted/likely) | **{o['closed']}** ({o['closed_rate_pct']}%) |",
        f"| Progress (closed + partial + CV) | {o['progress']} ({o['progress_rate_pct']}%) |",
        f"| Stuck same behaviour | {o['stuck']} ({o['stuck_rate_pct']}%) |",
        f"| CV uploaded | {o['cv_uploads']} ({o['cv_rate_pct']}%) |",
        f"| Submit-ish | {o['submitish']} ({o['submitish_rate_pct']}%) |",
        "",
        f"## Today ({t['date']})",
        "",
        f"- Attempts: **{t['attempts']}**",
        f"- Closed: **{t['closed']}** ({t['closed_rate_pct']}%)",
        f"- Stuck: **{t['stuck']}** ({t['stuck_rate_pct']}%)",
        "",
        "### Today by status",
        "",
    ]
    for k, v in t["by_status"].items():
        lines.append(f"- `{k}`: {v}")
    lines += ["", "## Closed rate by ATS", ""]
    for a in m["ats_rates"][:12]:
        lines.append(
            f"- **{a['ats']}**: {a['closed']}/{a['attempts']} = {a['rate_pct']}%"
        )
    lines += ["", "## Dead hosts (skip candidates)", ""]
    for d in m["dead_hosts"][:20]:
        lines.append(f"- `{d['host']}` stuck={d['stuck']} wins={d['wins']}")
    lines += ["", "## Recommendations", ""]
    for r in m["recommendations"]:
        lines.append(f"- {r}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    rows = load_ledger()
    m = measure(rows)
    OUT_JSON.write_text(json.dumps(m, indent=2), encoding="utf-8")
    OUT_MD.write_text(render_md(m), encoding="utf-8")
    print(render_md(m))
    print(f"\nWrote {OUT_MD} and {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
