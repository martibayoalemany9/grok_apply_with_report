#!/usr/bin/env python3
"""Durable application ledger — never apply twice to the same company/URL.

Files:
  applications_ledger.jsonl  — append-only full history
  applications_ledger.csv    — latest row per company (spreadsheet-friendly)
  APPLIED_COMPANIES.md       — human checklist of attempted companies
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path

W = Path(__file__).resolve().parent
LEDGER_JSONL = W / "applications_ledger.jsonl"
LEDGER_CSV = W / "applications_ledger.csv"
LEDGER_MD = W / "APPLIED_COMPANIES.md"
REPEAT_OPENS_MD = W / "REPEAT_OPENS.md"
REPEAT_OPENS_JSON = W / "repeat_opens.json"
# Also merge strategy sector + complete_apply results if present
STRATEGY_RESULTS = W / "strategy_sectors_results.json"
COMPLETE_RESULTS = W / "complete_apply_results.json"
SUCCESS_MD = W / "succeeded_applications.md"

# Confirmed closed — never re-apply (failed open_only / exception are retryable)
CLOSED_STATUSES = frozenset(
    {
        "submitted_or_confirmed",
        "likely_submitted",
        "submitted",
        "succeeded",
        "done",
        "applied",
    }
)
# Hard done for strategy sectors (CV reached)
DONE_STATUSES = CLOSED_STATUSES | frozenset(
    {
        "partial_form_filled",
        "cv_uploaded_only",
        "job_closed",
        "skipped_already_done",
    }
)
# Soft — only block re-apply if CV was uploaded (real form reached)
SOFT_DONE_IF_CV = frozenset(
    {
        "open_only",
        "login_required",
        "exception",
        "failed",
    }
)

# Why a company may be opened again without a closed application
REPEAT_REASON_BY_STATUS = {
    "open_only": "page opened but no CV upload and no confirmed submit",
    "exception": "prior run ended with browser/tab error before finishing",
    "login_required": "prior run hit login/SSO wall — guest apply not available",
    "stuck_on_board": "prior run never left job-board redirect to employer ATS",
    "partial_form_filled": "prior run filled fields but submit was not confirmed",
    "cv_uploaded_only": "prior run uploaded CV but submit/thank-you not confirmed",
    "failed": "prior run failed without closing the application",
    "failed_no_submit": "prior run reached form but submit click did not stick",
    "ats_opened": "prior run opened ATS only — form not completed",
    "ats_opened_incomplete": "prior run opened ATS but left form incomplete",
    "no_url": "prior run had no apply URL",
}


def _norm_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    return u.split("?")[0].rstrip("/").lower()


def _norm_company(c: str) -> str:
    return re.sub(r"\s+", " ", (c or "").strip().lower())


def load_jsonl() -> list[dict]:
    if not LEDGER_JSONL.exists():
        return []
    rows = []
    for line in LEDGER_JSONL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def load_strategy_results() -> list[dict]:
    if not STRATEGY_RESULTS.exists():
        return []
    try:
        data = json.loads(STRATEGY_RESULTS.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def load_complete_results() -> list[dict]:
    if not COMPLETE_RESULTS.exists():
        return []
    try:
        data = json.loads(COMPLETE_RESULTS.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _result_to_record(r: dict, *, source: str) -> dict:
    return {
        "ts": r.get("submitted_at") or r.get("ts") or "",
        "company": r.get("company", ""),
        "title": r.get("title", ""),
        "url": r.get("final_url") or r.get("ats_url") or r.get("url") or r.get("apply_url") or "",
        "status": r.get("status", ""),
        "detail": r.get("detail", ""),
        "app_id": r.get("app_id", ""),
        "source": source,
        "uploaded_cv": r.get("uploaded_cv"),
        "uploaded_certs": r.get("uploaded_certs"),
        "submitted_click": r.get("submitted_click"),
        "filled": r.get("filled"),
        "board": r.get("board", ""),
    }


def all_records() -> list[dict]:
    """Union of ledger jsonl + strategy + complete_apply (for skip decisions)."""
    out = load_jsonl()
    for r in load_strategy_results():
        out.append(_result_to_record(r, source="strategy_sectors_results"))
    for r in load_complete_results():
        out.append(_result_to_record(r, source="complete_apply_results"))
    return out


def _record_is_real_apply(r: dict) -> bool:
    st = (r.get("status") or "").strip()
    if st in DONE_STATUSES:
        return True
    if st in SOFT_DONE_IF_CV and r.get("uploaded_cv"):
        return True
    if r.get("uploaded_cv") and r.get("submitted_click"):
        return True
    return False


def _add_keys(cos: set, urls: set, ids: set, r: dict) -> None:
    c = _norm_company(r.get("company", ""))
    if c:
        cos.add(c)
    u = _norm_url(r.get("url") or r.get("apply_url") or r.get("final_url") or "")
    if u:
        urls.add(u)
    if r.get("app_id"):
        ids.add(r["app_id"])


def succeeded_sets() -> tuple[set[str], set[str], set[str]]:
    """Companies/URLs/app_ids with a closed application — block re-apply."""
    cos, urls, ids = set(), set(), set()
    try:
        from apply_metrics import collect_closed

        for app in collect_closed():
            _add_keys(cos, urls, ids, app)
    except Exception:
        pass
    for r in all_records():
        st = (r.get("status") or "").strip()
        if st not in CLOSED_STATUSES:
            continue
        _add_keys(cos, urls, ids, r)
    return cos, urls, ids


def attempted_sets() -> tuple[set[str], set[str], set[str]]:
    """Any company/url/app_id ever attempted — stats only, does not block retries."""
    cos, urls, ids = set(), set(), set()
    for r in all_records():
        st = (r.get("status") or "").strip()
        if st in ("skipped_role_filter", "skipped_already_done"):
            continue
        _add_keys(cos, urls, ids, r)
    return cos, urls, ids


def _sorted_records(records: list[dict]) -> list[dict]:
    return sorted(records, key=lambda r: (r.get("ts") or "", r.get("app_id") or ""))


def company_attempt_history(
    company: str = "",
    url: str = "",
    app_id: str = "",
    *,
    same_company_only: bool = True,
) -> list[dict]:
    """Prior ledger rows for this company (and optionally same URL/app_id)."""
    c_norm = _norm_company(company)
    u_norm = _norm_url(url)
    out: list[dict] = []
    for r in all_records():
        st = (r.get("status") or "").strip()
        if st in ("skipped_role_filter", "skipped_already_done"):
            continue
        if same_company_only and c_norm:
            if _norm_company(r.get("company", "")) != c_norm:
                continue
        if app_id and r.get("app_id") and r.get("app_id") != app_id:
            continue
        if u_norm:
            r_urls = {
                _norm_url(r.get(k) or "")
                for k in ("url", "apply_url", "final_url", "ats_url", "employer_url")
            }
            r_urls.discard("")
            if r_urls and u_norm not in r_urls:
                continue
        out.append(r)
    return _sorted_records(out)


def explain_repeat_open(
    company: str = "",
    url: str = "",
    app_id: str = "",
) -> dict:
    """Explain why we are opening a company again without a closed application."""
    history = company_attempt_history(company, url="", app_id="", same_company_only=True)
    c_norm = _norm_company(company)
    if not c_norm:
        return {
            "is_repeat": False,
            "attempt_n": 1,
            "repeat_reason": "",
            "prior_status": "",
            "prior_detail": "",
            "prior_ts": "",
            "prior_url": "",
            "same_url": False,
            "retry_policy": "first_open",
        }

    # Drop rows that already closed — those should have been skipped upstream
    open_history = [
        r
        for r in history
        if (r.get("status") or "").strip() not in CLOSED_STATUSES
    ]
    if not open_history:
        return {
            "is_repeat": False,
            "attempt_n": 1,
            "repeat_reason": "",
            "prior_status": "",
            "prior_detail": "",
            "prior_ts": "",
            "prior_url": "",
            "same_url": False,
            "retry_policy": "first_open",
        }

    prior = open_history[-1]
    attempt_n = len(open_history) + 1
    prior_st = (prior.get("status") or "").strip()
    prior_detail = (prior.get("detail") or "").strip()
    prior_url = prior.get("url") or ""
    u_norm = _norm_url(url)
    p_norm = _norm_url(prior_url)
    same_url = bool(u_norm and p_norm and u_norm == p_norm)

    base = REPEAT_REASON_BY_STATUS.get(
        prior_st,
        f"prior status '{prior_st or 'unknown'}' is not closed — retry policy allows re-open",
    )
    if not same_url and u_norm and p_norm:
        reason = (
            f"different job URL for same company; prior was {prior_st or 'unknown'} "
            f"({prior_url[:80]}) — {base}"
        )
    else:
        reason = base

    if prior_st in CLOSED_STATUSES:
        reason = f"skip miss: prior status was closed ({prior_st}) — investigate ledger"

    return {
        "is_repeat": True,
        "attempt_n": attempt_n,
        "repeat_reason": reason,
        "prior_status": prior_st,
        "prior_detail": prior_detail,
        "prior_ts": (prior.get("ts") or "")[:19],
        "prior_url": prior_url,
        "same_url": same_url,
        "retry_policy": "retry_unclosed",
    }


def summarize_queue_repeats(rows: list[dict]) -> list[dict]:
    """For each queued row, attach repeat-open metadata (does not filter)."""
    out: list[dict] = []
    for row in rows:
        company = row.get("company") or ""
        url = (
            row.get("employer_url")
            or row.get("apply_url")
            or row.get("url")
            or row.get("ats_url")
            or ""
        )
        app_id = row.get("app_id") or ""
        meta = explain_repeat_open(company, url, app_id)
        if meta.get("is_repeat"):
            out.append(
                {
                    "company": company,
                    "app_id": app_id,
                    "url": url,
                    **meta,
                }
            )
    return out


def is_already_attempted(company: str = "", url: str = "", app_id: str = "") -> tuple[bool, str]:
    """True only when a prior application was closed/succeeded — failed runs may retry."""
    cos, urls, ids = succeeded_sets()
    if app_id and app_id in ids:
        return True, "app_id already succeeded (ledger)"
    u = _norm_url(url)
    if u and u in urls:
        return True, "url already succeeded (ledger)"
    c = _norm_company(company)
    if c and c in cos:
        return True, "company already succeeded (ledger)"
    return False, ""


def filter_not_attempted(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Drop rows already succeeded. Returns (to_run, skipped)."""
    to_run: list[dict] = []
    skipped: list[dict] = []
    for row in rows:
        company = row.get("company") or ""
        app_id = row.get("app_id") or ""
        hit = False
        why = ""
        for k in ("employer_url", "apply_url", "url", "ats_url", "final_url"):
            u = row.get(k) or ""
            if not u:
                continue
            hit, why = is_already_attempted(company, u, app_id)
            if hit:
                break
        if not hit:
            hit, why = is_already_attempted(company, "", app_id)
        if hit:
            skipped.append({**row, "skip_reason": why})
        else:
            to_run.append(row)
    return to_run, skipped


