*** Settings ***
Documentation       Check a video plays within the firefox browser

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

Open Firefox and open a new tab
    [Documentation]    Open firefox and open a new tab
    Click LEFT Button on ${CURDIR}/snapshots/templates/firefox.jpg
    Sleep    90
    Keys Combo    Control_L    t
    Match    ${CURDIR}/snapshots/templates/new_tab.jpg    15

Run video and match first frame
    [Documentation]    Play a video, ensure it plays by matching the first frame
    Type String    https://people.ubuntu.com/~r41k0u/output_video.mp4
    Sleep    1
    Keys Combo    Return
    Match    ${CURDIR}/snapshots/templates/firefox_frame.jpg

Match last frame
    [Documentation]    Match the last frame of the video
    Match    ${CURDIR}/snapshots/templates/ubu_frame.jpg    16

Close Firefox
    [Documentation]    Close the firefox browser
    Click LEFT Button on ${CURDIR}/../rpi-common/templates/close.jpg
    Match    ${CURDIR}/../rpi-common/screens/big_circle_of_friends.jpg    15
