*** Settings ***
Documentation       Shared resources for Chromium testing

Resource            kvm.resource
Resource            ${Y}/common/common.resource


*** Variables ***
${Y}    ${CURDIR}


*** Keywords ***
Open Chromium
    Start Application    /snap/bin/chromium
    PlatformVideoInput.Match Text    New Tab

Install Mail Client
    Install Debian Package    evolution

Install Chromium
    Install Snap Package    chromium

Open Chromium Mail Link
    Start Application    /snap/bin/chromium wiki.ubuntu.com/DesktopTeam/TestPlans/Chromium
    PlatformVideoInput.Match Text    Attachments

    ${combo}    Create List    Control_L    f
    PlatformHid.Keys Combo    ${combo}
    PlatformHid.Type String    mailto
    ${esc}    Create List    Escape
    ${ret}    Create List    Return
    PlatformHid.Keys Combo    ${esc}
    PlatformHid.Keys Combo    ${ret}

Match Mail Client
    PlatformVideoInput.Match Text    From
    PlatformVideoInput.Match Text    To
    PlatformVideoInput.Match Text    foobar@nospam.org
