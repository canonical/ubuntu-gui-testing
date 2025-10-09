*** Settings ***
Documentation       Enable Camera permissions for the Cheese snap

Resource            ${Z}/../desktop-security-center.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log into ubuntu user
    Log In

Setup VM
    [Documentation]    Install the Cheese snap
    Install Snap Package    cheese

Open Security Center With Camera Interface
    [Documentation]    Open the Security Center from the cli
    Open Security Center With Camera Interface

Open Camera Snaps Page
    [Documentation]    Open the Camera interface snaps page on the App Permissions page
    Open Camera Snaps Page

Toggle Permissions On
    [Documentation]    Toggle camera permissions on for the Cheese and Firefox Snaps
    Move Pointer To ${Y}/generic/toggle-off.png
    EzClick
    Authenticate With Polkit
    Move Pointer To ${Y}/generic/toggle-off.png
    EzClick

Validate Cheese Has Camera Permissions
    [Documentation]    Validates that Cheese can access the camera
    Open Cheese
    Match    ${Y}/generic/cheese-camera-enabled.png
    Move Pointer To ${Y}/generic/cheese-cross-button.png
    EzClick

Toggle Permissions Off
    [Documentation]    Toggle camera permissions off for the Cheese and Firefox Snaps
    Click Security Center Icon
    Move Pointer To ${Y}/generic/toggle-on.png
    EzClick
    Move Pointer To ${Y}/generic/toggle-on.png
    EzClick

Validate Cheese Has No Camera Permissions
    [Documentation]    Validates that Cheese cannot access the camera
    Open Cheese
    Match    ${Y}/generic/cheese-camera-disabled.png
    Move Pointer To ${Y}/generic/cheese-cross-button.png
    EzClick
    Move Pointer To ${Y}/generic/warning-close-button.png
    EzClick

Reset All Permissions
    [Documentation]    Reset all camera permissions
    Click Security Center Icon
    Move Pointer To ${Y}/generic/reset-all-permissions.png
    EzClick

Assert Prompting Is Now Enabled
    [Documentation]    Asserts prompts are now reset
    Open Cheese
    Match Text    "Allow cheese to access your camera?"
