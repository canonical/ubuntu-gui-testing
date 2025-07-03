*** Settings ***
Documentation       Shared resources for installer testing

Resource            kvm.resource
Library             Collections


*** Variables ***
${X}    ${CURDIR}


*** Keywords ***
EzClick
    BuiltIn.Sleep    0.5
    Click LEFT Button
    BuiltIn.Sleep    0.5
    Move Pointer To (100, 100)

Move Pointer To Text
    [Arguments]    ${text}
    ${text_matches}    ${_}=    PlatformVideoInput.Match Text    ${text}
    ${text_match}=     Collections.Get From List    ${text_matches}    0
    ${region}=     PlatformVideoInput.Get Region From Text Match    ${text_match}
    Evaluate
    ...    sys.path.append('/home/adombeck/projects/yarf/yarf/rf_libraries/libraries')
    ...    from video_input_base import Region
    ...    isinstance(${region}, Region)
    ${position}=   Get Center Of  ${region}
    Move Pointer To ${position}

Click On Text
    [Arguments]    ${text}
    Move Pointer To Text    ${text}
    EzClick


Open Terminal
    ${combo}    Create List    Alt_L    Control_L    t
    PlatformHid.Keys Combo    ${combo}
    PlatformVideoInput.Match Text    ubuntu@ubuntu    15

Run Sudo Command In Terminal
    [Arguments]    ${command}
    ${ampersand}    Create List    Shift_L    7
    ${space}    Create List    space
    PlatformHid.Type String    clear
    PlatformHid.Keys Combo    ${space}
    PlatformHid.Keys Combo    ${ampersand}
    PlatformHid.Keys Combo    ${ampersand}
    PlatformHid.Keys Combo    ${space}
    PlatformHid.Type String    ${command}
    PlatformHid.Keys Combo    ${space}
    PlatformHid.Keys Combo    ${ampersand}
    PlatformHid.Keys Combo    ${ampersand}
    PlatformHid.Keys Combo    ${space}
    PlatformHid.Type String    echo FINISHED-HIT
    BuiltIn.Sleep    2    # hacky
    ${enter}    Create List    Return
    PlatformHid.Keys Combo    ${enter}
    BuiltIn.Sleep    4    # hacky
    PlatformHid.Type String    ubuntu
    BuiltIn.Sleep    2    # hacky
    PlatformHid.Keys Combo    ${enter}
    BuiltIn.Sleep    1    # hacky
    PlatformVideoInput.Match Text    FINISHED-HIT    120

Run Command In Terminal
    [Arguments]    ${command}
    ${ampersand}    Create List    Shift_L    7
    ${space}    Create List    space
    PlatformHid.Type String    clear
    PlatformHid.Keys Combo    ${space}
    PlatformHid.Keys Combo    ${ampersand}
    PlatformHid.Keys Combo    ${ampersand}
    PlatformHid.Keys Combo    ${space}
    PlatformHid.Type String    ${command}
    PlatformHid.Keys Combo    ${space}
    PlatformHid.Keys Combo    ${ampersand}
    PlatformHid.Keys Combo    ${ampersand}
    PlatformHid.Keys Combo    ${space}
    PlatformHid.Type String    echo FINISHED-HIT
    BuiltIn.Sleep    2    # hacky
    ${enter}    Create List    Return
    PlatformHid.Keys Combo    ${enter}
    BuiltIn.Sleep    2    # hacky
    PlatformVideoInput.Match Text    FINISHED-HIT    120

Close Terminal
    ${combo}    Create List    Control_L    Shift_L    w
    FOR    ${index}    IN RANGE    30
        ${terminal_finns}    Run Keyword And Return Status    PlatformVideoInput.Match Text    ubuntu@ubuntu    15
        IF    ${terminal_finns} == ${True}
            PlatformHid.Keys Combo    ${combo}
            BuiltIn.Sleep    1
        ELSE
            BREAK
        END
    END

Install Debian Package
    [Arguments]    ${package}
    Open Terminal
    Run Sudo Command In Terminal    sudo apt-get update -y
    Run Command In Terminal    sudo apt-get upgrade -y
    Run Command In Terminal    sudo apt-get install -y ${package}
    Close Terminal

Install Snap Package
    [Arguments]    ${package}
    Open Terminal
    Run Sudo Command In Terminal    sudo snap install ${package}
    Close Terminal

Run Command
    [Arguments]    ${command}
    PlatformHid.Keys Combo    Alt_L    F2
    PlatformVideoInput.Match Text    Run a Command    15
    PlatformHid.Type String    ${command}
    PlatformHid.Keys Combo   Return

Start Application
    [Arguments]    ${application}
    Run Command    ${application}

Log In
    PlatformVideoInput.Match Text    Not listed    120
    ${ret}    Create List    Return
    PlatformHid.Keys Combo    ${ret}
    BuiltIn.Sleep    2
    PlatformHid.Type String    ubuntu
    BuiltIn.Sleep    2
    PlatformHid.Keys Combo    ${ret}
    BuiltIn.Sleep    2
    PlatformVideoInput.Match    ${X}/circle-of-friends.png    60

Lock Screen
    PlatformHid.Keys Combo    Super_L    L
    # The screen blanks out when the screen is locked. Press backspace to
    # make the screen visible, so that we can match something on it.
    Sleep    2
    PlatformHid.Keys Combo    BackSpace
    PlatformVideoInput.Match    ${CURDIR}/show-password.png

Unlock Screen
    [Arguments]    ${password}
    Click LEFT Button On ${CURDIR}/show-password.png
    PlatformHid.Keys Combo    Shift_L
    PlatformHid.Keys Combo    Shift_L
    PlatformHid.Type String    ${password}
    Sleep    1
    PlatformHid.Keys Combo    Return
    PlatformVideoInput.Match    ${CURDIR}/circle-of-friends.png    60
