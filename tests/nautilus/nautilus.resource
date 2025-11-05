*** Settings ***
Documentation       Shared resources for application testing

Resource            kvm.resource
Resource            ${Y}/common/common.resource


*** Variables ***
${Y}    ${CURDIR}


*** Keywords ***
Open Nautilus
    [Documentation]         Open Nautilus app by clicking on its icon
    Move Pointer To ${Y}/generic/icon.png
    EzClick
    Match Text    Files
    BuiltIn.Sleep    5

Close Nautilus
    [Documentation]         Close Nautilus by clicking on the close button in the title-bar
    Move Pointer To ${Y}/generic/close-icon.png
    EzClick
    FOR    ${_}    IN RANGE    30
        ${found}    Run Keyword And Return Status    Match Text    Files    5
        IF    ${found}    BuiltIn.Sleep    1    ELSE    BREAK
    END

Open Context Menu At
    [Documentation]         Open the context menu at location (text or image)
    [Arguments]    ${where}
    Move Pointer To ${where}
    Click RIGHT Button
    MatchText    Open With...
    BuiltIn.Sleep    1

Open Background Context Menu
    [Documentation]         Open a context menu on the view backgroud
    Open Context Menu At    ${Y}/generic/background.png

Double Click
    [Documentation]         Perform a double click
    Click LEFT Button
    BuiltIn.Sleep    0.1
    Click LEFT Button

Match Home
    [Documentation]         Asserts that the current directory is Home
    Match Text    snap

Click On
    [Documentation]         Left-click on the specified text
    [Arguments]    ${text}
    Move Pointer To ${text}
    EzClick
