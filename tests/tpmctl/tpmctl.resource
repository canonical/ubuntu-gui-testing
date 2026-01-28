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

Answer Prompt
    [Documentation]    Answer to a prompt
    [Arguments]    ${prompt}    ${input}
    Match Text    ${prompt}    10
    Type String    ${input}
    Keys Combo    Return

Unlock System With Passphrase
    [Documentation]    Unlock the system with passphrase
    Answer Prompt    Please enter passphrase    ${PASSPHRASE}

System Reboot
    [Documentation]    Reboot the system and log in again
    Run Simple Command    reboot
    Unlock System With Passphrase
    Log In
    Open Terminal

Check No Match In Output
    [Documentation]    Run a command in terminal and check that the give output isn't present
    [Arguments]    ${cmd}    ${output}
    Run Command In Terminal    ${cmd} | grep ${output}
    Run Command In Terminal    echo $?
    Match Text    1
