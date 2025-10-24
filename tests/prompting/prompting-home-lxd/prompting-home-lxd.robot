*** Settings ***
Documentation       Spawns prompts for lxd snap

Library             String
Resource            ${Z}/../prompting.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log in to desktop session
    Log In

Install lxd
    [Documentation]    Install the lxd snap
    Install Snap Package    lxd
    Open Terminal
    Run Sudo Command In Terminal    sudo usermod -aG lxd "$USER"
    Run Simple Command    newgrp lxd
    Run Command In Terminal    lxd init --minimal

Enable Prompting
    [Documentation]    Enable prompting
    Enable Prompting
    BuiltIn.Sleep    1

Ensure No lxd Prompts
    [Documentation]    Ensure lxd won't trigger prompts
    ${release}=    Get System Version
    BuiltIn.Sleep    1
    Run Command In Terminal    lxc launch ubuntu:${release} mycontainer
    Run Command In Terminal    chmod o+w ~/Documents
    Run Command In Terminal    echo "hello world" > ~/Documents/TESTFILE
    Run Command In Terminal    lxc config device add mycontainer sharedhome disk source=~/Documents path=/mnt/shared
    Run Simple Command    lxc shell mycontainer
    Run Command In Terminal    cd /mnt/shared
    Run Command In Terminal    cat TESTFILE
    Run Command In Terminal    echo "hello world 2" > TESTFILE2
    Run Command In Terminal    cat TESTFILE2
    Ensure No Prompts
