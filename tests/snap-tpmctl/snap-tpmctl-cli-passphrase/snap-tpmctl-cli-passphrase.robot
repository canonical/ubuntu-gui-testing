*** Settings ***
Documentation       Passphrase behaviour tests for snap-tpmctl CLI

Resource            ${Z}/../snap-tpmctl.resource
Suite Setup         Bootstrap Snap Tpmctl CLI

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}                ${CURDIR}


*** Test Cases ***
# NOTE: decomment this after https://github.com/canonical/snapd/pull/16966 is merged in snapd
# Replace Passphrase With Fail
#    [Documentation]    Fail to replace the default passphrase due incorrect passphrase
#    Run Command With Prompt    sudo snap-tpmctl replace-passphrase
#    Answer Prompt    current passphrase    ${NEW_PASSPHRASE}
#    Answer Prompt    new passphrase    ${NEW_PASSPHRASE}
#    Answer Prompt    new passphrase    ${NEW_PASSPHRASE}
#    Match Text    passphrase is incorrect

Replace Passphrase
    [Documentation]    Replace the default passphrase
    Run Command With Prompt    sudo snap-tpmctl replace-passphrase
    Answer Prompt    current passphrase    ${PASSPHRASE}
    Answer Prompt    new passphrase    ${NEW_PASSPHRASE}
    Answer Prompt    new passphrase    ${NEW_PASSPHRASE}
    Match Text    Passphrase replaced successfully    60

Remove Passphrase
    [Documentation]    Remove the default passphrase
    Run Command In Terminal    sudo snap-tpmctl remove-passphrase
    Match Text    Passphrase removed successfully
    Check No Match In Output    snap-tpmctl list-passphrases    default

Clear System Status
    [Documentation]    Reboot system in order to change auth-mode
    System Reboot

Add Passphrase
    [Documentation]    Add the default passphrase
    Run Command With Prompt    sudo snap-tpmctl add-passphrase
    Answer Prompt    new passphrase    ${PASSPHRASE}
    Answer Prompt    new passphrase    ${PASSPHRASE}
    Match Text    Passphrase added successfully    120
    Run Command In Terminal    snap-tpmctl list-passphrases
    Match Text    default
