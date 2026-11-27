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
