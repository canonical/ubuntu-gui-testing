*** Settings ***
Documentation       Spawns a single prompt and replies to it

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
    Reply To Simple Prompt    Firefox wants to get write access    Allow always
    Verify Firefox Download
