*** Settings ***
Resource   ${TEST}/../ptyxis.resource
Test Tags  robot:exit-on-failure

*** Variables ***
${TEST}  ${CURDIR}

*** Test Cases ***
Log-in to Gnome
    Log In

Install Ptyxis
    Install Ptyxis

Start Ptyxis
    Open Ptyxis

Open a new tab
    ${combo}  Create List  Control_L  Shift_L  t
    PlatformHid.Keys Combo  ${combo}

A new tab is visible
    PlatformVideoInput.Match  ${PKG}/generic/tab-close-button.png  5
