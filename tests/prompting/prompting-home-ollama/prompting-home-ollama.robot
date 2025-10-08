*** Settings ***
Documentation       Spawns prompts for ollama snap

Resource            ${Z}/../prompting.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log in to desktop session
    Log In

Install ollama
    [Documentation]    Install the ollama snap
    Install Snap Package    ollama
    Install Debian Package    curl
    Open Terminal
    Run Command In Terminal    ollama pull gemma3:270m
    Run Command In Terminal    ollama pull gemma3:4b

Enable Prompting
    [Documentation]    Enable prompting
    Enable Prompting
    BuiltIn.Sleep    1

Ensure No ollama Prompts
    [Documentation]    Ensure ollama won't trigger prompts
    Run Command In Terminal    echo "En un lugar de la Mancha, de cuyo nombre no quiero acordarme" > ~/data.txt
    Run Command In Terminal    ollama run gemma3:270m "What language is this: $(cat ~/data.txt)"
    Match Text    Spanish    30

Deny ollama Prompts
    [Documentation]    Trigger prompt when analyzing a local file and deny it
    Run Command In Terminal    curl -s -L "https://upload.wikimedia.org/wikipedia/commons/thumb/9/90/Twemoji_1f600.svg/800px-Twemoji_1f600.svg.png" -o image.png
    Run Simple Command    ollama run gemma3:4b "What is this image: ./image.png"
    Focus Prompt
    Reply To Simple Prompt    ollama wants to get read access to image.png    Deny once
    BuiltIn.Sleep     1
    Match Text    Error: open ./image.png: permission denied

Allow ollama Prompts
    [Documentation]    Trigger prompt when analyzing a local file and allow it
    Run Simple Command    ollama run gemma3:4b "What is this image: ./image.png"
    Focus Prompt
    Reply To Simple Prompt    ollama wants to get read access to image.png    Allow always
    BuiltIn.Sleep     1
    Match Text    emoji    180
