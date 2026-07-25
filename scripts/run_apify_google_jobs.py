#!/usr/bin/env python3
"""Run johnvc Google Jobs Scraper via Apify API.

Actor console: https://console.apify.com/actors/CkLDY9GAQf6QlP6GP/input
Store page:    https://apify.com/johnvc/Google-Jobs-Scraper

Requires APIFY_TOKEN.

Example input (default):
{
  "include_lrad": false,
  "location": "Germany",
  "lrad_value": "5",
  "output_file": "google_jobs_results.json",
  "query": "Senior Software Engineer"
}

Usage:
  export APIFY_TOKEN=apify_api_...
  python3 scripts/run_apify_google_jobs.py
  python3 scripts/run_apify_google_jobs.py --input path/to/input.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.apify.com/v2"
DEFAULT_ACTOR = "johnvc~Google-Jobs-Scraper"
# Console id also works: CkLDY9GAQf6QlP6GP

DEFAULT_INPUT = {
    "include_lrad": False,
    "location": "Germany",
    "lrad_value": "5",
    "output_file": "google_jobs_results.json",
    "query": "Senior Software Engineer",
    # Recommended for DE results:
    "country": "de",
    "language": "en",
    "google_domain": "google.de",
    "num_results": 50,
    "max_pagination": 5,
}


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def run_actor(token: str, actor_id: str, run_input: dict, timeout_sec: int = 300) -> list[dict]:
    actor_id = actor_id.strip().replace("/", "~")
    wait = min(timeout_sec, 300)
    url = f"{API}/acts/{actor_id}/runs?waitForFinish={wait}"
    body = json.dumps(run_input).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=_headers(token), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec + 60) as resp:
            run = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode(errors="replace")[:800]
        raise SystemExit(f"Apify HTTP {e.code}: {err}") from e

    data = run.get("data") or run
    status = data.get("status")
    run_id = data.get("id")
    dataset_id = data.get("defaultDatasetId")
    print(f"run={run_id} status={status} dataset={dataset_id}")

    if status in ("READY", "RUNNING") and run_id:
        deadline = time.time() + max(timeout_sec - wait, 60)
        while time.time() < deadline:
            time.sleep(8)
            req_s = urllib.request.Request(
                f"{API}/actor-runs/{run_id}",
                headers=_headers(token),
            )
            with urllib.request.urlopen(req_s, timeout=30) as resp:
                run = json.loads(resp.read().decode())
            data = run.get("data") or run
            status = data.get("status")
            dataset_id = data.get("defaultDatasetId") or dataset_id
            print(f"  poll status={status}")
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break

    if not dataset_id:
        print(f"No dataset (status={status})")
        return []

    items_url = f"{API}/datasets/{dataset_id}/items?format=json&clean=1"
    req2 = urllib.request.Request(items_url, headers=_headers(token))
    with urllib.request.urlopen(req2, timeout=90) as resp:
        items = json.loads(resp.read().decode())
    return items if isinstance(items, list) else []


def main() -> int:
    p = argparse.ArgumentParser(description="Apify Google Jobs (johnvc)")
    p.add_argument("--token", default=os.environ.get("APIFY_TOKEN", ""))
    p.add_argument("--actor", default=os.environ.get("APIFY_ACTOR_ID", DEFAULT_ACTOR))
    p.add_argument("--input", default="", help="Path to input JSON")
    p.add_argument("--out", default="google_jobs_results.json")
    p.add_argument("--timeout", type=int, default=300)
    args = p.parse_args()

    if not args.token:
        print("Set APIFY_TOKEN or pass --token", file=sys.stderr)
        return 1

    if args.input:
        run_input = json.loads(Path(args.input).read_text(encoding="utf-8"))
    else:
        run_input = dict(DEFAULT_INPUT)

    out_name = run_input.get("output_file") or args.out
    print("Actor:", args.actor)
    print("Input:", json.dumps(run_input, indent=2))

    items = run_actor(args.token, args.actor, run_input, timeout_sec=args.timeout)
    Path(out_name).write_text(json.dumps(items, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {len(items)} items → {out_name}")

    # Short preview
    for it in items[:8]:
        if not isinstance(it, dict):
            continue
        title = it.get("title") or it.get("job_title") or ""
        company = it.get("company_name") or it.get("company") or ""
        loc = it.get("location") or ""
        if title:
            print(f"  - {title} @ {company} ({loc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
