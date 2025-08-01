*** Settings ***
Documentation       Update UEFI CA

Resource            ${Z}/../firmware-updater.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log in to desktop session
    Log In

Refresh Firmware Metadata
    [Documentation]    Fetch the firmware catalog    from LVFS
    Refresh Firmware Metadata

Open Firmware Updater
    [Documentation]    Open the firmware updater application
    Open Firmware Updater

Update UEFI CA
    [Documentation]    Update the Microsoft certificate
    Update UEFI CA

Confirm Update
    [Documentation]    Confirm the firmware update
    Confirm Update

Handle Reboot Prompt
    [Documentation]    Confirm to reboot the system
    Handle Reboot Prompt

Wait For Reboot To Finish
    [Documentation]    Log in after rebooting the machine
    Log In

Check For Successful UEFI CA Update
    [Documentation]    Confirm that the Microsoft certificate has been updated successfully
    Check For Successful UEFI CA Update
