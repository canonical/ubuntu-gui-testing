*** Settings ***
Documentation       Shared resources for installer testing
Resource    kvm.resource
Resource        ${CURDIR}/common/common.resource

Library         OperatingSystem
Library         String
Library         ./JournalMonitor.py  AS  JournalMonitor


*** Variables ***
${T}    ${CURDIR}


*** Keywords ***
Restart Stream And Wait For Passphrase Entry
    [Documentation]     Restarts stream (to help with rebooting testbed) and waits for passphrase input
    # 1800 seconds wait time
    FOR    ${_}    IN RANGE    120
        Restart Video Input
        ${match}                Run Keyword And Return Status
        ...                     Match Text      passphrase      10
        IF    ${match}    BREAK
        ${match}                Run Keyword And Return Status
        ...                     Match Text      unlock disk      10
        IF    ${match}    BREAK
    END
    IF    not ${match}    Fail    No match found

Restart Stream And Wait For Unlock Disk
    [Documentation]     Restarts stream (to help with rebooting testbed) and waits for unlock disk dialogue
    # 1800 seconds wait time
    FOR    ${_}    IN RANGE    20
        # let's try without this.
        # Restart Video Input
        ${match}                Run Keyword And Return Status
        ...                     Match Text      unlock disk      10
        IF    ${match}    BREAK
        ${match}                Run Keyword And Return Status
        ...                     Match Text      passphrase      10
        IF    ${match}    BREAK
    END
    # Print the read text here for debugging purposes.
    Read Text
    IF    not ${match}    Fail    No match found

Grub Menu
    # Only used in resolute tests
    [Documentation]     Boot live ISO from grub menu
    ${match}                Run Keyword And Return Status
    ...                     Match Text       GRUB      150
    ${ret}      Create List    KP_Enter
    ${down}       Create List       KP_Down
    ${up}       Create List       KP_Up
    IF       ${match}
        # If we are in the GRUB menu, let's press enter
        # on VM testing, we have GRUB menu, on HW testing, we do
        # not.
        FOR    ${_}    IN RANGE    30
            ${match}    Run Keyword And Return Status
            ...         Match Text    GRUB     5
            IF    not ${match}    BREAK
            Keys Combo     ${down}
            BuiltIn.Sleep    1
            Keys Combo     ${up}
            BuiltIn.Sleep    1
            Keys Combo     ${ret}
            BuiltIn.Sleep    1
        END
    ELSE
        # not matched? we assume we are at the first slide.
        # Let's double check that, though.
        Match Text    Choose your language     45
    END

Select Erase Disk and Reinstall
    # Only used in resolute tests
    [Documentation]    Erase the entire disk and reinstall
    Match Text      Disk setup      300
    Move Pointer To "Erase disk and install Ubuntu"
    EzClick
    Move Pointer To ${T}/generic-resolute/next.png
    EzClick

Ensure Not Unfocused After Boot
    [Documentation]         Workaround LP: #2112383
    [Arguments]     ${template}=generic
    FOR      ${_}     IN RANGE      36
        ${match}                Run Keyword And Return Status
        ...               Match Text    Choose your language     10
        IF    ${match}    BREAK
    END
    FOR     ${_}    IN RANGE      10
        ${match}                Run Keyword And Return Status
        ...                     Match       ${T}/${template}/next.png      15
        IF    ${match}    BREAK
        Move Pointer To Proportional (0.3, 0.3)
        EzClick
    END

Select Language
    [Documentation]    Select Language, we will default to English
    [Arguments]     ${template}=generic
    FOR    ${_}    IN RANGE    120
        Restart Video Input
        ${match}                Run Keyword And Return Status
        ...                     Match Text        Choose your language      10
        IF    ${match}    BREAK
    END
    IF    not ${match}    Fail    No match found
    Move Pointer To ${T}/${template}/next.png
    EzClick

A11y Slide
    [Documentation]    Accessibility Slide
    [Arguments]     ${template}=generic
    Match Text  Accessibility in Ubuntu  180
    Move Pointer To ${T}/${template}/next.png
    EzClick

Keyboard Layout
    [Documentation]    Keyboard Layout Slide
    [Arguments]     ${template}=generic
    Match Text  Keyboard layout  20
    Move Pointer To ${T}/${template}/next.png
    EzClick

