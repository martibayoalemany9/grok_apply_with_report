#!/usr/bin/env python3
"""Generate applications_dashboard.html — one row per application with progress bars."""
from __future__ import annotations

import csv
import html
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

W = Path(__file__).resolve().parent
OUT = W / "applications_dashboard.html"

STATUS_PROGRESS = {
    "submitted_or_confirmed": 100,
    "likely_submitted": 90,
    "partial_form_filled": 65,
    "cv_uploaded_only": 55,
    "login_required": 35,
    "open_only": 25,
    "ats_opened": 20,
    "ats_opened_incomplete": 30,
    "stuck_on_board": 15,
    "skipped_stuck_same_behaviour": 40,
    "skipped_stuck_on_board": 15,
    "skipped_no_company_careers": 10,
    "skipped_time_budget": 45,
    "skipped_prior_fail": 5,
    "skipped_already_done": 100,
    "skipped_cv_fit": 0,
    "skipped_no_software_keyword": 0,
    "skipped_role_filter": 0,
    "job_closed": 5,
    "exception": 10,
    "failed": 10,
    "failed_no_submit": 40,
    "no_url": 0,
    "queued": 5,
}

STATUS_LABEL = {
    "submitted_or_confirmed": "Submitted / confirmed",
    "likely_submitted": "Likely submitted (CV on form)",
    "partial_form_filled": "Partial form filled",
    "cv_uploaded_only": "CV uploaded only",
    "login_required": "Login wall",
    "open_only": "Opened only (no CV)",
    "skipped_stuck_same_behaviour": "Stuck (no progress)",
    "skipped_cv_fit": "Skipped — CV fit",
    "skipped_no_software_keyword": "Skipped — not software",
    "skipped_prior_fail": "Skipped — prior fail",
    "job_closed": "Job closed",
    "exception": "Error / exception",
    "queued": "Queued",
}


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def progress_for(status: str, uploaded_cv=False, filled=0, submitted=False) -> int:
    base = STATUS_PROGRESS.get((status or "").lower(), 15)
    if uploaded_cv:
        base = max(base, 55)
    if filled:
        try:
            base = max(base, min(85, 40 + int(filled) * 2))
        except Exception:
            pass
    if submitted or (status or "").lower() in ("likely_submitted", "submitted_or_confirmed"):
        base = max(base, 88 if (status or "").lower() == "likely_submitted" else 100)
    return min(100, max(0, int(base)))


def why_selected(title: str, company: str, board: str, source_note: str, status: str) -> str:
    reasons = []
    blob = f"{title} {company} {source_note or ''}".lower()
    if re.search(r"\bsoftware\b", blob):
        reasons.append("Title contains <b>software</b> (required keyword).")
    if re.search(r"java|kotlin|rust|python|backend|devops|platform", blob):
        reasons.append("Software-related stack (Java/Kotlin/Rust/Python/backend/DevOps/platform).")
    if re.search(r"\blead\b|senior|staff|principal|architect|director|manager|head of|technology lead", blob):
        reasons.append("Seniority signal: senior / lead / staff / architect / director.")
    if re.search(r"company_careers|careers_map|no_efc", blob):
        reasons.append("Resolved to <b>company careers</b> site (not eFinancialCareers apply).")
    if "efc" in (board or "").lower() or "efinancial" in blob or "alert" in blob:
        reasons.append("Discovered via job alert / eFC listing (company+title source only).")
    if "fit=" in blob or "cv_fit" in blob or "skills=" in blob:
        m = re.search(r"fit=([^;]+)", source_note or "")
        if m:
            reasons.append(f"CV-fit gate (0020_raw): <code>{esc(m.group(1).strip())}</code>.")
        else:
            reasons.append("Passed CV-fit gate against <b>0020_raw</b> résumé.")
    if re.search(r"intern|werkstudent|praktikum|junior|duales|student", blob):
        reasons.append("⚠ Would normally be excluded (student/junior) — check status.")
    if not reasons:
        if status and "skip" in status.lower():
            reasons.append("Attempted or filtered during batch; see status for outcome.")
        else:
            reasons.append("Included in automated senior software apply pipeline.")
    reasons.append(
        "Uploads when applying: <b>0020_raw</b> CV + <b>ETSETB academic</b> + "
        "<b>2020 work certificates</b>; degree year <b>2003</b>."
    )
    return " ".join(f"<li>{r}</li>" for r in reasons)


