*** Settings ***
Documentation       Real SysPrep application then the proceed-only repair.
...                 The runner injects a signed pre-OS application into the
...                 clone's ESP and adds a SysPrep boot option while the clone
...                 is stopped (fixture "prepare: sysprep-app"). The changed
...                 PCR4 makes the TPM unseal fail, so the guest stops at
...                 snapd's recovery prompt and the suite setup unlocks it with
...                 the fixture's own key.
...
...                 secboot maps sys-prep-applications-present to no fixing
...                 action but does allow the check to proceed, so the product
...                 must offer the repair and complete it. snapd and polkit are
...                 the real ones; only the firmware state is mutated.
...
...                 The firmware dispatches the injected SysPrep#### option
...                 before the OS boot option, so the PCR4 load event exists for
...                 the check to report.

Resource            ${CURDIR}/tpm-fde.resource

Suite Setup         Unlock Encrypted Boot
Suite Teardown      Close All

Test Tags           fde-reprovision


*** Test Cases ***
SysPrep application proceed repair
    [Documentation]    Proceed past a pre-OS application, repair, keep the key, restart
    Proceed Past The SysPrep Application And Repair


*** Keywords ***
Proceed Past The SysPrep Application And Repair
    [Documentation]    Every step of the case. The runner gives each case its own
    ...    disposable clone, so the steps cannot be split across tests.
    Log In To Fixture
    Open Disk Encryption Repair
    ${preflight}=    Preflight Fde Fixture
    ${home}=    Desktop Home
    ${baseline}=    Record Baseline
    ${saved}=    Set Variable    ${home}/ugt-recovery-${baseline}[boot_id].txt
    ${check}=    Assert Actual Repair Preconditions
    ...    recovery    running-in-vm    expected_result=failed-encryption-support,not-attempted
    Should Contain    ${check}[storage][recommendations]    require-reprovision
    Assert Repair Is Offered
    Log Pre OS Measurements
    Start Repair
    Hide Recovery Key In Recording
    Ignore Virtual Machine Warning
    Confirm Snapd Reports Issue
    ...    sys-prep-applications-present    recheck=${True}
    Clear Issue
    ...    software running at startup
    ...    New recovery key
    Answer Repair Prompts
    Continue Past Existing Authentication Warning    ${preflight}[auth_mode]
    Answer Repair Prompts
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