Internet Connection
    [Documentation]    Connect to the Internet Slide
    [Arguments]     ${template}=generic
    Match Text  Internet connection  45
    Move Pointer To ${T}/${template}/next.png
    EzClick

Skip Installer Update
    [Documentation]    Installer update available slide
    ${skippable}               Run Keyword And Return Status
    ...                     Match Text      Update available     20
    IF    ${skippable}
        Move Pointer To Skip
        EzClick
    END

Try Or Install
    [Documentation]    Choose try or install
    [Arguments]     ${template}=generic
    Match Text        Try or install Ubuntu       45
    Move Pointer To ${T}/${template}/next.png
    EzClick

Interactive vs Automated
    [Documentation]    Interactive vs automated installation slide
    [Arguments]     ${template}=generic
    Match Text       Type of installation       20
    Move Pointer To ${T}/${template}/next.png
    EzClick

Default vs Extended
    [Documentation]    Default vs extended installation slide
    [Arguments]     ${template}=generic
    Match Text        Default selection       20
    Move Pointer To ${T}/${template}/next.png
    EzClick

Proprietary Software
    [Documentation]    Slide prompting proprietary software installation
    [Arguments]     ${template}=generic
    Match Text  Optimise your computer  20
    Move Pointer To ${T}/${template}/next.png
    EzClick

Choose Where to Install Ubuntu
    [Documentation]    Choose the drive to install on - correct one pre-selected -
    ...                on a VM, or a setup with only the one disk, this slide
    ...                doesn't appear. In this instance, this function should do nothing.
    [Arguments]     ${template}=generic
    ${multiple_disks}                Run Keyword And Return Status
    ...                     Match Text  Choose where to install Ubuntu  30

    IF    ${multiple_disks}
        Move Pointer To ${T}/${template}/next.png
        EzClick
    END

Encryption And File System Zfs Encryption
    # Only used in resolute tests
    [Documentation]         Select zfs and encryption in the Encryption + FS slide
    Match Text  Encryption and file system  120
    Move Pointer To Advanced options
    EzClick
    Keys Combo  Page_Down
    BuiltIn.Sleep  1
    Move Pointer To Encrypt with a passphrase using ZFS
    EzClick
    Move Pointer To ${T}/generic-resolute/next.png
    EzClick

Disk Passphrase Setup Questing Onwards
    # Only used in resolute tests
    [Documentation]    Sets up passphrase for encrypted installations
    Match Text        Set an encryption passphrase        20
    ${combo}    Create List    Tab
    Keys Combo    ${combo}
    BuiltIn.Sleep       1
    Keys Combo    ${combo}
    BuiltIn.Sleep       1
    Type String    ubuntu
    BuiltIn.Sleep       1
    Keys Combo    ${combo}
    BuiltIn.Sleep       1
    Keys Combo    ${combo}
    BuiltIn.Sleep       1
    Keys Combo    ${combo}
    BuiltIn.Sleep    3
    Type String    ubuntu
    Move Pointer To ${T}/generic-resolute/next.png
    EzClick

Create Account
    [Documentation]    Create the user account
    [Arguments]     ${template}=generic
    Match Text  Create your account  20
    ${combo}    Create List    Tab
    BuiltIn.Sleep    2
    Type String    ubuntu
    BuiltIn.Sleep    2
    Keys Combo    ${combo}
    BuiltIn.Sleep    2
    Type String    ubuntu
    BuiltIn.Sleep    2
    Keys Combo    ${combo}
    BuiltIn.Sleep    2
    Type String    ubuntu
    BuiltIn.Sleep    2
    Keys Combo    ${combo}
    BuiltIn.Sleep    2
    Type String    ubuntu
    BuiltIn.Sleep    2
    Keys Combo    ${combo}
    BuiltIn.Sleep    2
    Keys Combo    ${combo}
    BuiltIn.Sleep    2
    Type String    ubuntu
    BuiltIn.Sleep    2
    Keys Combo    ${combo}
    BuiltIn.Sleep    2
    Move Pointer To (100, 100)
    Move Pointer To ${T}/${template}/next.png
    BuiltIn.Sleep    2
    EzClick

