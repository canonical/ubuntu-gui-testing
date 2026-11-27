*** Settings ***
Documentation       Copy an EFI file to ubuntu-seed and add a firmware entry for it.

Resource            ${CURDIR}/../common/guest-shell.resource


*** Variables ***
${APT_GET_COMMAND}      env DEBIAN_FRONTEND=noninteractive apt-get -q -y -o DPkg::Lock::Timeout=300


*** Test Cases ***
Install EFI Binary On Ubuntu Seed
    [Documentation]    Install efibootmgr, copy the EFI file to ubuntu-seed, and add its firmware entry.
    Wait Until Keyword Succeeds    8 min    10 s    Open Guest Shell
    # Package updates can lock the package lists after the guest starts.
    Wait Until Keyword Succeeds    5 min    15 s    Run In Guest    ${APT_GET_COMMAND} update
    Run In Guest    ${APT_GET_COMMAND} install --no-install-recommends efibootmgr
    SSHLibrary.Put File    %{UGT_EFI_FILE}    /tmp/ugt.efi
    ${install_args}    Evaluate
    ...    shlex.join([os.environ[name] for name in ("UGT_SEED_PATH", "UGT_EFI_LABEL", "UGT_EFI_MODE")])
    ...    modules=os,shlex
    ${install_script}    Catenate
    ...    set -eu;
    ...    seed=/run/mnt/ubuntu-seed;
    ...    device=$(readlink -e /dev/disk/by-label/ubuntu-seed);
    ...    mounted=$(findmnt -nro SOURCE --mountpoint "$seed");
    ...    [ "$(readlink -e "$mounted")" = "$device" ] || exit 1;
    ...    mkdir -p "$(dirname "$seed$1")"; cp /tmp/ugt.efi "$seed$1"; sync -f "$seed$1";
    ...    disk=/dev/$(lsblk -dno PKNAME "$device");
    ...    part=$(cat "/sys/class/block/$(basename "$device")/partition");
    ...    efibootmgr --create "$3" --disk "$disk" --part "$part" --loader "$1" --label "$2"
    Run In Guest    sh -c '${install_script}' ugt-efi ${install_args}
