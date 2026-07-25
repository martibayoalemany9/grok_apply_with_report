*** Settings ***
Documentation
...    Optional: run **Puppeteer** Chromium smoke test from Robot Framework.
...    Puppeteer does **not** support Firefox — for Firefox use apply_company_careers_firefox.robot.
Library    Process
Library    OperatingSystem

*** Variables ***
${WORKDIR}    ${EXECDIR}/..
${PDIR}       ${WORKDIR}/puppeteer

*** Test Cases ***
Puppeteer Chromium Smoke
    [Documentation]    Requires: cd puppeteer && npm install
    ${pkg}=    Set Variable    ${PDIR}${/}package.json
    File Should Exist    ${pkg}
    ${rc}    ${output}=    Run And Return Rc And Output
    ...    cd "${PDIR}" && npm run smoke
    Log    ${output}
    Should Be Equal As Integers    ${rc}    0
    Should Contain    ${output}    puppeteer chromium ok
