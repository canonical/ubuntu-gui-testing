*** Settings ***
Documentation       Host power cut during a real repair, then a clean retry.
...                 The clone starts at snapd's recovery prompt with a cleared
...                 TPM, so the installed Security Center offers a real
...                 reprovision. Once the user confirms, snapd's handler renames
...                 the old keyslots and adds the new recovery key before it
...                 seals the replacement TPM key. The host cuts power as soon
...                 as the handler's private stage signal changes, so the
...                 interrupted attempt has already replaced the keyslots but
...                 never sealed the new key.
...                 On the next boot snapd retries the interrupted task, finds
...                 the renamed keyslots without its in-memory repair context,
...                 restores the old keyslots, and fails the change with
...                 "missing reprovision context". The fixture's original
...                 recovery key must unlock the clone again, and the key the
...                 interrupted attempt had saved must unlock nothing. A second
...                 repair then has to complete and keep a working new key.
...                 Nothing here mocks snapd, polkit, or the TPM: the observer
...                 only reads the handler's private file and drives libvirt for
...                 the one disposable clone the runner created.

Resource            ${CURDIR}/tpm-fde.resource

Suite Setup         Unlock Encrypted Boot
Suite Teardown      Close All

Test Tags           fde-reprovision


*** Test Cases ***
Power cut during repair is rolled back and retried
    [Documentation]    Interrupt a real repair, prove the rollback, then repair again
    Cut Power During Repair And Repair Again


*** Keywords ***
Cut Power During Repair And Repair Again
    [Documentation]    Every step of the case. The runner gives each case its own
    ...    disposable clone, so the steps cannot be split across tests.
    Log In To Fixture
    Open Disk Encryption Repair
    ${preflight}=    Preflight Fde Fixture
    ${home}=    Desktop Home
    ${baseline}=    Record Baseline
    ${saved}=    Set Variable    ${home}/ugt-interrupted-${baseline}[boot_id].txt
    ${check}=    Assert Actual Repair Preconditions
    ...    recovery    running-in-vm    expected_result=not-attempted
    Should Contain    ${check}[storage][recommendations]    require-reprovision
    Assert Repair Is Offered
    Start Repair
    Hide Recovery Key In Recording
    Ignore Virtual Machine Warning
    Continue Past Existing Authentication Warning    ${preflight}[auth_mode]
    Wait For Repair Text    New recovery key
    Assert New Recovery Key Warning
    Save New Recovery Key To    ${saved}
    Acknowledge Saved Recovery Key
    Capture Saved Recovery Key    ${saved}    ${home}
    ${armed}=    Arm Power Cut Observer
    Confirm Repair
    Wait For Recovery Key Dialog To Close
    Show Recording Again
    ${evidence}=    Cut Power When Repair Starts
    Wait For Power Cut To Stop The Guest
    Start Clone After Power Cut
    Unlock Encrypted Boot
    Wait For Guest After Power Cut
    Wait For New Boot    ${armed}[boot_id]
    Log In After Power Cycle
    Open Disk Encryption Repair
    Assert Power Cut Interrupted Repair    ${armed}    ${evidence}
    Assert Fixture Recovery Key Works
    Assert Captured Recovery Key Rejected

    ${retry}=    Record Baseline
    ${saved_again}=    Set Variable    ${home}/ugt-repaired-${retry}[boot_id].txt
    Start Repair
    Hide Recovery Key In Recording
    Ignore Virtual Machine Warning
    Continue Past Existing Authentication Warning    ${preflight}[auth_mode]
    Wait For Repair Text    New recovery key
    Assert New Recovery Key Warning
    Save New Recovery Key To    ${saved_again}
    Acknowledge Saved Recovery Key
    Confirm Repair
    Wait For Recovery Key Dialog To Close
    Show Recording Again
    Wait For Repair Completed
    Show Logs Again
    Assert Reprovision Change    ${retry}
    Reboot Clone For Verification
    Wait For New Boot    ${retry}[boot_id]
    Log In After Power Cycle
    Open Disk Encryption Repair
    Wait For Repair Completed
    Assert Repair Is Not Needed
    Assert Recovery Credentials    ${saved_again}    ${home}    none
