*** Settings ***
Documentation       Shared resources for application testing

Resource            kvm.resource
Resource            ${Y}/common/common.resource


*** Variables ***
${Y}                ${CURDIR}
${RECOVERY_KEY}     62624-10584-39666-64718-31970-44050-59829-32069


*** Keywords ***
Open Firmware Updater
    [Documentation]         Open the firmware updater application with specific config
    Open Terminal

    # Write firmware-updater config file to make it pretend updating the fwupd
    # test device affects TPM FDE so that it triggers the recovery key dialog
    PlatformHid.Type String    mkdir -p snap/firmware-updater/current/.config/firmware-updater
    PlatformHid.Keys Combo    Return
    PlatformHid.Type String    echo 'testDeviceAffectsFde
    PlatformHid.Keys Combo    Shift_L    ;
    PlatformHid.Keys Combo    space
    PlatformHid.Type String    true'
    PlatformHid.Keys Combo    Shift_L    .
    PlatformHid.Type String    snap/firmware-updater/current/.config/firmware-updater/firmware-updater.yml
    PlatformHid.Keys Combo    Return
    Builtin.Sleep    5

    Start Application    firmware-updater
    PlatformVideoInput.Match Text    Firmware Updater    60

Update Fake Webcam
    [Documentation]         Make sure fake webcam device is selected
    Move Pointer To ${Y}/generic/fake-webcam-tile.png
    EzClick

    # Update to latest version
    Move Pointer To ${Y}/generic/update-button.png
    EzClick

    # Enter wrong recovery key
    Move Pointer To ${Y}/generic/passphrase-textfield.png
    EzClick
    PlatformHid.Type String    00000-00000-00000-00000-00000-00000-00000-00000
    Move Pointer To ${Y}/generic/confirm-button.png
    EzClick
    Handle PolKit Prompt
    PlatformVideoInput.Match Text    Recovery key does not work

    # Enter correct recovery key
    PlatformHid.Keys Combo    Tab
    PlatformHid.Type String    ${RECOVERY_KEY}
    Move Pointer To ${Y}/generic/confirm-button.png
    EzClick
    PlatformVideoInput.Match    ${Y}/generic/update-done.png    60

Handle PolKit Prompt
    PlatformVideoInput.Match    ${Y}/generic/polkit-prompt.png
    PlatformHid.Type String    ubuntu
    PlatformHid.Keys Combo    Return
