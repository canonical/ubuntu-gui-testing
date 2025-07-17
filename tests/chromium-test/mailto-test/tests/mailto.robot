*** Settings ***
Resource        ${CURDIR}/../chromium.resource

Test Tags       robot:exit-on-failure


*** Test Cases ***
Log-in to Gnome
    Log In

Install Mail Client
    Install Mail Client

Install Chromium
    Install Chromium

Open Chromium and Go To Test Plan website
    Open Chromium With URL      wiki.ubuntu.com/DesktopTeam/TestPlans/Chromium

Check that website was loaded
    Wait For Text   Attachments

Open Test Plan Mail Link
    Find and Press Enter On     mailto

Match Mail Client
    Match Mail Client
