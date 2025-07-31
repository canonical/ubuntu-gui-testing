*** Settings ***
Documentation       Change the passphrase and test rebooting using the replacement

Resource            ${Z}/../desktop-security-center.resource

Test Tags           exit-on-failure


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]    Log into ubuntu user
    Log In

Open Security Center
    [Documentation]    Open the Security Center from the cli
    Open Security Center

Open Disk Encryption Tab
    [Documentation]    Open the disk encryption tab in the Security Center
    Open Disk Encryption Tab

Change Passphrase
    [Documentation]    Change the passphrase from the Security Center
    Change Passphrase    myoldpassphrase    mynewpassphrase

Reboot
    [Documentation]    Reboot the system
    Start Application    reboot

Boot With Passphrase
    [Documentation]    Boot the system using a passphrase to unlock the TPM
    Boot With Passphrase    mynewpassphrase

Log In After Reboot
    [Documentation]    Log into ubuntu user
    Log In
