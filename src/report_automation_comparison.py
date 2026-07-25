#!/usr/bin/env python3
"""Compare automation stacks from applications_ledger.jsonl.

Writes:
  AUTOMATION_COMPARISON.md
  automation_comparison.html  (also served at progress report if linked)
  automation_comparison.json
"""
from __future__ import annotations

import html
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

W = Path(__file__).resolve().parent
LEDGER = W / "applications_ledger.jsonl"
OUT_MD = W / "AUTOMATION_COMPARISON.md"
OUT_HTML = W / "automation_comparison.html"
OUT_JSON = W / "automation_comparison.json"

SUCCESS = {
    "submitted",
    "submitted_or_confirmed",
    "likely_submitted",
    "succeeded",
    "done",
}
PROGRESS = {"partial_form_filled", "cv_uploaded_only"}
FAIL = {
    "exception",
    "failed",
    "failed_no_submit",
    "job_closed",
    "login_required",
    "skipped_stuck_same_behaviour",
    "stuck_on_board",
}


def load() -> list[dict]:
    rows = []
    if not LEDGER.exists():
        return rows
    for line in LEDGER.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def auto_key(r: dict) -> str:
    # extra may be nested or flat
    a = r.get("automation") or ""
    if not a and isinstance(r.get("extra"), dict):
        a = r["extra"].get("automation") or r["extra"].get("browser") or ""
    b = r.get("browser") or ""
    if isinstance(r.get("extra"), dict) and not b:
        b = r["extra"].get("browser") or ""
    return (a or b or r.get("source") or "unknown").strip() or "unknown"


