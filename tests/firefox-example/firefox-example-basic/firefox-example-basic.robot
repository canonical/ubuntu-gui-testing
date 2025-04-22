*** Settings ***
Resource        ${Z}/../firefox-example.resource

Test Tags       robot:exit-on-failure


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    Log In

Open Firefox
    Open Firefox

Open New Tab
    Open New Tab
