*** Settings ***
Documentation       Expire a real generated recovery key, retry, and prove the repaired boot.

Resource            ${CURDIR}/tpm-fde.resource

Suite Setup         Unlock Encrypted Boot
Suite Teardown      Close All

Test Tags           fde-reprovision


*** Test Cases ***
Expired recovery key can be regenerated and repaired
    [Documentation]    Let the new key expire, prove the repair fails, repair again, restart, prove it
    Repair Again After The Recovery Key Expires


*** Keywords ***
Repair Again After The Recovery Key Expires
    [Documentation]    Every step of the case. The runner gives each case its own
    ...    disposable clone, so the steps cannot be split across tests.
    Log In To Fixture
    Open Disk Encryption Repair
    Preflight Fde Fixture
    ${home}=    Desktop Home
    ${baseline}=    Record Baseline
    ${expired}=    Set Variable    ${home}/ugt-expired-${baseline}[boot_id].txt
    ${saved}=    Set Variable    ${home}/ugt-retry-${baseline}[boot_id].txt
    ${check}=    Assert Actual Repair Preconditions
    ...    recovery    running-in-vm    expected_result=not-attempted
    Should Contain    ${check}[storage][recommendations]    require-reprovision
    Assert Repair Is Offered
    Start Repair
    Hide Recovery Key In Recording
    Ignore Virtual Machine Warning
    Wait For Repair Text    New recovery key
    Assert New Recovery Key Warning
    Save New Recovery Key To    ${expired}
    Acknowledge Saved Recovery Key
    Mark Wait Start    recovery key expiry
    BuiltIn.Sleep    310 seconds
    Mark Wait End
    Confirm Repair
    Wait For Recovery Key Dialog To Close
    Show Recording Again
    Assert Repair Failed On Page
    ${failed}=    Assert Reprovision Failed    ${baseline}    recovery key has expired
    Assert Expired Recovery Key Was Rejected    ${expired}    ${home}
    Assert Repair Is Required
    Start Repair
    Hide Recovery Key In Recording
    Ignore Virtual Machine Warning
    Wait For Repair Text    New recovery key
    Assert New Recovery Key Warning
    Save New Recovery Key To    ${saved}
    Acknowledge Saved Recovery Key
    Confirm Repair
    Wait For Recovery Key Dialog To Close
    Show Recording Again
    Wait For Repair Completed
    Show Logs Again
    Assert Reprovision Change    ${failed}
    Reboot Clone For Verification
    Wait For New Boot    ${baseline}[boot_id]
    Log In After Power Cycle
    Open Disk Encryption Repair
    Wait For Repair Completed
    Assert Repair Is Not Needed
    Assert Recovery Credentials    ${saved}    ${home}    none
