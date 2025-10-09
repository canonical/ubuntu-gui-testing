*** Settings ***
Documentation       Opens Thunderbird

Resource            ${Z}/../prompting.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log in to desktop session
    Log In

Install Thunderbird Snap
    [Documentation]    Install the thunderbird snap
    Install Snap Package    thunderbird

Enable Prompting
    [Documentation]    Enable prompting
    Enable Prompting

Open Thunderbird And Deny Prompt
    [Documentation]    Open thunderbird and deny all prompts
    Open Thunderbird    Deny Once
    Close Current Window
    BuiltIn.Sleep    3

Open Thunderbird And Allow Prompt
    [Documentation]    Open thunderbird and deny all prompts
    Open Thunderbird    Allow always
    Close Current Window
    BuiltIn.Sleep    3
