*** Settings ***
Documentation       Update UEFI CA with TPM FDE

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

Update UEFI CA
    [Documentation]    Update the Microsoft certificate
    Update UEFI CA

Handle Recovery Key Prompt
    [Documentation]    Enter the recovery key in the dialog
    Handle Recovery Key Prompt

Confirm Update
    [Documentation]    Confirm the firmware update
    Confirm Update

Handle PolKit Prompt
    [Documentation]    Enter the user password in the polkit prompt to allow checking the recovery key
    Handle PolKit Prompt

Handle Reboot Prompt
    [Documentation]    Confirm to reboot the system
    Handle Reboot Prompt

Enter Recovery Key On Reboot
    [Documentation]    Enter the recovery key on reboot
    Enter Recovery Key On Reboot

Wait For Reboot To Finish
    [Documentation]    Log in after rebooting the machine
    Log In

Check For Successful UEFI CA Update
    [Documentation]    Confirm that the Microsoft certificate has been updated successfully
    Check For Successful UEFI CA Update
