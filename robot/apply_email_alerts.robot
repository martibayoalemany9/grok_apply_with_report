*** Settings ***
Documentation
...    Apply software roles from email job alerts (2 days).
...    Fit: 0020_raw · Upload: 0021_cc + certificates_2020 · degree 2004.
...    Browser: Playwright Chromium CDP :9223 (iteration-002).
...    Chatbots OFF · senior/professional only.
Resource          resources/common.resource
Library           Process
Library           OperatingSystem

*** Variables ***
${WORKDIR}         ${EXECDIR}/../..
${PYTHON}          %{HOME}/.browser-use-env/bin/python3
${QUEUE}           applications_email_alerts_2d_software.csv
${LOG}             email_alerts_2d_apply.log
${COMPLETE_MAX}    1
${DWELL_SEC}       110
${COMMIT_SEC}      80
${PER_APP_MAX_SEC} 320

*** Test Cases ***
Ensure Chromium CDP Ready
    ${rc}    ${output}=    Run And Return Rc And Output
    ...    APPLY_BROWSER=${APPLY_BROWSER} CDP_URL=${CDP_URL} CDP_PORT=${CDP_PORT} ${PYTHON} -c "from cdp_helpers import ensure_cdp_tab, default_cdp_url, APPLY_BROWSER; print(APPLY_BROWSER, default_cdp_url(), ensure_cdp_tab())"
    Log    ${output}
    Should Be Equal As Integers    ${rc}    0
    Should Contain    ${output}    True

Queue Exists Or Skip Build
    [Documentation]    Expect pre-built software email-alert CSV in private workdir.
    ${exists}=    Run Keyword And Return Status    File Should Exist    ${WORKDIR}/${QUEUE}
    Run Keyword If    not ${exists}
    ...    Log    Queue ${QUEUE} missing — build via Gmail harvest + cv_fit in private workdir    WARN
    Run Keyword If    ${exists}    File Should Exist    ${WORKDIR}/${QUEUE}

Apply Email Alert Software Jobs
    [Documentation]    FORCE_RETRY + APPLY_ALL · eFC treated as board · no chatbot.
    ${cmd}=    Catenate    SEPARATOR=${SPACE}
    ...    cd "${WORKDIR}" &&
    ...    APPLY_BROWSER=${APPLY_BROWSER} CDP_URL=${CDP_URL} CDP_PORT=${CDP_PORT}
    ...    COMPLETE_QUEUE_CSV=${QUEUE}
    ...    FORCE_RETRY=1 APPLY_ALL=1 USE_CHATBOT=${USE_CHATBOT}
    ...    SKIP_ATTEMPTED=0 SKIP_PRIOR_FAILS=0 SKIP_WORKDAY=0
    ...    COMPLETE_MAX=${COMPLETE_MAX} PER_APP_MAX_SEC=${PER_APP_MAX_SEC}
    ...    DWELL_SEC=${DWELL_SEC} COMMIT_SEC=${COMMIT_SEC}
    ...    STUCK_SAME_BEHAVIOUR=${STUCK_SAME_BEHAVIOUR}
    ...    "${PYTHON}" -u complete_apply.py >> ${LOG} 2>&1\;
    ...    echo EXIT:\$?
    ${rc}    ${output}=    Run And Return Rc And Output    ${cmd}
    Log    ${output}
    File Should Exist    ${WORKDIR}/${LOG}
