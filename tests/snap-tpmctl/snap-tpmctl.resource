*** Settings ***
Documentation       Shared resources for application testing

Resource            ${Y}/common/common.resource


*** Variables ***
${Y}    ${CURDIR}

${PASSPHRASE}           ubuntu1.
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
    [Documentation]    Log in, install snap-tpmctl and leave a terminal open
    # NOTE: add this when support for TPM/FDE passprahse is re-enabled during installtion
    # Answer Prompt    Enter passphrase or recovery key    ${PASSPHRASE}
    Log In
    Install Snap Package    snap-tpmctl
    Setup Sudo Terminal
