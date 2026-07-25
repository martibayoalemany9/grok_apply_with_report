*** Settings ***
Documentation
...    Apply to REAL eFinancialCareers job posts (senior/professional only).
...    Browser: Playwright Chromium CDP :9223 (iteration-001).
...    Chatbots OFF · no Werkstudent/intern · real job URLs only.
Resource          resources/common.resource
Library           Process
Library           OperatingSystem

*** Variables ***
${WORKDIR}    ${CURDIR}/..
${PYTHON}     %{HOME}/.browser-use-env/bin/python3
${QUEUE}      applications_efc_real_jobs.csv
${LOG}        efc_real_jobs_apply_run.log

*** Test Cases ***
Ensure Chromium CDP Ready
    [Documentation]    Launch dedicated Chromium on :9223 if offline.
    ${rc}    ${output}=    Run And Return Rc And Output
    ...    APPLY_BROWSER=${APPLY_BROWSER} CDP_URL=${CDP_URL} CDP_PORT=${CDP_PORT} ${PYTHON} -c "from cdp_helpers import ensure_cdp_tab, default_cdp_url; print(default_cdp_url(), ensure_cdp_tab())"
    Log    ${output}
    Should Be Equal As Integers    ${rc}    0

Refresh Real Job Queue
    ${rc}    ${output}=    Run And Return Rc And Output
    ...    cd ${WORKDIR} && ${PYTHON} efc_job_search.py
    Log    ${output}
    Should Be Equal As Integers    ${rc}    0
    File Should Exist    ${WORKDIR}/${QUEUE}

Apply Real Jobs No Chatbot
    ${rc}    ${output}=    Run And Return Rc And Output
    ...    cd ${WORKDIR} && APPLY_BROWSER=${APPLY_BROWSER} CDP_URL=${CDP_URL} COMPLETE_QUEUE_CSV=${QUEUE} APPLY_ALL=1 USE_CHATBOT=0 SKIP_PRIOR_FAILS=0 SKIP_WORKDAY=1 COMPLETE_MAX=1 PER_APP_MAX_SEC=300 ONE_PER_COMPANY=1 DWELL_SEC=100 COMMIT_SEC=70 ${PYTHON} -u complete_apply.py >> ${LOG} 2>&1; echo EXIT:$?
    Log    ${output}
    File Should Exist    ${WORKDIR}/${LOG}
