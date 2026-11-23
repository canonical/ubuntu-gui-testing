*** Settings ***
Documentation       Real TPM clear then full reprovisioning in one clone.
...                 The runner clears this clone's TPM state before it first
...                 boots (fixture "prepare: clear-tpm-state"), so the guest stops
...                 at snapd's recovery prompt before any SSH is possible and the
...                 suite setup unlocks it with the fixture's own key. The guest's
...                 own snapd detects the cleared endorsement hierarchy. The
...                 installed Security Center then repairs over the real
...                 /run/snapd.socket and the real polkit policy. Nothing in
...                 this case mocks snapd. The GUI runs as the desktop user;
...                 independent fixture and LUKS checks use a privileged helper.
...                 One case spans the whole flow because the runner selects
...                 exactly one case per disposable clone: a repair that is
...                 half executed in one clone and finished in another proves
...                 nothing.

Resource            ${CURDIR}/tpm-fde.resource

Suite Setup         Unlock Encrypted Boot
Suite Teardown      Close All

Test Tags           fde-reprovision


*** Test Cases ***
TPM clear recovery reprovision
    [Documentation]    Clear the TPM, repair, keep the new key, restart, prove it
    Repair The Cleared TPM And Restart


*** Keywords ***
Repair The Cleared TPM And Restart
    [Documentation]    Every step of the case. The runner gives each case its own
    ...    disposable clone, so the steps cannot be split across tests.
    Log In To Fixture
    Open Disk Encryption Repair
    ${preflight}=    Preflight Fde Fixture
    ${home}=    Desktop Home
    ${baseline}=    Record Baseline
    ${saved}=    Set Variable    ${home}/ugt-recovery-${baseline}[boot_id].txt
    ${check}=    Assert Actual Repair Preconditions
    ...    recovery    running-in-vm    expected_result=not-attempted
    ...    expected_support=unavailable
    ...    expected_features=passphrase-auth,pin-auth
    ...    expected_requirements=none
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
