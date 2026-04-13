*** Settings ***
Documentation       Shut down the raspberry pi

Resource            kvm.resource

Test Tags
...    stop-on-failure
...    yarf:category_id:com.canonical.yarf::basic
...    yarf:test_group_id:com.canonical.yarf::integration
...    yarf:certification_status:blocker


*** Test Cases ***
Assert test init
    [Documentation]    Ensure we're ready to begin the test
    Match    ${CURDIR}/../rpi-common/screens/big_circle_of_friends.jpg

Click top right toast
    [Documentation]    Click the top right shutdown/reboot widget
    Click LEFT Button on ${CURDIR}/../rpi-common/templates/pwr_toast.jpg
    Match    ${CURDIR}/../rpi-common/screens/settings_dock.jpg

Click power button
    [Documentation]    Click power menu
    Click LEFT Button on ${CURDIR}/../rpi-common/templates/pwr_btn.jpg
    Match    ${CURDIR}/../rpi-common/screens/pwr_opts.jpg

Click Power off Option
    [Documentation]    Click widget to power off
    Click LEFT Button on ${CURDIR}/snapshots/templates/pwr_off_txt.jpg
    Match    ${CURDIR}/snapshots/screens/screen_01.jpg

Click Power off Button
    [Documentation]    Click button to confirm power off
    Click LEFT Button on ${CURDIR}/snapshots/templates/pwr_off_btn.jpg
    Match    ${CURDIR}/../rpi-common/screens/no_signal.jpg    20
