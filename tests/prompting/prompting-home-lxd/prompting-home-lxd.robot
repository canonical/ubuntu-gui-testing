*** Settings ***
Documentation       Spawns prompts for lxd snap

Resource            ${Z}/../prompting.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}
${SYSTEM}    ubuntu:24.04


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
    Run Command In Terminal    lxc launch ${SYSTEM} mycontainer
    Run Command In Terminal    chmod o+w ~/Documents
    Run Command In Terminal    echo "hello world" > ~/Documents/file.txt
    Run Command In Terminal    lxc config device add mycontainer sharedhome disk source=~/Documents path=/mnt/shared
    Run Simple Command    lxc shell mycontainer
    Run Command In Terminal    cd /mnt/shared
    Run Command In Terminal    cat file.txt
    Run Command In Terminal    echo "hello world 2" > file2.txt
    Run Command In Terminal    cat file2.txt
    Ensure No Prompts
