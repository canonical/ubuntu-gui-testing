*** Settings ***
Documentation       Shared resources for application testing

Resource            kvm.resource
Resource            ${Y}/common/common.resource


*** Variables ***
${Y}    ${CURDIR}


*** Keywords ***
Open Firefox
    Start Application    firefox
    PlatformVideoInput.Match Text    Firefox    60

Open New Tab
    Move Pointer To ${Y}/generic/new-tab.png
    EzClick
    PlatformVideoInput.Match Text    New Tab    40
