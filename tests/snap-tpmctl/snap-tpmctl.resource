*** Settings ***
Documentation       Shared resources for application testing

Resource            ${Y}/common/common.resource


*** Variables ***
${Y}    ${CURDIR}

${NEW_PASSPHRASE}       ubuntu2.
${PIN}                  123451234512345
${NEW_PIN}              543215432154321
${RECOVERY_KEY_NAME}    test-recovery-key
${FAKE_RECOVERY_KEY}    11111-22222-33333-44444-55555-12345-23451-34512


*** Keywords ***
Setup Sudo Terminal
    [Documentation]    Open a terminal and cache sudo credentials.
    Open Terminal
    Run Sudo Command In Terminal   sudo -v

Bootstrap Snap Tpmctl CLI
    [Documentation]    Unlock, log in, install snap-tpmctl and leave a terminal open
    Answer Prompt    Enter passphrase or recovery key    ${PASSPHRASE}
    Log In
    Install Snap Package    snap-tpmctl
    Setup Sudo Terminal

Bootstrap And Remove Password
    [Documentation]    Bootstrap snap-tpmctl CLI and remove the existing passphrase.
    Bootstrap Snap Tpmctl CLI
    Run Command In Terminal    sudo snap-tpmctl remove-passphrase
    # reboot system in order to change the auth-mode from `passphrase` to `none`
    System Reboot
    Setup Sudo Terminal
