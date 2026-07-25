# grok_apply_with_report

**Owner:** [martibayoalemany9](https://github.com/martibayoalemany9)

One-command Grok job-apply automation:

1. Apply to **one** job (Playwright Chromium CDP `:9223` by default)  
2. Regenerate the **HTML progress report** from the application ledger  

Related Robot Framework iterations:

- [job-apply-robotframework-001](https://github.com/martibayoalemany9/job-apply-robotframework-001)  
- [job-apply-robotframework-002](https://github.com/martibayoalemany9/job-apply-robotframework-002)  

## Architecture

```text
grok_apply_with_report.py
        │
        ├─► complete_apply.py   (browser form fill, COMPLETE_MAX=1)
        │         └─ Playwright Chromium CDP :9223  (separate window / full-screen)
        │
        └─► generate_progress_report.py
                  └─ applications_progress_report.html
```

Optional: `cloud_mobile` via LambdaTest/BrowserStack Appium (see `docs/CLOUD_MOBILE.md`).

## Security — what is NOT in this repo

This repository **excludes**:

- CVs, certificates, cover letters  
- `candidate_prefs.json`, credentials, Keychain secrets  
- Application ledgers, queues, success lists, screenshots  

Keep a **private workdir** for personal data (example path used by the author):

```text
~/deepline/data/karlsruhe-public-co-job-apps/
```

## Setup

```bash
git clone https://github.com/martibayoalemany9/grok_apply_with_report.git
cd grok_apply_with_report
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Private data directory
export JOB_APPLY_WORKDIR=~/path/to/private/job-apply-data
cp templates/candidate_prefs.example.json "$JOB_APPLY_WORKDIR/candidate_prefs.json"
# Add cv.pdf, certificates, and a queue CSV in JOB_APPLY_WORKDIR
```

If your private workdir already contains the full Grok apply tree (`complete_apply.py`, ledger, CVs), point `JOB_APPLY_WORKDIR` there — live modules override `src/`.

## Run

```bash
# One application + report
export JOB_APPLY_WORKDIR=~/deepline/data/karlsruhe-public-co-job-apps
export COMPLETE_MAX=1
export APPLY_BROWSER=chromium
export CDP_URL=http://127.0.0.1:9223

python3 grok_apply_with_report.py

# Report only
python3 grok_apply_with_report.py --report-only

# Shell helper
./scripts/run_one_apply_with_report.sh
```

Open the report:

```bash
open "$JOB_APPLY_WORKDIR/applications_progress_report.html"
# or serve: python3 grok_apply_with_report.py --report-only --serve
```

## Defaults (policy)

| Setting | Default |
|---------|---------|
| `COMPLETE_MAX` | **1** (one application at a time) |
| Browser | Chromium CDP `:9223` (window separate from Grok TUI) |
| Full-screen browser | `APPLY_BROWSER_FULLSCREEN=1` |
| Chatbots | OFF |
| Reopen gap | 10s before navigating |
| Stuck grace | 60s before give-up |

## Layout

```text
grok_apply_with_report.py   # entry: apply + report
src/                        # automation + report modules
robot/                      # Robot Framework suites
scripts/                    # shell runners
templates/                  # prefs / cloud env examples
docs/                       # stack notes
```

## License

Private use by the owner unless stated otherwise. No warranty. Do not commit personal data.
