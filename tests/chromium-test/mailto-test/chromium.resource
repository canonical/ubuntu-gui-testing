*** Settings ***
Documentation       Shared resources for Chromium testing

Resource            kvm.resource
Resource            ${CURDIR}/common/common.resource


*** Keywords ***
Open Chromium
    Start Application    /snap/bin/chromium
    PlatformVideoInput.Match Text    New Tab

Install Mail Client
    Install Debian Package    evolution

Install Chromium
    Install Snap Package    chromium

Open Chromium With URL
    [Arguments]     ${url}
    Start Application    /snap/bin/chromium ${url}

Wait for Text
    [Arguments]     ${text2match}
    PlatformVideoInput.Match Text    ${text2match}    60

Find and Press Enter on
    [Arguments]     ${filename}
    ${combo}    Create List    Control_L    f
    PlatformHid.Keys Combo    ${combo}
    PlatformHid.Type String   ${filename}
    ${esc}    Create List    Escape
    ${ret}    Create List    Return
    PlatformHid.Keys Combo    ${ret}
    PlatformHid.Keys Combo    ${esc}
    PlatformHid.Keys Combo    ${ret}

Match Mail Client
    PlatformVideoInput.Match Text    From
    PlatformVideoInput.Match Text    To
    PlatformVideoInput.Match Text    foobar@nospam.org
