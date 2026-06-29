*** Settings ***
Documentation       Bootstrap tests for snap-tpmctl CLI

Resource            ${Z}/../snap-tpmctl.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}                ${CURDIR}


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

Print Status
    [Documentation]    Print TPM/FDE status
    Open Terminal
    Run Sudo Command In Terminal    sudo snap-tpmctl status
    Match Text    ACTIVE
