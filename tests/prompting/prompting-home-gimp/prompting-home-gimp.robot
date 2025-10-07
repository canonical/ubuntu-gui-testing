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

Open Image With Gimp From Nautilus
    [Documentation]    Open and image file with GIMP from the file manager and handle the prompt
    Start Application    nautilus
    BuiltIn.Sleep    1
    Click RIGHT Button On TESTIMAGE
    BuiltIn.Sleep    1
    Click LEFT Button On 'Open with...'
    BuiltIn.Sleep    1
    Click LEFT Button On GNU Image Manipulation
    BuiltIn.Sleep    1
    Keys Combo    Return
    Reply To Simple Prompt    gimp wants to get read access    Allow always
    Click LEFT Button On Welcome to GIMP
    BuiltIn.Sleep    5
    Close Current Window    # close GIMP welcome screen
    BuiltIn.Sleep    5

Save Image In Pictures Directory
    [Documentation]    Save the opened test file in the Pictures directory and answer all prompts
    Keys Combo    Control_L    s
    Reply To Simple Prompt    gimp wants to get read access to your Home folder    Allow always
    Click LEFT Button On Pictures
    BuiltIn.Sleep    1
    Keys Combo    Return
    Reply To Simple Prompt    gimp wants to get read access to the Pictures folder    Allow always
    BuiltIn.Sleep    1
    Keys Combo    Return
    Reply To Simple Prompt    gimp wants to get write access to TESTIMAGE.xcf    Allow always
    BuiltIn.Sleep    1
    Close Current Window
    BuiltIn.Sleep    5
    Click LEFT Button On Pictures
    BuiltIn.Sleep    1
    Keys Combo    Return
    Match Text    TESTIMAGE
