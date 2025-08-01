*** Settings ***
Documentation       Do raspi desktop initial setup

Resource            kvm.resource

Test Tags
...    robot:stop-on-failure
...    yarf:category_id:com.canonical.yarf::basic
...    yarf:test_group_id:com.canonical.yarf::integration
...    yarf:certification_status:blocker
# Comments:
# - Initial wait is 240 seconds for boot.
# - Sleep 1 second after each input.
# - Sleep 3 seconds before Match except for exceptions.
# - Exceptions:
#    + Password Screen
#    + Setup Complete
#    + Finish Screen
# - Move Pointer to (100, 100) before Matching so it doesn't
#    interfere with button template Matching.
# - Double tabs in Name Select and Password Select to go over
#    dropdown and "show password" button


*** Test Cases ***
Assert Test init
    [Documentation]    Ensure we're ready to begin the test
    Match    ${CURDIR}/snapshots/screens/screen_01.jpg    240

Language Select
    [Documentation]    Select English language
    Click LEFT Button on ${CURDIR}/snapshots/templates/lang_eng.jpg
    Match    ${CURDIR}/snapshots/templates/next_btn.jpg
    Click LEFT Button on ${CURDIR}/snapshots/templates/next_btn.jpg
    Move Pointer To (100, 100)
    Match    ${CURDIR}/snapshots/screens/screen_02.jpg

Keyboard Select
    [Documentation]    Go through keyboard select
    Click LEFT Button on ${CURDIR}/snapshots/templates/next_btn.jpg
    Move Pointer To (100, 100)
    Match    ${CURDIR}/snapshots/screens/screen_03.jpg

WiFi Screen
    [Documentation]    Go through wifi selection
    Click LEFT Button on ${CURDIR}/snapshots/templates/skip_btn.jpg
    Move Pointer To (100, 100)
    Match    ${CURDIR}/snapshots/screens/screen_04.jpg

Timezone Select
    [Documentation]    Go through timezone selection
    Click LEFT Button on ${CURDIR}/snapshots/templates/tz_ind.jpg
    Match    ${CURDIR}/snapshots/templates/next_btn.jpg
    Click LEFT Button on ${CURDIR}/snapshots/templates/next_btn.jpg
    Move Pointer To (100, 100)
    Match    ${CURDIR}/snapshots/screens/screen_05.jpg

Name Select
    [Documentation]    Go through user creation
    Type String    testuser
    Sleep    1
    Keys Combo    Tab
    Sleep    1
    Type String    raikou
    Sleep    1
    Keys Combo    Tab
    Sleep    1
    Keys Combo    Tab
    Sleep    1
    Type String    pi
    Match    ${CURDIR}/snapshots/templates/next_btn.jpg
    Click LEFT Button on ${CURDIR}/snapshots/templates/next_btn.jpg
    Move Pointer To (100, 100)
    Match    ${CURDIR}/snapshots/screens/screen_06.jpg

Password Select
    [Documentation]    Enter a password
    Type String    redactedpwd
    Sleep    1
    Keys Combo    Tab
    Sleep    1
    Keys Combo    Tab
    Type String    redactedpwd
    Match    ${CURDIR}/snapshots/templates/next_btn.jpg
    Click LEFT Button on ${CURDIR}/snapshots/templates/next_btn.jpg
    Move Pointer To (100, 100)
    Match    ${CURDIR}/snapshots/screens/screen_07.jpg    20

Langpack Download
    [Documentation]    Download langpacks
    Click LEFT Button on ${CURDIR}/snapshots/templates/cancel_btn.jpg
    Move Pointer To (100, 100)
    Match    ${CURDIR}/snapshots/screens/screen_08.jpg

Setup Complete
    [Documentation]    Download langpacks
    Click LEFT Button on ${CURDIR}/snapshots/templates/start_btn.jpg
    Move Pointer To (100, 100)
    Match    ${CURDIR}/snapshots/screens/screen_09.jpg    45

Welcome Screen
    [Documentation]    Go through the welcome screen
    Click LEFT Button on ${CURDIR}/snapshots/templates/next_btn.jpg
    Move Pointer To (100, 100)
    Match    ${CURDIR}/snapshots/screens/screen_10.jpg

Consent Screen
    [Documentation]    Go through the consent screen
    Click LEFT Button on ${CURDIR}/snapshots/templates/next_btn.jpg
    Move Pointer To (100, 100)
    Match    ${CURDIR}/snapshots/screens/screen_11.jpg

Finish Screen
    [Documentation]    Finish setup
    Click LEFT Button on ${CURDIR}/snapshots/templates/finish_btn.jpg
    Match    ${CURDIR}/../rpi-common/screens/big_circle_of_friends.jpg    15
