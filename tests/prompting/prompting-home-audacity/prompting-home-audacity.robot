*** Settings ***
Documentation       Opens and list a picture in audacity

Resource            ${Z}/../prompting.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log in to desktop session
    Log In

Install Audacity
    [Documentation]    Install the audacity snap
    Install Snap Package    audacity
    Open Terminal
    Run Sudo Command In Terminal    sudo snap connect audacity:alsa
    Close Terminal

Prepare Audio File
    [Documentation]    Prepare the test environment
    Install Debian Package    curl
    Open Terminal
    Run Command In Terminal    curl -s -o TESTAUDIO.ogg https://upload.wikimedia.org/wikipedia/commons/3/38/ICBSA_Verdi_-_Luisa_Miller%2C_Quando_le_sere_al_placido.ogg
    Close Current Window

Enable Prompting
    [Documentation]    Enable prompting
    Enable Prompting

First Launch
    [Documentation]    Reaching audacity editing screen and deny all prompts
    Start Application    audacity
    Focus Prompt
    Reply To Simple Prompt    audacity wants to get read access to your Home    Deny once
    Reply To Simple Prompt    audacity wants to get read access to your Home    Deny once
    Match Text    audacity    60
    # close welcome window
    Click LEFT Button On Don't show this again
    Click LEFT Button On OK
    Match Text    audacity
    Ensure TESTAUDIO Does Not Match
    Close Current Window

Open Nautilus
    [Documentation]    Open file explorer
    Start Application    nautilus
    BuiltIn.Sleep    1

Open Audio And Deny All Prompts
    [Documentation]    Open an audio file with audacity from the file manager and deny all prompts
    Open Audio With Audacity From Nautilus    Deny once

Close Audacity
    [Documentation]    Close audacity and try again
    Close Current Window

Open Audio And Allow All Prompts
    [Documentation]    Open an audio file with audacity from the file manager and allow all prompts
    Open Audio With Audacity From Nautilus    Allow always

Save Audio And Deny All Prompts
    [Documentation]    Save the opened test file in the Music directory and deny all prompts
    Save Audacity Audio In Music Directory    Deny once

Save Audio And Allow All Prompts
    [Documentation]    Save the opened test file in the Music directory and allow all prompts
    Save Audacity Audio In Music Directory    Allow always

Verify Saved Audio
    [Documentation]    Verifies that the audio has been saved to the Music directory
    Check File Exists    ~/Music/TESTAUDIO.aup3
