*** Settings ***
Documentation       Connect to wifi access point

Resource            kvm.resource

Test Tags
...    robot:stop-on-failure
...    yarf:category_id:com.canonical.yarf::basic
...    yarf:test_group_id:com.canonical.yarf::integration
...    yarf:certification_status:blocker
# Comments:
# - I make the following assumptions:
#    + The WiFi scanning is enabled by default on the DUT.
#    + It is not connected to any WiFi network.
#    + A WiFi AP named "Canonical" is available.


*** Test Cases ***
Assert test init
    [Documentation]    Ensure we're ready to start the test
    Match    ${CURDIR}/snapshots/templates/dark_circle_of_friends.jpg

Click top right toast
    [Documentation]    Click the top right shutdown/reboot widget
    Click LEFT Button on ${CURDIR}/snapshots/templates/pwr_toast.jpg
    Match    ${CURDIR}/snapshots/templates/settings_dock.jpg

Go to settings
    [Documentation]    Go to settings part of widget
    Click LEFT Button on ${CURDIR}/snapshots/templates/cog.jpg
    Match    ${CURDIR}/snapshots/templates/wifi_tab.jpg    20

Go to WiFi tab
    [Documentation]    Open wifi settings
    Click LEFT Button on ${CURDIR}/snapshots/templates/wifi_tab.jpg
    Match    ${CURDIR}/snapshots/templates/hidden_net.jpg

Enter WiFi details
    [Documentation]    Enter details of the WiFi network
    Click LEFT Button on ${CURDIR}/snapshots/templates/hidden_net.jpg
    Move Pointer To (100, 100)
    Match    ${CURDIR}/snapshots/templates/ssid_inp.jpg
    Click LEFT Button on ${CURDIR}/snapshots/templates/ssid_inp.jpg
    Sleep    3
    Type String    Canonical
    Match    ${CURDIR}/snapshots/templates/sec.jpg
    Click LEFT Button on ${CURDIR}/snapshots/templates/sec.jpg
    Match    ${CURDIR}/snapshots/templates/wpa.jpg
    Click LEFT Button on ${CURDIR}/snapshots/templates/wpa.jpg
    Match    ${CURDIR}/snapshots/templates/pwd_inp.jpg
    Keys Combo    Tab
    Sleep    3
    Type String   ${CANONICAL_WIFI_PASSWORD} 
    Sleep    1
    Keys Combo    Tab
    Keys Combo    Tab
    Keys Combo    Tab
    Keys Combo    Return 
    Match    ${CURDIR}/snapshots/templates/conn_cnf.jpg    30

Close window
    [Documentation]    Close wifi settings window
    Click LEFT Button on ${CURDIR}/snapshots/templates/close.jpg
    Match    ${CURDIR}/snapshots/templates/dark_circle_of_friends.jpg    15
