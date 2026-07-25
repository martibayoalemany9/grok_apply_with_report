# Cloud mobile device — wire into Grok job-apply automation

Rent a **real Android phone** (default **Galaxy S26**) on a device farm and drive **Chrome** with the same `complete_apply.py` queue, ledger, CV, and form logic as desktop CDP.

## Architecture

```
run_cloud_mobile_apply.py
        │
        ▼
complete_apply.py   (queue, ledger, form fill, protocol)
        │
        ▼
browser_session.open_session()   APPLY_BROWSER=cloud_mobile
        │
        ▼
Appium Remote WebDriver  →  LambdaTest / BrowserStack / Sauce / generic hub
        │
        ▼
Galaxy S26 + Chrome (real device)
```

Desktop path is unchanged:

```
APPLY_BROWSER=chromium  →  Playwright CDP :9223
```

Cloud path:

```
APPLY_BROWSER=cloud_mobile  →  Appium + Playwright-like shim (appium_playwright_shim.py)
```

## One-time setup

1. Create an account on a device farm that has Galaxy S26 (or S25 fallback):
   - [LambdaTest / TestMu AI](https://www.lambdatest.com/) (S26 announced on their farm)
   - [BrowserStack](https://www.browserstack.com/)
   - [Sauce Labs](https://saucelabs.com/)

2. Copy env template and fill keys:

```bash
cd ~/deepline/data/karlsruhe-public-co-job-apps
cp cloud_device.env.example credentials_local.env   # or merge into existing
# edit: LT_USERNAME, LT_ACCESS_KEY, CLOUD_DEVICE_NAME=Galaxy S26
```

3. Confirm device name in the provider **Live / Real Device** UI (names must match exactly).

## Smoke test (no job apply)

```bash
cd ~/deepline/data/karlsruhe-public-co-job-apps
python3 run_cloud_mobile_apply.py --smoke
```

Expect: session starts, `example.com` loads, screenshot at `screenshots/cloud_mobile_smoke.png`.

## Run job applications on the rented phone

**Use a tiny batch** — device minutes are expensive (~$0.1+/min on many farms).

```bash
# 1–3 applications max while validating
COMPLETE_MAX=2 PER_APP_MAX_SEC=180 \
  COMPLETE_QUEUE_CSV=applications_eu_all.csv \
  python3 run_cloud_mobile_apply.py
```

Same env knobs as desktop `complete_apply.py` (`DWELL_SEC`, `SKIP_ATTEMPTED`, `FORCE_RETRY`, etc.).

## Providers

| `CLOUD_DEVICE_PROVIDER` | Credentials |
|-------------------------|-------------|
| `lambdatest` (default) | `LT_USERNAME`, `LT_ACCESS_KEY` |
| `browserstack` | `BROWSERSTACK_USERNAME`, `BROWSERSTACK_ACCESS_KEY` |
| `sauce` | `SAUCE_USERNAME`, `SAUCE_ACCESS_KEY` |
| `generic` | `APPIUM_HUB_URL` (local or private farm) |

Optional: `APPIUM_HUB_URL` overrides the default hub for any provider.

## Files

| File | Role |
|------|------|
| `cloud_device.py` | Caps + hub URL builder |
| `appium_playwright_shim.py` | Playwright-like Page/Locator on Appium |
| `browser_session.py` | `cloud_mobile` session mode |
| `run_cloud_mobile_apply.py` | Entry + smoke + env load |
| `cloud_device.env.example` | Credentials template |
| `complete_apply.py` | Shared apply engine (cloud-aware session) |

## Limits vs desktop Chromium

| | Desktop CDP | Cloud S26 |
|--|-------------|-----------|
| Cost | Free (local) | Per device-minute |
| Fidelity | Desktop Chrome | Real Samsung Chrome |
| Multi-tab / popups | Strong | Best-effort (often same tab) |
| iframes | Full | Limited (main frame first) |
| File upload | Local path | `push_file` + send_keys |
| Gmail / long-lived profile | Optional local profile | Device wiped between sessions |
| CAPTCHA / anti-bot | Occasional | **Often worse** (farm IP) |

**Recommendation:** keep desktop `run_best_automation.py` / `complete_apply.py` on Chromium for most applies; use cloud S26 for mobile-only careers pages or when you need real-device proof.

## Device name fallbacks

If `Galaxy S26` is not in your plan’s catalog, try:

- `Galaxy S26 Ultra`
- `Galaxy S25`
- `Galaxy S25 Ultra`
- `Samsung Galaxy S24`

Set `CLOUD_DEVICE_NAME` to the **exact** catalog string.

## Do not

- Run cloud_mobile and desktop CDP apply at the same time (shared `.cdp_apply.lock`)
- Leave long idle sessions (you still pay)
- Commit real `LT_ACCESS_KEY` / BrowserStack keys to git

## Status

Wired into Grok apply stack as of 2026-07-25. Smoke first, then `COMPLETE_MAX=1` on a known-good Greenhouse/Personio URL before scaling.
