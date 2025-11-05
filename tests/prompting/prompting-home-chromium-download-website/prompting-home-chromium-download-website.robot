*** Settings ***
Documentation       Downloads a website with Chromium

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

Download Website
    [Documentation]    Download releases.ubuntu.com/noble as HTML
    Open Chromium
    Open Browser Tab    https://releases.ubuntu.com/noble/    Noble Numbat
    Save File
    FOR    ${_}    IN RANGE    11
        Reply To Simple Prompt    Chromium wants to get write access    Deny once
    END
    Check File Does Not Exist    ~/Downloads/Ubuntu\\ 24.04.3\\ \\(Noble\\ Numbat\\).html
    Check File Does Not Exist    ~/Downloads/Ubuntu\\ 24.04.3\\ \\(Noble\\ Numbat\\)_files/
    Save File
    Reply To Simple Prompt    Chromium wants to get write access    Allow always
    Check File Exists    ~/Downloads/Ubuntu\\ 24.04.3\\ \\(Noble\\ Numbat\\).html
    Check File Exists    ~/Downloads/Ubuntu\\ 24.04.3\\ \\(Noble\\ Numbat\\)_files/
