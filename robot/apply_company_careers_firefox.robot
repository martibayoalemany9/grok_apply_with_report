*** Settings ***
Documentation
...    Company-careers apply using **Firefox** (Playwright) + Robot Framework.
...    Never applies on eFinancialCareers.
...    Puppeteer is not used here — it does not support Firefox.
Resource          resources/common.resource
Library           Process
Library           OperatingSystem

*** Variables ***
${WORKDIR}         ${EXECDIR}/..
${PYTHON}          %{HOME}/.browser-use-env/bin/python3
${QUEUE}           applications_company_careers.csv
${LOG}             company_careers_firefox_apply_run.log
${COMPLETE_MAX}    1
# Force Firefox for this suite
${APPLY_BROWSER}   firefox
${CDP_URL}         ${EMPTY}

*** Test Cases ***
Smoke Firefox Session
    ${rc}    ${output}=    Run And Return Rc And Output
    ...    APPLY_BROWSER=firefox ${PYTHON} -c "import asyncio; from playwright.async_api import async_playwright; from browser_session import open_session;\nasync def m():\n async with async_playwright() as p:\n  b,c,pg,mode=await open_session(p); print(mode, pg.url); await c.close();\nasyncio.run(m())"
    Log    ${output}
    Should Be Equal As Integers    ${rc}    0
    Should Contain    ${output}    firefox

Build Company Careers Queue
    ${rc}    ${output}=    Run And Return Rc And Output
    ...    cd "${WORKDIR}" && "${PYTHON}" resolve_careers_queue.py applications_email_alerts_2d_software.csv applications_email_alerts_merged.csv -o ${QUEUE}
    Log    ${output}
    Should Be Equal As Integers    ${rc}    0
    File Should Exist    ${WORKDIR}/${QUEUE}

Apply On Company Careers With Firefox
    ${cmd}=    Catenate    SEPARATOR=${SPACE}
    ...    cd "${WORKDIR}" &&
    ...    APPLY_BROWSER=firefox
    ...    COMPLETE_QUEUE_CSV=${QUEUE}
    ...    FORCE_RETRY=1 APPLY_ALL=1 USE_CHATBOT=0
    ...    SKIP_ATTEMPTED=0 SKIP_PRIOR_FAILS=0 SKIP_WORKDAY=0
    ...    COMPLETE_MAX=${COMPLETE_MAX} PER_APP_MAX_SEC=360
    ...    DWELL_SEC=120 COMMIT_SEC=90
    ...    "${PYTHON}" -u complete_apply.py >> ${LOG} 2>&1\;
    ...    echo EXIT:\$?
    ${rc}    ${output}=    Run And Return Rc And Output    ${cmd}
    Log    ${output}
    File Should Exist    ${WORKDIR}/${LOG}
