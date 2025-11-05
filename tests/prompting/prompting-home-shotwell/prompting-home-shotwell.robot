*** Settings ***
Documentation       Opens and list a picture in shotwell

Resource            ${Z}/../prompting.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log in to desktop session
    Log In

Install shotwell
    [Documentation]    Install the shotwell snap
    Install Snap Package    shotwell

Prepare Image File
    [Documentation]    Copy the shotwell icon to the Pictures directory
    Open Terminal
    Run Command In Terminal    snap debug api /v2/icons/shotwell/icon > Pictures/TESTIMAGE.png
    Close Current Window

Enable Prompting
    [Documentation]    Enable prompting
    Enable Prompting

Deny Shotwell Prompt
    [Documentation]    Launch shotwell and deny prompt
    Start Application    shotwell
    Focus Prompt
    Reply To Simple Prompt    shotwell wants to get read access to Pictures    Deny once
    Reply To Simple Prompt    shotwell wants to get read access to Pictures    Deny once
    Match Text    Shotwell    60
    # close welcome window
    Click LEFT Button On OK
    Match Text    Shotwell
    Ensure Last Import Does Not Match
    Close Current Window

Allow Shotwell Prompt
    [Documentation]    Launch shotwell and allow prompt
    Start Application    shotwell
    Focus Prompt
    Reply To Simple Prompt    shotwell wants to get read access to Pictures    Allow always
    Match Text    Shotwell    60
    Keys Combo    Control_L    i
    Click LEFT Button On Pictures
    Click LEFT Button On TESTIMAGE
    Click LEFT Button On OK
    Match Text    Import Complete    60
    Click LEFT Button On OK
    Match Text    Shotwell
    Close Current Window
