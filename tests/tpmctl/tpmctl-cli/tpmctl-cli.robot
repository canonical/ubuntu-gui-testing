*** Settings ***
Documentation       Tests for tpmctl

Library             String
Resource            ${Z}/../tpmctl.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}

${NEW_PASSPHRASE}    ubuntu2.
${PIN}    123451234512345
${VOLUME_NAME}    my-vol
${RECOVERY_KEY_NAME}    test-recovery-key


*** Test Cases ***
Unlock System With Passphrase
    [Documentation]    Unlock the system with passphrase
    Unlock System With Passphrase

Log In
    [Documentation]    Log in to desktop session
    Log In

Install tpmctl
    [Documentation]    Install the tpmctl snap
    # TODO: install from the store
    Open Terminal
    Run Command In Terminal    git clone http://github.com/canonical/snap-tpmctl && cd snap-tpmctl
    Run Command In Terminal    snapcraft pack
    Run Command In Terminal    sudo snap install *.snap --dangerous
    Run Command In Terminal    cd $HOME
    Run Command In Terminal    sudo snap connect tpmctl:snapd-control && sudo snap connect tpmctl:hardware-observe && sudo snap connect tpmctl:mountctl && sudo snap connect tpmctl:mount-observe && sudo snap connect tpmctl:block-devices && sudo snap connect tpmctl:dm-crypt

Print Status
    [Documentation]    Print TPM/FDE status
    Run Command In Terminal    tpmctl status
    Match Text    INDETERMINATE

List All Recovery Keys
    [Documentation]    List all recovery keys
    Run Command In Terminal    tpmctl list-all
    Match Text    default-recovery
    Match Text    passphrase

Check Recovery Key
    [Documentation]    Check existing recovery key
    Run Command In Terminal    sudo tpmctl check-recovery-key
    Answer Prompt    Enter recovery key:    ${RECOVERY_KEY}
    Match Text    recovery key works

Check Recovery Key With Fail
    [Documentation]    Check existing recovery key
    Run Command In Terminal    sudo tpmctl check-recovery-key
    Answer Prompt    Enter recovery key:    ${VOLUME_RECOVERY_KEY}
    Match Text    recovery key doesn't work

Create A New Recovery Key
    [Documentation]    Create a new recovery key
    Run Command In Terminal    sudo tpmctl create-recovery-key ${RECOVERY_KEY_NAME}
    Match Text    Recovery Key:
    Run Command In Terminal    tpmctl list-recovery-keys
    Match Text    default
    Match Text    ${RECOVERY_KEY_NAME}

Regenerate An Existing Recovery Key
    [Documentation]    Regenerate a recovery key
    Run Command In Terminal    sudo tpmctl regenerate-recovery-key ${RECOVERY_KEY_NAME}
    Match Text    Recovery Key:

Replace Passphrase With Fail
    [Documentation]    Fail to replace the default passphrase due incorrect passphrase
    Run Command In Terminal    sudo tpmctl replace-passphrase
    Answer Prompt    current passphrase    ${NEW_PASSPHRASE}
    Answer Prompt    new passphrase    ${NEW_PASSPHRASE}
    Answer Prompt    new passphrase    ${NEW_PASSPHRASE}
    Match Text    passphrase is incorrect

Replace Passphrase
    [Documentation]    Replace the default passphrase
    Run Command In Terminal    sudo tpmctl replace-passphrase
    Answer Prompt    current passphrase    ${PASSPHRASE}
    Answer Prompt    new passphrase    ${NEW_PASSPHRASE}
    Answer Prompt    new passphrase    ${NEW_PASSPHRASE}
    Match Text    Passphrase replaced successfully

Remove Passphrase
    [Documentation]    Remove the default passphrase passphrase
    Run Command In Terminal    sudo tpmctl remove-passphrase
    Match Text    Passphrase removed successfully
    Check No Match In Output    tpmctl list-passphrases    default

Add Passphrase
    [Documentation]    Add the default passphrase passphrase
    Run Command In Terminal    sudo tpmctl add-passphrase
    Answer Prompt    new passphrase    ${PASSPHRASE}
    Answer Prompt    new passphrase    ${PASSPHRASE}
    Match Text    Passphrase added successfully
    Run Command In Terminal    tpmctl list-passphrases
    Match Text    default

Add Pin
    [Documentation]    Replace the passphrase with a pin
    Run Command In Terminal    sudo tpmctl remove-passphrase
    # reboot system in order to change the auth-mode from passphrase to none
    Reboot System
    Run Sudo Command In Terminal    sudo tpmctl add-pin
    Answer Prompt    new pin    ${PIN}
    Match Text    Pin added successfully
    Run Command In Terminal    tpmctl list-pins
    Match Text    default

Remove Pin
    [Documentation]    Remove pin from the system
    Run Command In Terminal    sudo tpmctl remove-pin
    Match Text    Pin removed successfully
    Check No Match In Output    tpmctl list-pins    default

Mount LUKS Volume
    [Documentation]    Mount a LUKS volume portected with a passphrase
    Run Simple Command    sudo tpmctl mount-volume ${DEVICE_PATH} ${VOLUME_NAME}
    Answer Prompt    Enter recovery key:    ${VOLUME_RECOVERY_KEY}
    BuiltIn.Sleep    1
    Run Command In Terminal    ls /dev/mapper
    Match Text    ${VOLUME_NAME}

Unmount LUKS Volume
    [Documentation]    Unmount a LUKS volume
    Run Command In Terminal    sudo tpmctl unmount-volume ${VOLUME_NAME}
    Run Command In Terminal    echo $?
    Match Text    0

Unmount LUKS Volume With Fail
    [Documentation]    Unmount a LUKS volume
    Run Command In Terminal    sudo tpmctl unmount-volume ${VOLUME_NAME}
    Match Text    ERROR systemd-cryptsetup failed with:
