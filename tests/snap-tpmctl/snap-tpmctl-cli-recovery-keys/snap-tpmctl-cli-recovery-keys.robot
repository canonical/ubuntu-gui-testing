*** Settings ***
Documentation       Recovery keys behaviour tests for snap-tpmctl CLI

Resource            ${Z}/../snap-tpmctl.resource
Suite Setup         Bootstrap Snap Tpmctl CLI

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}                ${CURDIR}


*** Test Cases ***
List All Recovery Keys
    [Documentation]    List all recovery keys
    Run Command In Terminal    snap-tpmctl list-all
    Match Text    default-recovery
    Match Text    passphrase

Check Recovery Key
    [Documentation]    Check existing recovery key
    Run Command With Prompt    sudo snap-tpmctl check-recovery-key
    Answer Prompt    Enter recovery key:    ${RECOVERY_KEY}
    Match Text    Recovery key works

Check Recovery Key With Fail
    [Documentation]    Check an invalid recovery key
    Run Command With Prompt    sudo snap-tpmctl check-recovery-key
    Answer Prompt    Enter recovery key:    ${FAKE_RECOVERY_KEY}
    Match Text    Recovery key does not work

Create A New Recovery Key
    [Documentation]    Create a new recovery key
    Run Simple Command    sudo snap-tpmctl create-recovery-key ${RECOVERY_KEY_NAME}
    Match Text    Recovery Key:    60
    Keys Combo    Return
    Run Command In Terminal    snap-tpmctl list-recovery-keys
    Match Text    default    60
    Match Text    ${RECOVERY_KEY_NAME}

Regenerate An Existing Recovery Key
    [Documentation]    Regenerate a recovery key
    Run Simple Command    sudo snap-tpmctl regenerate-recovery-key ${RECOVERY_KEY_NAME}
    Match Text    Recovery Key:    60
    Keys Combo    Return
