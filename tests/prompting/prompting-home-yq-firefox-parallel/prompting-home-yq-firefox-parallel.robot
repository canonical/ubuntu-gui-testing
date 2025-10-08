*** Settings ***
Documentation       Spawns parallel prompts in two different snaps

Resource            ${Z}/../prompting.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log in to desktop session
    Log In

Install yq
    [Documentation]    Install the yq snap
    Install Snap Package    yq

Enable Prompting
    [Documentation]    Enable prompting
    Enable Prompting

Trigger Firefox Download Prompt
    [Documentation]    Trigger prompt when downloading example.com as html
    Open Firefox
    Open Firefox Tab    example.com    Example Domain
    Save File

Trigger yq Prompt
    [Documentation]    Open a terminal, run yq on a second test file and wait for another prompt
    Trigger Second yq Prompt
    Deny Second yq Prompt

Allow Firefox Download Prompt
    [Documentation]    Return to Firefox and handle its active prompt
    Reply To Simple Prompt    Firefox wants to get write access    Allow always
    Verify Firefox Download
