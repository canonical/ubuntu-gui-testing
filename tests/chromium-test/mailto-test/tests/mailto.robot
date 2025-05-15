*** Settings ***
Resource        ${Z}/../chromium.resource

Test Tags       robot:exit-on-failure


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log-in to Gnome
    Log In

Install Mail Client
    Install Mail Client

Install Chromium
    Install Chromium

Open Chromium Mail Link
    Open Chromium Mail Link

Match Mail Client
    Match Mail Client
