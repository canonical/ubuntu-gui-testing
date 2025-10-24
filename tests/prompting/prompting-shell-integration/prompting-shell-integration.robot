*** Settings ***
Documentation       Spawns a single prompt and checks that the shell extension guarantees its visibility

Resource            ${Z}/../prompting.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log in to desktop session
    Log In

Enable Prompting
    [Documentation]    Enable prompting
    Enable Prompting

Download Example File
    [Documentation]    Download example.com as html
    Open Firefox
    Open Firefox Tab    example.com    Example Domain
    Save File
    Match Text    Firefox wants to get write access    60
    BuiltIn.Sleep    1
    # Try to re-focus firefox
    Click LEFT Button On Example Domain
    BuiltIn.Sleep    1
    Match Text    Firefox wants to get write access
    BuiltIn.Sleep    1
    # Try to close firefox
    Click LEFT Button On ${Y}/generic/inactive-window-close-button.png
    BuiltIn.Sleep    1
    Match Text    Firefox wants to get write access
