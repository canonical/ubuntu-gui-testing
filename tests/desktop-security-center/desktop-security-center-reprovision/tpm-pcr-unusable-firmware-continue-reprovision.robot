*** Settings ***
Documentation       Leaving the firmware setup with "Continue", then the full repair.
...                 The clone starts with a cleared TPM (fixture "prepare:
...                 clear-tpm-state") and the suite setup unlocks it with the
...                 fixture's own key. The case restarts into the firmware setup,
...                 which is the user's own action, and picks "Continue", so the
...                 firmware boots the system in the same session. snapd's check
...                 then reports the PCR as unusable, whose only action is
...                 contact-oem; the application never shows contact actions, so
...                 the dialog says the hardware cannot be repaired. A plain
...                 restart starts a clean session and the repair runs as usual.

Resource            ${CURDIR}/tpm-fde.resource

Suite Setup         Unlock Encrypted Boot
Suite Teardown      Close All

Test Tags           fde-reprovision


*** Test Cases ***
Firmware setup Continue leaves the PCR unusable then repair
    [Documentation]    Visit the firmware setup, continue, see the unavailable repair, restart, repair
    Continue From Firmware Setup Then Repair


*** Keywords ***
Continue From Firmware Setup Then Repair
    [Documentation]    Every step of the case. The runner gives each case its own
    ...    disposable clone, so the steps cannot be split across tests.
    Log In To Fixture
    Open Disk Encryption Repair
    Preflight Fde Fixture
    ${first}=    Record Baseline
    Reboot Clone For Verification
    Open Firmware Setup
    Leave Firmware Setup    continue
    Unlock Encrypted Boot
    ${second}=    Wait For New Boot    ${first}[boot_id]
    Log In After Power Cycle
    Open Disk Encryption Repair
    Assert Repair Is Offered
    Start Repair
    Ignore Virtual Machine Warning
    Confirm Snapd Reports Issue
    ...    tpm-pcr-unusable
    ...    expected_actions=contact-oem
    ...    recheck=${True}
    Wait For Repair Text    Hardware-backed encryption could not be repaired
    Match Text Without Echo    There is an issue with this computer's firmware.    10
    ${proceed}=    Run Keyword And Return Status
    ...    Match Text Without Echo    Ignore and continue    1
    Should Not Be True    ${proceed}    An unusable PCR must not offer a proceed action
    Keys Combo    Escape
    Assert Repair Is Offered
    Show Logs Again
    Reboot Clone For Verification
    Unlock Encrypted Boot
    Wait For New Boot    ${second}
    Log In After Power Cycle
    Repair After Firmware Action
