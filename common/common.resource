*** Settings ***
Documentation       Shared resources for installer testing

Resource            kvm.resource


*** Variables ***
${X}    ${CURDIR}


*** Keywords ***
EzClick
    BuiltIn.Sleep    0.5
    Click LEFT Button
    BuiltIn.Sleep    0.5
    Move Pointer To (100, 100)

Open Terminal
    ${combo}    Create List    Alt_L    Control_L    t
    PlatformHid.Keys Combo    ${combo}
    PlatformVideoInput.Match Text    ubuntu@ubuntu    15

Run Command In Terminal
    [Arguments]    ${command}
    PlatformHid.Type String    ${command} && echo FINISHED-HIT
    BuiltIn.Sleep    2    # hacky
    ${enter}    Create List    Return
    PlatformHid.Keys Combo    ${enter}
    BuiltIn.Sleep    2    # hacky
    PlatformHid.Type String    ubuntu
    PlatformVideoInput.Match Text    FINISHED-HIT    120

Close Terminal
    ${combo}    Create List    Control_L    Shift_L    w
    FOR    ${index}    IN RANGE    30
        ${terminal_finns}    Run Keyword And Return Status    PlatformVideoInput.Match Text    ubuntu@ubuntu    15
        IF    ${terminal_finns} == ${True}
            Keys Combo    ${combo}
            BuiltIn.Sleep    1
        ELSE
            BREAK
        END
    END

Install Debian Package
    [Arguments]    ${package}
    Open Terminal
    Run Command In Terminal    sudo apt-get install -y ${package}
    Close Terminal

Install Snap Package
    [Arguments]    ${package}
    Open Terminal
    Run Command In Terminal    sudo snap install -y ${package}
    Close Terminal

Start Application
    [Arguments]    ${application}
    ${combo}    Create List    Alt_L    F2
    PlatformHid.Keys Combo    ${combo}
    PlatformVideoInput.Match Text    Run a Command    15
    PlatformHid.Type String    ${application}
    ${ret}    Create List    Return
    PlatformHid.Keys Combo    ${ret}

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
