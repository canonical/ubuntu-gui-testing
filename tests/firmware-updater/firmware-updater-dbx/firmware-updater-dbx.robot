*** Settings ***
Documentation       Update UEFI dbx

Resource            ${Z}/../firmware-updater.resource

Test Tags           exit-on-failure


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

Update UEFI dbx
    [Documentation]    Update the dbx database
    Update UEFI dbx

Confirm Update
    [Documentation]    Confirm the firmware update
    Confirm Update

Handle Reboot Prompt
    [Documentation]    Confirm to reboot the system
    Handle Reboot Prompt

Wait For Reboot To Finish
    [Documentation]    Log in after rebooting the machine
    Log In
