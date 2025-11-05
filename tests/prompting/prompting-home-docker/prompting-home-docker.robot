*** Settings ***
Documentation       Spawns prompts for docker snap

Library             String
Resource            ${Z}/../prompting.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log in to desktop session
    Log In

Install docker
    [Documentation]    Install the docker snap
    Install Snap Package    docker
    Open Terminal
    Run Sudo Command In Terminal    sudo addgroup --system docker
    Run Command In Terminal    sudo sudo adduser $USER docker
    Run Simple Command    newgrp docker
    Run Command In Terminal    sudo snap disable docker
    Run Command In Terminal    sudo snap enable docker

Enable Prompting
    [Documentation]    Enable prompting
    Enable Prompting
    BuiltIn.Sleep    1

Ensure No docker Prompts
    [Documentation]    Ensure docker won't trigger prompts
    ${release}=    Get System Version
    BuiltIn.Sleep    1
    Run Command In Terminal    docker run -d --name mycontainer -v ~/Documents:/mnt/shared ubuntu:${release} tail -f /dev/null
    Run Command In Terminal    chmod o+w ~/Documents
    Run Command In Terminal    echo "hello world" > ~/Documents/TESTFILE
    Run Simple Command    docker exec -it mycontainer /bin/bash
    Run Command In Terminal    cd /mnt/shared
    Run Command In Terminal    cat TESTFILE
    Run Command In Terminal    echo "hello world 2" > TESTFILE2
    Run Command In Terminal    cat TESTFILE2
    Ensure No Prompts
