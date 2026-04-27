*** Settings ***
Documentation       Opens and saves a file in Notepad Plus Plus

Resource            ${Z}/../prompting.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log in to desktop session
    Log In

Install Notepad Plus Plus
    [Documentation]    Install the Notepad Plus Plus snap
    Install Snap Package    notepad-plus-plus

Prepare Test File
    [Documentation]    Cetea test file in the home directory
    Open Terminal
    Run Command In Terminal    echo "hello world" > TESTFILE
    Close Current Window

Enable Prompting
    [Documentation]    Enable prompting
    Enable Prompting

First Launch
    [Documentation]    Launch Notepad Plus Plus for the first time and init Wine
    Start Application    notepad-plus-plus
    Reply To Simple Prompt    notepad-plus-plus wants to get read access    Deny once
    Match Text    Wine    60
    BuiltIn.Sleep    10
    FOR    ${_}    IN RANGE    8
        Reply To Simple Prompt    notepad-plus-plus wants to get read access    Deny once
    END
    Click LEFT Button On Never
    BuiltIn.Sleep    1
    Close Current Window

Open Nautilus
    [Documentation]    Open file explorer
    Start Application    nautilus
    BuiltIn.Sleep    1

Open File And Deny All Prompts
    [Documentation]    Open a file with Notepad Plus Plus from the file manager and deny all prompts
    Open File With Notepad Plus Plus From Nautilus    Deny once

Close Notepad Plus Plus
    [Documentation]    Close Notepad Plus Plus and try again
    Close Current Window

Open File And Allow All Prompts
    [Documentation]    Open a file with Notepad Plus Plus from the file manager and allow all prompts
    Open File With Notepad Plus Plus From Nautilus    Allow always

# Deny path is too messy for now, we can ignore it until we have a better general workflow for prompting
#
# Save File And Deny All Prompts
#     [Documentation]    Save the opened test file in the Documents directory and deny all prompts
#     Save Notepad Plus Plus File In Documents Directory    Deny once

Save Image And Allow All Prompts
    [Documentation]    Save the opened test file in the Documents directory and allow all prompts
    Save Notepad Plus Plus File In Documents Directory    Allow always

Verify Saved File
    [Documentation]    Verifies that the file has been saved to the Documents directory
    Check File Exists    ~/TESTFILE.txt
