*** Settings ***
Documentation       Shared resources for application testing

Resource            kvm.resource
Resource            ${Y}/common/common.resource
Library             OperatingSystem
Library             String


*** Variables ***
${Y}                        ${CURDIR}
${DEFAULT_RECOVERY_KEY}     27923-40354-64135-46675-37087-49770-10618-41883


*** Keywords ***
Open Security Center
    [Documentation]    Opens the Security Center
    Open Terminal
    Type String    desktop-security-center
    Keys Combo    Return

Click Security Center Icon
    [Documentation]    Opens the Security Center via clicking its icon
    Move Pointer To ${Y}/generic/security-center-icon.png
    EzClick

Open Disk Encryption Tab
    [Documentation]    Opens the Disk Encryption Tab in the Security Center
    Move Pointer To ${Y}/generic/disk-icon.png
    EzClick
    Match    ${Y}/generic/disk-icon-selected.png

Open Camera Snaps Page
    [Documentation]    Opens the camera interface snaps page on the App Permissions page
    Move Pointer To ${Y}/generic/camera-icon.png
    EzClick
    Match Text    "Allow apps to access your cameras."

Check Recovery Key Success
    [Documentation]    Check a valid recovery key in the Security Center
    Move Pointer To Check
    ${RECOVERY_KEY}=    Get Variable Value    ${recovery_key}    ${DEFAULT_RECOVERY_KEY}
    EzClick
    Move Pointer To XXXX
    EzClick
    Type String    ${RECOVERY_KEY}
    Move Pointer To ${Y}/generic/check-recovery-key-button.png
    EzClick
    Authenticate With Polkit
    Match    ${Y}/generic/check-recovery-key-success.png

Change Passphrase
    [Documentation]    Changes the systems passphrase from the Security Centers Disk Encryption Page
    [Arguments]    ${old}    ${new}
    Move Pointer To Change passphrase...
    EzClick
    Move Pointer To Current Passphrase
    EzClick
    Type String    ${old}
    Move Pointer To New Passphrase
    EzClick
    Type String    ${new}
    Move Pointer To Confirm Passphrase
    EzClick
    Type String    ${new}
    Move Pointer To ${Y}/generic/change-button.png
    EzClick
    Match    ${Y}/generic/change-passphrase-success.png

Boot With Passphrase
    [Documentation]    Boot the system using a passphrase
    [Arguments]    ${passphrase}
    Match Text    Please enter the passphrase for volume    120
    Type String    ${passphrase}
    Keys Combo    Return

Check Recovery Key Failure
    [Documentation]    Check an invalid recovery key in the Security Center
    Move Pointer To Check
    EzClick
    Move Pointer To XXXX
    EzClick
    Type String    00000-00000-00000-00000-00000-00000-00000-00000
    Move Pointer To ${Y}/generic/check-recovery-key-button.png
    EzClick
    Authenticate With Polkit
    Match    ${Y}/generic/check-recovery-key-failure.png

Replace Recovery Key
    [Documentation]    Replace the systems recovery key, validating it is saved to a file
    Move Pointer to Replace
    EzClick
    Authenticate With Polkit
    ${text}=    Read Text
    # Catch the recovery key line
    ${recovery_key_text}=    String.Get Line    ${text}    -11
    # String whitespace
    ${recovery_key}=    Replace String    ${recovery_key_text}    ${space}    ${empty}
    # QR code generates and shows recovery key
    Move Pointer to "Show QR code"
    EzClick
    Match Text    ${recovery_key}
    Move Pointer To ${Y}/generic/cross-button.png
    EzClick
    # We can save to a file
    Move Pointer to "Save to file"
    EzClick
    Move Pointer To ${Y}/generic/save-orange.png
    EzClick
    Move Pointer to "I saved"
    EzCLick
    Move Pointer To ${Y}/generic/replace-recovery-key-button.png
    EzClick
    Match    ${Y}/generic/replace-recovery-key-success.png
    Move Pointer To ${Y}/generic/cross-button.png
    EzCLick
    Move Pointer To ${Y}/generic/cross-button.png
    EzCLick
    # cat recovery-key.txt to validate we saved the key
    Type String    cat /home/ubuntu/recovery-key.txt
    Keys Combo    Return
    Match Text    ${recovery_key}
    RETURN    ${recovery_key}

Test Unlock With Recovery Key
    [Documentation]    Reboot the system and boot using the recovery key
    [Arguments]    ${recovery_key}
    Start Application    reboot
    Wait Until Keyword Succeeds    25 seconds    3 seconds    Match Text    "Please enter the passphrase"
    Keys Combo    Return
    Match Text    "Please enter the recovery"
    Type String    ${recovery_key}
    Keys Combo    Return
    Log In

Authenticate With Polkit
    [Documentation]    Authenticate using a polkit prompt
    Match Text    "Authentication Required"
    Move Pointer To Password
    EzCLick
    Type String    ubuntu
    Move Pointer To Authenticate
    EzCLick
