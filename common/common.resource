*** Settings ***
Documentation       Shared resources for installer testing

Resource            kvm.resource


*** Variables ***
${X}    ${CURDIR}


*** Keywords ***
EzClick
    [Documentation]         Slow click and move pointer to top left of screen
    BuiltIn.Sleep    0.5
    Click LEFT Button
    BuiltIn.Sleep    0.5
    Move Pointer To (100, 100)

Open Terminal
    [Documentation]         Open terminal with ctrl+alt+T
    ${combo}    Create List    Alt_L    Control_L    t
    PlatformHid.Keys Combo    ${combo}
    PlatformVideoInput.Match Text    ubuntu@ubuntu    15

Run Sudo Command In Terminal
    [Documentation]         Run a command prepended with sudo in the terminal
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
    [Documentation]         Run a command in the terminal
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
    [Documentation]         Close terminal with ctrl+shift+w
    ${combo}    Create List    Control_L    Shift_L    w
    FOR    ${_}    IN RANGE    30
        ${terminal_finns}    Run Keyword And Return Status    PlatformVideoInput.Match Text    ubuntu@ubuntu    15
        IF    not ${terminal_finns}      BREAK
        PlatformHid.Keys Combo    ${combo}
        BuiltIn.Sleep    1
    END

Install Debian Package
    [Documentation]         Install a debian package
    [Arguments]    ${package}
    Open Terminal
    Run Sudo Command In Terminal    sudo apt-get update -y
    Run Command In Terminal    sudo apt-get upgrade -y
    Run Command In Terminal    sudo apt-get install -y ${package}
    Close Terminal

Install Snap Package
    [Documentation]         Install a snap package
    [Arguments]    ${package}
    Open Terminal
    Run Sudo Command In Terminal    sudo snap install ${package}
    Close Terminal

Start Application
    [Documentation]         Start an application from the command prompt
    [Arguments]    ${application}
    ${combo}    Create List    Alt_L    F2
    PlatformHid.Keys Combo    ${combo}
    PlatformVideoInput.Match Text    Run a Command    15
    PlatformHid.Type String    ${application}
    ${ret}    Create List    Return
    PlatformHid.Keys Combo    ${ret}

Log In
    [Documentation]         Log in to desktop session
    PlatformVideoInput.Match Text    Not listed    120
    ${ret}    Create List    Return
    PlatformHid.Keys Combo    ${ret}
    BuiltIn.Sleep    2
    PlatformHid.Type String    ubuntu
    BuiltIn.Sleep    2
    PlatformHid.Keys Combo    ${ret}
    BuiltIn.Sleep    2
    PlatformVideoInput.Match    ${X}/circle-of-friends.png    60

Match Text Exactly
    # https://github.com/canonical/ubuntu-gui-testing/issues/37
    [Documentation]    Matches the specified text exactly: no subphrases will be matched
    [Arguments]    ${text}
    ${matches}    ${image}    PlatformVideoInput.Match Text    ${text}
    FOR    ${match}    IN    @{matches}
        IF    '${match}[text]'.encode('ascii', 'ignore').decode('ascii').strip() == '${text}'
            RETURN    ${match}    ${image}
        END
    END
    Fail    Could not match '${text}' exactly. Other results were: ${matches}, ${image}

Move Pointer To Text Exactly
    # https://github.com/canonical/ubuntu-gui-testing/issues/37
    [Documentation]    Move the pointer to the location identified by the text, using Match Text Exactly
    [Arguments]    ${text}
    ${match}    ${_}    Match Text Exactly    ${text}
    ${region}    Set Variable    ${match}[region]
    PlatformHid.Move Pointer To Absolute    ${region.center.x}    ${region.center.y}
