*** Settings ***
Documentation       Downloads a file with Firefox

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

Download File
    [Documentation]    Download 24.04 netboot image
    Open Chromium
    Open Browser Tab    https://releases.ubuntu.com/noble/ubuntu-24.04.3-netboot-amd64.tar.gz
    FOR    ${_}    IN RANGE    2
        Reply To Simple Prompt    Chromium wants to get write access    Deny once
    END
    Check File Does Not Exist    ~/Downloads/ubuntu-24.04.3-netboot-amd64.tar.gz

    Open Browser Tab    https://releases.ubuntu.com/noble/ubuntu-24.04.3-netboot-amd64.tar.gz
    Reply To Simple Prompt    Chromium wants to get write access    Allow always
    Reply To Simple Prompt    Chromium wants to get read access    Allow always
    Match Text    Done    120
    Check File Exists    ~/Downloads/ubuntu-24.04.3-netboot-amd64.tar.gz
    Check File Does Not Exist    ~/Downloads/*.part