def already_applied_sets() -> tuple[set[str], set[str], set[str]]:
    """Return (companies_norm, urls_norm, app_ids) that must not be re-applied.

    Only real applications (CV uploaded or confirmed submit) block retries.
    """
    cos, urls, ids = set(), set(), set()
    for r in all_records():
        if not _record_is_real_apply(r):
            continue
        c = _norm_company(r.get("company", ""))
        if c:
            cos.add(c)
        u = _norm_url(r.get("url") or r.get("apply_url") or r.get("final_url") or "")
        if u:
            urls.add(u)
        if r.get("app_id"):
            ids.add(r["app_id"])
    return cos, urls, ids


def is_already_applied(company: str = "", url: str = "", app_id: str = "") -> tuple[bool, str]:
    """True when a real apply (CV/submit) is on record — used by strategy sectors."""
    cos, urls, ids = already_applied_sets()
    if app_id and app_id in ids:
        return True, "app_id already applied (ledger)"
    if company and _norm_company(company) in cos:
        return True, "company already applied with CV/submit (ledger)"
    if url and _norm_url(url) in urls:
        return True, "url already applied (ledger)"
    return False, ""


def record_attempt(
    *,
    company: str,
    title: str = "",
    url: str = "",
    status: str = "",
    detail: str = "",
    app_id: str = "",
    sector: str = "",
    source: str = "strategy_sectors",
    uploaded_cv: bool | None = None,
    uploaded_certs: bool | None = None,
    extra: dict | None = None,
    refresh_views: bool = False,
) -> dict:
    """Append one attempt to the ledger and refresh CSV/MD views."""
    row = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "company": company,
        "title": (title or "")[:200],
        "url": url or "",
        "status": status or "",
        "detail": (detail or "")[:300],
        "app_id": app_id or "",
        "sector": sector or "",
        "source": source,
        "uploaded_cv": uploaded_cv,
        "uploaded_certs": uploaded_certs,
        "submitted_click": (extra or {}).get("submitted_click"),
        "filled": (extra or {}).get("filled"),
        "board": (extra or {}).get("board", ""),
    }
    for k in (
        "repeat_open",
        "repeat_reason",
        "attempt_n",
        "prior_status",
        "prior_detail",
        "prior_ts",
        "prior_url",
        "same_url",
        "retry_policy",
        "browser",
        "automation",
        "worker_id",
        "fill_a11y",
    ):
        if extra and k in extra:
            row[k] = extra[k]
    with LEDGER_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    if refresh_views:
        rebuild_views()
    return row


