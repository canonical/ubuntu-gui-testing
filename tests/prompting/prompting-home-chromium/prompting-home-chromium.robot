*** Settings ***
Documentation       Downloads a file with Chromium

Resource            ${Z}/../prompting.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log in to desktop session
    Log In

Install Chromium
    [Documentation]    Install the chromium snap
    Install Snap Package    chromium

Enable Prompting
    [Documentation]    Enable prompting
    Enable Prompting

Download Example File
    [Documentation]    Download example.com as html
    Open Chromium
    Open Browser Tab    example.com    Example Domain
    Save File
    Reply To Simple Prompt    chromium wants to get write access    Allow always
