#!/usr/bin/env python3
"""Measure script improvement by counting closed (submitted) applications.

A closed application = succeeded_or_confirmed or likely_submitted in the
canonical ledger + results JSON files (deduped by URL / app_id).

Hourly snapshots: IMPROVEMENT_METRICS.json + IMPROVEMENT_METRICS.md
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

W = Path(__file__).resolve().parent
SUCCESS_MD = W / "succeeded_applications.md"
METRICS_JSON = W / "IMPROVEMENT_METRICS.json"
METRICS_MD = W / "IMPROVEMENT_METRICS.md"

CLOSED_STATUS = frozenset(
    {
        "submitted",
        "submitted_or_confirmed",
        "likely_submitted",
        "succeeded",
        "done",
    }
)

RESULT_GLOBS = (
    "complete_apply_results.json",
    "strategy_sectors_results.json",
    "serious_apply_results.json",
    "browser_apply_now_results.json",
    "apple_apply_results.json",
    "session_20min_results.json",
)


def _norm_url(u: str) -> str:
    return (u or "").strip().rstrip("/").split("?")[0].lower()


def _parse_success_md() -> list[dict]:
    apps: list[dict] = []
    if not SUCCESS_MD.exists():
        return apps
    for line in SUCCESS_MD.read_text(encoding="utf-8").splitlines():
        if not line.startswith("- **SUCCESS**"):
            continue
        m_ts = re.search(r"\*\*SUCCESS\*\*\s+([0-9T:+-]+)", line)
        m_co = re.search(r"\*\*([^*]+)\*\*\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*(https?://\S+)", line)
        if not m_co:
            continue
        apps.append(
            {
                "source": "succeeded_applications.md",
                "company": m_co.group(1).strip(),
                "title": m_co.group(2).strip(),
                "status": m_co.group(3).strip(),
                "url": m_co.group(4).strip().rstrip(")"),
                "ts": m_ts.group(1) if m_ts else "",
            }
        )
    return apps


def _parse_results_json(path: Path) -> list[dict]:
    apps: list[dict] = []
    if not path.exists():
        return apps
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return apps
    if not isinstance(data, list):
        return apps
    for r in data:
        st = (r.get("status") or "").lower()
        ok = bool(r.get("succeeded")) or st in CLOSED_STATUS
        if not ok:
            continue
        url = r.get("final_url") or r.get("ats_url") or r.get("url") or r.get("apply_url") or ""
        apps.append(
            {
                "source": path.name,
                "app_id": r.get("app_id") or "",
                "company": r.get("company") or "",
                "title": r.get("title") or "",
                "status": r.get("status") or "succeeded",
                "url": url,
            }
        )
    return apps


def collect_closed() -> list[dict]:
    """All closed applications, deduped by URL then app_id."""
    seen_url: set[str] = set()
    seen_id: set[str] = set()
    out: list[dict] = []

    def add(app: dict):
        u = _norm_url(app.get("url") or "")
        aid = (app.get("app_id") or "").strip()
        if u and u in seen_url:
            return
        if aid and aid in seen_id:
            return
        if u:
            seen_url.add(u)
        if aid:
            seen_id.add(aid)
        out.append(app)

    for a in _parse_success_md():
        add(a)
    for name in RESULT_GLOBS:
        for a in _parse_results_json(W / name):
            add(a)
    return out


def count_closed() -> int:
    return len(collect_closed())


def load_metrics() -> list[dict]:
    if not METRICS_JSON.exists():
        return []
    try:
        return json.loads(METRICS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_metrics(rows: list[dict]) -> None:
    METRICS_JSON.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_metrics_md(rows)


def _write_metrics_md(rows: list[dict]) -> None:
    lines = [
        "# Improvement metrics — applications closed per hour",
        "",
        "Primary KPI: **closed applications** (submitted / likely_submitted).",
        "Each hourly cycle records total closed and **delta** since last hour.",
        "",
        "| Hour | Time | Closed total | Δ closed | New applications | Cycle |",
        "|------|------|-------------:|---------:|------------------|-------|",
    ]
    for r in rows:
        new = r.get("new_titles") or []
        new_s = "; ".join(t[:45] for t in new[:3])
        if len(new) > 3:
            new_s += f" (+{len(new)-3})"
        lines.append(
            f"| {r.get('hour', '?')} "
            f"| {r.get('timestamp', '')[:16]} "
            f"| {r.get('closed_total', 0)} "
            f"| **+{r.get('closed_delta', 0)}** "
            f"| {new_s or '—'} "
            f"| {r.get('cycle_note', '')} |"
        )
    if len(rows) >= 2:
        deltas = [r.get("closed_delta", 0) for r in rows[1:]]
        total_delta = sum(deltas)
        hours = max(len(deltas), 1)
        lines.extend(
            [
                "",
                f"**Summary:** {rows[-1].get('closed_total', 0)} closed total · "
                f"+{total_delta} over {hours} measured hour(s) · "
                f"avg **{total_delta/hours:.1f}**/hour",
            ]
        )
    METRICS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def record_hour(
    *,
    hour: int,
    closed_before: int,
    closed_after: int,
    cycle_note: str = "",
    actions: list[str] | None = None,
) -> dict:
    """Append one hourly measurement row."""
    before_keys = {_norm_url(a.get("url") or "") or a.get("app_id", "") for a in collect_closed()}
    # re-collect after — caller ensures after count is current
    after_apps = collect_closed()
    after_keys = {_norm_url(a.get("url") or "") or a.get("app_id", "") for a in after_apps}

    rows = load_metrics()
    prev_keys: set[str] = set()
    if rows:
        prev_keys = set(rows[-1].get("closed_keys") or [])

    new_apps = [
        a for a in after_apps
        if (_norm_url(a.get("url") or "") or a.get("app_id", "")) not in prev_keys
    ]
    delta = max(0, closed_after - closed_before)
    if rows and closed_after == closed_before and new_apps:
        delta = len(new_apps)

    entry = {
        "hour": hour,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "closed_before": closed_before,
        "closed_after": closed_after,
        "closed_total": closed_after,
        "closed_delta": delta,
        "new_titles": [a.get("title", "") for a in new_apps],
        "new_companies": [a.get("company", "") for a in new_apps],
        "cycle_note": cycle_note,
        "actions": actions or [],
        "closed_keys": sorted(after_keys),
    }
    rows.append(entry)
    save_metrics(rows)
    return entry


def baseline_snapshot() -> dict:
    """Hour 0 baseline without a cycle."""
    n = count_closed()
    entry = {
        "hour": 0,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "closed_before": n,
        "closed_after": n,
        "closed_total": n,
        "closed_delta": 0,
        "new_titles": [],
        "new_companies": [],
        "cycle_note": "baseline",
        "actions": ["metrics_initialized"],
        "closed_keys": sorted(
            _norm_url(a.get("url") or "") or a.get("app_id", "") for a in collect_closed()
        ),
    }
    rows = load_metrics()
    if not rows or rows[0].get("cycle_note") != "baseline":
        if rows and rows[0].get("hour") == 0:
            rows[0] = entry
        else:
            rows.insert(0, entry)
        save_metrics(rows)
    return entry


def main():
    baseline_snapshot()
    n = count_closed()
    print(json.dumps({"closed_total": n, "metrics": str(METRICS_MD)}, indent=2))


if __name__ == "__main__":
    main()