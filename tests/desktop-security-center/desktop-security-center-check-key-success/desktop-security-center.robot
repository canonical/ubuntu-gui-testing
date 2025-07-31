*** Settings ***
Documentation       Check a valid recovery key is recognized as valid

Resource            ${Z}/../desktop-security-center.resource

Test Tags           exit-on-failure


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log into ubuntu user
    Log In

Open Security Center
    [Documentation]    Open the Security Center from the cli
    Open Security Center

Open Disk Encryption Tab
    [Documentation]    Open the disk encryption tab in the Security Center
    Open Disk Encryption Tab

Check Recovery Key Success
    [Documentation]    Checks a valid recovery key in the Security Center
    Check Recovery Key Success
