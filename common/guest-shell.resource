*** Settings ***
Documentation       Run commands as root in the guest over SSH on its vsock CID.

Library             SSHLibrary


*** Variables ***
${GUEST_USERNAME}       ubuntu
${GUEST_PASSWORD}       ubuntu


*** Keywords ***
Open Guest Shell
    [Documentation]    Log in to the guest over vsock.
    # Full names: SSHLibrary.Login clashes with common.resource's Log In.
    # Close first: callers retry this with Wait Until Keyword Succeeds while the guest boots.
    SSHLibrary.Close All Connections
    SSHLibrary.Open Connection    localhost    timeout=60s
    SSHLibrary.Login    ${GUEST_USERNAME}    ${GUEST_PASSWORD}
    ...    proxy_cmd=/usr/bin/socat - VSOCK-CONNECT:${CID}:22

Run In Guest
    [Documentation]    Run a command as root; fail on non-zero exit, return stdout.
    ...    Only the first pipeline stage runs as root, so callers must wrap
    ...    pipes, redirects, and compound commands in sh -c.
    [Arguments]    ${command}    ${timeout}=600s
    # Not sudo=True: SSHLibrary 3.8.0 sends two blank lines before the password (robotframework/SSHLibrary#412).
    ${stdout}    ${stderr}    ${rc}    SSHLibrary.Execute Command
    ...    echo '${GUEST_PASSWORD}' | sudo -k --stdin --prompt '' ${command}
    ...    return_stderr=True    return_rc=True    timeout=${timeout}
    Should Be Equal As Integers    ${rc}    0    msg=${command} failed: ${stderr}
    RETURN    ${stdout}

Arm Guest Power Cut When File Is Written
    [Documentation]    Arm a guest reset for when the file is written; return the boot ID from before the reset.
    ...    The reset skips saving disk data. The guest checks every 20 ms for 10 minutes, so the reset comes a little late.
    [Arguments]    ${path}
    ${quoted_path}    Evaluate    shlex.quote($path)    modules=shlex
    ${stat_command}    Set Variable    stat -c "%i %y %z" -- "$0" 2>/dev/null
    ${watcher_script}    Catenate
    ...    until [ -f "$0" ] && current=$(${stat_command}) && [ "$current" != "$1" ]; do sleep 0.02; done;
    ...    echo b > /proc/sysrq-trigger
    ${arm_script}    Catenate
    ...    s=$(${stat_command});
    ...    cat /proc/sys/kernel/random/boot_id || exit 1;
    ...    setsid timeout 10m sh -c "$1" "$0" "$s" >/dev/null 2>&1 </dev/null &
    ${boot_id}    Run In Guest    sh -c '${arm_script}' ${quoted_path} '${watcher_script}'
    RETURN    ${boot_id}
