*** Settings ***
Documentation       Shared resources for installer testing
Resource    kvm.resource
Resource        ${CURDIR}/common/common.resource

Library         OperatingSystem
Library         String


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
    [Documentation]    Erase the entire disk and reinstall
    Match Text      Disk setup      300
    Move Pointer To "Erase disk and install Ubuntu"
    EzClick
    Move Pointer To ${T}/generic/next.png
    EzClick

Ensure Not Unfocused After Boot
    [Documentation]         Workaround LP: #2112383
    FOR      ${_}     IN RANGE      36
        ${match}                Run Keyword And Return Status
        ...               Match Text    Choose your language     10
        IF    ${match}    BREAK
    END
    FOR     ${_}    IN RANGE      10
        ${match}                Run Keyword And Return Status
        ...                     Match       ${T}/generic/next.png      15
        IF    ${match}    BREAK
        Move Pointer To Proportional (0.3, 0.3)
        EzClick
    END

Select Language
    [Documentation]    Select Language, we will default to English
    FOR    ${_}    IN RANGE    120
        Restart Video Input
        ${match}                Run Keyword And Return Status
        ...                     Match Text        Choose your language      10
        IF    ${match}    BREAK
    END
    IF    not ${match}    Fail    No match found
    Move Pointer To ${T}/generic/next.png
    EzClick

A11y Slide
    [Documentation]    Accessibility Slide
    Match    ${T}/generic/a11y.png    180
    Move Pointer To ${T}/generic/next.png
    EzClick

Keyboard Layout
    [Documentation]    Keyboard Layout Slide
    Match    ${T}/generic/keyboard-layout.png    20
    Move Pointer To ${T}/generic/next.png
    EzClick

Internet Connection
    [Documentation]    Connect to the Internet Slide
    Match    ${T}/generic/internet-connection.png    45
    Move Pointer To ${T}/generic/next.png
    EzClick

Skip Installer Update
    [Documentation]    Installer update available slide
    ${skippable}               Run Keyword And Return Status
    ...                     Match Text      Update available     20
    IF    ${skippable}
        Move Pointer To ${T}/generic/skip.png
        EzClick
    END

Try Or Install
    [Documentation]    Choose try or install
    Match Text        Try or install Ubuntu       45
    Move Pointer To ${T}/generic/next.png
    EzClick

Interactive vs Automated
    [Documentation]    Interactive vs automated installation slide
    Match Text       Type of installation       20
    Move Pointer To ${T}/generic/next.png
    EzClick

Default vs Extended
    [Documentation]    Default vs extended installation slide
    Match Text        Default selection       20
    Move Pointer To ${T}/generic/next.png
    EzClick

Proprietary Software
    [Documentation]    Slide prompting proprietary software installation
    Match    ${T}/generic/proprietary-software.png    20
    Move Pointer To ${T}/generic/next.png
    EzClick

Choose Where to Install Ubuntu
    [Documentation]    Choose the drive to install on - correct one pre-selected -
    ...                on a VM, or a setup with only the one disk, this slide
    ...                doesn't appear. In this instance, this function should do nothing.
    ${multiple_disks}                Run Keyword And Return Status
    ...                     Match    ${T}/generic/choose-where-to-install.png    30

    IF    ${multiple_disks}
        Move Pointer To ${T}/generic/next.png
        EzClick
    END

Encryption And File System Zfs Encryption
    [Documentation]         Select zfs and encryption in the Encryption + FS slide
    Match    ${T}/generic/encryption-and-file-system.png    120
    Match    ${T}/generic/encryption-and-file-system.png    120
    Match    ${T}/generic/encryption-and-file-system-no-encryption-selected.png    20
    Match    ${T}/generic/encryption-and-file-system-encrypt-unselected.png    20
    Move Pointer To ${T}/generic/encryption-and-file-system-show-advanced.png
    EzClick
    # let's use text here! and in all of the places here I suppose.
    ${matches}      Match Text        Encrypt with a passphrase using ZFS       20
    # for some reason, this indexing seems to differ from interactive terminal to in this resource file?
    # an extra [0]? weird, keep an eye on it. Will be solved by yarf PR anyway
    Move Pointer To (${matches[0][0]['region'].left}, ${matches[0][0]['region'].top})
    # Move Pointer To ${T}/generic/encryption-and-file-system-show-advanced-zfs-encryption.png
    EzClick
    Move Pointer To ${T}/generic/next.png
    EzClick

Disk Passphrase Setup Questing Onwards
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
    Move Pointer To ${T}/generic/next.png
    EzClick

Create Account
    [Documentation]    Create the user account
    Match    ${T}/generic/create-your-account.png    20
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
    Move Pointer To ${T}/generic/next.png
    BuiltIn.Sleep    2
    EzClick

Select Timezone
    [Documentation]    Select timezone slide
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
    Move Pointer To ${T}/generic/next.png
    EzClick

