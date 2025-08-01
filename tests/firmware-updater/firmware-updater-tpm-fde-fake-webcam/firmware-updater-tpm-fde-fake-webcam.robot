*** Settings ***
Documentation       Update fake webcam with TPM FDE

Resource            ${Z}/../firmware-updater.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log in to desktop environment
    Log In

Setup Fake Webcam
    [Documentation]    Setup the fake webcam device from fwupd-tests
    Setup Fake Webcam

Setup Mock TPM FDE Update
    [Documentation]    Write firmware-updater config file to make it pretend updating the fwupd test device affects TPM FDE so that it triggers the recovery key dialog
    Setup Mock TPM FDE Update

Open Firmware Updater
    [Documentation]    Open the firmware-updater snap
    Open Firmware Updater

Update Fake Webcam
    [Documentation]    Update the given device
    Update Fake webcam

Handle Recovery Key Prompt
    [Documentation]    Enter the recovery key in the dialog
    Handle Recovery Key Prompt

Confirm Update
    [Documentation]    Confirm the firmware update
    Confirm Update

Handle PolKit Prompt
    [Documentation]    Enter the user password in the polkit prompt to allow checking the recovery key
    Handle PolKit Prompt

Check For Successful Fake Webcam Update
    [Documentation]    Confirm that the Fake Webcam has been updated successfully
    Check For Successful Fake Webcam Update
