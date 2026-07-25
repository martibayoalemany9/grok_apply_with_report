*** Settings ***
Documentation    Shared variables for job-apply Robot suites (iteration-002).
Library          OperatingSystem
Library          Process

*** Variables ***
${DEFAULT_PYTHON}    %{HOME}/.browser-use-env/bin/python3
${CDP_URL}           http://127.0.0.1:9223
${APPLY_BROWSER}     chromium
${CDP_PORT}          9223
# Docs: fit+upload 0020_raw · ETSETB academic · work certs 2020 · degree 2003
${USE_CHATBOT}       0
${STUCK_SAME_BEHAVIOUR}    2