def main() -> None:
    rows = load()
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[auto_key(r)].append(r)

    stats = []
    for name, items in sorted(by.items(), key=lambda x: -len(x[1])):
        n = len(items)
        ok = sum(1 for r in items if (r.get("status") or "").lower() in SUCCESS)
        prog = sum(1 for r in items if (r.get("status") or "").lower() in PROGRESS)
        fail = sum(1 for r in items if (r.get("status") or "").lower() in FAIL)
        cv = sum(1 for r in items if r.get("uploaded_cv") or (isinstance(r.get("extra"), dict) and r["extra"].get("uploaded_cv")))
        filled_vals = []
        for r in items:
            f = r.get("filled")
            if f is None and isinstance(r.get("extra"), dict):
                f = r["extra"].get("filled")
            try:
                if f is not None:
                    filled_vals.append(int(f))
            except Exception:
                pass
        avg_fill = sum(filled_vals) / len(filled_vals) if filled_vals else 0
        rate = 100.0 * ok / n if n else 0
        progress_rate = 100.0 * (ok + prog) / n if n else 0
        stats.append(
            {
                "automation": name,
                "attempts": n,
                "success": ok,
                "progress": prog,
                "fail_stuck": fail,
                "cv_uploads": cv,
                "success_rate_pct": round(rate, 2),
                "progress_rate_pct": round(progress_rate, 2),
                "avg_fields_filled": round(avg_fill, 2),
            }
        )

    # Rank: success rate, then progress rate, then attempts
    ranked = sorted(
        stats,
        key=lambda s: (-s["success_rate_pct"], -s["progress_rate_pct"], -s["attempts"]),
    )
    winner = ranked[0]["automation"] if ranked else "n/a"

    # Prefer stacks with meaningful volume
    ranked_volume = [s for s in ranked if s["attempts"] >= 3] or ranked
    winner_vol = ranked_volume[0]["automation"] if ranked_volume else winner

    now = datetime.now().isoformat(timespec="seconds")
    OUT_JSON.write_text(
        json.dumps(
            {
                "generated": now,
                "winner_by_success_rate": winner_vol,
                "stacks": ranked,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        f"# Automation comparison",
        f"",
        f"Generated: {now}",
        f"",
        f"**Best (success rate, ≥3 attempts):** `{winner_vol}`",
        f"",
        f"| Rank | Automation | Attempts | Success | Progress | Fail/stuck | Success % | Progress % | Avg fields |",
        f"|-----:|------------|---------:|--------:|---------:|-----------:|----------:|-----------:|-----------:|",
    ]
    for i, s in enumerate(ranked, 1):
        lines.append(
            f"| {i} | `{s['automation']}` | {s['attempts']} | {s['success']} | "
            f"{s['progress']} | {s['fail_stuck']} | {s['success_rate_pct']}% | "
            f"{s['progress_rate_pct']}% | {s['avg_fields_filled']} |"
        )
    lines += [
        f"",
        f"## How stacks are tagged",
        f"",
        f"| Tag | Meaning |",
        f"|-----|---------|",
        f"| `pw_chromium_rules` | Playwright Chromium isolated, heuristic `fill()` |",
        f"| `pw_chromium_a11y` | Playwright Chromium + accessibility label fill |",
        f"| `pw_safari` | Playwright WebKit (Safari engine) |",
        f"| `chrome_cdp` | Real Chrome via CDP (shared profile) |",
        f"| `chromium_cdp` | Chromium CDP :9223 |",
        f"| `complete_apply` / browser name | Older rows without APPLY_AUTOMATION |",
        f"",
        f"## Recommendation",
        f"",
        f"- Prefer **{winner_vol}** for production batches when sample size is adequate.",
        f"- Keep **a11y** as second pass (`FILL_A11Y=1`) when forms are React-heavy.",
        f"- Use **isolated Chromium workers** for parallel apply (no CDP lock fights).",
        f"- CDP Chrome is best when Gmail verification / logged-in sessions are required.",
        f"",
        f"## Re-run parallel experiment",
        f"",
        f"```bash",
        f"COMPLETE_QUEUE_CSV=applications_discovered_all.csv COMPLETE_MAX=6 \\",
        f"  python3 -u parallel_apply_instances.py",
        f"python3 -u report_automation_comparison.py",
        f"```",
        f"",
        f"HTML: `automation_comparison.html` · Progress: http://127.0.0.1:8790/",
        f"",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    # HTML
    rows_html = []
    for i, s in enumerate(ranked, 1):
        badge = " 🏆" if s["automation"] == winner_vol else ""
        rows_html.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td><code>{html.escape(s['automation'])}</code>{badge}</td>"
            f"<td>{s['attempts']}</td>"
            f"<td>{s['success']}</td>"
            f"<td>{s['progress']}</td>"
            f"<td>{s['fail_stuck']}</td>"
            f"<td><strong>{s['success_rate_pct']}%</strong></td>"
            f"<td>{s['progress_rate_pct']}%</td>"
            f"<td>{s['avg_fields_filled']}</td>"
            "</tr>"
        )
    page = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta http-equiv="refresh" content="600"/>
<title>Automation comparison</title>
<style>
 body {{ font-family: system-ui,sans-serif; background:#0f1419; color:#e7ecf3; margin:0; padding:1.5rem; }}
 h1 {{ margin-top:0; }}
 a {{ color:#59c2ff; }}
 table {{ border-collapse: collapse; width:100%; max-width:1100px; background:#1a2332; }}
 th,td {{ border:1px solid #2a3548; padding:.5rem .6rem; text-align:left; font-size:.9rem; }}
 th {{ color:#8b9bb4; }}
 .meta {{ color:#8b9bb4; margin-bottom:1rem; }}
 code {{ background:#243044; padding:.1rem .35rem; border-radius:4px; }}
</style></head>
<body>
<h1>Automation stack comparison</h1>
<p class="meta">Generated {html.escape(now)} · Best: <strong>{html.escape(winner_vol)}</strong>
· <a href="http://127.0.0.1:8790/">Progress report</a>
· <a href="AUTOMATION_COMPARISON.md">Markdown</a></p>
<table>
<thead><tr>
<th>Rank</th><th>Automation</th><th>Attempts</th><th>Success</th>
<th>Progress</th><th>Fail/stuck</th><th>Success %</th><th>Progress %</th><th>Avg fields</th>
</tr></thead>
<tbody>
{''.join(rows_html)}
</tbody></table>
<p class="meta">Parallel run: <code>python3 -u parallel_apply_instances.py</code></p>
</body></html>
"""
    OUT_HTML.write_text(page, encoding="utf-8")
    print(OUT_MD.read_text(encoding="utf-8")[:2500])
    print(f"\nWinner: {winner_vol}")
    print(f"Wrote {OUT_MD.name}, {OUT_HTML.name}, {OUT_JSON.name}")


if __name__ == "__main__":
    main()
