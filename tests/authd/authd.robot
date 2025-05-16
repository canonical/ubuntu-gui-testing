*** Settings ***
Resource        authd.resource

Test Tags       robot:exit-on-failure


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log in with Entra ID broker via login command
    Log In  # Log in to GNOME with the default user
    Open GNOME Terminal
    Log in with Entra ID
