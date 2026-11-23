*** Settings ***
Documentation       Real unusable PCR bank, firmware settings visit, then the full repair.
...                 The clone starts with a cleared TPM (fixture "prepare:
...                 clear-tpm-state") and the suite setup unlocks it with the
...                 fixture's own key. The case then extends PCR 4 with the TPM's
...                 own command (TPM2_PCR_Extend), so the event log no longer
...                 replays to the PCR value and snapd's check reports
...                 no-suitable-pcr-bank. The only fix the application can offer
...                 is the guidance "Enable PCR banks manually": it restarts into
...                 the firmware settings, where the user resets the machine. The
...                 reset clears the PCR, so the repair then runs as usual.

Resource            ${CURDIR}/tpm-fde.resource

Suite Setup         Unlock Encrypted Boot
Suite Teardown      Close All

Test Tags           fde-reprovision


*** Test Cases ***
PCR bank firmware settings then repair
    [Documentation]    Break the PCR bank, visit the firmware settings, repair, restart
    Visit Firmware Settings For An Unusable PCR Bank Then Repair


*** Keywords ***
Visit Firmware Settings For An Unusable PCR Bank Then Repair
    [Documentation]    Every step of the case. The runner gives each case its own
    ...    disposable clone, so the steps cannot be split across tests.
    Log In To Fixture
    Open Disk Encryption Repair
    Preflight Fde Fixture
    ${first}=    Record Baseline
    ${check}=    Assert Actual Repair Preconditions
    ...    recovery    running-in-vm    expected_result=not-attempted
    Should Contain    ${check}[storage][recommendations]    require-reprovision
    Apply Real Fde Fault    extend-pcr4
    Start Repair
    Ignore Virtual Machine Warning
    Confirm Snapd Reports Issue
    ...    no-suitable-pcr-bank
    ...    expected_actions=reboot-to-fw-settings,contact-oem
    ...    recheck=${True}
    # snapd also offers contact-oem; the application hides it, so one solution is left
    Wait For Repair Text    Try the solution below or contact IT support
    Open Solution    Enable PCR banks manually
    Apply Solution    Continue
    Wait For Repair Text    Restart now
    Show Logs Again
    Restart Now
    Open Firmware Setup
    Leave Firmware Setup
    Unlock Encrypted Boot
    Wait For New Boot    ${first}[boot_id]
    Log In After Power Cycle
    Repair After Firmware Action
