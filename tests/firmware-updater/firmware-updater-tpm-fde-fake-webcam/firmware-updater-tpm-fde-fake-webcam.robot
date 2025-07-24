*** Settings ***
Documentation         Test the firmware updater snap
Resource        ${Z}/../firmware-updater.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]         Log in to desktop environment
    Log In

Setup Fake Webcam
    Setup Fake Webcam

Setup Mock TPM FDE Update
    Setup Mock TPM FDE Update

Open Firmware Updater
    [Documentation]         Open the firmware-updater snap
    Open Firmware Updater

Update Fake Webcam
    Update Fake webcam

Handle Recovery Key Prompt
    Handle Recovery Key Prompt

Confirm Update
    Confirm Update

Handle PolKit Prompt
    Handle PolKit Prompt

Check For Successful Fake Webcam Update
    Check For Successful Fake Webcam Update
