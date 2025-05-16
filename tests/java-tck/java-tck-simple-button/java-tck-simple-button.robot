*** Settings ***
Resource        ${Z}/../java-tck.resource

Test Tags       robot:exit-on-failure


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    Log In

Install Git
    Install Debian Package    git

Clone Simple Repo
    ${ampersand}=    Create List    Shift_L    7
    Open Terminal
    PlatformHid.Type String    clear
    PlatformHid.Keys Combo    ${space}
    PlatformHid.Keys Combo    ${ampersand}
    PlatformHid.Keys Combo    ${ampersand}
    PlatformHid.Keys Combo    ${space}
    PlatformHid.Type String    git clone https
    ${colon}=    Create List    Shift_L    ;
    PlatformHid.Keys Combo    ${colon}
    PlatformHid.Type String    //github.com/pushkarnk/simple-java-test
    PlatformHid.Keys Combo    ${space}
    PlatformHid.Keys Combo    ${ampersand}
    PlatformHid.Keys Combo    ${ampersand}
    PlatformHid.Keys Combo    ${space}
    PlatformHid.Type String    echo FINISHED HIT
    BuiltIn.Sleep    2
    ${ret}=    Create List    Return
    PlatformHid.Keys Combo    ${ret}
    BuiltIn.Sleep    2
    PlatformVideoInput.Match Text    FINISHED HIT    30
    Close Terminal

Install OpenJdk
    Install Debian Package    openjdk-17-jdk

Run The Test
    Open Terminal
    ${ampersand}=    Create List    Shift_L    7
    PlatformHid.Type String    cd simple-java-test
    ${ret}=    Create List    Return
    PlatformHid.Keys Combo    ${ret}
    PlatformHid.Type String    clear
    PlatformHid.Keys Combo    ${space}
    PlatformHid.Keys Combo    ${ampersand}
    PlatformHid.Keys Combo    ${ampersand}
    PlatformHid.Keys Combo    ${space}
    PlatformHid.Type String    javac SimpleAWTApp.java
    PlatformHid.Keys Combo    ${space}
    PlatformHid.Keys Combo    ${ampersand}
    PlatformHid.Keys Combo    ${ampersand}
    PlatformHid.Keys Combo    ${space}
    PlatformHid.Type String    echo FINISHED HIT
    PlatformHid.Keys Combo    ${ret}
    BuiltIn.Sleep    2
    ${ret}=    Create List    Return
    PlatformHid.Keys Combo    ${ret}
    BuiltIn.Sleep    2
    PlatformVideoInput.Match Text    FINISHED HIT    30
    PlatformHid.Type String    clear
    PlatformHid.Keys Combo    ${space}
    PlatformHid.Keys Combo    ${ampersand}
    PlatformHid.Keys Combo    ${ampersand}
    PlatformHid.Keys Combo    ${space}
    PlatformHid.Type String    java SimpleAWTApp
    PlatformHid.Keys Combo    ${ret}
    PlatformVideoInput.Match Text    Simple AWT Application    30
    Move Pointer To /home/andersson123/canonical/code/canonical/ubuntu-gui-testing/tests/java-tck/generic/button.png
    Click LEFT Button
    PlatformVideoInput.Match
    ...    /home/andersson123/canonical/code/canonical/ubuntu-gui-testing/tests/java-tck/generic/button-pressed.png
