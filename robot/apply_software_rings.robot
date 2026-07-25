*** Settings ***
Documentation
...    Search keyword **software** from City rings 200→5000 km.
...    Browser: Playwright Chromium CDP :9223 (iteration-001).
Resource          resources/common.resource
Library           Process
Library           OperatingSystem

*** Variables ***
${WORKDIR}              ${CURDIR}/..
${PYTHON}               %{HOME}/.browser-use-env/bin/python3
${QUEUE}                applications_software_rings_cvfit.csv
${LOG}                  software_rings_apply_run.log
${COMPLETE_MAX}         1
${PER_APP_MAX_SEC}      300
${STUCK_SAME_BEHAVIOUR}  2
${DWELL_SEC}             100
${COMMIT_SEC}            70

*** Test Cases ***
Ensure Chromium CDP Ready
    ${rc}    ${output}=    Run And Return Rc And Output
    ...    APPLY_BROWSER=${APPLY_BROWSER} CDP_URL=${CDP_URL} ${PYTHON} -c "from cdp_helpers import ensure_cdp_tab; print(ensure_cdp_tab())"
    Log    ${output}
    Should Be Equal As Integers    ${rc}    0

Build Software Rings Queue
    ${rc}    ${output}=    Run And Return Rc And Output
    ...    cd "${WORKDIR}" && "${PYTHON}" efc_job_search.py
    Log    ${output}
    Should Be Equal As Integers    ${rc}    0
    ${exists}=    Run Keyword And Return Status    File Should Exist    ${WORKDIR}/${QUEUE}
    Run Keyword If    not ${exists}    Set Suite Variable    ${QUEUE}    applications_efc_real_jobs.csv
    File Should Exist    ${WORKDIR}/${QUEUE}

Apply Software Rings Batch
    ${cmd}=    Catenate    SEPARATOR=${SPACE}
    ...    cd "${WORKDIR}" &&
    ...    APPLY_BROWSER=${APPLY_BROWSER} CDP_URL=${CDP_URL}
    ...    COMPLETE_QUEUE_CSV=${QUEUE}
    ...    APPLY_ALL=1 USE_CHATBOT=0 SKIP_PRIOR_FAILS=1 SKIP_WORKDAY=1
    ...    COMPLETE_MAX=${COMPLETE_MAX} PER_APP_MAX_SEC=${PER_APP_MAX_SEC}
    ...    ONE_PER_COMPANY=1 DWELL_SEC=${DWELL_SEC} COMMIT_SEC=${COMMIT_SEC}
    ...    STUCK_SAME_BEHAVIOUR=${STUCK_SAME_BEHAVIOUR}
    ...    SKIP_ATTEMPTED=1
    ...    "${PYTHON}" -u complete_apply.py >> "${WORKDIR}/${LOG}" 2>&1\;
    ...    echo EXIT:\$?
    ${rc}    ${output}=    Run And Return Rc And Output    ${cmd}
    Log    ${output}
    File Should Exist    ${WORKDIR}/${LOG}