def index_screenshots() -> dict[str, list[str]]:
    """Map app_id / company tokens → relative screenshot paths under screenshots/ and offer_screenshots/."""
    by_key: dict[str, list[str]] = defaultdict(list)
    for sub in ("screenshots", "offer_screenshots"):
        d = W / sub
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.png"), key=lambda x: x.stat().st_mtime, reverse=True):
            rel = f"{sub}/{p.name}"
            stem = p.stem.lower()
            by_key[stem].append(rel)
            # also index by app_id-like tokens (e.g. complete_ET-0012, cdp_ET-0001)
            for part in re.split(r"[_\-]+", stem):
                if len(part) >= 4:
                    by_key[part].append(rel)
    # de-dupe preserving order
    for k, v in list(by_key.items()):
        seen = set()
        out = []
        for x in v:
            if x not in seen:
                seen.add(x)
                out.append(x)
        by_key[k] = out
    return by_key


def shots_for_row(r: dict, shot_index: dict[str, list[str]]) -> list[str]:
    found: list[str] = []
    app_id = (r.get("app_id") or "").strip().lower()
    company = re.sub(r"[^a-z0-9]+", "", (r.get("company") or "").lower())
    candidates = []
    if app_id:
        candidates.append(app_id)
        candidates.append(app_id.replace("-", "_"))
        candidates.append(app_id.replace("_", "-"))
    if company and len(company) >= 4:
        candidates.append(company[:24])
    for c in candidates:
        for path in shot_index.get(c, []):
            if path not in found:
                found.append(path)
        # partial stem match
        for stem, paths in shot_index.items():
            if c and c in stem:
                for path in paths:
                    if path not in found:
                        found.append(path)
    return found[:6]


def load_all() -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    def add(r: dict, origin: str):
        co = (r.get("company") or "").strip()
        title = (r.get("title") or "").strip()
        if not co and not title:
            return
        url = (r.get("final_url") or r.get("ats_url") or r.get("apply_url") or r.get("url") or "").strip()
        key = (co.lower(), title.lower()[:80], (r.get("status") or "")[:40])
        # allow multiple statuses per job over time but prefer richer
        status = r.get("status") or "unknown"
        ts = r.get("ts") or r.get("timestamp") or r.get("ended_at") or ""
        prog = progress_for(
            status,
            uploaded_cv=bool(r.get("uploaded_cv")),
            filled=r.get("filled") or r.get("fields_filled") or 0,
            submitted=bool(r.get("submitted") or r.get("submitted_click") or r.get("succeeded")),
        )
        item = {
            "company": co or "—",
            "title": title or "—",
            "status": status,
            "status_label": STATUS_LABEL.get(status, status.replace("_", " ")),
            "progress": prog,
            "ts": ts or "—",
            "duration": r.get("duration_s") or "",
            "board": r.get("board") or "",
            "url": url,
            "uploaded_cv": bool(r.get("uploaded_cv")),
            "uploaded_certs": bool(r.get("uploaded_certs") or r.get("certs")),
            "filled": r.get("filled") or r.get("fields_filled") or 0,
            "detail": (r.get("detail") or r.get("lesson") or "")[:220],
            "source_note": r.get("source_note") or "",
            "app_id": r.get("app_id") or "",
            "origin": origin,
            "search_query": r.get("search_query") or "",
            "careers_url": r.get("careers_url") or r.get("employer_url") or "",
        }
        # merge: keep higher progress for same company+title
        mkey = (co.lower(), title.lower()[:80])
        for i, existing in enumerate(rows):
            if (existing["company"].lower(), existing["title"].lower()[:80]) == mkey:
                if prog >= existing["progress"]:
                    # keep best ts if newer
                    if ts and (existing["ts"] == "—" or str(ts) >= str(existing["ts"])):
                        rows[i] = item
                    elif prog > existing["progress"]:
                        rows[i] = item
                return
        rows.append(item)

    # 1) complete_apply_results.json
    p = W / "complete_apply_results.json"
    if p.exists():
        try:
            for r in json.loads(p.read_text(encoding="utf-8")):
                add(r, "complete_apply_results")
        except Exception:
            pass

    # 2) application_protocol.jsonl (adds timestamps)
    p = W / "application_protocol.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                o = json.loads(line)
            except Exception:
                continue
            add(o, "protocol")

    # 3) company careers queue (queued future)
    p = W / "applications_company_careers.csv"
    if p.exists():
        for r in csv.DictReader(p.open(encoding="utf-8")):
            r = dict(r)
            r.setdefault("status", r.get("status") or "queued")
            add(r, "company_careers_queue")

    # 4) other application CSVs for volume
    for name in (
        "applications_email_alerts_2d_software.csv",
        "applications_email_alerts_merged.csv",
        "applications_software_rings_cvfit.csv",
        "applications_efc_real_jobs.csv",
        "applications_complete_apply.csv",
    ):
        p = W / name
        if not p.exists():
            continue
        try:
            for r in csv.DictReader(p.open(encoding="utf-8")):
                r = dict(r)
                if not r.get("status"):
                    r["status"] = "queued"
                add(r, name)
        except Exception:
            continue

    # sort: by progress desc then company
    rows.sort(key=lambda x: (-x["progress"], x["company"].lower(), x["title"].lower()))
    return rows


