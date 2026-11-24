*** Settings ***
Documentation       Run commands as root in the guest over SSH on its vsock CID.
...                 Needs socat on the host and sshd with password login in the guest.
...                 SSHLibrary keywords are called by their full names because
...                 SSHLibrary's Login and common.resource's Log In normalize to
...                 the same keyword name.

Library             SSHLibrary


*** Variables ***
${GUEST_USERNAME}       ubuntu
${GUEST_PASSWORD}       ubuntu


*** Keywords ***
Open Guest Shell
    [Documentation]    Log in to the guest through the CID the runner passes,
    ...    replacing any open connection, so it can be retried with
    ...    Wait Until Keyword Succeeds while the guest boots.
    SSHLibrary.Close All Connections
    SSHLibrary.Open Connection    localhost    timeout=60s
    SSHLibrary.Login    ${GUEST_USERNAME}    ${GUEST_PASSWORD}
    ...    proxy_cmd=/usr/bin/socat - VSOCK-CONNECT:${CID}:22

Run In Guest
    [Documentation]    Run the command as root, fail on a non-zero exit status,
    ...    and return its stdout. sudo covers only the first command, so wrap
    ...    pipelines and redirections in sh -c. The command must not read
    ...    stdin, because SSHLibrary feeds the sudo password there.
    [Arguments]    ${command}    ${timeout}=60s
    ${stdout}    ${stderr}    ${rc}    SSHLibrary.Execute Command    ${command}
    ...    return_stderr=True    return_rc=True    timeout=${timeout}
    ...    sudo=True    sudo_password=${GUEST_PASSWORD}
    Should Be Equal As Integers    ${rc}    0    msg=${command} failed: ${stderr}
    RETURN    ${stdout}

Cut Guest Power When File Is Written
    [Documentation]    Arm a power cut: reset the guest as soon as the file at the
    ...    path is written (created, replaced or modified), at once and without
    ...    syncing its disks. A watcher in the guest compares the file's inode
    ...    and times with those at arming every 20 ms and gives up after 10
    ...    minutes, so arm it just before the action that writes the file.
    ...    Returns the boot ID at arming: after reconnecting with Open Guest
    ...    Shell, check that /proc/sys/kernel/random/boot_id changed, which
    ...    proves the guest was reset. The domain keeps running, so the VNC
    ...    display and the CID stay the same.
    [Arguments]    ${path}
    ${stat}    Set Variable    stat -c "%i %y %z" "$0"
    ${watcher}    Catenate
    ...    until [ -f "$0" ] && [ "$(${stat})" != "$1" ]; do sleep 0.02; done;
    ...    echo b > /proc/sysrq-trigger
    ${arm}    Catenate
    ...    s=$(${stat} 2>/dev/null);
    ...    setsid timeout 10m sh -c "$1" "$0" "$s" >/dev/null 2>&1 </dev/null &
    ...    cat /proc/sys/kernel/random/boot_id
    ${boot_id}    Run In Guest    sh -c '${arm}' '${path}' '${watcher}'
    RETURN    ${boot_id}