Select Timezone
    [Documentation]    Select timezone slide
    [Arguments]     ${template}=generic
    Match Text      Select your timezone      20
    ${london_selected}               Run Keyword And Return Status
    ...                     Match    ${T}/generic/london-selected.png    20
    IF    not ${london_selected}
        ${tab}     Create List     Tab
        Keys Combo     ${tab}
        BuiltIn.Sleep    1
        Keys Combo     ${tab}
        BuiltIn.Sleep    1
        Type String    london
        BuiltIn.Sleep    1
        ${ret}     Create List     Return
        Keys Combo     ${ret}
    END
    Move Pointer To ${T}/${template}/next.png
    EzClick

Review Installation
    [Documentation]    Review installation slide
    [Arguments]     ${template}=generic
    Match Text  Ready to install  180
    Move Pointer To ${T}/${template}/install-button.png
    EzClick

Wait For Install To Finish
    [Documentation]    Install finished slide
    # Match Text      Restart Now     1800
    BuiltIn.Sleep       60
    Match Text      Installation Complete       7200
    Move Pointer To "Restart now"
    Click LEFT Button

Wait For ZFS Encrypted Reboot To Finish
    [Documentation]    Waits for an encrypted reboot to finish, enters passphrase, and logs in

    ${combo}    Create List    Return
    Match Text       Please remove        120
    Keys Combo    ${combo}

    Restart Stream And Wait For Unlock Disk

    Type String    ubuntu
    ${combo}    Create List    Return
    Keys Combo    ${combo}
    Match Text        Not listed       300
    ${combo}    Create List    Return
    Keys Combo    ${combo}
    BuiltIn.Sleep     5
    Type String    ubuntu
    Keys Combo    ${combo}
    Match Text      Welcome to Ubuntu     360
    Move Pointer To (300, 300)
    EzClick

Wait For GIS Popup
    [Documentation]         Wait for gnome-initial-setup
    Match Text      Welcome to Ubuntu         600
    BuiltIn.Sleep       10

Install OpenSSHServer
    [Documentation]         Install openssh-server
    [Arguments]     ${livesession}=False
    Install Debian Package      openssh-server  livesession=${livesession}

Start sshd VSOCK socket
    [Documentation]         Start sshd-vsock.socket
    [Arguments]     ${livesession}=False
    Open Terminal
    Run Sudo Command In Terminal With Context  sudo systemctl start sshd-vsock.socket   livesession=${livesession}
    Close Terminal

Expose SSH Over VSOCK Noble
    [Documentation]         Expose ssh over VSOCK via socat
    [Arguments]     ${livesession}=False
    Install Debian Package  socat   livesession=${livesession}
    Open Terminal
    Run Sudo Command In Terminal With Context  sudo echo    livesession=${livesession}
    Type String     sudo socat VSOCK-LISTEN:22,reuseaddr,fork TCP:localhost:22 &
    Keys Combo  Return
    Run Command In Terminal     disown
    Close Terminal

Entire Disk With ZFS
    # Only used in noble tests
    [Documentation]    This slide assumes the disk is empty
    Match    ${T}/generic/disk-setup.png    180
    Move Pointer To "Erase disk and install Ubuntu"
    EzClick
    # Match    ${T}/generic/entire-disk.png    20
    Move Pointer To ${T}/generic/advanced-features.png
    EzClick
    Move Pointer To ${T}/generic/erase-disk-use-zfs.png
    EzClick
    Move Pointer To ${T}/generic/advanced-features-ok.png
    EzClick
    Match    ${T}/generic/check-zfs-selected.png    20
    Move Pointer To ${T}/generic/next.png
    EzClick

Restart Stream And Wait For Login
    [Documentation]         Restart stream and wait for the login screen
    FOR    ${_}    IN RANGE    120
        Restart Video Input
        ${match}                Run Keyword And Return Status
        ...                     Match       ${T}/generic/login-prompt.png       15
        IF    ${match}    BREAK
    END
    IF    not ${match}    Fail    No match found

