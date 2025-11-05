*** Settings ***
Documentation       Opens a file in VLC

Resource            ${Z}/../prompting.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log in to desktop session
    Log In

Install vlc
    [Documentation]    Install the vlc snap
    Install Snap Package    vlc

Prepare Image File
    [Documentation]    Copy the vlc icon to the home directory
    Open Terminal
    Run Command In Terminal    snap debug api /v2/icons/vlc/icon>TESTIMAGE.png
    Close Terminal

Enable Prompting
    [Documentation]    Enable prompting
    Enable Prompting

Open Image In VLC And Deny All Prompts
    [Documentation]    Open the test image in vlc
    Start Application    vlc TESTIMAGE.png
    Reply To Simple Prompt    vlc wants to get read access to the Documents folder    Deny once
    FOR    ${_}    IN RANGE    6
        Focus Prompt
        Reply To Simple Prompt    vlc wants to get read access to TESTIMAGE.png    Deny once
    END
    Match Text    Continue    60
    Click LEFT Button On Continue
    Match Text    Your input can't be opened
    Close Current Window
    Close Current Window

Open Image In VLC And Allow All Prompts
    [Documentation]    Open the test image in vlc
    Start Application    vlc TESTIMAGE.png
    FOR    ${folder}    IN    Documents    Desktop    Downloads    Music    Pictures    Videos    Public    Templates
        Reply To Simple Prompt    vlc wants to get read access to the ${folder} folder    Allow always
    END
    Reply To Simple Prompt    vlc wants to get read access to TESTIMAGE.png    Allow always
    Reply To Simple Prompt    vlc wants to get read access to your Home folder    Allow always
    Match Text    0:10
