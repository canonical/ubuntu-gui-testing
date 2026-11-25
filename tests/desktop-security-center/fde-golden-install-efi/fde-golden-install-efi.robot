*** Settings ***
Documentation       Copy an EFI binary onto ubuntu-seed for the TPM-FDE golden
...                 derivation in runner/ubuntu_gui_testing_runner/fde_golden.py,
...                 and record where ubuntu-seed sits on the disk.

Library             OperatingSystem
Resource            ${CURDIR}/../common/guest-shell.resource


*** Test Cases ***
Install EFI Binary On Ubuntu Seed
    [Documentation]    Copy %{UGT_EFI_FILE} to %{UGT_SEED_PATH} on ubuntu-seed
    ...    and write "NUMBER START SIZE PARTUUID" of ubuntu-seed to
    ...    seed-partition.txt in the output directory.
    Wait Until Keyword Succeeds    8 min    10 s    Open Guest Shell
    SSHLibrary.Put File    %{UGT_EFI_FILE}    /tmp/ugt.efi
    ${target}    Set Variable    /run/mnt/ubuntu-seed%{UGT_SEED_PATH}
    Run In Guest    sh -c 'mkdir -p "$(dirname "$0")" && cp /tmp/ugt.efi "$0" && sync' '${target}'
    ${partition}    Run In Guest
    ...    sh -c 'p=$(basename "$(readlink -f /dev/disk/by-label/ubuntu-seed)"); echo "$(cat /sys/class/block/$p/partition) $(cat /sys/class/block/$p/start) $(cat /sys/class/block/$p/size) $(blkid -s PARTUUID -o value /dev/$p)"'
    Create File    ${OUTPUT DIR}/seed-partition.txt    ${partition}