Review Installation
    [Documentation]    Review installation slide
    Match    ${T}/generic/review-installation.png    180
    Move Pointer To ${T}/generic/install-button.png
    EzClick

Wait For Install To Finish
    [Documentation]    Install finished slide
    # Match Text      Restart Now     1800
    BuiltIn.Sleep       60
    Match Text      Installation Complete       1800
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
    Install Debian Package      openssh-server

Entire Disk With ZFS
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
    [Documentation]    This slide assumes the disk is empty
    Match    ${T}/generic/disk-setup.png    180
    Move Pointer To "Erase disk and install Ubuntu"
    EzClick
    # Match    ${T}/generic/entire-disk.png    20
    Move Pointer To ${T}/generic/next.png
    EzClick

Entire Disk With LVM Plus Encryption
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
    [Documentation]         Ensure that TPM isn't available on the encryption slide
    Match    ${T}/generic/encryption-and-file-system.png    120
    Match    ${T}/generic/encryption-and-file-system-no-encryption-selected.png    20
    Match    ${T}/generic/encryption-and-file-system-encrypt-unselected.png    20
    Move Pointer To ${T}/generic/encryption-and-file-system-show-advanced.png
    EzClick
    ${tpm_available}               Run Keyword And Return Status
    ...                     Press Key And Match     Down      ${T}/generic/encryption-and-file-system-show-advanced-tpm-encryption.png        20      2
    IF    ${tpm_available}
        Fail      The installer offers TPM when there is no tpm!
    END

Encryption And File System Tpm Encryption
    [Documentation]         Choose TPM encryption on encryption slide
    Match    ${T}/generic/encryption-and-file-system.png    120
    Match    ${T}/generic/encryption-and-file-system-no-encryption-selected.png    20
    Match    ${T}/generic/encryption-and-file-system-encrypt-unselected.png    20
    Move Pointer To ${T}/generic/encryption-and-file-system-show-advanced.png
    EzClick
    Press Key And Match     Down      ${T}/generic/encryption-and-file-system-show-advanced-tpm-encryption.png        10        5
    Move Pointer To ${T}/generic/encryption-and-file-system-show-advanced-tpm-encryption.png
    EzClick
    Match    ${T}/generic/encryption-and-file-system-show-advanced-tpm-encryption-clicked.png
    Move Pointer To ${T}/generic/next.png
    EzClick

Encryption PIN Or Passphrase Use PIN
    [Documentation]         Choose pin authentication method for tpm encryption
    Match Text       Encryption       30
    Move Pointer To "Require a PIN"
    EzClick
    Move Pointer To ${T}/generic/next.png
    EzClick

Encryption PIN Slide
    [Documentation]         Choose a pin for tpm authentication
    Match Text        Set an encryption PIN         30
    ${tab}     Create List     Tab
    Keys Combo      ${tab}
    BuiltIn.Sleep     1
    Type String     111111
    FOR       ${_}      IN RANGE      2
        Keys Combo      ${tab}
        BuiltIn.Sleep     1
    END
    Type String     111111
    Move Pointer To ${T}/generic/next.png
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
    Create File         ${RECOVERY_KEY_PATH}        ${RECOVERY_KEY}

    Keys Combo      Escape
    Move Pointer To "I saved my"
    EzClick
    Move Pointer To ${T}/generic/next.png
    EzClick
    Move Pointer To "Restart now"
    EzClick
    RETURN            ${RECOVERY_KEY}

Wait For TPM Encrypted Reboot To Finish With Pin
    [Documentation]    Waits for an encrypted reboot to finish, enters passphrase, and logs in

    ${combo}    Create List    Return
    Match Text       Please remove        120
    Keys Combo    ${combo}

    Restart Stream And Wait For Passphrase Entry

    Type String    111111
    ${combo}    Create List    Return
    Keys Combo    ${combo}
    Match Text        Not listed       300
    ${combo}    Create List    Return
    Keys Combo    ${combo}
    BuiltIn.Sleep     5
    Type String    ubuntu
    Keys Combo    ${combo}
    # Match    ${T}/generic/noble-desktop.png    360
    # Match    ${T}/generic/firefox-icon.png    360
    Match Text      Welcome to Ubuntu     360
    Move Pointer To (300, 300)
    EzClick

Encryption And File System Lvm Encryption
    [Documentation]         Choose LVM + encryption
    Match    ${T}/generic/encryption-and-file-system.png    120
    Match    ${T}/generic/encryption-and-file-system-no-encryption-selected.png    20
    Match    ${T}/generic/encryption-and-file-system-encrypt-unselected.png    20
    Move Pointer To ${T}/generic/encryption-and-file-system-show-advanced.png
    EzClick
    Move Pointer To ${T}/generic/encryption-and-file-system-encrypt-unselected.png
    EzClick
    Move Pointer To ${T}/generic/next.png
    EzClick

