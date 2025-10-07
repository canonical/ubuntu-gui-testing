*** Settings ***
Documentation       Opens and saves a file in gimp

Resource            ${Z}/../prompting.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log in to desktop session
    Log In

Install gimp
    [Documentation]    Install the gimp snap
    Install Snap Package    gimp

Prepare Image File
    [Documentation]    Copy the gimp icon to the home directory
    Open Terminal
    Run Command In Terminal    snap debug api /v2/icons/gimp/icon>TESTIMAGE.png
    Close Terminal

Enable Prompting
    [Documentation]    Enable prompting
    Enable Prompting

First Launch
    [Documentation]    Launch GIMP for the first time
    Open Gimp
    Ensure No Prompts
    Close Current Window

Open Nautilus
    [Documentation]    Open file explorer
    Start Application    nautilus
    BuiltIn.Sleep    1

Open Image And Deny All Prompts
    [Documentation]    Open and image file with GIMP from the file manager and deny all prompts
    Open Image With Gimp From Nautilus    Deny once

Close GIMP
    [Documentation]    Close GIMP and try again
    Close Current Window

Open Image And Allow All Prompts
    [Documentation]    Open and image file with GIMP from the file manager and allow all prompts
    Open Image With Gimp From Nautilus    Allow always

Save Image And Deny All Prompts
    [Documentation]    Save the opened test file in the Pictures directory and deny all prompts
    Save Gimp Image In Pictures Directory    Deny once

Save Image And Allow All Prompts
    [Documentation]    Save the opened test file in the Pictures directory and allow all prompts
    Save Gimp Image In Pictures Directory    Allow always

Verify Saved Image
    [Documentation]    Verifies that the image has been saved to the Pictures directory
    Close Current Window    # close GIMP
    BuiltIn.Sleep    5
    Click LEFT Button On Pictures
    Keys Combo    Return
    Match Text    TESTIMAGE
