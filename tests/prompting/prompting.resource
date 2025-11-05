*** Settings ***
Documentation       Shared resources for application testing

Resource            kvm.resource
Resource            ${Y}/common/common.resource


*** Variables ***
${Y}    ${CURDIR}


*** Keywords ***
Enable Prompting
    [Documentation]    Enable snap prompting in the security center
    Start Application    desktop-security-center
    BuiltIn.Sleep    5
    Move Pointer To ${Y}/generic/prompting-toggle-disabled.png
    EzClick
    Handle PolKit Prompt
    Match    ${Y}/generic/prompting-toggle-enabled.png    60
    Close Current Window

Get System Version
    [Documentation]    Get ubuntu version number
    Open Terminal
    Run Command In Terminal    grep VERSION_ID /etc/os-release | cut -d'"' -f2
    ${text}=    Read Text
    ${matches}=    Get Regexp Matches    ${text}    [0-9]{2}\\.[0-9]{2}
    ${release}=    Get From List    ${matches}    0
    Close Current Window
    RETURN    ${release}

Handle PolKit Prompt
    [Documentation]    Handle a PolKit prompt
    Match Text    Authentication Required
    Type String    ubuntu
    Keys Combo    Return

Open Firefox
    [Documentation]    Open Firefox
    Start Application    firefox
    Match Text    Firefox    60

Open Thunderbird
    [Documentation]    Open Thunderbird and reply to startup prompts
    [Arguments]    ${reply}
    Start Application    thunderbird
    Match Text    Downloads/thunderbird.tmp
    Reply To Simple Prompt    thunderbird wants to get write access    ${reply}
    Match Text    Account Setup

Open Gimp
    [Documentation]    Open gimp
    Start Application    gimp
    Match Text    Welcome to GIMP    60
    Click LEFT Button On Welcome to GIMP
    BuiltIn.Sleep    1
    Close Current Window    # Close the welcome window
    Match Text    GNU Image Manipulation Program

Open Firefox Tab
    [Documentation]    Open a new tab in Firefox, navigate to the given URL and match the title of the website
    [Arguments]    ${url}    ${title}
    Keys Combo    Ctrl    t
    Type String    ${url}
    Keys Combo    Return
    Match Text    ${title}    60

Save File
    [Documentation]    Common 'Save File' action
    Keys Combo    Ctrl    s
    Match Text    Save
    BuiltIn.Sleep    1
    Keys Combo    Return
    BuiltIn.Sleep    1

Verify Firefox Download
    [Documentation]    Verify successful download of a file in Firefox
    Click LEFT Button On ${Y}/generic/home/downloads.png
    Match Text    Completed 60

Focus Prompt
    [Documentation]    Focus the prompting-client UI
    Move Pointer To ${Y}/generic/shield-icon.png
    EzClick

Ensure No Prompts
    [Documentation]    Ensure there are no active prompts
    Ensure ${Y}/generic/shield-icon.png Does Not Match

Trigger First yq Prompt
    [Documentation]    Open a terminal, run yq on a test file and wait for a prompt
    Open Terminal
    Run Simple Command    echo 'a:1'>a.yaml
    Run Simple Command    yq a.yaml
    Match Text    yq wants to get read access to a.yaml

Trigger Second yq Prompt
    [Documentation]    Open a terminal, run yq on a second test file and wait for another prompt
    Open Terminal
    Run Simple Command    echo 'b:2'>b.yaml
    Run Simple Command    yq b.yaml
    Match Text    yq wants to get read access to b.yaml

Deny Second yq Prompt
    [Documentation]    Deny prompt for second yq command, verify that read access is denied
    Reply To Simple Prompt    yq wants to get read access to b.yaml    Deny once
    Match Text    Error: open b.yaml: permission denied
    Type String    exit
    Keys Combo    Return

