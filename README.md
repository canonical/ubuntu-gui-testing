# ubuntu-gui-testing
GUI Testing on Ubuntu

## Pre-requisite Knowledge

The tests in this repository are all written using Robot Framework, and executed using Yarf.

Here's the yarf [documentation](https://canonical-yarf.readthedocs-hosted.com/).

Here's the yarf [repository](https://github.com/canonical/yarf/).

## Repository Structure

This repository is structured as follows - taking a snippet from the initial PR with an example test case, we have:
```
├── README.md
├── common
│   ├── circle-of-friends.png
│   └── common.resource
└── tests
    └── firefox-example
        ├── common -> ../../common/
        ├── firefox-basic
        │   └── firefox-basic.robot
        ├── firefox-example.resource
        └── generic
            ├── firefox.png
            └── new-tab.png
```

Under `common`, there exists `common.resource`. A resource file is a Robot Framework file wherein you can define functions that'll be used in `.robot` files.
 
`.robot` files are the "scripts" which make up an individual test case. They "import" `.resource` files.

Each directory under `tests` corresponds to an application - the name should be the same as the deb/snap package which provides the application.

Under each application directory, there should be `$test_case` directories, containing at least a `$test_case.robot` file, which provides the script to run the actual test case. In this `$test_case` directory, there should also exist any templates that are used *only for that test case*.

Under each application directory, outside of the test case directories, there should be the following subdirectories:
```
- generic  # for templates used in more than one $test_case
- common  # a symlink to the common directory at the root of the repo
```

Under each application directory, there should be an `$application.resource` file - full of functions used by the various `$test_case`'s for that application.

For more information on the semantics of setting up your test case, please see Robot Framework documentation.

## Writing Your Own Test Case

First, create a directory for your `$application`, if it doesn't already exist, with:
```
./scripts/new-application-test-suite-setup.sh $application
```

Congrats! Your test suites are now bootstrapped.

TBD! Need the template_factory [PR](https://github.com/canonical/yarf/pull/160) to land first.

Can use this [gist](https://gist.github.com/andersson1234/43eecdd90b02f33980500aee1ad9c183) as reference and for some helpful copy paste.

Spawning VM with pre-installed desktop image:
```
qemu-system-x86_64 -drive format=raw,file=ubuntu25-04.img -enable-kvm -m 8192M -smp 2 -machine type=q35,accel=kvm -usbdevice tablet -vga virtio -vnc :0,share=ignore
```

Running yarf:
```
VNC_PORT=0 yarf --platform=Vnc  # for interactive console
VNC_PORT=0 yarf --platform=Vnc /path/to/test/suite/  # for running a test suite
```

## OVERLAY QEMU IMG

```
qemu-img create -o backing_file=ubuntu25-04.img,backing_fmt=raw -f qcow2 img1.cow
```

