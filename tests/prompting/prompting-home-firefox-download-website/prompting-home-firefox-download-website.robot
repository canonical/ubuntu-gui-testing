*** Settings ***
Documentation       Downloads a website with Firefox

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

Download Website
    [Documentation]    Download releases.ubuntu.com/noble as HTML
    Open Firefox
    Open Browser Tab    https://releases.ubuntu.com/noble/    Noble Numbat
    Save File
    Reply To Simple Prompt    Firefox wants to get write access    Deny once
    Check File Does Not Exist    ~/Downloads/Ubuntu\\ 24.04.3\\ \\(Noble\\ Numbat\\).html
    Check File Does Not Exist    ~/Downloads/Ubuntu\\ 24.04.3\\ \\(Noble\\ Numbat\\)_files/
    Save File
    Reply To Simple Prompt    Firefox wants to get write access    Allow always
    Check File Exists    ~/Downloads/Ubuntu\\ 24.04.3\\ \\(Noble\\ Numbat\\).html
    Check File Exists    ~/Downloads/Ubuntu\\ 24.04.3\\ \\(Noble\\ Numbat\\)_files/
