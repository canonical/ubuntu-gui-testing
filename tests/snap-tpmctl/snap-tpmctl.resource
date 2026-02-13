*** Settings ***
Documentation       Shared resources for application testing

Resource            kvm.resource
Resource            ${Y}/common/common.resource


*** Variables ***
${Y}    ${CURDIR}


*** Keywords ***
Run Simple Command
    [Documentation]    Run command in terminal without verifying the exit status
    [Arguments]    ${cmd}
    Type String    ${cmd}
    Keys Combo    Return

Run Command With Prompt
    [Documentation]    Run command expecting an input prompt
    [Arguments]    ${cmd}
    Run Simple Command    clear && ${cmd}

Answer Prompt
    [Documentation]    Answer to a prompt
    [Arguments]    ${prompt}    ${input}
    Match Text    ${prompt}    20
    Type String    ${input}
    Keys Combo    Return

System Reboot
    [Documentation]    Reboot the system and log in again
    [Arguments]    ${with_prompt}=${False}    ${prompt}=""    ${input}=""
    Run Simple Command    reboot
    BuiltIn.Sleep    60
    IF    ${with_prompt}    Answer Prompt    ${prompt}    ${input}
    Log In
    Open Terminal
    Run Sudo Command In Terminal    sudo echo

Check No Match In Output
    [Documentation]    Run a command in terminal and check that the give output isn't present
    [Arguments]    ${cmd}    ${output}
    Run Simple Command   ${cmd} | grep ${output}
    Run Command In Terminal    echo $?
    Match Text    1
