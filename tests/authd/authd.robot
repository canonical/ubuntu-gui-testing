*** Settings ***
Resource        authd.resource

Test Tags       robot:exit-on-failure


*** Variables ***
${Z}    ${CURDIR}


*** Test Cases ***
# Pre-requisites:
# * A VM with authd and auth-msentraid installed, booted to the login screen.
#Log in with Entra ID broker with device authentication via login command
#    Log In  # Log in to GNOME with the default user
#    Open GNOME Terminal
#    Log in with Entra ID via login command
#    Add user to sudo group
#    Log out
#    # Log in once to avoid the "Welcome to Ubuntu" app opening on subsequent logins
#    Log in with local password via GDM
#    Closes "Welcome to Ubuntu" app
#    Log out
#
## Pre-requisites:
## * A VM with authd and auth-msentraid installed, booted to the login screen.
## * The authd test user is already created (e.g. by logging in via device authentication)
#Log in with local password via GDM
#    Log in with local password via GDM
#
## Pre-requisites:
## * A VM with authd and auth-msentraid installed
## * A running GNOME session for the authd test user
##Log in with local password via login command
##    Log in with local password via login command
#
## Pre-requisites:
## * A VM with authd and auth-msentraid installed
## * A running GNOME session for the authd test user
#Authenticate via polkit
#    Run a command with pkexec

# Pre-requisites:
# * A VM with authd and auth-msentraid installed
# * A running GNOME session for the authd test user
Lock and unlock the screen

#    Lock Screen
#    Unlock Screen    ${local_password}
