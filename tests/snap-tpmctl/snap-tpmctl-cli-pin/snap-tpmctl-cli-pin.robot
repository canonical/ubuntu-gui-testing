*** Settings ***
Documentation       PIN behaviour tests for snap-tpmctl CLI

Resource            ${Z}/../snap-tpmctl.resource
Suite Setup         Bootstrap Snap Tpmctl CLI

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}                ${CURDIR}


*** Test Cases ***
Add PIN
    [Documentation]    Add authentication with pin
    Run Command With Prompt    sudo snap-tpmctl add-pin
    Answer Prompt    new PIN    ${PIN}
    Answer Prompt    new PIN    ${PIN}
    Match Text    PIN added successfully    60
    Run Command In Terminal    snap-tpmctl list-pins
    Match Text    default    60

Clear System Status
    [Documentation]    Reboot system in order to change auth-mode
    System Reboot    Enter PIN or recovery key    ${PIN}

Replace PIN
    [Documentation]    Replace the current pin
    Run Command With Prompt    sudo snap-tpmctl replace-pin
    Answer Prompt    current PIN    ${PIN}
    Answer Prompt    new PIN    ${NEW_PIN}
    Answer Prompt    new PIN    ${NEW_PIN}
    Match Text    PIN replaced successfully    60

Remove PIN
    [Documentation]    Remove pin from the system
    Run Command In Terminal    sudo snap-tpmctl remove-pin
    Match Text    PIN removed successfully    60
    Check No Match In Output    snap-tpmctl list-pins    default