Allow First yq Prompt
    [Documentation]    Allow the prompt for the first yq command, verify that the command succeeds
    Focus Prompt
    Reply To Simple Prompt    yq wants to get read access to a.yaml    Allow until logout
    Match Text    a: 1

Answer Both yq Prompts
    [Documentation]    Answer the prompt for the second yq command so that it also resolves the first prompt, verify that both commands succeed
    Click LEFT Button On More options
    Click LEFT Button On Everything in the
    Click LEFT Button On Allow
    Match Text    b: 2
    Type String    exit
    Keys Combo    Return
    Match Text    a: 1
    Ensure No Prompts

Reply To Simple Prompt
    [Documentation]    Replies to a prompt given the prompt text and a reply
    [Arguments]    ${prompt}    ${reply}
    Match Text    ${prompt}    30
    Click LEFT Button On ${reply}

Run Simple Command
    [Documentation]    Run command in terminal without verifying the exit status
    [Arguments]    ${cmd}
    Type String    ${cmd}
    Keys Combo    Return

Cheese No Device
    [Documentation]    Find "cheese" application open with no device message
    Match    ${Y}/generic/camera/cheese_no_device.png    30

Cheese With Video
    [Documentation]    Find "cheese" application open with fake test video
    Match    ${Y}/generic/camera/cheese_with_video.png    30

Open Image With Gimp From Nautilus
    [Documentation]    Open and image file with GIMP from the file manager and handle the prompt
    [Arguments]    ${reply}
    Click RIGHT Button On TESTIMAGE
    BuiltIn.Sleep    1
    Click LEFT Button On 'Open with...'
    BuiltIn.Sleep    1
    Click LEFT Button On GNU Image Manipulation
    BuiltIn.Sleep    1
    Keys Combo    Return
    IF    $reply == 'Deny once'
        Reply To Simple Prompt    gimp wants to get read access    ${reply}
        Reply To Simple Prompt    gimp wants to get read access    ${reply}
        Reply To Simple Prompt    gimp wants to get read access    ${reply}
        Match Text    GIMP Message
        Match Text    Permission denied
        Keys Combo    Return
    ELSE
        Reply To Simple Prompt    gimp wants to get read access    ${reply}
    END
    Click LEFT Button On Welcome to GIMP
    BuiltIn.Sleep    3
    Close Current Window    # close GIMP welcome screen
    BuiltIn.Sleep    3

Save Gimp Image In Pictures Directory
    [Documentation]    Save the opened test file in the Pictures directory and answer all prompts
    [Arguments]    ${reply}
    Keys Combo    Control_L    s
    Reply To Simple Prompt    gimp wants to get read access to your Home folder    ${reply}
    IF    $reply == 'Deny once'
        Reply To Simple Prompt    gimp wants to get read access to your Home folder    ${reply}
        Match Text    Permission denied
        Keys Combo    Return
    END
    BuiltIn.Sleep    1
    Click LEFT Button On Pictures
    BuiltIn.Sleep    1
    # Keys Combo    Return
    Reply To Simple Prompt    gimp wants to get read access to the Pictures folder    ${reply}
    IF    $reply == 'Deny once'
        Reply To Simple Prompt    gimp wants to get read access to the Pictures folder    ${reply}
        Match Text    Permission denied
        Keys Combo    Return
    END
    BuiltIn.Sleep    1
    Keys Combo    Return
    Reply To Simple Prompt    gimp wants to get write access to TESTIMAGE.xcf    ${reply}
    IF    $reply == 'Deny once'
        Reply To Simple Prompt    gimp wants to get read access to the Pictures folder    ${reply}
        Match Text    Permission denied
        Keys Combo    Return
        Match Text    GIMP Message
        Match Text    Error creating '/home/ubuntu/Pictures/TESTIMAGE.xcf'
        Click LEFT Button On GIMP Message
        BuiltIn.Sleep    1
        Keys Combo    Return
        BuiltIn.Sleep    1
        Close Current Window
    END
    BuiltIn.Sleep    3
