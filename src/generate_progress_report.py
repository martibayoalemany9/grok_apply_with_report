#!/usr/bin/env python3
"""Generate applications_progress_report.html — success / fail progress for localhost.

  python3 generate_progress_report.py
  → applications_progress_report.html  (meta-refresh every 10 minutes)
"""
from __future__ import annotations

import html
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

W = Path(__file__).resolve().parent
LEDGER = W / "applications_ledger.jsonl"
OUT = W / "applications_progress_report.html"
RESULTS = W / "complete_apply_results.json"
REFRESH_SEC = int(__import__("os").environ.get("PROGRESS_REFRESH_SEC", "600"))  # 10 min

SUCCESS = frozenset(
    {
        "submitted",
        "submitted_or_confirmed",
        "likely_submitted",
        "succeeded",
        "done",
        "skipped_already_done",  # already closed success
    }
)
FAIL = frozenset(
    {
        "exception",
        "failed",
        "failed_no_submit",
        "job_closed",
        "login_required",
        "stuck_on_board",
        "skipped_stuck_same_behaviour",
        "skipped_stuck_on_board",
        "skipped_time_budget",
        "skipped_prior_fail",
        "no_url",
    }
)
SKIP = frozenset(
    {
        "skipped_cv_fit",
        "skipped_no_software_keyword",
        "skipped_role_filter",
        "skipped_no_company_careers",
        "skipped_student_academic",
        "skipped_never_apply",
    }
)
PROGRESS = frozenset(
    {
        "partial_form_filled",
        "cv_uploaded_only",
        "open_only",
        "ats_opened",
        "ats_opened_incomplete",
        "queued",
    }
)


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def host(u: str) -> str:
    try:
        return urlparse(u or "").netloc.lower() or "—"
    except Exception:
        return "—"


def load_ledger() -> list[dict]:
    rows = []
    if not LEDGER.exists():
        return rows
    for line in LEDGER.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def bucket(status: str) -> str:
    s = (status or "").lower()
    if s in SUCCESS:
        return "success"
    if s in FAIL:
        return "fail"
    if s in SKIP:
        return "skip"
    if s in PROGRESS:
        return "progress"
    if "submit" in s or "success" in s:
        return "success"
    if "skip" in s or "fail" in s or "exception" in s or "stuck" in s:
        return "fail"
    return "other"


def latest_per_key(rows: list[dict]) -> list[dict]:
    """Keep latest attempt per company+url."""
    by: dict[str, dict] = {}
    for r in rows:
        key = (
            (r.get("url") or r.get("final_url") or r.get("apply_url") or "").strip().lower()
            or f"{r.get('company')}|{r.get('title')}"
        )
        prev = by.get(key)
        ts = r.get("ts") or r.get("timestamp") or ""
        if not prev or ts >= (prev.get("ts") or ""):
            by[key] = r
    return list(by.values())


