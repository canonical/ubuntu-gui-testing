*** Settings ***
Documentation         TPM FDE with passphrase installation
Resource        kvm.resource
Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word
Resource    ${CURDIR}/../../installer.resource


*** Variables ***
${T}    ${CURDIR}
${RECOVERY_KEY}         ${EMPTY}


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
    [Documentation]         Go through proprietary software slide
    # TODO: modify this to just move to text, or something
    Match    ${T}/../../generic/disk-setup.png    120
    ${erase_unselected}=               Run Keyword And Return Status
    ...                     Match    ${T}/../../generic/erase-and-reinstall-unselected.png    120
    IF    ${erase_unselected}
        Move Pointer To ${T}/../../generic/erase-and-reinstall-unselected.png
        EzClick
    END
    Match    ${T}/../../generic/erase-and-reinstall-selected.png    120
    Move Pointer To ${T}/../../generic/next.png
    EzClick

Choose Where to Install Ubuntu
    [Documentation]         Go through slide showing various disks, if present
    Choose Where to Install Ubuntu

Encryption And File System Tpm Encryption
    [Documentation]         Select tpm encryption from the encryption menu
    Encryption And File System Tpm Encryption

Encryption PIN Or Passphrase Use Passphrase
    [Documentation]         Choose to use passphrase authentication for the TPM
    Encryption PIN Or Passphrase Use Passphrase

Encryption Passphrase Slide Test Entropy
    [Documentation]         Enter a passphrase on the passphrase slide and test the entropy dialogue
    Encryption Passphrase Slide Test Entropy

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
    [Documentation]         Wait for the installation to finish, and print the recovery key
    ${recovery_key}=          Wait For TPM Install To Finish
    Log
    ...                     recovery key: ${recovery_key}
    ...                     html=true
    ...                     console=true
    VAR       ${RECOVERY_KEY}       ${recovery_key}       scope=GLOBAL  # robocop: off=no-global-variable

Wait For TPM Encrypted Reboot To Finish
    [Documentation]         Wait for the post-install reboot to finish, and enter passphrase on reboot
    Wait For TPM Encrypted Reboot To Finish

Wait For GIS Popup
    [Documentation]         Wait for the gnome-initial-setup popup
    Wait For GIS Popup

Reboot And Use Recovery Key Instead Of Passphrase
    [Documentation]         Reboot again from the desktop environment and use the recovery key instead of the passphrase
    Reboot And Use Recovery Key Instead Of Passphrase           ${RECOVERY_KEY}

# Install OpenSSHServer
#     [Documentation]         Install openssh-server to collect logs
#     Install OpenSSHServer
