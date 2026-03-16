*** Settings ***
Documentation       GNOME Papers Basic Testing
Resource            kvm.resource
Resource            ${Y}/common/common.resource


*** Variables ***
${Y}    ${CURDIR}


*** Keywords ***
Open Papers
    Start Application                papers
    PlatformVideoInput.Match Text    Document Viewer   60

Open Document
    Move Pointer To ${Y}/generic/papers-open-100%.png
    EzClick
    PlatformVideoInput.Match Text    Pick Files   40
    PlatformHid.Keys Combo           Control_L   L
    PlatformHid.Type String          /usr/share/cups/data/default-testpage.pdf
    PlatformHid.Keys Combo           Return
    PlatformVideoInput.Match Text    default-testpage.pdf
    PlatformHid.Keys Combo           Return
    PlatformVideoInput.Match Text    Printer test page  40

Read Inverted
    PlatformVideoInput.Match Text    Printer test page  40
    PlatformHid.Keys Combo           Control_L   I
    BuiltIn.Sleep                    1
    PlatformVideoInput.Match Text    Printer test page  40
    PlatformHid.Keys Combo           Control_L   I

Read Rotated
    PlatformVideoInput.Match Text    Printer test page  40
    PlatformHid.Keys Combo           Control_L   Right
    BuiltIn.Sleep                    1
    PlatformHid.Keys Combo           Control_L   Right
    BuiltIn.Sleep                    1
    PlatformHid.Keys Combo           Control_L   Right
    BuiltIn.Sleep                    1
    PlatformHid.Keys Combo           Control_L   Right
    BuiltIn.Sleep                    1
    PlatformVideoInput.Match Text    Printer test page  40

Toggle Sidebar
    Move Pointer To ${Y}/generic/sidebar-on.png
    EzClick
    BuiltIn.Sleep                    1
    Move Pointer To ${Y}/generic/sidebar-off.png
    EzClick
