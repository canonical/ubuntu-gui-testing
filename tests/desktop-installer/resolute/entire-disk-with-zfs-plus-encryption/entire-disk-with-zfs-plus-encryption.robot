*** Settings ***
Documentation         Encrypted zfs installation
Resource        kvm.resource
Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word
Resource    ${CURDIR}/../../installer.resource


*** Test Cases ***
Grub Menu
    [Documentation]         Go through grub menu, if present
    Grub Menu

Ensure Not Unfocused After Boot
    [Documentation]         Workaround LP: #2112383
    Ensure Not Unfocused After Boot  template=generic-resolute

Install OpenSSHServer
    [Documentation]         Install openssh-server to collect logs
    Install OpenSSHServer   livesession=True

Start sshd VSOCK socket
    [Documentation]         Start sshd-vsock.socket
    Start sshd VSOCK socket     livesession=True

Set Live Session User Password
    [Documentation]         Set password of the live session user to 'ubuntu'
    Set Live Session User Password       ubuntu  ubuntu

Start Journal Monitor
    [Documentation]         Start monitoring the system journal
    JournalMonitor.Start

Language Slide
    [Documentation]         Go through language slide
    Select Language  template=generic-resolute

A11y Slide
    [Documentation]         Go through a11y slide
    A11y Slide  template=generic-resolute

Keyboard Layout
    [Documentation]         Use default keyboard layout
    Keyboard Layout  template=generic-resolute

Internet Connection
    [Documentation]         Go through internet connection slide
    Internet Connection  template=generic-resolute

Skip Installer Update
    [Documentation]         Skip installer update, if present
    Skip Installer Update

Try Or Install
    [Documentation]         Go through try or install slide
    Try Or Install  template=generic-resolute

Interactive vs Automated
    [Documentation]         Go through interactive vs automated slide
    Interactive vs Automated  template=generic-resolute

Default vs Extended
    [Documentation]         Go through default vs extended slide
    Default vs Extended  template=generic-resolute

Proprietary Software
    [Documentation]         Go through proprietary software slide
    Proprietary Software  template=generic-resolute

Select Erase Disk and Reinstall
    [Documentation]         Select erase disk and reinstall
    Select Erase Disk and Reinstall

Choose Where to Install Ubuntu
    [Documentation]         Go through slide showing various disks, if present
    Choose Where to Install Ubuntu  template=generic-resolute

Encryption And File System Zfs Encryption
    [Documentation]         Select zfs encryption from the encryption menu
    Encryption And File System Zfs Encryption

Disk Passphrase Setup Questing Onwards
    [Documentation]         Set up a passphrase for the zfs encrypted volumes
    Disk Passphrase Setup Questing Onwards

Create Account
    [Documentation]         Create a user on the installed system
    Create Account  template=generic-resolute

Select Timezone
    [Documentation]         Choose a timezone
    Select Timezone  template=generic-resolute

Review Installation
    [Documentation]         Review installation slide
    Review Installation  template=generic-resolute

Wait For Install To Finish
    [Documentation]         Wait for the installation to finish
    Wait For Install To Finish

Stop Journal Monitor
    [Documentation]         Stop monitoring the system journal
    JournalMonitor.Stop

Wait For ZFS Encrypted Reboot To Finish
    [Documentation]         Wait for the post-install reboot to finish, and enter passphrase on reboot
    Wait For ZFS Encrypted Reboot To Finish

Wait For GIS Popup
    [Documentation]         Wait for the gnome-initial-setup popup
    Wait For GIS Popup

Install OpenSSHServer In Installed System
    [Documentation]         Install openssh-server to collect logs
    Install OpenSSHServer

Start sshd VSOCK socket In Installed System
    [Documentation]         Start sshd-vsock.socket
    Start sshd VSOCK socket

Start Journal Monitor In Installed System
    [Documentation]         Start monitoring the system journal
    JournalMonitor.Start
