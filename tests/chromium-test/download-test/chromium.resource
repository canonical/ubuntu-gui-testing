*** Settings ***
Documentation       Shared resources for Chromium testing

Resource            kvm.resource
Resource            ${CURDIR}/common/common.resource


*** Keywords ***
Open Chromium
    Start Application    /snap/bin/chromium
    PlatformVideoInput.Match Text    New Tab

Install Chromium
    Install Snap Package    chromium

Open Chromium With URL
    [Arguments]     ${url}
    Start Application    /snap/bin/chromium ${url}

Wait for Text
    [Arguments]     ${text2match}
    PlatformVideoInput.Match Text    ${text2match}    90

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

Open Downloads Page
    ${combo}    Create List    Control_L    j
    PlatformHid.Keys Combo    ${combo}
    PlatformVideoInput.Match Text    Download history

Open Downloaded Item
    Move Pointer To ${CURDIR}/tests/assets/open-in-folder.png
    EzClick

Open First Downloaded Item
	${down}    Create List    Down
	${ret}     Create List    Return
	PlatformHid.Keys Combo  ${down}
	PlatformHid.Keys Combo  ${enter}

Check For Downloaded Item
    [Arguments]     ${itemname}
    PlatformVideoInput.Match        ${CURDIR}/tests/assets/open-in-folder.png
    PlatformVideoInput.Match Text   ${itemname}  60
