*** Settings ***
Documentation       Update UEFI CA with Bitlocker

Resource            ${Z}/../firmware-updater.resource

Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log in to desktop environment
    Log In

Refresh Firmware Metadata
    [Documentation]    Fetch the firmware catalog from LVFS
    Refresh Firmware Metadata

Setup Mock Bitlocker Partition
    [Documentation]    Setup a mock Bitlocker partition by loopmounting a test image from cryptsetup
    Setup Mock Bitlocker Partition

Open Firmware Updater
    [Documentation]    Open the firmware updater application
    Open Firmware Updater

Update UEFI CA
    [Documentation]    Update the Microsoft certificate
    Update UEFI CA

Handle Recovery Key Checkbox
    [Documentation]    Enter the recovery key in the dialog
    Handle Recovery Key Checkbox

Confirm Update
    [Documentation]    Confirm the firmware update
    Confirm Update

Handle PolKit Prompt
    [Documentation]    Enter the user password in the polkit prompt to allow checking the recovery key
    Handle PolKit Prompt

Handle Reboot Prompt
    [Documentation]    Confirm to reboot the system
    Handle Reboot Prompt

Wait For Reboot To Finish
    [Documentation]    Log back into the desktop environment after the reboot
    Log In

Check For Successful UEFI CA Update
    [Documentation]    Confirm that the Microsoft certificate has been updated successfully
    Check For Successful UEFI CA Update
