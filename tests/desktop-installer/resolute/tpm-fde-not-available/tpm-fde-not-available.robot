*** Settings ***
Documentation         Ensure that TPM isn't offered by the installer on non-tpm systems
Resource        kvm.resource
Test Tags           robot:exit-on-failure    # robocop: off=tag-with-reserved-word
Resource    ${CURDIR}/../../installer.resource


*** Test Cases ***
Grub Menu
    [Documentation]         Go through grub menu, if present
    Grub Menu

Ensure Not Unfocused After Boot
    [Documentation]         Workaround LP: #2112383
    Ensure Not Unfocused After Boot

Language Slide
    [Documentation]         Go through language slide
    Select Language

A11y Slide
    [Documentation]         Go through a11y slide
    A11y Slide

Keyboard Layout
    [Documentation]         Use default keyboard layout
    Keyboard Layout

Internet Connection
    [Documentation]         Go through internet connection slide
    Internet Connection

Skip Installer Update
    [Documentation]         Skip installer update, if present
    Skip Installer Update

Try Or Install
    [Documentation]         Go through try or install slide
    Try Or Install

Interactive vs Automated
    [Documentation]         Go through interactive vs automated slide
    Interactive vs Automated

Default vs Extended
    [Documentation]         Go through default vs extended slide
    Default vs Extended

Proprietary Software
    [Documentation]         Go through proprietary software slide
    Proprietary Software

Select Erase Disk and Reinstall
    [Documentation]         Go through proprietary software slide
    Select Erase Disk and Reinstall

Choose Where to Install Ubuntu
    [Documentation]         Go through slide showing various disks, if present
    Choose Where to Install Ubuntu

Encryption And File System Tpm Not Available
    [Documentation]         Ensure that the TPM FDE encryption option is greyed out, and not selectable
    Encryption And File System Tpm Not Available
