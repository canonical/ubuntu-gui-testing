*** Settings ***
Documentation       Shared resources for application testing

Resource            kvm.resource
Resource            ${Y}/common/common.resource


*** Variables ***
${Y}    ${CURDIR}


*** Keywords ***
Open Security Center
    Start Application    desktop-security-center
    PlatformVideoInput.Match Text    Security Center    60

Enable Prompting
    BuiltIn.Sleep    5
    Move Pointer To ${Y}/generic/prompting-toggle-disabled.png
    EzClick
    Handle PolKit Prompt
    PlatformVideoInput.Match    ${Y}/generic/prompting-toggle-enabled.png    60

Handle PolKit Prompt
    ${ret}    Create List    Return
    PlatformVideoInput.Match    ${Y}/generic/polkit-dialog.png
    PlatformHid.Type String    ubuntu
    PlatformHid.Keys Combo    ${ret}

Open Firefox
    Start Application    firefox
    PlatformVideoInput.Match Text    Firefox    60

Open Example Domain
    ${ret}    Create List    Return
    ${new_tab}    Create List    Ctrl    t
    PlatformHid.Keys Combo    ${new_tab}
    PlatformHid.Type String    example.com
    PlatformHid.Keys Combo    ${ret}
    PlatformVideoInput.Match Text    Example Domain 60

Save File
    ${ret}    Create List    Return
    ${save}    Create List    Ctrl    s
    PlatformHid.Keys Combo    ${save}
    BuiltIn.Sleep    1
    Focus Prompt
    Click Text    Allow always
    BuiltIn.Sleep    1
    PlatformHid.Keys Combo    ${ret}
    BuiltIn.Sleep    1
    Focus Prompt
    Click Text    Allow always

Close Current Window
    ${close}    Create List    Alt    F4
    PlatformHid.Keys Combo    ${close}

Focus Prompt
    Move Pointer To ${Y}/generic/shield-icon.png
    EzClick

Click Text
    [Arguments]    ${text}
    Move Pointer To Text    ${text}
    EzClick

Move Pointer To Text
    [Arguments]    ${text}
    ${match}    PlatformVideoInput.Match Text    ${text}
    PlatformHid.Move Pointer To Absolute
    ...    x=${{(${match[0]['region'].right} + ${match[0]['region'].left})//2}}
    ...    y=${{(${match[0]['region'].bottom} + ${match[0]['region'].top})//2}}
