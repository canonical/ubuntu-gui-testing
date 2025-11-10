*** Settings ***
Documentation         Do a TPM FDE (pin code) installation
Resource        kvm.resource
Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word
Resource    ${CURDIR}/../../installer.resource


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
    Select Erase Disk and Reinstall

Choose Where to Install Ubuntu
    [Documentation]         Go through slide showing various disks, if present
    Choose Where to Install Ubuntu

Encryption And File System Tpm Encryption
    [Documentation]         Select tpm encryption from the encryption menu
    Encryption And File System Tpm Encryption

Encryption PIN Or Passphrase Use PIN
    [Documentation]         Choose to use pin authentication for the TPM
    Encryption PIN Or Passphrase Use PIN

Encryption PIN Slide
    [Documentation]         Choose a pin for authentication
    Encryption PIN Slide

Create Account
    [Documentation]         Create a user on the installed system
    Create Account

Select Timezone
    [Documentation]         Choose a timezone
    Select Timezone

Review Installation
    [Documentation]         Review installation slide
    Review Installation

Wait For TPM Install To Finish
    [Documentation]         Wait for the installation to finish
    Wait For TPM Install To Finish

Wait For TPM Encrypted Reboot To Finish With Pin
    [Documentation]         Wait for the post-install reboot to finish, and enter pin code on reboot
    Wait For TPM Encrypted Reboot To Finish With Pin

Wait For GIS Popup
    [Documentation]         Wait for the gnome-initial-setup popup
    Wait For GIS Popup

# Install OpenSSHServer
#     [Documentation]         Install openssh-server to collect logs
#     Install OpenSSHServer
