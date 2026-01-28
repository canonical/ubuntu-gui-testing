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
