*** Settings ***
Documentation       Real disabled TPM, enabled and cleared by the firmware, then the full repair.
...                 The clone starts with a cleared TPM (fixture "prepare:
...                 clear-tpm-state") and the suite setup unlocks it with the
...                 fixture's own key. The case then disables the endorsement
...                 hierarchy with the TPM's own command (TPM2_HierarchyControl),
...                 so snapd's check reports tpm-device-disabled. The user picks
...                 "Enable and clear TPM on restart" in the application, restarts
...                 from it, and approves the firmware's physical presence prompt
...                 with F12. The firmware clears the TPM and the repair then runs
...                 as usual. snapd, polkit and the firmware are the real ones.

Resource            ${CURDIR}/tpm-fde.resource

Suite Setup         Unlock Encrypted Boot
Suite Teardown      Close All

Test Tags           fde-reprovision


*** Test Cases ***
TPM disabled enable and clear then repair
    [Documentation]    Disable the TPM, let the firmware enable and clear it, repair, restart
    Enable And Clear A Disabled TPM Then Repair


*** Keywords ***
Enable And Clear A Disabled TPM Then Repair
    [Documentation]    Every step of the case. The runner gives each case its own
    ...    disposable clone, so the steps cannot be split across tests.
    Log In To Fixture
    Open Disk Encryption Repair
    Preflight Fde Fixture
    ${first}=    Record Baseline
    ${check}=    Assert Actual Repair Preconditions
    ...    recovery    running-in-vm    expected_result=not-attempted
    Should Contain    ${check}[storage][recommendations]    require-reprovision
    Apply Real Fde Fault    disable-endorsement-hierarchy
    Start Repair
    Ignore Virtual Machine Warning
    Confirm Snapd Reports Issue
    ...    tpm-device-disabled
    ...    expected_actions=enable-and-clear-tpm-via-firmware,reboot-to-fw-settings
    ...    recheck=${True}
    Wait For Repair Text    TPM is disabled
    Open Solution    Enable and clear TPM on restart
    Accept TPM Clear Risk
    Apply Solution    Enable and clear TPM on restart
    Take Restart Solution
    Show Logs Again
    Restart Now
    Confirm Firmware TPM Request
    Unlock Encrypted Boot
    Wait For New Boot    ${first}[boot_id]
    Log In After Power Cycle
    Repair After Firmware Action
