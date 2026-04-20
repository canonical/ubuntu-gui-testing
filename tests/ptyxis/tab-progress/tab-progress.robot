*** Settings ***
Resource   ${TEST}/../ptyxis.resource
Test Tags  robot:exit-on-failure

*** Variables ***
${TEST}  ${CURDIR}

*** Test Cases ***
Log-in to Gnome
    Log In

Install Ptyxis
    Install Ptyxis

Start Ptyxis
    Open Ptyxis

Open a new tab
    Move Pointer To ${PKG}/generic/new-tab-button.png
    EzClick
    PlatformVideoInput.Match  ${PKG}/generic/tab-close-button.png  5

Set progress to 0%
    Set Progress  0
    PlatformVideoInput.Match  ${PKG}/generic/tab-progress-0.png  5

Set progress to 25%
    Set Progress  25
    PlatformVideoInput.Match  ${PKG}/generic/tab-progress-25.png  5

Set progress to 50%
    Set Progress  50
    PlatformVideoInput.Match  ${PKG}/generic/tab-progress-50.png  5

Set progress to 75%
    Set Progress  75
    PlatformVideoInput.Match  ${PKG}/generic/tab-progress-75.png  5

Set progress to 100%
    Set Progress  100
    PlatformVideoInput.Match  ${PKG}/generic/tab-progress-100.png  5
