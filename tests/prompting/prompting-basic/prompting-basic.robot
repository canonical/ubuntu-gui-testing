*** Settings ***
Resource        ${Z}/../prompting.resource

Test Tags       robot:exit-on-failure


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    Log In

Enable Prompting
    Open Security Center
    Enable Prompting
    Close Current Window
    BuiltIn.Sleep    1

Download Example File
    Open Firefox
    Open Example Domain
    Save File
