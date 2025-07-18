*** Settings ***
Resource        ${Z}/../papers.resource

Test Tags       robot:exit-on-failure


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    Log In

Open Papers
    Open Papers

Open Document
    Open Document

Manipulate View
    Read Inverted
    Read Rotated
    Toggle Sidebar
