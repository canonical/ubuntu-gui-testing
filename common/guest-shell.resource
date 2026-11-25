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
