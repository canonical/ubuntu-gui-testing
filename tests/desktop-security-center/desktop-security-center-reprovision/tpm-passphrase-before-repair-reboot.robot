*** Settings ***
Documentation       Add a passphrase before the first repaired boot and prove that credential unlocks it.

Resource            ${CURDIR}/tpm-fde.resource

Suite Setup         Unlock Encrypted Boot
Suite Teardown      Close All

Test Tags           fde-reprovision


*** Test Cases ***
Passphrase added after repair unlocks the first reboot
    [Documentation]    Repair, keep the new key, add a passphrase, restart, prove the passphrase unlocks it
    Repair And Add A Passphrase Before Restarting


*** Keywords ***
Repair And Add A Passphrase Before Restarting
    [Documentation]    Every step of the case. The runner gives each case its own
    ...    disposable clone, so the steps cannot be split across tests.
    Log In To Fixture
    Open Disk Encryption Repair
    ${preflight}=    Preflight Fde Fixture
    Should Be Equal    ${preflight}[auth_mode]    none
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
    Assert Recovery Credentials    ${saved}    ${home}    none
    Add Encryption Authentication    passphrase
    Assert Recovery Credentials    ${saved}    ${home}    passphrase
    Reboot Clone For Verification
    Unlock Encrypted Boot    regex:(?i)Enter passphrase.* for    passphrase
    Wait For New Boot    ${baseline}[boot_id]
    Log In After Power Cycle
    Open Disk Encryption Repair
    Wait For Repair Completed
    Assert Repair Is Not Needed
    Assert Recovery Credentials    ${saved}    ${home}    passphrase
