*** Settings ***
Documentation       Ensure we can connect to a bluetooth device

Resource            kvm.resource

Test Tags
...    stop-on-failure
...    yarf:category_id:com.canonical.yarf::basic
...    yarf:test_group_id:com.canonical.yarf::integration
...    yarf:certification_status:blocker
# Comments:
# - I make the following assumptions:
#    + The BT scanning is enabled by default on the DUT.
#    + It is not connected to any BT device.


*** Test Cases ***
Assert test init
    [Documentation]    Ensure we're ready to start the test
    Match    ${CURDIR}/../rpi-common/screens/big_circle_of_friends.jpg

Click top right toast
    [Documentation]    Click the top right shutdown/reboot widget
    Click LEFT Button on ${CURDIR}/../rpi-common/templates/pwr_toast.jpg
    Match    ${CURDIR}/../rpi-common/screens/settings_dock.jpg

Go to settings
    [Documentation]    Open the settings GUI application
    Click LEFT Button on ${CURDIR}/../rpi-common/templates/cog.jpg
    Match    ${CURDIR}/snapshots/templates/bt_tab.jpg    20

Go to BT tab
    [Documentation]    Open the bluetooth settings menu
    Click LEFT Button on ${CURDIR}/snapshots/templates/bt_tab.jpg
    Move Pointer To (100, 100)
    Match    ${CURDIR}/snapshots/templates/ts_bt.jpg    30

Connect to TS BT
    [Documentation]    Connect to the available desired bluetooth device
    Click LEFT Button on ${CURDIR}/snapshots/templates/ts_bt.jpg
    Move Pointer To (100, 100)
    Match    ${CURDIR}/snapshots/templates/conn_cnf.jpg    30

Close window
    [Documentation]    Close the settings application
    Click LEFT Button on ${CURDIR}/../rpi-common/templates/close.jpg
    Match    ${CURDIR}/../rpi-common/screens/big_circle_of_friends.jpg    15