def rebuild_repeat_opens_view() -> int:
    """Companies opened 2+ times without a closed application."""
    by_co: dict[str, list[dict]] = {}
    for r in all_records():
        st = (r.get("status") or "").strip()
        if st in ("skipped_role_filter", "skipped_already_done"):
            continue
        c = _norm_company(r.get("company", ""))
        if not c:
            continue
        by_co.setdefault(c, []).append(r)

    repeats: list[dict] = []
    for c_norm, rows in by_co.items():
        rows = _sorted_records(rows)
        open_rows = [r for r in rows if (r.get("status") or "").strip() not in CLOSED_STATUSES]
        if len(open_rows) < 2:
            continue
        company = rows[-1].get("company") or c_norm
        last = open_rows[-1]
        first_open = open_rows[0]
        repeats.append(
            {
                "company": company,
                "open_count": len(open_rows),
                "total_attempts": len(rows),
                "last_status": (last.get("status") or ""),
                "last_detail": (last.get("detail") or "")[:120],
                "last_ts": (last.get("ts") or "")[:19],
                "first_ts": (first_open.get("ts") or "")[:19],
                "last_repeat_reason": last.get("repeat_reason") or explain_repeat_open(
                    company,
                    last.get("url") or "",
                    last.get("app_id") or "",
                ).get("repeat_reason", ""),
                "last_prior_status": last.get("prior_status") or "",
                "app_id": last.get("app_id") or "",
                "url": last.get("url") or "",
            }
        )

    repeats.sort(key=lambda x: (-int(x.get("open_count") or 0), (x.get("company") or "").lower()))
    REPEAT_OPENS_JSON.write_text(
        json.dumps(repeats, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    lines = [
        "# Repeat opens without closed application\n\n",
        f"Updated: {datetime.now().isoformat(timespec='seconds')}\n\n",
        "Companies opened **more than once** without `submitted_or_confirmed` / `likely_submitted`.\n",
        "Each new open logs `REPEAT OPEN` with the reason in `apply_once_each.log` and `applications_ledger.jsonl`.\n\n",
        f"**{len(repeats)}** companies with 2+ unclosed opens.\n\n",
        "| Opens | Company | Last status | Why opened again | Last when | First when |\n",
        "|------:|---------|-------------|------------------|-----------|------------|\n",
    ]
    for r in repeats:
        why = (r.get("last_repeat_reason") or "—").replace("|", "/")[:90]
        lines.append(
            f"| {r.get('open_count', '')} | {r.get('company', '')} | {r.get('last_status', '')} | "
            f"{why} | {r.get('last_ts', '')} | {r.get('first_ts', '')} |\n"
        )
    lines.append(
        "\n## Policy\n\n"
        "- **Skip** only when a prior run is **closed** (success ledger).\n"
        "- **Retry** `open_only`, `exception`, `login_required`, `partial_form_filled`, `cv_uploaded_only`.\n"
        "- Every retry records `repeat_reason` so we know why the same company was opened again.\n"
    )
    REPEAT_OPENS_MD.write_text("".join(lines), encoding="utf-8")
    return len(repeats)


def rebuild_views() -> None:
    """Latest row per company → CSV + markdown checklist."""
    records = all_records()
    # latest by company (jsonl order + strategy; prefer later ts)
    by_co: dict[str, dict] = {}
    for r in records:
        c = r.get("company") or ""
        if not c:
            continue
        key = _norm_company(c)
        prev = by_co.get(key)
        if not prev or (r.get("ts") or "") >= (prev.get("ts") or ""):
            by_co[key] = r

    rows = sorted(by_co.values(), key=lambda x: (x.get("company") or "").lower())
    fields = [
        "ts",
        "company",
        "status",
        "title",
        "url",
        "sector",
        "app_id",
        "uploaded_cv",
        "uploaded_certs",
        "detail",
        "source",
    ]
    with LEDGER_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})

    lines = [
        "# Applied / attempted companies (do not re-apply)\n\n",
        f"Updated: {datetime.now().isoformat(timespec='seconds')}\n\n",
        f"Unique companies on record: **{len(rows)}**\n\n",
        "| # | Company | Status | CV | Certs | When | Title |\n",
        "|---|---------|--------|:--:|:-----:|------|-------|\n",
    ]
    for i, r in enumerate(rows, 1):
        cv = "✓" if r.get("uploaded_cv") else ""
        cert = "✓" if r.get("uploaded_certs") else ""
        title = (r.get("title") or "")[:50].replace("|", "/")
        lines.append(
            f"| {i} | {r.get('company','')} | {r.get('status','')} | {cv} | {cert} | "
            f"{(r.get('ts') or '')[:19]} | {title} |\n"
        )
    lines.append(
        "\n## Rule\n\n"
        "Any company listed here has already been attempted. "
        "Apply scripts **must skip** these (company / URL / app_id).\n"
        "Override only with `STRATEGY_FORCE_RETRY=1`.\n\n"
        f"Sources: `{LEDGER_JSONL.name}`, `{STRATEGY_RESULTS.name}`, `{COMPLETE_RESULTS.name}`\n"
    )
    LEDGER_MD.write_text("".join(lines), encoding="utf-8")
    rebuild_repeat_opens_view()


