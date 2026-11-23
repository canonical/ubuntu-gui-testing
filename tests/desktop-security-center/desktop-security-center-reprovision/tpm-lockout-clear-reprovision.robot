*** Settings ***
Documentation       Real locked-out TPM, cleared by the firmware, then the full repair.
...                 The clone starts with a cleared TPM (fixture "prepare:
...                 clear-tpm-state") and the suite setup unlocks it with the
...                 fixture's own key. The case then locks the lockout hierarchy
...                 with the TPM's own commands (TPM2_DictionaryAttackParameters
...                 followed by a wrong lockout authorization), so snapd's check
...                 reports tpm-device-lockout-locked-out. The user picks "Clear
...                 TPM on restart" in the application, restarts from it, and
...                 approves the firmware's physical presence prompt with F12.
...                 The firmware clears the TPM, which also ends the lockout, and
...                 the repair then runs as usual.

Resource            ${CURDIR}/tpm-fde.resource

Suite Setup         Unlock Encrypted Boot
Suite Teardown      Close All

Test Tags           fde-reprovision


*** Test Cases ***
TPM lockout clear then repair
    [Documentation]    Lock the TPM, let the firmware clear it, repair, restart
    Clear A Locked Out TPM Then Repair


*** Keywords ***
Clear A Locked Out TPM Then Repair
    [Documentation]    Every step of the case. The runner gives each case its own
    ...    disposable clone, so the steps cannot be split across tests.
    Log In To Fixture
    Open Disk Encryption Repair
    Preflight Fde Fixture
    ${first}=    Record Baseline
    ${check}=    Assert Actual Repair Preconditions
    ...    recovery    running-in-vm    expected_result=not-attempted
    Should Contain    ${check}[storage][recommendations]    require-reprovision
    Apply Real Fde Fault    dictionary-lockout
    Start Repair
    Ignore Virtual Machine Warning
    Confirm Snapd Reports Issue
    ...    tpm-device-lockout-locked-out
    ...    expected_actions=clear-tpm-via-firmware,enable-and-clear-tpm-via-firmware,reboot-to-fw-settings
    ...    recheck=${True}
    Wait For Repair Text    TPM is currently locked
    Open Solution    Solution 1: Clear TPM on restart
    Accept TPM Clear Risk
    Apply Solution    Clear TPM on restart
    Take Restart Solution
    Show Logs Again
    Restart Now
    Confirm Firmware TPM Request
    Unlock Encrypted Boot
    Wait For New Boot    ${first}[boot_id]
    Log In After Power Cycle
    Repair After Firmware Action
