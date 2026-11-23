*** Settings ***
Documentation       Repair a cleared TPM after real passphrase enrollment and verify its removal.

Resource            ${CURDIR}/tpm-fde.resource

Suite Setup         Unlock Encrypted Boot
Suite Teardown      Close All

Test Tags           fde-reprovision


*** Test Cases ***
Repair removes a previously enrolled passphrase
    [Documentation]    Start with a passphrase, repair, keep the new key, restart, prove the passphrase is gone
    Repair Over The Enrolled Passphrase And Restart


*** Keywords ***
Repair Over The Enrolled Passphrase And Restart
    [Documentation]    Every step of the case. The runner gives each case its own
    ...    disposable clone, so the steps cannot be split across tests.
    Log In To Fixture
    Open Disk Encryption Repair
    ${preflight}=    Preflight Fde Fixture
    Should Be Equal    ${preflight}[auth_mode]    passphrase
    ${home}=    Desktop Home
    ${baseline}=    Record Baseline
    ${saved}=    Set Variable    ${home}/ugt-recovery-${baseline}[boot_id].txt
    ${check}=    Assert Actual Repair Preconditions
    ...    recovery    running-in-vm    expected_result=not-attempted
    Should Contain    ${check}[storage][recommendations]    require-reprovision
    Assert Repair Is Offered
    Start Repair
    Hide Recovery Key In Recording
    Ignore Virtual Machine Warning
    Continue Past Existing Authentication Warning    passphrase
    Wait For Repair Text    New recovery key
    Assert New Recovery Key Warning
    Save New Recovery Key To    ${saved}
    Acknowledge Saved Recovery Key
    Confirm Repair
    Wait For Recovery Key Dialog To Close
    Show Recording Again
    Wait For Repair Completed
    Show Logs Again
    Assert Reprovision Change    ${baseline}
    Reboot Clone For Verification
    Wait For New Boot    ${baseline}[boot_id]
    Log In After Power Cycle
    Open Disk Encryption Repair
    Wait For Repair Completed
    Assert Repair Is Not Needed
    Assert Recovery Credentials    ${saved}    ${home}    none
