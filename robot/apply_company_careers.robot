*** Settings ***
Documentation
...    Resolve companies from alerts → apply on *company careers sites only*.
...    NEVER apply on eFinancialCareers.
...    Browser: Playwright Chromium CDP :9223.
...    Fit 0020_raw · upload 0021_cc + certs 2020 · chatbots OFF.
Resource          resources/common.resource
Library           Process
Library           OperatingSystem

*** Variables ***
${WORKDIR}         ${EXECDIR}/..
${PYTHON}          %{HOME}/.browser-use-env/bin/python3
${QUEUE}           applications_company_careers.csv
${LOG}             company_careers_apply_run.log
${COMPLETE_MAX}    1
${DWELL_SEC}       120
${COMMIT_SEC}      90
${PER_APP_MAX_SEC} 360

*** Test Cases ***
Ensure Chromium CDP Ready
    ${rc}    ${output}=    Run And Return Rc And Output
    ...    APPLY_BROWSER=${APPLY_BROWSER} CDP_URL=${CDP_URL} CDP_PORT=${CDP_PORT} ${PYTHON} -c "from cdp_helpers import ensure_cdp_tab, default_cdp_url, APPLY_BROWSER; print(APPLY_BROWSER, default_cdp_url(), ensure_cdp_tab())"
    Log    ${output}
    Should Be Equal As Integers    ${rc}    0

Build Company Careers Queue From Alerts
    [Documentation]    Map company+title → employer careers URL (no eFC apply links).
    ${rc}    ${output}=    Run And Return Rc And Output
    ...    cd "${WORKDIR}" && "${PYTHON}" resolve_careers_queue.py applications_email_alerts_2d_software.csv applications_email_alerts_merged.csv applications_gmail_alerts_24h.csv -o ${QUEUE}
    Log    ${output}
    Should Be Equal As Integers    ${rc}    0
    File Should Exist    ${WORKDIR}/${QUEUE}

Apply On Company Careers Sites
    [Documentation]    FORCE_RETRY · never eFC · search job title on careers hub.
    ${cmd}=    Catenate    SEPARATOR=${SPACE}
    ...    cd "${WORKDIR}" &&
    ...    APPLY_BROWSER=${APPLY_BROWSER} CDP_URL=${CDP_URL} CDP_PORT=${CDP_PORT}
    ...    COMPLETE_QUEUE_CSV=${QUEUE}
    ...    FORCE_RETRY=1 APPLY_ALL=1 USE_CHATBOT=0
    ...    SKIP_ATTEMPTED=0 SKIP_PRIOR_FAILS=0 SKIP_WORKDAY=0
    ...    COMPLETE_MAX=${COMPLETE_MAX} PER_APP_MAX_SEC=${PER_APP_MAX_SEC}
    ...    DWELL_SEC=${DWELL_SEC} COMMIT_SEC=${COMMIT_SEC}
    ...    STUCK_SAME_BEHAVIOUR=2
    ...    "${PYTHON}" -u complete_apply.py >> ${LOG} 2>&1\;
    ...    echo EXIT:\$?
    ${rc}    ${output}=    Run And Return Rc And Output    ${cmd}
    Log    ${output}
    File Should Exist    ${WORKDIR}/${LOG}