def bar_class(p: int) -> str:
    if p >= 88:
        return "ok"
    if p >= 50:
        return "mid"
    if p >= 25:
        return "low"
    return "none"


def render(rows: list[dict]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n = len(rows)
    n_ok = sum(1 for r in rows if r["progress"] >= 88)
    n_cv = sum(1 for r in rows if r["uploaded_cv"])
    n_mid = sum(1 for r in rows if 40 <= r["progress"] < 88)
    n_fail = sum(1 for r in rows if r["progress"] < 40)
    shot_index = index_screenshots()
    n_shots = sum(1 for r in rows if shots_for_row(r, shot_index))
    all_shot_count = sum(len(list((W / s).glob("*.png"))) for s in ("screenshots", "offer_screenshots") if (W / s).is_dir())

    cards = []
    for i, r in enumerate(rows, 1):
        p = r["progress"]
        bc = bar_class(p)
        docs = []
        if r["uploaded_cv"]:
            docs.append("CV✓")
        if r["uploaded_certs"]:
            docs.append("Certs✓")
        if r["filled"]:
            docs.append(f"fields={r['filled']}")
        docs_s = " · ".join(docs) if docs else "—"
        url = r["url"] or r["careers_url"]
        url_html = (
            f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(url[:90])}{"…" if len(url) > 90 else ""}</a>'
            if url
            else "—"
        )
        why = why_selected(r["title"], r["company"], r["board"], r["source_note"], r["status"])
        ts_end = esc(r["ts"])
        dur = f" · {esc(r['duration'])}s" if r["duration"] else ""
        shots = shots_for_row(r, shot_index)
        if shots:
            thumbs = "".join(
                f'<a class="shot" href="/{esc(s)}" target="_blank" rel="noopener">'
                f'<img src="/{esc(s)}" alt="screenshot" loading="lazy"/></a>'
                for s in shots
            )
            shot_html = f'<div class="shots"><span class="shots-label">Screenshots</span><div class="shot-row">{thumbs}</div></div>'
        else:
            shot_html = ""
        cards.append(
            f"""
<article class="row" data-progress="{p}" data-status="{esc(r['status'])}" data-company="{esc(r['company']).lower()}">
  <div class="idx">#{i:03d}</div>
  <div class="main">
    <div class="topline">
      <h2>{esc(r['company'])}</h2>
      <span class="badge {bc}">{esc(r['status_label'])}</span>
    </div>
    <div class="title">{esc(r['title'])}</div>
    <div class="meta">
      <span>board: {esc(r['board'] or '—')}</span>
      <span>docs: {esc(docs_s)}</span>
      <span>id: {esc(r['app_id'] or '—')}</span>
      <span>source: {esc(r['origin'])}</span>
    </div>
    <div class="bar-wrap" title="{p}%">
      <div class="bar {bc}" style="width:{p}%"></div>
      <span class="pct">{p}%</span>
    </div>
    {shot_html}
    <details class="why">
      <summary>Why this offer was selected</summary>
      <ul>{why}</ul>
      {f'<p class="detail">Detail: {esc(r["detail"])}</p>' if r['detail'] else ''}
      {f'<p class="detail">Search query: <code>{esc(r["search_query"])}</code></p>' if r['search_query'] else ''}
    </details>
    <div class="url">{url_html}</div>
  </div>
  <div class="ts">
    <div class="ts-label">Timestamp</div>
    <time>{ts_end}</time>
    <div class="dur">{dur.strip(' ·') if dur else ''}</div>
  </div>
</article>"""
        )

    body_rows = "\n".join(cards)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Job applications dashboard — {n} offers</title>
