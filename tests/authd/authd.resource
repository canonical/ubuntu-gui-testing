*** Settings ***
Documentation       authd test resources

Resource            kvm.resource
Resource            common/common.resource
Library             common/StringUtils.py    AS    StringUtils


*** Keywords ***
Open GNOME Terminal
    Start Application    /usr/bin/gnome-terminal
    PlatformVideoInput.Match Text    ubuntu@ubuntu:~$

Log in with Entra ID
    # TODO: Ugly workaround for the issue that `PlatformHid.Type String` doesnt
    #       correctly enter special characters which require a Shift modifier
    PlatformHid.Type String    sudo login test
    PlatformHid.Keys Combo    Shift_L    @
    PlatformHid.Type String    uaadtest.onmicrosoft.com
    PlatformHid.Keys Combo    Return

    # Wait for the password prompt
    PlatformVideoInput.Match Text    [sudo] password for ubuntu

    # Enter the sudo password
    PlatformHid.Type String    ubuntu
    PlatformHid.Keys Combo    Return

    # Check that the provider selection contains the Entra ID provider
    PlatformVideoInput.Match Text    Select your provider
    PlatformVideoInput.Match Text    2. Microsoft Entra ID

    # Select the Entra ID provider
    PlatformHid.Type String    2

    # Wait until the verification URL and login code are displayed
    PlatformVideoInput.Match Text    https://microsoft.com/devicelogin

    # Read the user code
    ${text} =    PlatformVideoInput.Read Text
    ${user_code} =    StringUtils.FirstMatch    https://microsoft.com/devicelogin\n([A-Z0-9]+)    ${text}
    Log To Console    XXX: user code: ${user_code}

    # Launch Firefox
    Start Application    /usr/bin/firefox
    ${timeout_sec} =    Set Variable    60  # Launching Firefox can take a while
    PlatformVideoInput.Match Text    Welcome to Firefox    ${timeout_sec}

    # Open a new tab
    PlatformHid.Keys Combo    Control_L    t
    PlatformVideoInput.Match Text    New Tab

    # Open the verification URL
    PlatformHid.Type String    https://microsoft.com/devicelogin
    PlatformHid.Keys Combo    Return

    # Wait for the page to load
    ${timeout_sec} =    Set Variable    60  # The page is slow
    PlatformVideoInput.Match Text    Enter code to allow access    ${timeout_sec}

    # Enter the code
    PlatformHid.Type String    ${user_code}
    PlatformHid.Keys Combo    Return

    # Wait for the Sign in page to load
    ${timeout_sec} =    Set Variable    60  # The page is slow
    PlatformVideoInput.Match Text    Sign in

    # Enter the username
    # TODO: Ugly workaround for the issue that `PlatformHid.Type String` doesnt
    #       correctly enter special characters which require a Shift modifier
    PlatformHid.Type String    test
    PlatformHid.Keys Combo    Shift_L    @
    PlatformHid.Type String    uaadtest.onmicrosoft.com
    PlatformHid.Keys Combo    Return

    # Wait for the password prompt
    PlatformVideoInput.Match Text    Password

    # Enter the password
    PlatformHid.Type String    Password123!
