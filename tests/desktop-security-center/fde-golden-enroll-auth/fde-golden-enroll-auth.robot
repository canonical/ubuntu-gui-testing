*** Settings ***
Documentation       Enroll a PIN or passphrase through snapd for the TPM-FDE
...                 golden derivation in
...                 runner/ubuntu_gui_testing_runner/fde_golden.py.

Resource            ${CURDIR}/../common/guest-shell.resource


*** Test Cases ***
Enroll Authentication On Platform Keyslots
    [Documentation]    Send the replace-platform-key request in
    ...    %{UGT_AUTH_BODY_FILE} to snapd and wait until the platform keyslots
    ...    use %{UGT_AUTH_MODE}. The body holds the secret, so it travels as a
    ...    file and never appears in the log.
    Wait Until Keyword Succeeds    8 min    10 s    Open Guest Shell
    SSHLibrary.Put File    ${CURDIR}/enroll_auth.py    /tmp/enroll_auth.py
    SSHLibrary.Put File    %{UGT_AUTH_BODY_FILE}    /tmp/ugt-auth.json    mode=0600
    ${mode}    Run In Guest    python3 /tmp/enroll_auth.py /tmp/ugt-auth.json
    ...    timeout=11 min
    Should Be Equal    ${mode}    %{UGT_AUTH_MODE}
