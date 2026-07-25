# Browser for job-apply automation

## Chrome + Safari dual apply (2026-07-25)

```bash
# Parallel: real Chrome (CDP) + Safari WebKit
python3 -u run_chrome_safari_apply.py

# Real Safari.app instead of WebKit (after enabling Remote Automation):
#   Safari → Settings → Advanced → Show Develop menu
#   Develop → Allow Remote Automation
#   sudo safaridriver --enable
APPLY_SAFARI=safari_system python3 -u run_chrome_safari_apply.py
```

| Browser | Env | How |
|---------|-----|-----|
| **Chrome** | `APPLY_BROWSER=chrome` `CDP_URL=http://127.0.0.1:9222` | Your Chrome profile (Gmail) |
| **Safari (WebKit)** | `APPLY_BROWSER=safari` | Playwright WebKit persistent profile `~/.browser-job-apply-safari` |
| **Safari.app** | `APPLY_BROWSER=safari_system` | Selenium safaridriver (limited form API) |

---

**Default (2026-07-19):** Playwright **Chromium** on CDP `:9223`

| Item | Value |
|------|--------|
| Binary | Playwright `Google Chrome for Testing` |
| Profile | `~/.browser-job-apply-chromium` |
| CDP | `http://127.0.0.1:9223` |
| Env | `APPLY_BROWSER=chromium` |
| Batch | **`COMPLETE_MAX=1`** (one application at a time) |
| Window | Separate from Grok TUI; auto full-screen via `APPLY_BROWSER_FULLSCREEN=1` |

**Previous:** personal Google Chrome `~/.browser-use-chrome-profile-with-gmail` on `:9222` (Gmail session). No longer the default — it closed tabs under concurrent use.

### Switch back to personal Chrome (not recommended)

```bash
export APPLY_BROWSER=chrome CDP_URL=http://127.0.0.1:9222 CDP_PORT=9222
```

### Smoke test

```bash
export APPLY_BROWSER=chromium CDP_URL=http://127.0.0.1:9223
python3 cdp_helpers.py
```

### Cloud mobile (rented Galaxy S26)

```bash
# keys in credentials_local.env — see cloud_device.env.example + CLOUD_MOBILE.md
python3 run_cloud_mobile_apply.py --smoke
COMPLETE_MAX=2 python3 run_cloud_mobile_apply.py
```

Stack: `APPLY_BROWSER=cloud_mobile` → Appium → device farm Chrome (same `complete_apply` ledger).

### Robot Framework

- https://github.com/martibayoalemany9/job-apply-robotframework-001
- https://github.com/martibayoalemany9/job-apply-robotframework-002
