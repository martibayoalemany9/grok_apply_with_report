#!/usr/bin/env python3
"""Run complete_apply on a rented cloud phone (Galaxy S26 default).

Stack:
  complete_apply.py → browser_session (cloud_mobile) → Appium → provider device farm
  → Chrome on real Android (Playwright-compatible shim)

  # 1) Put keys in credentials_local.env (from cloud_device.env.example)
  # 2) Smoke-test device only:
  python3 run_cloud_mobile_apply.py --smoke
  # 3) Apply from queue (small batch recommended — device minutes cost money):
  COMPLETE_MAX=3 python3 run_cloud_mobile_apply.py
  # 4) Explicit provider/device:
  CLOUD_DEVICE_PROVIDER=browserstack CLOUD_DEVICE_NAME='Samsung Galaxy S26' \\
    python3 run_cloud_mobile_apply.py --smoke
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

W = Path(__file__).resolve().parent
ENV_FILE = W / "credentials_local.env"
PAUSE = W / ".APPLICATIONS_PAUSED"


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _defaults() -> None:
    os.environ.setdefault("APPLY_BROWSER", "cloud_mobile")
    os.environ.setdefault("CLOUD_DEVICE_PROVIDER", "lambdatest")
    os.environ.setdefault("CLOUD_DEVICE_NAME", "Galaxy S26")
    os.environ.setdefault("CLOUD_BROWSER", "Chrome")
    os.environ.setdefault("COMPLETE_MAX", "3")
    os.environ.setdefault("PER_APP_MAX_SEC", "240")
    os.environ.setdefault("SKIP_WORKDAY", "1")
    os.environ.setdefault("ONE_PER_COMPANY", "1")
    os.environ.setdefault("SKIP_ATTEMPTED", "1")
    os.environ.setdefault("USE_CHATBOT", "0")
    os.environ.setdefault("DWELL_SEC", "80")
    os.environ.setdefault("COMMIT_SEC", "50")


async def smoke() -> int:
    """Open cloud device, load example.com, screenshot, quit."""
    from browser_session import open_session
    from cloud_device import load_config, redacted_hub

    cfg = load_config()
    print(
        f"Smoke: provider={cfg.provider} device={cfg.device_name} "
        f"hub={redacted_hub(cfg.hub_url)}",
        flush=True,
    )
    browser, ctx, page, mode = await open_session(None)
    try:
        await page.goto("https://example.com", timeout=90000)
        title = await page.title()
        url = page.url
        shot = W / "screenshots" / "cloud_mobile_smoke.png"
        shot.parent.mkdir(exist_ok=True)
        await page.screenshot(path=str(shot))
        print(f"OK mode={mode} title={title!r} url={url} shot={shot}", flush=True)
        return 0
    finally:
        try:
            await ctx.close()
        except Exception:
            pass
        try:
            await browser.close()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Cloud mobile job apply (S26)")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Only open device + example.com (no job queue)",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ENV_FILE,
        help="Env file with LT_/BS_ credentials (default: credentials_local.env)",
    )
    args = parser.parse_args()

    _load_env_file(args.env_file)
    _defaults()
    os.environ["APPLY_BROWSER"] = "cloud_mobile"

    if PAUSE.exists():
        print("PAUSED — .APPLICATIONS_PAUSED present; remove to apply.", file=sys.stderr)
        return 2

    if args.smoke:
        return asyncio.run(smoke())

    # Hand off to complete_apply (same ledger / queue / form logic)
    sys.path.insert(0, str(W))
    from complete_apply import main as apply_main

    asyncio.run(apply_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
