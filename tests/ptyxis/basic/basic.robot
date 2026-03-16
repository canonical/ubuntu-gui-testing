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

Run a command
    PlatformHid.Type String  cat /etc/os-release
    ${enter}  Create List  Return
    PlatformHid.Keys Combo  ${enter}
    PlatformVideoInput.Match Text  NAME="Ubuntu"  5