Wait For Reboot To Finish
    [Documentation]    Login Prompt
    ${combo}    Create List    Return
    Match Text       Please remove        120
    Keys Combo    ${combo}

    Restart Stream And Wait For Login
    Move Pointer To ${T}/generic/login-prompt.png
    EzClick

    Keys Combo    ${combo}
    BuiltIn.Sleep     5
    Type String    ubuntu
    Keys Combo    ${combo}
    Match Text      Welcome to Ubuntu     360
    Move Pointer To (300, 300)
    EzClick

Entire Disk With ZFS Plus Encryption
    # Only used in noble tests
    [Documentation]    This slide assumes the disk is empty
    Match    ${T}/generic/disk-setup.png    180
    Move Pointer To "Erase disk and install Ubuntu"
    EzClick
    # Match    ${T}/generic/entire-disk.png    20
    Move Pointer To ${T}/generic/advanced-features.png
    EzClick
    Move Pointer To ${T}/generic/erase-disk-use-zfs-plus-encryption.png
    EzClick
    Move Pointer To ${T}/generic/advanced-features-ok.png
    EzClick
    Match    ${T}/generic/check-zfs-plus-encryption-selected.png    20
    Move Pointer To ${T}/generic/next.png
    EzClick

Disk Passphrase Setup
    # Only used in noble tests
    [Documentation]    Sets up passphrase for encrypted installations
    Match    ${T}/generic/disk-passphrase.png    20
    Move Pointer To ${T}/generic/choose-a-passphrase.png
    EzClick
    ${combo}    Create List    Tab
    Type String    ubuntu
    BuiltIn.Sleep       1
    Keys Combo    ${combo}
    BuiltIn.Sleep       1
    Keys Combo    ${combo}
    BuiltIn.Sleep    3
    Type String    ubuntu
    Move Pointer To ${T}/generic/next.png
    EzClick

Entire Disk
    # Only used in noble tests
    [Documentation]    This slide assumes the disk is empty
    Match    ${T}/generic/disk-setup.png    180
    Move Pointer To "Erase disk and install Ubuntu"
    EzClick
    # Match    ${T}/generic/entire-disk.png    20
    Move Pointer To ${T}/generic/next.png
    EzClick

Entire Disk With LVM Plus Encryption
    # Only used in noble tests
    [Documentation]    This slide assumes the disk is empty
    Match    ${T}/generic/disk-setup.png    180
    Move Pointer To "Erase disk and install Ubuntu"
    EzClick
    # Match    ${T}/generic/entire-disk.png    20
    Move Pointer To ${T}/generic/advanced-features.png
    EzClick
    Move Pointer To ${T}/generic/erase-disk-use-lvm-plus-encryption.png
    EzClick
    Move Pointer To ${T}/generic/advanced-features-ok.png
    EzClick
    Match    ${T}/generic/check-lvm-plus-encryption-selected.png    20
    Move Pointer To ${T}/generic/next.png
    EzClick

Wait For LVM Encrypted Reboot To Finish
    [Documentation]    Waits for an encrypted reboot to finish, enters passphrase, and logs in
    ${combo}    Create List    Return
    Match Text       Please remove        120
    Keys Combo    ${combo}

    Restart Stream And Wait For Passphrase Entry

    Type String    ubuntu
    ${combo}    Create List    Return
    Keys Combo    ${combo}
    Match Text        Not listed       300
    ${combo}    Create List    Return
    Keys Combo    ${combo}
    BuiltIn.Sleep     5
    Type String    ubuntu
    Keys Combo    ${combo}
    # Match    ${T}/generic/firefox-icon.png    360
    Match Text      Welcome to Ubuntu     360
    Move Pointer To (300, 300)
    EzClick

Encryption And File System Tpm Not Available
    # Only used in resolute tests
    [Documentation]         Check for error message that says TPM/FDE could not be enabled
    Match Text  Encryption and file system  120
    Match Text  Hardware-backed encryption could not be enabled  120

Encryption And File System Tpm Encryption
    # Only used in resolute tests
    [Documentation]         Choose TPM encryption on encryption slide
    Match Text  Encryption and file system  120
    Move Pointer To Use hardware-backed encryption
    EzClick
    Move Pointer To ${T}/generic-resolute/next.png
    EzClick

