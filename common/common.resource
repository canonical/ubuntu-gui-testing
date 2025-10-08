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
    Keys Combo    ${combo}
    Match Text    ubuntu@ubuntu    15

Run Sudo Command In Terminal
    [Documentation]         Run a command prepended with sudo in the terminal
    [Arguments]    ${command}
    ${ampersand}    Create List    Shift_L    7
    ${space}    Create List    space
    Type String    clear
    Keys Combo    ${space}
    Keys Combo    ${ampersand}
    Keys Combo    ${ampersand}
    Keys Combo    ${space}
    Type String    ${command}
    Keys Combo    ${space}
    Keys Combo    ${ampersand}
    Keys Combo    ${ampersand}
    Keys Combo    ${space}
    Type String    echo FINISHED-HIT
    BuiltIn.Sleep    2    # hacky
    ${enter}    Create List    Return
    Keys Combo    ${enter}
    BuiltIn.Sleep    4    # hacky
    Type String    ubuntu
    BuiltIn.Sleep    2    # hacky
    Keys Combo    ${enter}
    BuiltIn.Sleep    1    # hacky
    Match Text    FINISHED-HIT    120

Run Command In Terminal
    [Documentation]         Run a command in the terminal
    [Arguments]    ${command}
    ${ampersand}    Create List    Shift_L    7
    ${space}    Create List    space
    Type String    clear
    Keys Combo    ${space}
    Keys Combo    ${ampersand}
    Keys Combo    ${ampersand}
    Keys Combo    ${space}
    Type String    ${command}
    Keys Combo    ${space}
    Keys Combo    ${ampersand}
    Keys Combo    ${ampersand}
    Keys Combo    ${space}
    Type String    echo FINISHED-HIT
    BuiltIn.Sleep    2    # hacky
    ${enter}    Create List    Return
    Keys Combo    ${enter}
    BuiltIn.Sleep    2    # hacky
    Match Text    FINISHED-HIT    120

Close Terminal
    [Documentation]         Close terminal with ctrl+shift+w
    ${combo}    Create List    Control_L    Shift_L    w
    FOR    ${_}    IN RANGE    30
        ${terminal_finns}    Run Keyword And Return Status    Match Text    ubuntu@ubuntu    15
        IF    not ${terminal_finns}      BREAK
        Keys Combo    ${combo}
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
    Keys Combo    ${combo}
    Match Text    Run a Command    15
    Type String    ${application}
    ${ret}    Create List    Return
    Keys Combo    ${ret}

Log In
    [Documentation]         Log in to desktop session
    Match Text    Not listed    120
    ${ret}    Create List    Return
    Keys Combo    ${ret}
    BuiltIn.Sleep    2
    Type String    ubuntu
    BuiltIn.Sleep    2
    Keys Combo    ${ret}
    BuiltIn.Sleep    2
    Match    ${X}/circle-of-friends.png    60

Log Out
    [Documentation]    Log out of the desktop session
    Start Application    gnome-session-quit --logout
    Match Text    Log Out
    Keys Combo    Tab
    Keys Combo    Return

Check File Exists
    [Documentation]    Asserts that the given file exists and optionally deletes it
    [Arguments]    ${path}    ${remove}=False
    Open Terminal
    Run Command In Terminal    [ -e ${path} ] && echo FILE EXISTS
    Match Text    FILE EXISTS    1
    IF    ${remove}    Run Command In Terminal    rm -f ${path}
    Close Terminal

Close Current Window
    [Documentation]    Close the current window
    Keys Combo    Alt    F4
