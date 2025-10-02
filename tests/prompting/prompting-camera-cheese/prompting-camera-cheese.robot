*** Settings ***
Documentation       Basic tests for the prompting-client snap

Resource            ${Z}/../prompting.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Setup
    [Documentation]    Use rapidocr rather than tesseract-ocr in yarf
    Set Ocr Method    rapidocr

Log In
    [Documentation]    Log in to desktop environment
    Log In

Prepare Test Enviroment
    [Documentation]    Prepare test enviroment
    Install Snap Package    cheese
    Install Debian Package    gstreamer1.0-tools
    Open Terminal
    Run Sudo Command In Terminal    sudo modprobe v4l2loopback devices=1 video_nr=0 exclusive_caps=1
    Run Simple Command    gst-launch-1.0 videotestsrc ! videoconvert ! v4l2sink device=/dev/video0
    BuiltIn.Sleep    2

Enable Prompting
    [Documentation]    Enable prompting
    Enable Prompting

Deny Once
    [Documentation]    Deny access to camera interface
    Start Application    cheese
    # The first attempt will spawn 3 prompts
    Reply To Simple Prompt    Allow cheese to access your camera?    Deny Once
    Reply To Simple Prompt    Allow cheese to access your camera?    Deny Once
    Reply To Simple Prompt    Allow cheese to access your camera?    Deny Once
    Cheese No Device
    Close Current Window
    BuiltIn.Sleep    2

Allow Until Logout
    [Documentation]    Allow access to camera interface until logout
    Start Application    cheese
    Reply To Simple Prompt    Allow cheese to access your camera?    Allow until logout
    Cheese With Video
    Close Current Window
    BuiltIn.Sleep    2

No Prompt
    [Documentation]    Verify no prompt is shown due the "Allow Until Logout"
    Start Application    cheese
    Cheese With Video
    Close Current Window
    BuiltIn.Sleep    2