Wait For TPM Install To Finish
    [Documentation]    Waits for recovery key slide after TPM installation finishes
    Match Text     Show QR code     1800
    BuiltIn.Sleep       5
    Move Pointer To "Show QR code"
    EzClick
    Match Text      Scan the QR code

    VAR     ${RECOVERY_KEY}    ""      scope=SUITE

    FOR       ${_}      IN RANGE      30
      ${text}       Read Text
      Log
      ...                     Text read on QR code screen is: ${text}
      ...                     html=true
      ...                     console=true
      ${matches}     Get Regexp Matches    ${text}      [0-9]{5}(-|- | -)[0-9]{5}(-|- | -)[0-9]{5}(-|- | -)[0-9]{5}(-|- | -)[0-9]{5}(-|- | -)[0-9]{5}(-|- | -)[0-9]{5}(-|- | -)[0-9]{5}
      ${num_matches}        Get Length      ${matches}
      IF      ${num_matches} > 0
        VAR     ${RECOVERY_KEY}    ${matches}[0]     scope=SUITE
        BREAK
      END
      BuiltIn.Sleep     3
    END

    Log
    ...                     Recovery parsed as: ${RECOVERY_KEY}
    ...                     html=true
    ...                     console=true

    Keys Combo      Escape
    Move Pointer To "I saved my"
    EzClick
    Move Pointer To ${T}/generic-resolute/next.png
    EzClick
    Move Pointer To "Restart now"
    EzClick
    RETURN            ${RECOVERY_KEY}

Encryption And File System Lvm Encryption
    # Only used in resolute tests
    [Documentation]         Choose LVM + encryption
    Match Text  Encryption and file system  120
    Move Pointer To Encrypt with a passphrase
    EzClick
    Move Pointer To ${T}/generic-resolute/next.png
    EzClick

Encryption And File System No Encryption
    # Only used in resolute tests
    [Documentation]         Select no encryption in the Encryption + FS slide
    Match Text  Encryption and filesystem
    Move Pointer To ${T}/generic-resolute/next.png
    EzClick

Encryption And File System Zfs No Encryption
    # Only used in resolute tests
    [Documentation]         Select zfs no encryption in the Encryption + FS slide
    Match Text  Encryption and file system  120
    Move Pointer To Advanced options
    EzClick
    Move Pointer To Use ZFS without encryption
    EzClick
    Move Pointer To ${T}/generic-resolute/next.png
    EzClick

Open Firmware Updater
    [Documentation]     Opens the firmware updater
    BuiltIn.Sleep       45
    Match    ${T}/generic/firefox-icon.png    120
    Start Application           firmware-updater
    Match Text          Firmware Updater       90
    ${cnf}                Run Keyword And Return Status
    ...                     Match Text        Command not found      10
    IF    ${cnf}        Fail        firmware-updater command not found

Reboot Via Terminal
    [Documentation]    Run sudo reboot in a terminal
    Open Terminal
    Type String    sudo reboot
    BuiltIn.Sleep    2    # hacky
    ${enter}    Create List    Return
    Keys Combo    ${enter}
    Match Text    Password    15
    Type String    ubuntu
    BuiltIn.Sleep    2    # hacky
    Keys Combo    ${enter}

Install Debian Package
    [Documentation]    Install a debian package
    [Arguments]    ${package}   ${livesession}=False
    Open Terminal
    Run Sudo Command In Terminal With Context    sudo apt-get update -y     livesession=${livesession}
    Run Command In Terminal    sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y ${package}
    Close Terminal

Run Sudo Command In Terminal With Context
    [Documentation]     Runs a sudo command in a terminal. Ignores the password prompt in the live session.
    [Arguments]    ${command}   ${livesession}=False
    IF    ${livesession}
        Run Command In Terminal  ${command}
    ELSE
        Run Sudo Command In Terminal  ${command}
    END

Set Live Session User Password
    [Documentation]    Changes the password of a given user
    [Arguments]    ${username}    ${password}
    Open Terminal
    Type String    sudo passwd ${username}
    Keys Combo    Return
    BuiltIn.Sleep    1
    Type String    ${password}
    Keys Combo    Return
    BuiltIn.Sleep    1
    Type String    ${password}
    Keys Combo    Return
    BuiltIn.Sleep    1
    Close Terminal
