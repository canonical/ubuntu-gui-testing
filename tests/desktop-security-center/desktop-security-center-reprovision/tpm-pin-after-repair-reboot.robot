*** Settings ***
Documentation       Add a PIN after the repaired machine boots, then prove a PIN-authenticated boot.

Resource            ${CURDIR}/tpm-fde.resource

Suite Setup         Unlock Encrypted Boot
Suite Teardown      Close All

Test Tags           fde-reprovision


*** Test Cases ***
PIN added after repair and reboot unlocks the next boot
    [Documentation]    Repair, restart, add a PIN, restart again, prove the PIN unlocks it
    Repair, Restart, And Add A PIN


*** Keywords ***
Repair, Restart, And Add A PIN
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
    Reboot Clone For Verification
    Wait For New Boot    ${baseline}[boot_id]
    Log In After Power Cycle
    Open Disk Encryption Repair
    Wait For Repair Completed
    Assert Repair Is Not Needed
    Assert Recovery Credentials    ${saved}    ${home}    none
    Add Encryption Authentication    pin
    Assert Recovery Credentials    ${saved}    ${home}    pin
    ${enrolled}=    Record Baseline
    Reboot Clone For Verification
    Unlock Encrypted Boot    regex:(?i)Enter .*PIN.* for    pin
    Wait For New Boot    ${enrolled}[boot_id]
    Log In After Power Cycle
    Open Disk Encryption Repair
    Wait For Repair Completed
    Assert Repair Is Not Needed
    Assert Recovery Credentials    ${saved}    ${home}    pin