Encryption PIN Or Passphrase Use Neither
    [Documentation]         Choose no authentication method for tpm encryption
    Match Text       Encryption       30
    Match       ${T}/generic/encryption-pin-or-passphrase-unlock-automatically.png    10
    Move Pointer To ${T}/generic/next.png
    EzClick

Encryption And File System No Encryption
    [Documentation]         Select no encryption in the Encryption + FS slide
    Match    ${T}/generic/encryption-and-file-system.png    120
    Match    ${T}/generic/encryption-and-file-system-no-encryption-selected.png    120
    Move Pointer To ${T}/generic/next.png
    EzClick

Encryption PIN Or Passphrase Use Passphrase
    [Documentation]         Choose to use a passphrase
    Match Text       Encryption       30
    Move Pointer To "Require a passphrase"
    EzClick
    Move Pointer To ${T}/generic/next.png
    EzClick

Encryption Passphrase Slide Test Entropy
    [Documentation]         Ensure the user is prompted to enter a complicated enough passphrase
    Match Text        Set an encryption Passphrase         30
    ${tab}     Create List     Tab
    Keys Combo      ${tab}
    BuiltIn.Sleep     1
    Keys Combo      ${tab}
    BuiltIn.Sleep     1
    Type String       ubuntu
    BuiltIn.Sleep     10
    Match Text        Weak passphrase         15
    BuiltIn.Sleep     10
    Type String       isthebestdistro
    Match Text        Fair passphrase         15
    BuiltIn.Sleep     10
    Type String       1234
    Match Text        Strong passphrase         15
    BuiltIn.Sleep     10
    FOR       ${_}      IN RANGE      3
        Keys Combo      ${tab}
        BuiltIn.Sleep     1
    END
    Type String      ubuntuisthebestdistro1234
    BuiltIn.Sleep     10
    Move Pointer To ${T}/generic/next.png
    EzClick

Wait For TPM Encrypted Reboot To Finish
    [Documentation]    Waits for an encrypted reboot to finish, enters passphrase, and logs in

    ${combo}    Create List    Return
    Match Text       Please remove        120
    Keys Combo    ${combo}

    Restart Stream And Wait For Passphrase Entry

    Type String    ubuntuisthebestdistro1234
    ${combo}    Create List    Return
    Keys Combo    ${combo}
    Match Text        Not listed       300
    ${combo}    Create List    Return
    Keys Combo    ${combo}
    BuiltIn.Sleep     5
    Type String    ubuntu
    Keys Combo    ${combo}
    # Match    ${T}/generic/noble-desktop.png    360
    # Match    ${T}/generic/firefox-icon.png    360
    Match Text      Welcome to Ubuntu     360
    Move Pointer To (300, 300)
    EzClick

Reboot And Use Recovery Key Instead Of Passphrase
    [Documentation]         Reboot from desktop environment and use recovery key instead of passphrase
    [Arguments]       ${RECOVERY_KEY}
    Log
    ...                     Recovery key passed as: ${RECOVERY_KEY}
    ...                     html=true
    ...                     console=true

    # Because of snap seeding issues, we need to wait for the firefox
    # icon. Let's be safe and wait five minutes.
    # LP: #2116949
    Match    ${T}/generic/firefox-icon.png    300
    Reboot Via Terminal Questing
    Restart Stream And Wait For Passphrase Entry
    BuiltIn.Sleep       10
    ${combo}    Create List    Return
    Keys Combo    ${combo}
    BuiltIn.Sleep       2
    Keys Combo    ${combo}
    BuiltIn.Sleep       2
    Keys Combo    ${combo}
    BuiltIn.Sleep       10        # hack
    Type String       ${RECOVERY_KEY.strip()}
    BuiltIn.Sleep       2
    Keys Combo    ${combo}
    Match Text        Not listed       600
    ${combo}    Create List    Return
    Keys Combo    ${combo}
    BuiltIn.Sleep     5
    Type String    ubuntu
    Keys Combo    ${combo}
    Match Text      Welcome to Ubuntu     360
    Move Pointer To (300, 300)
    EzClick

Encryption And File System Zfs No Encryption
    [Documentation]         Select zfs no encryption in the Encryption + FS slide
    Match    ${T}/generic/encryption-and-file-system.png    120
    Match    ${T}/generic/encryption-and-file-system-no-encryption-selected.png    20
    Match    ${T}/generic/encryption-and-file-system-encrypt-unselected.png    20
    Move Pointer To ${T}/generic/encryption-and-file-system-show-advanced.png
    EzClick
    Move Pointer To ${T}/generic/encryption-and-file-system-show-advanced-zfs.png
    EzClick
    Match    ${T}/generic/encryption-and-file-system-show-advanced-zfs-selected.png    20
    Move Pointer To ${T}/generic/next.png
    EzClick
