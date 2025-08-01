*** Settings ***
Documentation       Reboot

Resource            kvm.resource

Test Tags
...    robot:stop-on-failure
...    yarf:category_id:com.canonical.yarf::basic
...    yarf:test_group_id:com.canonical.yarf::integration
...    yarf:certification_status:blocker


*** Test Cases ***
Assert test init
    [Documentation]    Ensure we're ready to start the test
    Match    ${CURDIR}/../rpi-common/screens/big_circle_of_friends.jpg

Click top right toast
    [Documentation]    Click the top right shutdown/reboot widget
    Click LEFT Button on ${CURDIR}/../rpi-common/templates/pwr_toast.jpg
    Match    ${CURDIR}/../rpi-common/screens/settings_dock.jpg

Click power button
    [Documentation]    Click the power button
    Click LEFT Button on ${CURDIR}/../rpi-common/templates/pwr_btn.jpg
    Match    ${CURDIR}/../rpi-common/screens/pwr_opts.jpg

Click Reboot Option
    [Documentation]    Open reboot option
    Click LEFT Button on ${CURDIR}/snapshots/templates/restart_txt.jpg
    Match    ${CURDIR}/snapshots/screens/screen_01.jpg

Click Reboot Button
    [Documentation]    Click the reboot option and wait for a reboot
    Click LEFT Button on ${CURDIR}/snapshots/templates/restart_btn.jpg
    Match    ${CURDIR}/snapshots/screens/screen_02.jpg    100

Login
    [Documentation]    Log in to desktop environment
    Keys Combo    Return
    Sleep    1
    Type String    redactedpwd
    Sleep    1
    Keys Combo    Return
    Match    ${CURDIR}/../rpi-common/screens/big_circle_of_friends.jpg    20
