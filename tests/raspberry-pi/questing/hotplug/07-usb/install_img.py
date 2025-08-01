#!/usr/bin/python3
# This is meant to run on the TS to install or remove an image on a USB drive.

import os
import sys
import subprocess

if len(sys.argv) < 2:
    print("Usage: python3 install_img.py <install/remove>")
    sys.exit(1)

if sys.argv[1] not in ["install", "remove"]:
    print("Invalid argument. Use 'install' or 'remove'.")
    sys.exit(1)

if not os.path.exists("usb"):
    subprocess.run(["mkdir", "-p", "usb"], check=True)

if not os.path.ismount("usb"):
    print("Mounting USB drive...")
    subprocess.run(["sudo", "mount", "/dev/sdb1", "usb"], check=True)

if sys.argv[1] == "install":
    print("Installing image...")
    subprocess.run(["wget", "https://assets.ubuntu.com/v1/a7e3c509-Canonical%20Ubuntu.svg", "-O", "usb/ubuntu.svg"], check=True)
    subprocess.run(["sudo", "umount", "usb"], check=True)
    print("Image installed successfully.")
elif sys.argv[1] == "remove":
    print("Removing image...")
    subprocess.run(["sudo", "rm", "-f", "usb/ubuntu.svg"], check=True)
    subprocess.run(["sudo", "umount", "usb"], check=True)
    print("Image removed successfully.")
