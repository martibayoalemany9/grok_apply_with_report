# Iteration: grok_apply_with_report

Builds on [job-apply-robotframework-002](https://github.com/martibayoalemany9/job-apply-robotframework-002).

## New

- Single entrypoint `grok_apply_with_report.py` (apply then HTML progress report)
- Default **one application at a time** (`COMPLETE_MAX=1`)
- Full-screen CDP browser helpers (separate window from Grok chat)
- Cloud mobile adapter stubs (`cloud_device.py`, Appium shim) — optional
- Report generators: progress HTML, dashboard, automation comparison
- 10s reopen gap, 60s stuck grace (see complete_apply)

## Private data stays private

CVs, prefs, ledgers, credentials remain only in `JOB_APPLY_WORKDIR`.
