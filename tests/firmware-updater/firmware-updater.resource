*** Settings ***
Documentation       Shared resources for application testing

Resource            kvm.resource
Resource            ${Y}/common/common.resource


*** Variables ***
${Y}                ${CURDIR}
${RECOVERY_KEY}     62624-10584-39666-64718-31970-44050-59829-32069


*** Keywords ***
Open Firmware Updater
    Start Application    firmware-updater
    PlatformVideoInput.Match Text    Firmware Updater    60

Refresh Firmware Metadata
    Open Terminal
    Run Sudo Command In Terminal    sudo fwupdmgr refresh --force
    Close Terminal

Setup Fake Webcam
    Install Debian Package    fwupd-tests
    Open Terminal
    Run Sudo Command In Terminal    sudo echo foo
    PlatformHid.Type String    sudo snap connect firmware-updater
    PlatformHid.Keys Combo    Shift_L    ;
    PlatformHid.Type String    hostfs-usr-share-installed-tests-fwupd
    PlatformHid.Keys Combo    Return
    Close Terminal

Setup Mock TPM FDE Update
    # Write firmware-updater config file to make it pretend updating the fwupd
    # test device affects TPM FDE so that it triggers the recovery key dialog
    Open Terminal
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
    Close Terminal

Setup Mock Bitlocker Partition
    Open Terminal
    Run Command In Terminal
    ...    wget gitlab.com/cryptsetup/cryptsetup/-/raw/2cf4c9a360e6c9497898ad89a1cb3c81f77ce458/tests/bitlk-images.tar.xz
    Run Command In Terminal    tar xvf bitlk-images.tar.xz bitlk-images/bitlk-aes-xts-128.img
    Run Sudo Command In Terminal    sudo losetup -f --show bitlk-images/bitlk-aes-xts-128.img
    Run Command In Terminal    sudo systemctl restart fwupd.service
    Close Terminal

Update ${device}
    PlatformVideoInput.Match Text    ${device}    60
    Move Pointer To ${device}
    EzClick
    Move Pointer To ${Y}/generic/update-to-latest-button.png
    EzClick

Handle Reboot Prompt
    PlatformVideoInput.Match    ${Y}/generic/reboot-now-button.png    60
    Move Pointer To ${Y}/generic/reboot-now-button.png
    EzClick

Handle Recovery Key Prompt
    Move Pointer To ${Y}/generic/passphrase-textfield.png
    EzClick
    PlatformHid.Type String    ${RECOVERY_KEY}

Handle Recovery Key Checkbox
    Move Pointer To I have recovery keys for all my encrypted drives
    EzClick

Confirm Update
    Move Pointer To ${Y}/generic/update-button.png
    EzClick

Enter Recovery Key On Reboot
    PlatformVideoInput.Match Text    Please enter the recovery key    120
    PlatformHid.Type String    ${RECOVERY_KEY}
    PlatformHid.Keys Combo    Return

Check For Successful Fake Webcam Update
    PlatformVideoInput.Match    ${Y}/generic/fake-webcam-update-done.png    60

Check For Successful UEFI CA Update
    Open Terminal
    PlatformHid.Type String    fwupdmgr get-updates
    PlatformHid.Keys Combo    Return
    PlatformVideoInput.Match    ${Y}/generic/uefi-ca-update-done.png    60

Handle PolKit Prompt
    PlatformVideoInput.Match    ${Y}/generic/polkit-prompt.png
    PlatformHid.Type String    ubuntu
    PlatformHid.Keys Combo    Return
