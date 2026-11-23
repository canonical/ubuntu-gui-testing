*** Settings ***
Documentation       Real pre-OS digest authorization then the proceed-only repair.
...                 The runner adds a SHA-256 digest entry to the clone's db and
...                 injects a pre-OS boot-service driver into the ESP with a
...                 Driver#### entry while the clone is stopped (fixture
...                 "prepare: preos-digest-sb"). The firmware dispatches that
...                 driver before the OS loader, so secboot sees a pre-OS
...                 component authenticated by an enrolled digest. The Canonical
...                 CA entries stay in db, so shim and grub are still verified
...                 by signature; the changed PCR4 and db (PCR7) make the TPM
...                 unseal fail, so the guest stops at snapd's recovery prompt
...                 and the suite setup unlocks it with the fixture's own key.
...
...                 secboot reports
...                 pre-os-secure-boot-auth-by-enrolled-digests with no fixing
...                 action but permits the check to proceed, so the product
...                 must offer the repair and complete it. snapd and polkit
...                 are the real ones; only firmware state is mutated.

Resource            ${CURDIR}/tpm-fde.resource

Suite Setup         Unlock Encrypted Boot
Suite Teardown      Close All

Test Tags           fde-reprovision


*** Test Cases ***
Pre-OS digest authorization proceed repair
    [Documentation]    Proceed past a digest-authorized pre-OS driver, repair, keep the key, restart
    Proceed Past The Digest-Authorized Driver And Repair


*** Keywords ***
Proceed Past The Digest-Authorized Driver And Repair
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
    ...    pre-os-secure-boot-auth-by-enrolled-digests    recheck=${True}
    Clear Issue
    ...    manual allowlist
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