def bootstrap_from_complete_apply() -> int:
    """Ensure every complete_apply result is also in jsonl."""
    existing = load_jsonl()
    seen = {
        (
            _norm_company(r.get("company", "")),
            r.get("status", ""),
            _norm_url(r.get("url", "")),
            r.get("app_id", ""),
        )
        for r in existing
    }
    added = 0
    for r in load_complete_results():
        key = (
            _norm_company(r.get("company", "")),
            r.get("status", ""),
            _norm_url(r.get("final_url") or r.get("ats_url") or r.get("url") or ""),
            r.get("app_id", ""),
        )
        if key in seen or not (r.get("company") or r.get("url") or r.get("app_id")):
            continue
        rec = _result_to_record(r, source="bootstrap_complete_apply")
        rec["ts"] = datetime.now().isoformat(timespec="seconds")
        with LEDGER_JSONL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        seen.add(key)
        added += 1
    if added:
        rebuild_views()
    return added


def bootstrap_from_strategy() -> int:
    """One-time / on-start: ensure every strategy result is also in jsonl."""
    existing = load_jsonl()
    seen = {
        ( _norm_company(r.get("company","")), r.get("status",""), _norm_url(r.get("url","")), r.get("app_id","") )
        for r in existing
    }
    added = 0
    for r in load_strategy_results():
        key = (
            _norm_company(r.get("company", "")),
            r.get("status", ""),
            _norm_url(r.get("url") or r.get("final_url") or ""),
            r.get("app_id", ""),
        )
        if key in seen or not r.get("company"):
            continue
        with LEDGER_JSONL.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "ts": datetime.now().isoformat(timespec="seconds"),
                        "company": r.get("company", ""),
                        "title": (r.get("title") or "")[:200],
                        "url": r.get("url") or r.get("final_url") or "",
                        "status": r.get("status", ""),
                        "detail": (r.get("detail") or "")[:300],
                        "app_id": r.get("app_id", ""),
                        "sector": r.get("sector", ""),
                        "source": "bootstrap_strategy_results",
                        "uploaded_cv": r.get("uploaded_cv"),
                        "uploaded_certs": r.get("uploaded_certs"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        seen.add(key)
        added += 1
    rebuild_views()
    return added


if __name__ == "__main__":
    n1 = bootstrap_from_strategy()
    n2 = bootstrap_from_complete_apply()
    rebuild_views()
    attempted = attempted_sets()
    applied = already_applied_sets()
    print(f"bootstrap strategy={n1} complete_apply={n2}")
    print(f"attempted companies={len(attempted[0])} urls={len(attempted[1])} app_ids={len(attempted[2])}")
    print(f"real-apply companies={len(applied[0])} urls={len(applied[1])} app_ids={len(applied[2])}")
    n_rep = rebuild_repeat_opens_view()
    print(f"wrote {LEDGER_CSV} {LEDGER_MD} {REPEAT_OPENS_MD} ({n_rep} repeat companies)")
