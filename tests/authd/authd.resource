*** Settings ***
Documentation       authd test resources

Resource            kvm.resource
Resource            common/common.resource
Library             common/StringUtils.py    AS    StringUtils

*** Variables ***
${local_password}     qwer1234

*** Keywords ***
Open GNOME Terminal
    Start Application    /usr/bin/gnome-terminal
    PlatformVideoInput.Match Text    ubuntu@ubuntu:~$

Log in with Entra ID via login command
    # TODO: Ugly workaround for the issue that `PlatformHid.Type String` doesnt
    #       correctly enter special characters which require a Shift modifier
    PlatformHid.Type String    sudo login test
    PlatformHid.Keys Combo    Shift_L    @
    PlatformHid.Type String    ubudev1.onmicrosoft.com
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

    # Read the user code. Use RapidOCR instead of Tesseract for better accuracy.
    PlatformVideoInput.SetOCRMethod    rapidocr
    ${text} =    PlatformVideoInput.Read Text
    ${user_code} =    StringUtils.FirstMatch    https://microsoft.com/devicelogin\n([A-Z0-9]+)    ${text}
    Log To Console    XXX: user code: ${user_code}

    # Reset the OCR method to Tesseract
    PlatformVideoInput.SetOCRMethod    tesseract

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
    PlatformVideoInput.Match Text    You're signing in to

    # Enter the username
    # TODO: Ugly workaround for the issue that `PlatformHid.Type String` doesnt
    #       correctly enter special characters which require a Shift modifier
    PlatformHid.Type String    test
    PlatformHid.Keys Combo    Shift_L    @
    PlatformHid.Type String    ubudev1.onmicrosoft.com
    PlatformHid.Keys Combo    Return

    # Wait for the password prompt
    PlatformVideoInput.Match Text    Enter password

    # Enter the password
    PlatformHid.Type String    %{TEST_PASSWORD}
    PlatformHid.Keys Combo    Return

    # Wait for the login confirmation page to load
    ${timeout_sec} =    Set Variable    10
    PlatformVideoInput.Match Text    Are you trying to sign in to

    # Activate the "Continue" button
    PlatformHid.Keys Combo    Return
#    Click LEFT Button On ${CURDIR}/continue-button.png

    # Wait for the sign in to complete
    ${timeout_sec} =    Set Variable    10
    PlatformVideoInput.Match Text    You have signed in to the

    # Close Firefox
    PlatformHid.Keys Combo    Alt_L    F4

    # The terminal should now be visible and focused again. 
    # Check that we're prompted to set a local password.
    # We've seen this being parsed incorrectly by Tesseract, so we use RapidOCR instead.
    PlatformVideoInput.SetOCRMethod    rapidocr
    PlatformVideoInput.Match Text    New password:
    # Reset the OCR method to Tesseract
    PlatformVideoInput.SetOCRMethod    tesseract

    # Set a local password
    PlatformHid.Type String    ${local_password}
    PlatformHid.Keys Combo    Return

    # Confirm the local password
    PlatformVideoInput.Match Text    Confirm password:
    PlatformHid.Type String    ${local_password}
    PlatformHid.Keys Combo    Return

    # Wait for the login to complete
    PlatformVideoInput.Match Text    test@ubudev1.onmicrosoft.com@ubuntu

Add user to sudo group
    # Open GNOME Terminal
    Open GNOME Terminal

    # TODO: Ugly workaround for the issue that `PlatformHid.Type String` doesnt
    #       correctly enter special characters which require a Shift modifier
    PlatformHid.Type String    sudo usermod -aG sudo test
    PlatformHid.Keys Combo    Shift_L    @
    PlatformHid.Type String    ubudev1.onmicrosoft.com
    # Print [COMMAND DONE] when the command is done
    PlatformHid.Keys Combo    space
    PlatformHid.Keys Combo    Shift_L    &
    PlatformHid.Keys Combo    Shift_L    &
    PlatformHid.Keys Combo    space
    PlatformHid.Type String   echo W0NPTU1BTkQgRE9ORV0K
    PlatformHid.Keys Combo    Shift_L    |
    PlatformHid.Type String   base64 -d
    PlatformHid.Keys Combo    Return

    # Wait for the password prompt
    PlatformVideoInput.Match Text    [sudo] password for ubuntu

    # Enter the sudo password
    PlatformHid.Type String    ubuntu
    PlatformHid.Keys Combo    Return

    # Wait for the command to finish
    PlatformVideoInput.Match Text    [COMMAND DONE]

Log in with local password via GDM
    # Click on the "Not Listed?" button
    Click LEFT Button On ${CURDIR}/not-listed.png

    # Enter the username
    PlatformVideoInput.SetOCRMethod    rapidocr
    PlatformVideoInput.Match Text    Username
    # TODO: Ugly workaround for the issue that `PlatformHid.Type String` doesnt
    #       correctly enter special characters which require a Shift modifier
    PlatformHid.Type String    test
    PlatformHid.Keys Combo    Shift_L    @
    PlatformHid.Type String    ubudev1.onmicrosoft.com
    PlatformHid.Keys Combo    Return

    # Enter the password
    PlatformVideoInput.Match Text    Password
    PlatformHid.Type String   ${local_password}
    PlatformHid.Keys Combo    Return

    # Wait for the desktop to load
    PlatformVideoInput.Match    ${X}/circle-of-friends.png    60

Run a command with pkexec
    # Open GNOME Terminal
    Start Application    /usr/bin/gnome-terminal
    PlatformVideoInput.Match Text    test@ubudev1.onmicrosoft.com@ubuntu

    # Run the command with pkexec
    PlatformHid.Type String    pkexec cat /etc/shadow
    # Print [COMMAND DONE] when the command is done
    PlatformHid.Keys Combo    space
    PlatformHid.Keys Combo    Shift_L    &
    PlatformHid.Keys Combo    Shift_L    &
    PlatformHid.Keys Combo    space
    PlatformHid.Type String   echo W0NPTU1BTkQgRE9ORV0K
    PlatformHid.Keys Combo    Shift_L    |
    PlatformHid.Type String   base64 -d
    PlatformHid.Keys Combo    Return
    
    # Authenticate to polkit
    PlatformVideoInput.Match Text    Authentication Required
    PlatformHid.Type String    ${local_password}
    PlatformHid.Keys Combo    Return

    # Wait for the command to finish
    PlatformVideoInput.Match Text    [COMMAND DONE]

    # Close the terminal
    Close Terminal

Closes "Welcome to Ubuntu" app
    PlatformVideoInput.Match Text    Welcome to Ubuntu
    PlatformHid.Keys Combo    Alt_L    F4

Log out
    Run Command    gnome-session-quit --logout --no-prompt
