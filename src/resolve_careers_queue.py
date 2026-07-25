#!/usr/bin/env python3
"""Convert eFC / job-board CSV rows into company-careers apply queue.

NEVER keeps eFinancialCareers apply URLs. For each row:
  company + title → careers site → optional search URL with job keywords.

Usage:
  python3 resolve_careers_queue.py applications_email_alerts_2d_software.csv
  python3 resolve_careers_queue.py applications_efc_real_jobs.csv -o applications_company_careers.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from candidate_profile import CERTS, CV
from company_careers import (
    careers_search_url,
    is_board_url,
    resolve_careers_url,
    search_query_from_title,
)
from cv_fit import job_fit_score
from role_filter import is_junior_or_student_track, is_never_apply, is_target_role

W = Path(__file__).resolve().parent


def load_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def resolve_row(row: dict, *, use_web: bool, probe: bool, min_score: int) -> dict | None:
    company = (row.get("company") or "").strip()
    title = (row.get("title") or "").strip()
    if not company or not title:
        return None
    if is_never_apply(title, company) or is_junior_or_student_track(title, "", company):
        return None

    fits, score, reason = job_fit_score(title, "", company, min_score=min_score)
    if not fits and not is_target_role(title, company):
        # still allow software-related titles that target_role accepts
        return None

    careers, src = resolve_careers_url(company, title, use_web=use_web, probe=probe)
    if not careers or is_board_url(careers):
        return None

    q = search_query_from_title(title)
    apply_url = careers_search_url(careers, q)

    out = dict(row)
    out["board"] = "company_careers"
    out["apply_url"] = apply_url
    out["employer_url"] = careers  # hub
    out["careers_url"] = careers
    out["search_query"] = q
    out["match_score"] = str(score if score else row.get("match_score") or 5)
    out["cv_path"] = row.get("cv_path") or str(CV)
    out["certs_path"] = row.get("certs_path") or str(CERTS)
    out["status"] = "queued"
    out["resolve"] = "ok"
    note = row.get("source_note") or ""
    out["source_note"] = (
        f"{note}; careers={src}; no_efc; search={q!r}; fit={reason}"
    ).strip("; ")
    # keep original eFC url for reference only
    orig = row.get("apply_url") or row.get("url") or ""
    if orig and is_board_url(orig):
        out["source_board_url"] = orig
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Resolve company careers queue (no eFC apply)")
    ap.add_argument("inputs", nargs="+", help="Input CSV path(s)")
    ap.add_argument(
        "-o",
        "--output",
        default=str(W / "applications_company_careers.csv"),
        help="Output CSV",
    )
    ap.add_argument("--no-web", action="store_true", help="Skip DuckDuckGo lookup")
    ap.add_argument("--probe", action="store_true", help="HTTP-probe heuristic careers URLs")
    ap.add_argument("--min-score", type=int, default=3)
    args = ap.parse_args()

    seen: set[tuple[str, str]] = set()
    out_rows: list[dict] = []
    skipped = 0
    unresolved = 0

    for inp in args.inputs:
        path = Path(inp)
        if not path.is_absolute():
            path = W / path
        if not path.exists():
            print(f"skip missing {path}", file=sys.stderr)
            continue
        for row in load_rows(path):
            company = (row.get("company") or "").strip()
            title = (row.get("title") or "").strip()
            key = (company.lower(), title.lower())
            if key in seen:
                continue
            r = resolve_row(
                row,
                use_web=not args.no_web,
                probe=args.probe,
                min_score=args.min_score,
            )
            if not r:
                # try still resolve for logging
                careers, src = resolve_careers_url(
                    company, title, use_web=not args.no_web, probe=args.probe
                )
                if not careers:
                    unresolved += 1
                    print(f"  UNRESOLVED  {company[:28]:28} | {title[:50]}")
                else:
                    skipped += 1
                    print(f"  SKIP fit    {company[:28]:28} | {title[:50]}")
                continue
            seen.add(key)
            # stable app ids
            if not r.get("app_id") or str(r["app_id"]).startswith("AL2D") or "efc" in str(r.get("board", "")).lower():
                r["app_id"] = f"CC-{len(out_rows)+1:03d}"
            out_rows.append(r)
            print(f"  OK  {company[:28]:28} → {r['apply_url'][:70]}")

    if not out_rows:
        print("No rows resolved.", file=sys.stderr)
        return 1

    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = W / out_path
    # fieldnames union
    fields: list[str] = []
    for r in out_rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    preferred = [
        "app_id",
        "board",
        "company",
        "title",
        "location",
        "apply_url",
        "employer_url",
        "careers_url",
        "search_query",
        "match_score",
        "cv_path",
        "certs_path",
        "salary_target",
        "status",
        "resolve",
        "source_note",
        "source_board_url",
    ]
    fieldnames = [f for f in preferred if f in fields] + [f for f in fields if f not in preferred]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(out_rows)

    print(
        f"\nWrote {len(out_rows)} company-careers jobs → {out_path}\n"
        f"  skipped_fit={skipped} unresolved={unresolved}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
