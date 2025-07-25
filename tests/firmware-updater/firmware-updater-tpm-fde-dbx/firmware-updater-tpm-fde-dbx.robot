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

Update UEFI dbx
    Update UEFI dbx

Confirm Update
    Confirm Update

Handle PolKit Prompt
    Handle PolKit Prompt

Handle Reboot Prompt
    Handle Reboot Prompt

Wait For Reboot To Finish
    Log In
