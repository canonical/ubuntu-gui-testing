*** Settings ***
Documentation       Spawns two parallel prompts for two instances of the same snap and verifies that allowing read access to all files in the first prompt resolves the other one as well

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

Answer Both yq Prompts
    [Documentation]    Answer the prompt for the second yq command so that it also resolves the first prompt, verify that both commands succeed
    Answer Both yq Prompts
