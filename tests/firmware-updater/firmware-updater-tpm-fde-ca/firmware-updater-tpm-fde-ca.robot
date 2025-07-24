*** Settings ***
Resource        ${Z}/../firmware-updater.resource

Test Tags       robot:exit-on-failure


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    Log In

Refresh Firmware Metadata
    Refresh Firmware Metadata

Open Firmware Updater
    Open Firmware Updater

Update UEFI CA
    Update UEFI CA

Handle Recovery Key Prompt
    Handle Recovery Key Prompt

Confirm Update
    Confirm Update

Handle PolKit Prompt
    Handle PolKit Prompt

Handle Reboot Prompt
    Handle Reboot Prompt

Enter Recovery Key On Reboot
    Enter Recovery Key On Reboot

Wait For Reboot To Finish
    Log In

Check For Successful UEFI CA Update
    Check For Successful UEFI CA Update
