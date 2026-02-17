*** Settings ***
Documentation       Tests for snap-tpmctl

Library             String
Resource            ${Z}/../snap-tpmctl.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}

${DIRECTORY}    /media/my-vol


*** Test Cases ***
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
