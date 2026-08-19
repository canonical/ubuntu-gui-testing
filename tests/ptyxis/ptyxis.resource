*** Settings ***
Documentation  Shared resources for Ptyxis testing

Resource       kvm.resource
Resource       ${PKG}/common/common.resource

*** Variables ***
${PKG}  ${CURDIR}

*** Keywords ***
Install Ptyxis
    Install Debian Package  ptyxis

Open Ptyxis
    Start Application  ptyxis
    PlatformVideoInput.Match Text  ubuntu@ubuntu: ~

Set Progress
    [Arguments]  ${progress}
    PlatformHid.Type String  echo -e '\\e]9;4;1;
    PlatformHid.Type String  ${progress}
    PlatformHid.Type String  \\e\\\\'
    ${enter}  Create List  Return
    PlatformHid.Keys Combo  ${enter}