def main() -> None:
    raw = load_ledger()
    rows = latest_per_key(raw)
    by_b: dict[str, list] = defaultdict(list)
    for r in rows:
        by_b[bucket(r.get("status") or "")].append(r)

    success = sorted(
        by_b["success"],
        key=lambda r: r.get("ts") or "",
        reverse=True,
    )
    fail = sorted(by_b["fail"], key=lambda r: r.get("ts") or "", reverse=True)
    progress = sorted(by_b["progress"], key=lambda r: r.get("ts") or "", reverse=True)
    skip = sorted(by_b["skip"], key=lambda r: r.get("ts") or "", reverse=True)
    other = sorted(by_b["other"], key=lambda r: r.get("ts") or "", reverse=True)

    status_counts = Counter((r.get("status") or "unknown") for r in rows)
    total = len(rows)
    n_ok = len(success)
    n_fail = len(fail)
    n_prog = len(progress)
    n_skip = len(skip)
    rate = (100.0 * n_ok / total) if total else 0.0
    now = datetime.now().isoformat(timespec="seconds")

    # screenshots index
    shot_dir = W / "screenshots"
    shots = sorted(shot_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)[
        :24
    ] if shot_dir.is_dir() else []

    def rows_table(items: list[dict], limit: int = 80) -> str:
        if not items:
            return "<p class='empty'>None yet.</p>"
        parts = [
            "<table><thead><tr>"
            "<th>When</th><th>Company</th><th>Title</th><th>Status</th>"
            "<th>Host</th><th>Detail</th>"
            "</tr></thead><tbody>"
        ]
        for r in items[:limit]:
            parts.append(
                "<tr>"
                f"<td class='mono'>{esc((r.get('ts') or '')[:19])}</td>"
                f"<td>{esc((r.get('company') or '')[:40])}</td>"
                f"<td>{esc((r.get('title') or '')[:70])}</td>"
                f"<td><span class='pill'>{esc(r.get('status') or '')}</span></td>"
                f"<td class='mono'>{esc(host(r.get('url') or r.get('final_url') or ''))}</td>"
                f"<td class='detail'>{esc((r.get('detail') or r.get('message') or '')[:120])}</td>"
                "</tr>"
            )
        if len(items) > limit:
            parts.append(
                f"<tr><td colspan='6' class='muted'>… and {len(items)-limit} more</td></tr>"
            )
        parts.append("</tbody></table>")
        return "\n".join(parts)

    status_bars = []
    for st, n in status_counts.most_common(15):
        pct = 100.0 * n / total if total else 0
        status_bars.append(
            f"<div class='bar-row'><span class='bar-label'>{esc(st)}</span>"
            f"<div class='bar'><i style='width:{pct:.1f}%'></i></div>"
            f"<span class='bar-n'>{n}</span></div>"
        )

    shot_html = ""
    if shots:
        figs = []
        for p in shots:
            rel = f"screenshots/{p.name}"
            figs.append(
                f"<figure><a href='/{esc(rel)}' target='_blank'>"
                f"<img src='/{esc(rel)}' alt='{esc(p.name)}' loading='lazy'/>"
                f"</a><figcaption class='mono'>{esc(p.name[:40])}</figcaption></figure>"
            )
        shot_html = "<div class='shots'>" + "\n".join(figs) + "</div>"
    else:
        shot_html = "<p class='empty'>No screenshots yet.</p>"

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta http-equiv="refresh" content="{REFRESH_SEC}"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Job apply progress — success / fail</title>
  <style>
    :root {{
      --bg: #0f1419;
      --card: #1a2332;
      --text: #e7ecf3;
      --muted: #8b9bb4;
      --ok: #3dd68c;
      --fail: #f07178;
      --prog: #59c2ff;
      --skip: #c4a35a;
      --border: #2a3548;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif;
      background: var(--bg); color: var(--text); line-height: 1.45;
    }}
    header {{
      padding: 1.25rem 1.5rem; border-bottom: 1px solid var(--border);
      background: linear-gradient(180deg, #1a2740 0%, var(--bg) 100%);
      position: sticky; top: 0; z-index: 10;
    }}
    h1 {{ margin: 0 0 .35rem; font-size: 1.35rem; font-weight: 650; }}
    .meta {{ color: var(--muted); font-size: .9rem; }}
    .meta a {{ color: var(--prog); }}
    main {{ padding: 1.25rem 1.5rem 3rem; max-width: 1400px; margin: 0 auto; }}
    .kpis {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: .75rem; margin-bottom: 1.25rem;
    }}
    .kpi {{
      background: var(--card); border: 1px solid var(--border); border-radius: 12px;
      padding: 1rem;
    }}
    .kpi .n {{ font-size: 1.75rem; font-weight: 700; letter-spacing: -.02em; }}
    .kpi .l {{ color: var(--muted); font-size: .8rem; text-transform: uppercase; letter-spacing: .04em; }}
    .kpi.ok .n {{ color: var(--ok); }}
    .kpi.fail .n {{ color: var(--fail); }}
    .kpi.prog .n {{ color: var(--prog); }}
    .kpi.skip .n {{ color: var(--skip); }}
    section {{
      background: var(--card); border: 1px solid var(--border); border-radius: 12px;
      padding: 1rem 1.1rem; margin-bottom: 1rem;
    }}
    section h2 {{ margin: 0 0 .75rem; font-size: 1.05rem; }}
    table {{ width: 100%; border-collapse: collapse; font-size: .88rem; }}
    th, td {{ text-align: left; padding: .4rem .45rem; border-bottom: 1px solid var(--border); vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 600; font-size: .75rem; text-transform: uppercase; }}
    .pill {{
      display: inline-block; padding: .1rem .45rem; border-radius: 999px;
      background: #243044; font-size: .75rem;
    }}
    tr.success-row {{ background: rgba(61,214,140,.06); }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .78rem; }}
    .detail {{ color: var(--muted); max-width: 280px; }}
    .empty, .muted {{ color: var(--muted); }}
    .bar-row {{ display: grid; grid-template-columns: minmax(120px, 220px) 1fr 40px; gap: .5rem; align-items: center; margin: .25rem 0; }}
    .bar-label {{ font-size: .8rem; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .bar {{ height: 8px; background: #243044; border-radius: 4px; overflow: hidden; }}
    .bar i {{ display: block; height: 100%; background: linear-gradient(90deg, var(--prog), #7aa2f7); }}
    .bar-n {{ font-size: .8rem; text-align: right; }}
    .shots {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: .6rem; }}
    .shots figure {{ margin: 0; background: #0c1017; border-radius: 8px; overflow: hidden; border: 1px solid var(--border); }}
    .shots img {{ width: 100%; height: 100px; object-fit: cover; display: block; }}
    .shots figcaption {{ padding: .3rem .4rem; font-size: .65rem; color: var(--muted); }}
    .countdown {{ color: var(--prog); font-weight: 600; }}
    footer {{ color: var(--muted); font-size: .8rem; padding: 0 1.5rem 2rem; text-align: center; }}
  </style>
</head>
<body>
  <header>
    <h1>Job applications — success &amp; fail</h1>
    <div class="meta">
      Generated <strong>{esc(now)}</strong> ·
      Auto-refresh every <span class="countdown">{REFRESH_SEC // 60} min</span>
      (<span id="tick">{REFRESH_SEC}</span>s) ·
      Ledger attempts: {len(raw)} · Unique latest: {total} ·
      <a href="/api/summary.json">API</a> ·
      <a href="/">Full dashboard</a>
    </div>
  </header>
  <main>
    <div class="kpis">
      <div class="kpi ok"><div class="n">{n_ok}</div><div class="l">Succeeded</div></div>
      <div class="kpi fail"><div class="n">{n_fail}</div><div class="l">Failed / stuck</div></div>
      <div class="kpi prog"><div class="n">{n_prog}</div><div class="l">In progress</div></div>
      <div class="kpi skip"><div class="n">{n_skip}</div><div class="l">Filtered skip</div></div>
      <div class="kpi"><div class="n">{rate:.1f}%</div><div class="l">Success rate</div></div>
      <div class="kpi"><div class="n">{total}</div><div class="l">Tracked roles</div></div>
    </div>

    <section>
      <h2>Status breakdown</h2>
      {''.join(status_bars) or '<p class="empty">No data</p>'}
    </section>

    <section>
      <h2 style="color:var(--ok)">✓ Succeeded ({n_ok})</h2>
      {rows_table(success, 100)}
    </section>

    <section>
      <h2 style="color:var(--fail)">✗ Failed / stuck ({n_fail})</h2>
      {rows_table(fail, 100)}
    </section>

    <section>
      <h2 style="color:var(--prog)">… In progress ({n_prog})</h2>
      {rows_table(progress, 60)}
    </section>

    <section>
      <h2 style="color:var(--skip)">⊘ Filtered / skipped ({n_skip})</h2>
      {rows_table(skip, 40)}
    </section>

    <section>
      <h2>Recent screenshots</h2>
      {shot_html}
    </section>
  </main>
  <footer>
    Playwright multi-display viewers reload this page every {REFRESH_SEC // 60} minutes ·
    port via serve_progress_report.py
  </footer>
  <script>
    // Client countdown + soft reload if meta refresh blocked
    let left = {REFRESH_SEC};
    const el = document.getElementById('tick');
    setInterval(() => {{
      left -= 1;
      if (el) el.textContent = String(Math.max(0, left));
      if (left <= 0) location.reload();
    }}, 1000);
    // Soft poll API to show live KPI without full reload (optional)
    setInterval(async () => {{
      try {{
        const r = await fetch('/api/summary.json?t=' + Date.now());
        if (!r.ok) return;
        // full reload handled by meta / countdown for fresh tables
      }} catch (e) {{}}
    }}, 60000);
  </script>
</body>
</html>
"""
    OUT.write_text(page, encoding="utf-8")
    print(f"Wrote {OUT} success={n_ok} fail={n_fail} progress={n_prog} total={total}")


if __name__ == "__main__":
    main()
