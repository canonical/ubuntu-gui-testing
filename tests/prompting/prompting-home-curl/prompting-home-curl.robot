*** Settings ***
Documentation       Spawns prompts for curl snap

Resource            ${Z}/../prompting.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log in to desktop session
    Log In

Install Curl
    [Documentation]    Install the curl snap
    Install Snap Package    curl
    Open Terminal
    Run Command In Terminal    curl.snap-acked

Prepare Curl File
    [Documentation]    Serve a file with a web server to be able to download with curl
    Run Command In Terminal    mkdir -p /tmp/hostmedir
    Run Command In Terminal    cd /tmp/hostmedir
    Run Command In Terminal    echo "hello world" > TESTFILE
    Run Simple Command    python3 -m http.server 9999 > /dev/null 2>&1 &
    Run Command In Terminal    cd -

Enable Prompting
    [Documentation]    Enable prompting
    Enable Prompting
    BuiltIn.Sleep    1

Deny Curl Prompts
    [Documentation]    Trigger prompt when downloading a file and deny it
    Run Simple Command    curl -s -O http://localhost:9999/TESTFILE
    Focus Prompt
    Reply To Simple Prompt    curl wants to get write access to TESTFILE    Deny once
    BuiltIn.Sleep     1
    Run Command In Terminal    ls
    Ensure TESTFILE Does Not Match

Allow Curl Prompts
    [Documentation]    Trigger prompt when downloading a file and allow it
    Run Simple Command    curl -s -O http://localhost:9999/TESTFILE
    Focus Prompt
    Reply To Simple Prompt    curl wants to get write access to TESTFILE    Allow always
    BuiltIn.Sleep     1
    Run Simple Command    cat TESTFILE
    Match Text    hello world
