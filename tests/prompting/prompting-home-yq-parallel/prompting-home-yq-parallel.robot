*** Settings ***
Documentation       Spawns two parallel prompts for two instances of the same snap and answers them in reverse order

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
    Open Terminal
    Run Sudo Command In Terminal    sudo snap install yq
    Close Terminal

Enable Prompting
    [Documentation]    Enable prompting
    Enable Prompting

Trigger First yq Prompt
    [Documentation]    Open a terminal, run yq on a test file and wait for a prompt
    Trigger First yq Prompt

Trigger Second yq Prompt
    [Documentation]    Open a terminal, run yq on a second test file and wait for another prompt
    Trigger Second yq Prompt

Deny Second yq Prompt
    [Documentation]    Deny prompt for second yq command, verify that read access is denied
    Deny Second yq Prompt

Allow First yq Prompt
    [Documentation]    Allow the prompt for the first yq command, verify that the command succeeds
    Allow First yq Prompt
