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
