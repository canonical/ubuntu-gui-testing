*** Settings ***
Resource        ${CURDIR}/../chromium.resource

Test Tags       robot:exit-on-failure


*** Test Cases ***
Log-in to Gnome
    Log In

Install Chromium
    Install Chromium

Open Chromium and Go To Test Plan website
    Open Chromium With URL      wiki.ubuntu.com/DesktopTeam/TestPlans/Chromium

Check that website was loaded
    Wait For Text   Attachments

Download file
    Find and Press Enter On     grace

Go To Download History
    Open Downloads Page

Check Downloaded item
    Check For Downloaded Item   grace

Open Downloaded Item
    Open Downloaded Item

Check For Item in Files
    Wait For Text   Files
