# Automation stack: Puppeteer, Robot Framework, Firefox

## Short answers

| Tool | Can we use it? | With Firefox? |
|------|----------------|---------------|
| **Robot Framework** | **Yes** — already the suite runner (`robot/*.robot`) | Yes (orchestrates any backend) |
| **Firefox** | **Yes** — via Playwright Firefox (`APPLY_BROWSER=firefox`) | Native |
| **Puppeteer** | **Yes for Chromium** (Node); optional parallel path | **No** (modern Puppeteer dropped Firefox) |

## Recommended combinations

### A) Default (current)
```
Robot Framework  →  complete_apply.py  →  Playwright Chromium (CDP :9223)
```

### A2) Chrome + Safari dual (recommended desktop)
```
run_chrome_safari_apply.py
  ├─ complete_apply.py  →  Google Chrome CDP :9222
  └─ complete_apply.py  →  Safari / Playwright WebKit
```

### B) Firefox
```
Robot Framework  →  complete_apply.py  →  Playwright Firefox (persistent profile)
```

```bash
export APPLY_BROWSER=firefox
export APPLY_USER_DATA_DIR=~/.browser-job-apply-firefox
python3 -u complete_apply.py
# or
robot robot/apply_company_careers_firefox.robot
```

### C) Puppeteer (Chromium only)
```
Robot Framework  →  node puppeteer_runner.js  →  Chromium
```

Puppeteer cannot replace the Firefox path. Use it only if you want a Node-based Chromium driver.

### D) Selenium + Firefox (alternative)
```
Robot Framework Browser/SeleniumLibrary  →  geckodriver  →  Firefox
```

Not wired into `complete_apply.py` yet; possible future adapter.

### E) Cloud mobile (rented Galaxy S26 / real Android Chrome)
```
run_cloud_mobile_apply.py  →  complete_apply.py  →  Appium  →  LambdaTest/BrowserStack/Sauce
                                                                    →  Galaxy S26 + Chrome
```

```bash
# credentials in credentials_local.env (see cloud_device.env.example)
python3 run_cloud_mobile_apply.py --smoke
COMPLETE_MAX=2 python3 run_cloud_mobile_apply.py
```

Full docs: **CLOUD_MOBILE.md**. Uses Playwright-compatible Appium shim so the same form/ledger path runs on a rented phone.

## Why not Puppeteer + Firefox together?

- **Puppeteer** is maintained primarily for **Chrome/Chromium** DevTools Protocol.
- Firefox automation in the JS ecosystem is effectively **Playwright** or **Selenium WebDriver** (geckodriver).
- **Playwright** already supports Chromium + Firefox + WebKit with one API — that is what this repo uses under the hood for Firefox.

## Env reference

| Variable | Values | Meaning |
|----------|--------|---------|
| `APPLY_BROWSER` | `chromium` (default), `chrome`, `edge`, `firefox`, **`cloud_mobile`** | Which browser |
| `CDP_URL` | e.g. `http://127.0.0.1:9223` | CDP only (Chromium/Chrome/Edge) |
| `APPLY_USER_DATA_DIR` | path | Profile directory |
| `HEADLESS` | `0`/`1` | Firefox/headless (Playwright launch) |
| `CLOUD_DEVICE_PROVIDER` | `lambdatest`, `browserstack`, `sauce`, `generic` | Device farm |
| `CLOUD_DEVICE_NAME` | e.g. `Galaxy S26` | Exact catalog device name |
| `LT_USERNAME` / `LT_ACCESS_KEY` | secrets | LambdaTest (default provider) |

## Form-fill comparison (multi-tech bench)

See **`FORM_FILL_OPTIONS.md`** for improvement options and:

```bash
# Dry-run: Playwright rules vs a11y vs Puppeteer (no submit)
python3 -u form_fill_bench.py
# → FORM_FILL_BENCH.md + form_fill_bench_results.json
```

| Tech ID | Driver | Filler |
|---------|--------|--------|
| `pw_rules` | Playwright Chromium | `complete_apply.fill` (production) |
| `pw_a11y` | Playwright Chromium | `form_fill_a11y` label/ARIA graph |
| `puppeteer` | Puppeteer Chromium | `puppeteer/form_fill_bench.js` |
| `browser_use` | browser-use agent | LLM (needs API key) |

## Smoke tests

```bash
# Chromium CDP
APPLY_BROWSER=chromium python3 cdp_helpers.py

# Firefox launch
APPLY_BROWSER=firefox python3 -c "
import asyncio
from playwright.async_api import async_playwright
from browser_session import open_session
async def main():
    async with async_playwright() as p:
        b, ctx, page, mode = await open_session(p)
        print(mode, page.url)
        await page.goto('https://example.com')
        print(await page.title())
        await ctx.close()
asyncio.run(main())
"
```

## Multi-source discovery

See **`DISCOVER_SOURCES.md`**. Unified runner:

```bash
python3 -u discover_all_sources.py
# → applications_discovered_all.csv
```

| Source | Module |
|--------|--------|
| Greenhouse / Lever public APIs | `discover_sources/greenhouse.py`, `lever.py` |
| Apify / Crawlee | `discover_sources/apify_client.py` |
| Bright Data / Oxylabs proxies | `discover_sources/proxies.py` |
| TheirStack / PredictLeads | `theirstack.py`, `predictleads.py` |
| Gmail alerts | `gmail_alerts.py` + Cloud Function |
| eFC / Stepstone | `efc_stepstone.py` |

## CI/CD (Jenkins / Actions / launchd)

See **`CI_CD.md`**. Shared stages: `ci/pipeline.sh`.

```bash
DRY_RUN=1 ./ci/pipeline.sh all          # safe
DRY_RUN=0 COMPLETE_MAX=8 ./ci/pipeline.sh apply
```

- Jenkins: `Jenkinsfile`
- GitHub Actions: `.github/workflows/job-apply.yml`
- macOS schedule: `ci/com.user.job-apply.plist.example`
- Argo CD is for K8s deploy — use Jenkins/launchd for browser apply
