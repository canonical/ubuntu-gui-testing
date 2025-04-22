#!/bin/bash
# shellcheck disable=SC1079,SC1078

USAGE="""
Use this script like this:
./scripts/new-application-test-suite-setup.sh \$application_name

For example, if \$application_name is \"asdf\", running the above results in:
└── tests
    └── asdf
        ├── common -> ../../common/
        ├── asdf-basic
        │   └── asdf-basic.robot
        ├── asdf.resource
        └── generic
            └── asdf.png
"""

if [ "$#" -ne 1 ]; then
    echo "${USAGE}"
    exit 1
fi

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
REPO_ROOT_DIR="${SCRIPT_DIR}/../"
APP_NAME="${1}"

ROBOT_FILE_TEMPLATE="""*** Settings ***
Resource        \${Z}/../${APP_NAME}.resource

Test Tags       robot:exit-on-failure


*** Variables ***
\${Z}    \${CURDIR}


*** Test Cases ***
Function One
    Function One
"""

RESOURCE_FILE_TEMPLATE="""*** Settings ***
Documentation       Shared resources for application testing

Resource            kvm.resource
Resource            \${Y}/common/common.resource


*** Variables ***
\${Y}    \${CURDIR}


*** Keywords ***
Function One
    BuiltIn.Sleep   1
"""

echo "You have selected application name: $1"

APP_DIR="${REPO_ROOT_DIR}/tests/${APP_NAME}/"
BASIC_TC_DIR="${REPO_ROOT_DIR}/tests/${APP_NAME}/${APP_NAME}-basic/"
BASIC_TC_SCRIPT="${REPO_ROOT_DIR}/tests/${APP_NAME}/${APP_NAME}-basic/${APP_NAME}-basic.robot"
RESOURCE_FILE="${APP_DIR}/${APP_NAME}.resource"
GENERIC_DIR="${APP_DIR}/generic/"
EMPTY_PNG="${GENERIC_DIR}/${APP_NAME}.png"

mkdir -p "${APP_DIR}"
mkdir -p "${BASIC_TC_DIR}"
printf "%s\n" "${ROBOT_FILE_TEMPLATE}" > "${BASIC_TC_SCRIPT}"
printf "%s\n" "${RESOURCE_FILE_TEMPLATE}" > "${RESOURCE_FILE}"
mkdir -p "${GENERIC_DIR}"
touch "${EMPTY_PNG}"
cd "${APP_DIR}" || exit
ln -s "../../common" "common"
cd - || exit

echo "All done! Created the following application directory:"
tree "${APP_DIR}"

