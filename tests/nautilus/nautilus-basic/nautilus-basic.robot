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
    Match Text    Folder Name
    Type String    myfolder
    Match Text    Create
    Keys Combo    Return
    Match Home
    Match Text    myfolder

Enter Folder
    [Documentation]         Enter the newly created folder
    Move Pointer To myfolder
    Double Click
    Match Text    Folder is Empty
    Match Text    myfolder

Open in Terminal
    [Documentation]         Open the current directory in terminal, create a file, and verify its location
    Open Background Context Menu
    Click On    Open in Terminal
    Match Text    ubuntu@ubuntu    # wait for terminal window to be open
    Match Text    ~/myfolder$    # match bash prompt
    ${redirect}    Create List    Shift_L    >
    Type String    echo "sample text"
    Keys Combo    ${redirect}
    Type String    foo.txt
    Keys Combo    Return
    Close Terminal
    Match Text    foo.txt

Copy File
    [Documentation]         Copy and paste the file
    Click On    foo.txt
    Keys Combo    Ctrl    c
    Click On    Home
    Match Home
    Keys Combo    Ctrl    v
    Match Text    foo.txt

Open Text File
    [Documentation]         Open the file with text editor
    Move Pointer To foo.txt
    Double Click
    Match Text    Open
    Match Text    sample text
    Match Text    foo.txt
    Keys Combo    Alt    F4
    Match Home

Recent Files
    [Documentation]         Inspect recently opened files
    Click On    Recent
    Match Text    foo.txt
    Open Context Menu At    foo.txt
    Match Text    Remove From Recent
    Keys Combo    Esc

Move to Trash
    [Documentation]         Move file to trash
    Click On    Home
    Match Home
    Open Context Menu At    foo.txt
    Click On    Move to Trash
    Click On    Trash
    Match Text    foo.txt

Restore from Trash
    [Documentation]         Restore file from trash
    Open Context Menu At    foo.txt
    Click On    Restore From Trash
    Match Text    Trash is Empty
    Click On    Home
    Match Home
    Match Text    foo.txt

Empty trash
    [Documentation]         Delete files and empty the trash bin
    Click On    foo.txt
    Keys Combo    Del
    Click On    myfolder
    Keys Combo    Del
    Click On    Trash
    Match Text    foo.txt
    Match Text    myfolder
    Click On    Empty Trash...
    Match Text    Cancel
    Keys Combo    Return
    BuiltIn.Sleep    5    # Grace period for popup to close
    Match Text    Trash is Empty

Remote Directory
    [Documentation]         Open a remote directory through sftp
    Open Terminal
    Run Command In Terminal    rm -f .ssh/known_hosts
    Close Terminal
    Click On    Network
    Match Text    No Known Connections
    Click On    Server address
    ${colon}    Create List    Shift    ;
    Type String    sftp
    Keys Combo    ${colon}
    Type String    //people.ubuntu.com
    Keys Combo    Return
    BuiltIn.Sleep    15
    Match Text    Identity Verification Failed
    Click On    Log In Anyway
    Match Text    Unable to access location
    Click On    Close
    Match Text    No Known Connections

Open Again
    [Documentation]         Close and open Nautilus again
    Close Nautilus
    Open Nautilus
