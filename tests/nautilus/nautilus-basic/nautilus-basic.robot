*** Settings ***
Documentation       Test nautilus basic functionality
Resource        ${Z}/../nautilus.resource

Test Tags       robot:exit-on-failure    # robocop: off=tag-with-reserved-word


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
Log In
    [Documentation]         Log in to desktop environment
    Log In

Open Nautilus
    [Documentation]         Open the Nautilus app
    Open Nautilus

New Folder
    [Documentation]         Create a new folder
    Open Background Context Menu
    Click On    New Folder...
    Match Text Exactly    Folder Name
    PlatformHid.Type String    myfolder
    Match Text Exactly    Create
    PlatformHid.Keys Combo    Return
    Match Home
    Match Text Exactly    myfolder

Enter Folder
    [Documentation]         Enter the newly created folder
    Move Pointer To Text Exactly    myfolder
    Double Click
    Match Text Exactly    Folder is Empty
    Match Text Exactly    myfolder

Open in Terminal
    [Documentation]         Open the current directory in terminal, create a file, and verify its location
    Open Background Context Menu
    Click On    Open in Terminal
    PlatformVideoInput.Match Text    ubuntu@ubuntu    # wait for terminal window to be open
    PlatformVideoInput.Match Text    ~/myfolder$    # match bash prompt
    ${redirect}    Create List    Shift_L    >
    PlatformHid.Type String    echo "sample text"
    PlatformHid.Keys Combo    ${redirect}
    PlatformHid.Type String    foo.txt
    PlatformHid.Keys Combo    Return
    Close Terminal
    Match Text Exactly    foo.txt

Copy File
    [Documentation]         Copy and paste the file
    Click On    foo.txt
    PlatformHid.Keys Combo    Ctrl    C
    Click On    Home
    Match Home
    PlatformHid.Keys Combo    Ctrl    V
    Match Text Exactly    foo.txt

Open Text File
    [Documentation]         Open the file with text editor
    Move Pointer To Text Exactly    foo.txt
    Double Click
    Match Text Exactly    Open
    Match Text Exactly    sample text
    Match Text Exactly    foo.txt
    PlatformHid.Keys Combo    Alt    F4
    Match Home

Recent Files
    [Documentation]         Inspect recently opened files
    Click On    Recent
    Match Text Exactly    foo.txt
    Open Context Menu At    foo.txt
    Match Text Exactly    Remove From Recent
    PlatformHid.Keys Combo    Esc

Move to Trash
    [Documentation]         Move file to trash
    Click On    Home
    Match Home
    Open Context Menu At    foo.txt
    Click On    Move to Trash
    Click On    Trash
    Match Text Exactly    foo.txt

Restore from Trash
    [Documentation]         Restore file from trash
    Open Context Menu At    foo.txt
    Click On    Restore From Trash
    Match Text Exactly    Trash is Empty
    Click On    Home
    Match Home
    Match Text Exactly    foo.txt

Empty trash
    [Documentation]         Delete files and empty the trash bin
    Click On    foo.txt
    PlatformHid.Keys Combo    Del
    Click On    myfolder
    PlatformHid.Keys Combo    Del
    Click On    Trash
    Match Text Exactly    foo.txt
    Match Text Exactly    myfolder
    Click On    Empty Trash...
    Match Text Exactly    Cancel
    PlatformHid.Keys Combo    Return
    BuiltIn.Sleep    5    # Grace period for popup to close
    Match Text Exactly    Trash is Empty

Remote Directory
    [Documentation]         Open a remote directory through sftp
    Open Terminal
    Run Command In Terminal    rm -f .ssh/known_hosts
    Close Terminal
    Click On    Network
    Match Text Exactly    No Known Connections
    Click On    Server address
    ${colon}    Create List    Shift    ;
    PlatformHid.Type String    sftp
    PlatformHid.Keys Combo    ${colon}
    PlatformHid.Type String    //people.ubuntu.com
    PlatformHid.Keys Combo    Return
    BuiltIn.Sleep    15
    Match Text Exactly    Identity Verification Failed
    Click On    Log In Anyway
    Match Text Exactly    Unable to access location
    Click On    Close
    Match Text Exactly    No Known Connections

Open Again
    [Documentation]         Close and open Nautilus again
    Close Nautilus
    Open Nautilus
