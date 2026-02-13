*** Settings ***
Documentation       Tests for snap-tpmctl

Library             String
Resource            ${Z}/../snap-tpmctl.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}

${NEW_PASSPHRASE}    ubuntu2.
${PIN}    123451234512345
${DIRECTORY}    /media/my-vol
${RECOVERY_KEY_NAME}    test-recovery-key


*** Test Cases ***
Unlock System With Passphrase
    [Documentation]    Unlock the system with passphrase
    Answer Prompt    Enter passphrase or recovery key    ${PASSPHRASE}

Log In
    [Documentation]    Log in to desktop session
    Log In

Install snap-tpmctl
    [Documentation]    Install the snap-tpmctl snap
    Install Snap Package    snap-tpmctl
    Open Terminal
    Run Sudo Command In Terminal    sudo snap connect snap-tpmctl:snapd-control
    Run Command In Terminal    sudo snap connect snap-tpmctl:hardware-observe
    Run Command In Terminal    sudo snap connect snap-tpmctl:mountctl
    Run Command In Terminal    sudo snap connect snap-tpmctl:mount-observe
    Run Command In Terminal    sudo snap connect snap-tpmctl:block-devices
    Run Command In Terminal    sudo snap connect snap-tpmctl:dm-crypt

Print Status
    [Documentation]    Print TPM/FDE status
    Open Terminal
    Run Command In Terminal    snap-tpmctl status
    Match Text    INDETERMINATE

List All Recovery Keys
    [Documentation]    List all recovery keys
    Run Command In Terminal    snap-tpmctl list-all
    Match Text    default-recovery
    Match Text    passphrase

Check Recovery Key
    [Documentation]    Check existing recovery key
    Run Command With Prompt    sudo snap-tpmctl check-recovery-key
    Answer Prompt    Enter recovery key:    ${RECOVERY_KEY}
    Match Text    recovery key works

Check Recovery Key With Fail
    [Documentation]    Check existing recovery key
    Run Command With Prompt    sudo snap-tpmctl check-recovery-key
    Answer Prompt    Enter recovery key:    ${VOLUME_RECOVERY_KEY}
    Match Text    recovery key doesn't work

Create A New Recovery Key
    [Documentation]    Create a new recovery key
    Run Command In Terminal    sudo snap-tpmctl create-recovery-key ${RECOVERY_KEY_NAME}
    Match Text    Recovery Key:
    Keys Combo    Return
    Run Command In Terminal    snap-tpmctl list-recovery-keys
    Match Text    default
    Match Text    ${RECOVERY_KEY_NAME}

Regenerate An Existing Recovery Key
    [Documentation]    Regenerate a recovery key
    Run Command In Terminal    sudo snap-tpmctl regenerate-recovery-key ${RECOVERY_KEY_NAME}
    Match Text    Recovery Key:
    Keys Combo    Return

Replace Passphrase With Fail
    [Documentation]    Fail to replace the default passphrase due incorrect passphrase
    Run Command With Prompt    sudo snap-tpmctl replace-passphrase
    Answer Prompt    current passphrase    ${NEW_PASSPHRASE}
    Answer Prompt    new passphrase    ${NEW_PASSPHRASE}
    Answer Prompt    new passphrase    ${NEW_PASSPHRASE}
    Match Text    passphrase is incorrect

Replace Passphrase
    [Documentation]    Replace the default passphrase
    Run Command With Prompt    sudo snap-tpmctl replace-passphrase
    Answer Prompt    current passphrase    ${PASSPHRASE}
    Answer Prompt    new passphrase    ${NEW_PASSPHRASE}
    Answer Prompt    new passphrase    ${NEW_PASSPHRASE}
    Match Text    Passphrase replaced successfully    60

Remove Passphrase
    [Documentation]    Remove the default passphrase passphrase
    Run Command In Terminal    sudo snap-tpmctl remove-passphrase
    Match Text    Passphrase removed successfully
    Check No Match In Output    snap-tpmctl list-passphrases    default

Add PIN
    [Documentation]    Replace the passphrase with a pin
    # reboot system in order to change the auth-mode from passphrase to none
    System Reboot

    Run Command With Prompt    sudo snap-tpmctl add-pin
    Answer Prompt    new PIN    ${PIN}
    Answer Prompt    new PIN    ${PIN}
    Match Text    PIN added successfully
    Run Command In Terminal    snap-tpmctl list-pins
    Match Text    default

Remove PIN
    [Documentation]    Remove pin from the system
    # reboot system in order to change the auth-mode from none to pin
    System Reboot    Enter PIN or recovery key    ${PIN}
    Run Command In Terminal    sudo snap-tpmctl remove-pin
    Match Text    PIN removed successfully
    Check No Match In Output    snap-tpmctl list-pins    default

Add Passphrase
    [Documentation]    Add the default passphrase passphrase
    # reboot system in order to change the auth-mode from pin to none
    System Reboot
    Run Command With Prompt    sudo snap-tpmctl add-passphrase
    Answer Prompt    new passphrase    ${PASSPHRASE}
    Answer Prompt    new passphrase    ${PASSPHRASE}
    Match Text    Passphrase added successfully    60
    Run Command In Terminal    snap-tpmctl list-passphrases
    Match Text    default

Mount LUKS Volume With Fail
    [Documentation]    Mount a LUKS volume portected with a passphrase
    Run Command With Prompt    sudo snap-tpmctl mount-volume ${DEVICE} test
    Match Text    directory path must be a valid absolute path

Mount LUKS Volume
    [Documentation]    Mount a LUKS volume portected with a passphrase
    Run Command With Prompt    sudo snap-tpmctl mount-volume ${DEVICE} ${DIRECTORY}
    Answer Prompt    Enter recovery key:    ${VOLUME_RECOVERY_KEY}
    BuiltIn.Sleep    1
    Run Command In Terminal    lsblk | grep ${DIRECTORY}
    Match Text    crypt ${DIRECTORY}

Unmount LUKS Volume
    [Documentation]    Unmount a LUKS volume
    Run Command In Terminal    sudo snap-tpmctl unmount-volume ${DIRECTORY}
    Run Command In Terminal    lsblk | grep ${DIRECTORY}
    Run Command In Terminal    echo $?
    Match Text    1

Unmount LUKS Volume With Fail
    [Documentation]    Unmount a LUKS volume
    Run Command In Terminal    sudo snap-tpmctl unmount-volume ${DIRECTORY}
    Match Text    ERROR systemd-cryptsetup failed with:
