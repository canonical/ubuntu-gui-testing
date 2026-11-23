*** Settings ***
Documentation       Cancelling the repair leaves the machine as snapd reported it.
...                 A user who declines the repair must not be half repaired: the
...                 banner stays, and snapd still requires reprovisioning
...                 afterwards.

Resource            ${CURDIR}/tpm-fde.resource

Suite Setup         Unlock Encrypted Boot
Suite Teardown      Close All

Test Tags           fde-reprovision


*** Test Cases ***
Cancel repair keeps the machine unrepaired
    [Documentation]    Decline repair; preserve boot, authentication and repair history

    Log In To Fixture
    Open Disk Encryption Repair
    Preflight Fde Fixture
    ${check}=    Assert Actual Repair Preconditions
    ...    recovery    running-in-vm    expected_result=not-attempted
    Should Contain    ${check}[storage][recommendations]    require-reprovision
    ${baseline}=    Record Baseline
    Assert Repair Is Offered
    Start Repair
    Cancel Repair
    Assert Repair Is Offered
    Show Logs Again
    Assert Repair Is Required
    Assert Repair Was Cancelled    ${baseline}
    Assert Fixture Recovery Key Works
