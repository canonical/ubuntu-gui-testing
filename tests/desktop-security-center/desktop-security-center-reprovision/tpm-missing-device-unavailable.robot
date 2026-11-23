*** Settings ***
Documentation       A clone without a TPM reports the real unavailable-repair state without changing credentials.

Resource            ${CURDIR}/tpm-fde.resource

Suite Setup         Unlock Encrypted Boot
Suite Teardown      Close All

Test Tags           fde-reprovision


*** Test Cases ***
Missing TPM offers no unsafe repair action
    [Documentation]    Open the repair without a TPM, prove it offers no unsafe action and changes nothing
    Try To Repair Without A TPM


*** Keywords ***
Try To Repair Without A TPM
    [Documentation]    Every step of the case. The runner gives each case its own
    ...    disposable clone, so the steps cannot be split across tests.
    Log In To Fixture
    Open Disk Encryption Repair
    ${preflight}=    Preflight Fde Fixture
    Should Be Equal    ${preflight}[auth_mode]    none
    ${baseline}=    Record Baseline
    ${check}=    Assert Actual Repair Preconditions
    ...    recovery    running-in-vm    expected_result=not-attempted
    Should Contain    ${check}[storage][recommendations]    require-reprovision
    Assert Repair Is Offered
    Start Repair
    Ignore Virtual Machine Warning
    ${unavailable}=    Assert Actual Repair Preconditions
    ...    recovery    no-suitable-tpm2-device    expected_result=not-attempted
    ...    expected_support=unavailable    recheck=${True}
    ${issues}=    Set Variable    ${unavailable}[systems][storage-encryption][availability-check-errors]
    ${actions}=    Evaluate
    ...    next(issue.get('actions', []) for issue in $issues if issue.get('kind') == 'no-suitable-tpm2-device')
    Should Be Empty    ${actions}
    Wait For Repair Text    Hardware-backed encryption could not be repaired
    Match Text Without Echo    required security hardware    10
    Match Text Without Echo    Learn more    10
    ${proceed}=    Run Keyword And Return Status
    ...    Match Text Without Echo    Ignore and continue    1
    Should Not Be True    ${proceed}    Missing hardware must not offer a proceed action
    ${repair}=    Run Keyword And Return Status
    ...    Match Text Without Echo    regex:(?m)^Repair$    1
    Should Not Be True    ${repair}    Missing hardware must not offer repair confirmation
    Keys Combo    Escape
    Assert Repair Is Offered
    Show Logs Again
    Assert Repair Was Cancelled    ${baseline}
    Assert Fixture Recovery Key Works