<style>
  :root {{
    --bg: #0b1020;
    --panel: #141b2d;
    --panel2: #1a2338;
    --text: #e8eefc;
    --muted: #9aabcb;
    --line: #2a3550;
    --ok: #22c55e;
    --mid: #eab308;
    --low: #f97316;
    --none: #64748b;
    --accent: #38bdf8;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
    background: radial-gradient(1200px 600px at 10% -10%, #1e3a5f 0%, transparent 50%),
                radial-gradient(900px 500px at 100% 0%, #312e81 0%, transparent 45%),
                var(--bg);
    color: var(--text); line-height: 1.45;
  }}
  header {{
    padding: 28px 24px 12px; max-width: 1200px; margin: 0 auto;
  }}
  header h1 {{ margin: 0 0 8px; font-size: 1.65rem; letter-spacing: -0.02em; }}
  header p {{ margin: 0; color: var(--muted); max-width: 70ch; }}
  .stats {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px; max-width: 1200px; margin: 16px auto 8px; padding: 0 24px;
  }}
  .stat {{
    background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
    padding: 14px 16px;
  }}
  .stat b {{ display: block; font-size: 1.5rem; }}
  .stat span {{ color: var(--muted); font-size: 0.85rem; }}
  .toolbar {{
    max-width: 1200px; margin: 12px auto; padding: 0 24px;
    display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  }}
  .toolbar input, .toolbar select {{
    background: var(--panel); border: 1px solid var(--line); color: var(--text);
    border-radius: 8px; padding: 8px 12px; font-size: 0.95rem;
  }}
  .toolbar input {{ flex: 1; min-width: 200px; }}
  #list {{ max-width: 1200px; margin: 0 auto 48px; padding: 8px 24px; display: flex; flex-direction: column; gap: 12px; }}
  .row {{
    display: grid; grid-template-columns: 56px 1fr 150px; gap: 12px;
    background: linear-gradient(180deg, var(--panel) 0%, var(--panel2) 100%);
    border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px;
    box-shadow: 0 8px 24px rgba(0,0,0,.25);
  }}
  .idx {{ color: var(--muted); font-variant-numeric: tabular-nums; font-size: 0.85rem; padding-top: 4px; }}
  .topline {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: space-between; }}
  .topline h2 {{ margin: 0; font-size: 1.05rem; }}
  .title {{ color: #dbe7ff; margin: 4px 0 8px; font-weight: 500; }}
  .meta {{ display: flex; flex-wrap: wrap; gap: 10px 14px; color: var(--muted); font-size: 0.8rem; margin-bottom: 8px; }}
  .badge {{
    font-size: 0.75rem; font-weight: 600; padding: 3px 8px; border-radius: 999px;
    border: 1px solid var(--line);
  }}
  .badge.ok {{ background: rgba(34,197,94,.15); color: #86efac; border-color: rgba(34,197,94,.35); }}
  .badge.mid {{ background: rgba(234,179,8,.12); color: #fde047; border-color: rgba(234,179,8,.35); }}
  .badge.low {{ background: rgba(249,115,22,.12); color: #fdba74; border-color: rgba(249,115,22,.35); }}
  .badge.none {{ background: rgba(100,116,139,.15); color: #cbd5e1; }}
  .bar-wrap {{
    position: relative; height: 18px; background: #0f172a; border-radius: 999px;
    border: 1px solid var(--line); overflow: hidden; margin: 6px 0 10px;
  }}
  .bar {{ height: 100%; border-radius: 999px; transition: width .4s ease; }}
  .bar.ok {{ background: linear-gradient(90deg, #15803d, var(--ok)); }}
  .bar.mid {{ background: linear-gradient(90deg, #a16207, var(--mid)); }}
  .bar.low {{ background: linear-gradient(90deg, #c2410c, var(--low)); }}
  .bar.none {{ background: linear-gradient(90deg, #475569, var(--none)); }}
  .pct {{
    position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
    font-size: 0.72rem; font-weight: 700; color: #fff; text-shadow: 0 1px 2px #000;
  }}
  .why {{ margin: 4px 0; }}
  .why summary {{ cursor: pointer; color: var(--accent); font-size: 0.9rem; }}
  .why ul {{ margin: 8px 0 0; padding-left: 1.2rem; color: #c5d4f0; font-size: 0.88rem; }}
  .why li {{ margin: 4px 0; }}
  .detail {{ color: var(--muted); font-size: 0.82rem; margin: 6px 0 0; }}
  .url {{ font-size: 0.78rem; margin-top: 6px; word-break: break-all; }}
  .url a {{ color: #7dd3fc; text-decoration: none; }}
  .url a:hover {{ text-decoration: underline; }}
  .ts {{
    border-left: 1px solid var(--line); padding-left: 12px;
    font-variant-numeric: tabular-nums; font-size: 0.82rem;
  }}
  .ts-label {{ color: var(--muted); font-size: 0.72rem; text-transform: uppercase; letter-spacing: .04em; }}
  time {{ display: block; margin-top: 4px; color: #e2e8f0; }}
  .dur {{ color: var(--muted); margin-top: 6px; }}
  .shots {{ margin: 8px 0 4px; }}
  .shots-label {{ display:block; color: var(--muted); font-size: 0.72rem; text-transform: uppercase; letter-spacing: .04em; margin-bottom: 6px; }}
  .shot-row {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .shot {{ display:block; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: #0f172a; }}
  .shot img {{ display:block; width: 160px; height: 100px; object-fit: cover; }}
  .shot:hover {{ border-color: var(--accent); }}
  section.faq {{
    max-width: 1200px; margin: 0 auto 64px; padding: 0 24px;
  }}
  section.faq h2 {{ margin-top: 32px; }}
  section.faq .card {{
    background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
    padding: 18px 20px; margin: 12px 0; color: #d5e0f5;
  }}
  section.faq code {{ background: #0f172a; padding: 1px 6px; border-radius: 4px; }}
  footer {{ text-align: center; color: var(--muted); padding: 24px; font-size: 0.85rem; }}
  @media (max-width: 800px) {{
    .row {{ grid-template-columns: 40px 1fr; }}
    .ts {{ grid-column: 1 / -1; border-left: none; border-top: 1px solid var(--line); padding: 10px 0 0; }}
  }}
</style>
</head>
<body>
<header>
  <h1>Job applications dashboard</h1>
  <p>
    One row per application attempt / offer in the local pipeline.
    Progress reflects how far automation got (open → CV upload → form fill → submit).
    Screenshots stored under <code>screenshots/</code> and <code>offer_screenshots/</code> after each apply attempt.
    Generated <b>{esc(now)}</b> · <b>{n}</b> rows · docs: <b>0020_raw</b> + ETSETB academic + work certs <b>2020</b> · degree <b>2003</b>.
  </p>
</header>

<div class="stats">
  <div class="stat"><b>{n}</b><span>Total offers / rows</span></div>
  <div class="stat"><b>{n_ok}</b><span>≥88% likely / submitted</span></div>
  <div class="stat"><b>{n_cv}</b><span>CV uploaded</span></div>
  <div class="stat"><b>{n_mid}</b><span>In progress (40–87%)</span></div>
  <div class="stat"><b>{n_fail}</b><span>Low progress (&lt;40%)</span></div>
  <div class="stat"><b>{n_shots}</b><span>Rows with screenshots</span></div>
  <div class="stat"><b>{all_shot_count}</b><span>PNG files on disk</span></div>
</div>

<div class="toolbar">
  <input id="q" type="search" placeholder="Filter company, title, status…"/>
  <select id="filterStatus">
    <option value="">All statuses</option>
    <option value="high">High progress (≥88%)</option>
    <option value="mid">Mid (40–87)</option>
    <option value="low">Low (&lt;40)</option>
    <option value="cv">CV uploaded</option>
  </select>
  <span id="shown" style="color:var(--muted);font-size:0.9rem"></span>
</div>

<div id="list">
{body_rows}
</div>

<section class="faq">
  <h2>How selection works</h2>
  <div class="card">
    <p><b>Discovery:</b> Job alerts (Gmail / eFinancialCareers emails) and eFC search give a list of
    <em>company + job title</em>. We do <b>not</b> fill forms on eFinancialCareers anymore.</p>
    <p><b>Filter:</b> Keep software-related senior/professional roles only. Drop internship, Werkstudent,
    Duales Studium, junior, facility, pure sales/HR. Fit is scored against the <code>0020_raw</code> CV.</p>
    <p><b>Resolve:</b> Map company → official careers / ATS (SmartRecruiters, Workday, Merck careers, …)
    via <code>company_careers.py</code>, then search the job title on that site.</p>
    <p><b>Apply:</b> Upload <code>0020_raw</code> CV + <code>etsetb_with</code> academic certificates +
    <code>2020</code> work certificates; degree year <code>2003</code>; chatbots off.
    Progress bar advances as CV/certs attach, fields fill, and submit is clicked.
    Screenshots are saved after each attempt and shown on this page when the local server is running.</p>
  </div>

  <h2>Do you need Playwright?</h2>
  <div class="card">
    <p><b>No — Playwright is not mandatory.</b> It is what this pipeline uses today because it:</p>
    <ul>
      <li>Drives a real browser (Chromium) with file uploads, multi-step ATS forms, and CDP attach</li>
      <li>Handles modern SPAs (Workday, SmartRecruiters, Greenhouse) better than pure HTTP clients</li>
      <li>Works with Robot Framework as an outer runner (<code>robot/*.robot</code>)</li>
    </ul>
    <p>You can replace or complement it with other automation frameworks:</p>
    <table style="width:100%;border-collapse:collapse;font-size:0.9rem">
      <tr style="text-align:left;border-bottom:1px solid var(--line)">
        <th style="padding:8px">Framework</th><th>Use case</th><th>Notes</th>
      </tr>
      <tr style="border-bottom:1px solid var(--line)">
        <td style="padding:8px"><b>Playwright</b> (current)</td>
        <td style="padding:8px">Browser apply automation</td>
        <td style="padding:8px">Best multi-browser ATS support; CDP Chromium on :9223</td>
      </tr>
      <tr style="border-bottom:1px solid var(--line)">
        <td style="padding:8px"><b>Selenium / SeleniumBase</b></td>
        <td style="padding:8px">Same class of browser automation</td>
        <td style="padding:8px">Wider corporate adoption; often slower / more brittle</td>
      </tr>
      <tr style="border-bottom:1px solid var(--line)">
        <td style="padding:8px"><b>Puppeteer / pyppeteer</b></td>
        <td style="padding:8px">Chrome-only automation</td>
        <td style="padding:8px">Similar to Playwright’s Chrome path</td>
      </tr>
      <tr style="border-bottom:1px solid var(--line)">
        <td style="padding:8px"><b>Robot Framework</b> (+ Browser/Selenium lib)</td>
        <td style="padding:8px">Test/ops orchestration</td>
        <td style="padding:8px">Already used as thin runner around Python apply scripts</td>
      </tr>
      <tr style="border-bottom:1px solid var(--line)">
        <td style="padding:8px"><b>Browser-use / agentic tools</b></td>
        <td style="padding:8px">LLM-driven clicking</td>
        <td style="padding:8px">Flexible but less deterministic for mass apply</td>
      </tr>
      <tr>
        <td style="padding:8px"><b>HTTP/API only</b> (requests)</td>
        <td style="padding:8px">Rare ATS with public APIs</td>
        <td style="padding:8px">Cannot handle most careers UIs / uploads / CAPTCHAs alone</td>
      </tr>
    </table>
    <p style="margin-top:12px">Practical recommendation: keep <b>Playwright (or Selenium)</b> for form apply;
    keep <b>Robot Framework</b> for suite orchestration; keep eFC/Gmail only as a <em>job list source</em>.</p>
  </div>
</section>

<footer>
  Local tracker · no credentials embedded · serve with
  <code>python3 serve_applications_dashboard.py</code>
  (http://127.0.0.1:8765/) · regenerate with
  <code>python3 generate_applications_dashboard.py</code>
</footer>

<script>
const q = document.getElementById('q');
const sel = document.getElementById('filterStatus');
const rows = [...document.querySelectorAll('.row')];
const shown = document.getElementById('shown');
function applyFilter() {{
  const text = (q.value || '').toLowerCase();
  const mode = sel.value;
  let n = 0;
  for (const el of rows) {{
    const hay = el.innerText.toLowerCase();
    const p = Number(el.dataset.progress || 0);
    const cv = hay.includes('cv✓') || hay.includes('docs: cv');
    let ok = !text || hay.includes(text);
    if (ok && mode === 'high') ok = p >= 88;
    if (ok && mode === 'mid') ok = p >= 40 && p < 88;
    if (ok && mode === 'low') ok = p < 40;
    if (ok && mode === 'cv') ok = el.innerText.includes('CV✓');
    el.style.display = ok ? '' : 'none';
    if (ok) n++;
  }}
  shown.textContent = n + ' / ' + rows.length + ' shown';
}}
q.addEventListener('input', applyFilter);
sel.addEventListener('change', applyFilter);
applyFilter();
</script>
</body>
</html>
"""


def main() -> None:
    rows = load_all()
    OUT.write_text(render(rows), encoding="utf-8")
    print(f"Wrote {OUT} with {len(rows)} application rows")
    print(f"  open file://{OUT}")


if __name__ == "__main__":
    main()
