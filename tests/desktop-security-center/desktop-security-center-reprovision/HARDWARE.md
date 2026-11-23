# TPM-FDE repair: hardware run sheet

One physical PC, run before each promotion of the Security Center or snapd
build. The VM suite covers every state and action a VM can reach (see
`COVERAGE.md`). This sheet covers what only real hardware shows: the vendor's
own firmware prompts, a power-off request, the host security checks that secboot
skips under virtualization, and a TPM that behaves like a shipped part.

## Setup

- A PC that can be wiped: TPM 2.0, UEFI, Secure Boot on, Ubuntu 26.04.1 desktop
  installed with hardware-backed encryption and no PIN. The encrypted
  partitions are labelled `ubuntu-data` and `ubuntu-save`.
- The build being promoted. Record `snap version`, `dpkg-query -W snapd`,
  `snap list desktop-security-center` and `snap connections
  desktop-security-center`; the `shutdown` plug must be connected. Never run
  `apt upgrade` first: a newer snapd deb outranks an edge snapd snap and the
  desktop user then gets 401 or 403 from snapd.
- The recovery key copied to a private file on another computer. Keep it off
  camera: stop the recording before it is typed or shown, and start it again
  after.
- Screen recording on for every row.
- The page is Security Center, "Disk encryption". The repair starts from the
  banner "Disk encryption needs repair" with the button "Start repair...".

## Rows

A PC is not a VM, so the "The current environment is a virtual machine." warning
does not appear. The first host issue snapd finds is shown directly. Each issue
panel reads "There is an issue with hardware-backed encryption", names the issue,
and lists "Solution N: ..." entries; a panel with only "Ignore and continue" is a
warning to accept. The contact actions (contact the OEM, contact the OS vendor)
are never shown by the application, so a panel can list fewer solutions than
snapd offered. Technical details lists the issue kind.

| # | Do | Expect | Record |
| --- | --- | --- | --- |
| 1 | Open Disk encryption on the healthy machine. | "Hardware-backed encryption is enabled", no repair banner. | Screenshot. |
| 2 | Clear the TPM in firmware setup. Boot, type the recovery key, open the page, press "Start repair...". | The banner "Disk encryption needs repair". Any real host issue appears before the repair, each with its solutions. The repair ends with a new key to save and "Done". After a restart no key is asked. | Every issue kind shown (Technical details), the change id, whether the next boot is unattended. |
| 3 | Disable the TPM in firmware setup. Boot, type the recovery key, press "Start repair...". | "This computer's TPM is disabled." with firmware solutions, or "This computer does not have the required security hardware (TPM 2.0) for this encryption method." if the firmware hides the device. Take "Enable TPM on restart" or "Enable and clear TPM on restart" if offered (tick "I understand the risk" for the clearing one). The page then reads "Restart is required." or "Power off is required."; open "Solution 1", press "Continue", then "Restart now" or "Power off now". Approve the firmware's prompt. Boot with the recovery key and repair as in row 2. | Which kind and which solutions were offered, the firmware prompt text, restart or power off, then as in row 2. If only "Enable TPM manually" is offered, take it and record what the firmware setup screen offered. |
| 4 | Turn Secure Boot off in firmware setup. Boot, type the recovery key, open the page. Turn Secure Boot on again and boot. | Record whether the banner appears. If it does, the panel says "Secure boot is disabled in this computer or is not set in deployed mode." with "Enable secure boot manually". After the next normal boot the banner is gone and no key is asked. | Panel text or its absence, whether the banner cleared. |
| 5 | Add a PIN in the application and restart to confirm it is asked. Clear the TPM in firmware setup, boot, type the recovery key, repair. | "Any PIN and passphrase will be removed" before the key is generated. The repair ends with "Done"; a restart needs no key. | Warning shown, boot behaviour. |
| 6 | Optional: boot once with `intel_iommu=off` (or `amd_iommu=off`) on the kernel command line, open the page. | "This computer is missing a required security feature (IOMMU)." with "Enable IOMMU manually" as the only solution (snapd also offers contact-os-vendor, which the application hides). | Panel text, and snapd's own answer from `sudo snap debug api '/v2/systems?running=true'`, which must list `contact-os-vendor`. |

Rows 3 and 6 are the only evidence for `enable-tpm-via-firmware`, `shutdown` and
`contact-os-vendor`: OVMF offers no enable-only request, answers every request
with a restart, and the host security checks are skipped in a VM. Record which of
those a real firmware gives.

## Pass criteria for every completed repair

- The snapd change for the repair ends `Done`.
- The next boot unlocks with no key typed.
- On `ubuntu-data` and `ubuntu-save`, `cryptsetup open --test-passphrase`
  accepts the new recovery key and rejects the old one.
- The repair banner is gone.

A boot after a repair that asks for the recovery key is a product failure
(snapd can reuse a TPM NV handle after a clear). Report it with the change id;
do not retry it away.

## After the run

Reinstall or restore the PC. Keep the recordings private until the keys are
masked.
