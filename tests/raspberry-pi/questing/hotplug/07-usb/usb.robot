*** Settings ***
Documentation       Check files can be read and opened from usb via desktop environment & applications

Resource            kvm.resource

Test Tags
...    robot:stop-on-failure
...    yarf:category_id:com.canonical.yarf::basic
...    yarf:test_group_id:com.canonical.yarf::integration
...    yarf:certification_status:blocker
# Comments:
# - I make the following assumptions:
#    + The USB flash drive is connected
#    + It has an Ubuntu logo SVG inside (and that is the only thing)


*** Test Cases ***
Assert test init
    [Documentation]    Ensure we're ready to start the test
    Match    ${CURDIR}/../rpi-common/screens/big_circle_of_friends.jpg

Click USB icon
    [Documentation]    Click the usb icon in the sidebar
    Click LEFT Button on ${CURDIR}/snapshots/templates/usb_icon.jpg
    Move Pointer To (100, 100)
    Match    ${CURDIR}/snapshots/screens/screen_01.jpg    15

Click Ubuntu logo
    [Documentation]    Click the ubuntu logo and open the image
    Click LEFT Button on ${CURDIR}/snapshots/templates/svg_icon.jpg
    Click LEFT Button
    Move Pointer To (100, 100)
    Match    ${CURDIR}/snapshots/templates/final_img.jpg

Exit image viewer
    [Documentation]    Close the image viewer
    Click LEFT Button on ${CURDIR}/snapshots/templates/dark_cross.jpg
    Move Pointer To (100, 100)
    Match    ${CURDIR}/snapshots/screens/screen_01.jpg

Exit folder
    [Documentation]    Close Nautilus
    Click LEFT Button on ${CURDIR}/snapshots/templates/light_cross.jpg
    Move Pointer To (100, 100)
    Match    ${CURDIR}/../rpi-common/screens/big_circle_of_friends.jpg    15
