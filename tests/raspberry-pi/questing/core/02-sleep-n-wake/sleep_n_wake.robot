*** Settings ***
Documentation       Sleep from desktop environment and then wake

Resource            kvm.resource

Test Tags
...    robot:stop-on-failure
...    yarf:category_id:com.canonical.yarf::basic
...    yarf:test_group_id:com.canonical.yarf::integration
...    yarf:certification_status:blocker


*** Test Cases ***
Assert Test init
    [Documentation]    Ensure we're ready to begin the test
    Match    ${CURDIR}/../rpi-common/screens/big_circle_of_friends.jpg

Sleep
    [Documentation]    Sleep from the desktop environment
    Keys Combo    Meta_L    l
    Match    ${CURDIR}/../rpi-common/screens/no_signal.jpg

Login Prompt
    [Documentation]    Ensure we get back to the login prompt
    Move Pointer To (100, 100)
    Sleep    1
    Click LEFT Button
    Match    ${CURDIR}/snapshots/screens/screen_01.jpg

Desktop
    [Documentation]    Enter desktop environment
    Type String    redactedpwd
    Sleep    1
    Keys Combo    Return
    Match    ${CURDIR}/../rpi-common/screens/big_circle_of_friends.jpg    15
