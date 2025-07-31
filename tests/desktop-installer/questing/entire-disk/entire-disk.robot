*** Settings ***
Documentation         Normal, entire disk install
Resource        kvm.resource
Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word
Resource    ${CURDIR}/../../installer.resource


*** Variables ***
${T}    ${CURDIR}


*** Test Cases ***
Grub Menu
    [Documentation]         Go through grub menu, if present
    Grub Menu

Ensure Not Unfocused After Boot
    [Documentation]         Workaround LP: #2112383
    Ensure Not Unfocused After Boot

Language Slide
    [Documentation]         Go through language slide
    Select Language

A11y Slide
    [Documentation]         Go through a11y slide
    A11y Slide

Keyboard Layout
    [Documentation]         Use default keyboard layout
    Keyboard Layout

Internet Connection
    [Documentation]         Go through internet connection slide
    Internet Connection

Skip Installer Update
    [Documentation]         Skip installer update, if present
    Skip Installer Update

Try Or Install
    [Documentation]         Go through try or install slide
    Try Or Install

Interactive vs Automated
    [Documentation]         Go through interactive vs automated slide
    Interactive vs Automated

Default vs Extended
    [Documentation]         Go through default vs extended slide
    Default vs Extended

Proprietary Software
    [Documentation]         Go through proprietary software slide
    Proprietary Software

Select Erase Disk and Reinstall
    [Documentation]         Select erase disk and reinstall
    Match    ${T}/../../../../generic/disk-setup.png    180
    ${erase_unselected}=               Run Keyword And Return Status
    ...                     Match    ${T}/../../../../generic/erase-and-reinstall-unselected.png    120
    IF    ${erase_unselected}
        Move Pointer To ${T}/../../../../generic/erase-and-reinstall-unselected.png
        EzClick
    END
    Move Pointer To ${T}/../../../../generic/next.png
    EzClick

Choose Where to Install Ubuntu
    [Documentation]         Go through slide showing various disks, if present
    Choose Where to Install Ubuntu

Encryption And File System No Encryption
    [Documentation]         Select no encryption
    Encryption And File System No Encryption

Create Account
    [Documentation]         Create a user on the installed system
    Create Account

Select Timezone
    [Documentation]         Choose a timezone
    Select Timezone

Review Installation
    [Documentation]         Review installation slide
    Review Installation

Wait For Install To Finish
    [Documentation]         Wait for the installation to finish
    Wait For Install To Finish

Wait For Reboot To Finish
    [Documentation]         Wait for the reboot post-install
    Wait For Reboot To Finish

Wait For GIS Popup
    [Documentation]         Wait for the gnome-initial-setup popup
    Wait For GIS Popup

# Install OpenSSHServer
#     [Documentation]         Install openssh-server to collect logs
#     Install OpenSSHServer
