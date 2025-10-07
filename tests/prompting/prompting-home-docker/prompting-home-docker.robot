*** Settings ***
Documentation       Spawns prompts for docker snap

Resource            ${Z}/../prompting.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}
${SYSTEM}    ubuntu:24.04


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
    Run Command In Terminal    docker run -d --name mycontainer -v ~/Documents:/mnt/shared ${SYSTEM} tail -f /dev/null
    Run Command In Terminal    chmod o+w ~/Documents
    Run Command In Terminal    echo "hello world" > ~/Documents/file.txt
    Run Simple Command    docker exec -it mycontainer /bin/bash
    Run Command In Terminal    cd /mnt/shared
    Run Command In Terminal    cat file.txt
    Run Command In Terminal    echo "hello world 2" > file2.txt
    Run Command In Terminal    cat file2.txt
    Ensure No Prompts
