# TPM-FDE repair coverage

What the VM suite covers of Security Center's "Start repair..." flow, what
it leaves to the hardware pass (`HARDWARE.md`), and why the rest cannot be
reached.

`tpm-fde-cases.json` is the source of truth. Its `cases` are what runs. Its
`inventory` gives every secboot issue kind, snapd action, check status and support
value one verdict (`executed`, `blocked` or `source-inapplicable`) with the case
and evidence, or the reason. `fde_suite --validate` fails when a declared value
has no row or an `executed` row names no case. `tpm-fde-coverage.yaml` is a
snapshot of the same inventory for reading; nothing reads it back. This page
explains the manifest; where they disagree, the manifest is right.

## What a case proves

A case runs on a disposable clone of a golden VM: an Ubuntu 26.04.1 desktop
installed from the ISO with hardware-backed encryption. The clone has what a
user's machine has: the real snapd (the edge snap is the running daemon), polkit,
GDM and GNOME, Security Center installed as a snap, UEFI firmware with Secure Boot
(OVMF) and a software TPM (swtpm). YARF drives the screen over VNC and reads it by
OCR; the keywords read the machine through the guest helper over vsock SSH.

Nothing sits between the application and snapd: no `--dry-run`, no proxy, no bind
mount, no canned TPM reply, no injected fault. TPM states are made with the TPM's
own commands, firmware requests are approved at the firmware's own prompt, and the
pre-OS cases change what the firmware really verifies. A completed repair is
proven from the machine, not from the screen: a new `fde-reprovision` change ends
`Done`, the next boot unlocks without the recovery key (the two cases that add a
PIN or passphrase after the repair type that secret instead), `cryptsetup` accepts
the new recovery key and rejects the old one on both containers, and the banner is
gone.

Each case's preflight checks the stack before any state changes: snapd's socket is
served by `snapd.service`'s own process, the running snapd binary, its version and
the application revision equal the fixture's pins, and the application (the
`security_center` process) runs as the desktop user without `--dry-run`,
`--fake-service` or `--test-fde-repair`. It fails when no such process runs. It does
not look for `SNAPPY_TESTING` or snapd drop-ins; add that refusal when the store lane
starts. The rehearsal rests that point on the golden's recorded build steps, which
have no test-mode step, and on no case enabling snapd's test mode
(`snapd_test_mode` in `coverage.json` is empty).

Some steps belong to the harness, not to the user's path. They are real calls, not
stand-ins: the preflight and `Confirm Snapd Reports Issue` read snapd over its
socket as root (a `recheck` replaces snapd's cached check context), the checks of
changes and credentials read the machine over vsock SSH, the runner enrolls a
pre-existing PIN or passphrase through snapd's API as root, and the verification
reboot goes through the root helper, not GNOME's power menu.

## Pins and lanes

The manifest's `pins` record what the cases were written against: snapd
`2.78+g260.e4a83bb`, Security Center `x1` (a side-loaded build) and the golden
domain `ugt-fde-golden-2604-edge-20261118`. Issue kinds and actions come from
secboot `4924adcf6262` (`efi/preinstall/error_kinds.go`, `errorKindToActions` in
`checks_context.go`, `actions.go`).

| Lane | Security Center | snapd | Counts as |
| --- | --- | --- | --- |
| Rehearsal (now) | tip of `tpm-fde-repair/enable-real-systems`, with the snapd version gate in `feature_service.dart` lowered from 2.79 to 2.78 in a throwaway build clone; side-loaded over the store snap; `shutdown` plug connected by hand | edge channel, `2.78+g260` | a bug finding; the report's provenance line reads "REHEARSAL, side-loaded Security Center build; this run is not store evidence" |
| Store (when it exists) | a store channel, by `snap refresh` | a store channel with 2.79 or later | evidence |
| Hardware (before each promotion) | the build being promoted | the same | evidence for real machines; see `HARDWARE.md` |

The app's gate wants snapd 2.79 and the edge build reads as 2.78, so the unpatched
app shows no banner on it. The `shutdown` plug is connected by hand because the
base declaration does not grant it to a store snap. Both go away once the feature
is in the store.

## How a state reaches the repair dialog

1. The banner "Disk encryption needs repair" shows when snapd records
   `require-reprovision`, which it does when the boot-time unseal fails. The
   fixtures start from a state that fails it: a cleared TPM, a missing TPM or a
   changed pre-OS chain. The first boot asks for the recovery key, which the case
   types from the fixture's private file.
2. "Start repair..." makes the application ask snapd for a check, and snapd
   answers one issue at a time. In a VM the first issue is always `running-in-vm`
   ("The current environment is a virtual machine."). The user chooses "Ignore and
   continue", and only then do the other issues snapd found come through. The
   cases do this in the application, as a user does, and read snapd's state with
   the helper's `recheck` option, which keeps that answer in snapd's check
   context.
3. A real TPM command run in the guest right before "Start repair..." changes
   what that check reports: `tpm2_hierarchycontrol` on the endorsement hierarchy
   (TPM disabled), `tpm2_dictionarylockout` plus one wrong authorization (locked
   out) and `tpm2_pcrextend` on PCR 4 (the event log no longer replays to it).
   These four commands are the only fault recipes the suite may run
   (`REAL_TPM_RECIPES` in `fde.py`); every other recipe plants a bind mount or a
   canned reply and is never called.
4. snapd queues a firmware request and OVMF carries it out at the next boot; the
   case approves it at the firmware prompt (F12) and the TPM is cleared. OVMF
   reports PPI operations 5 (clear) and 14 (enable and clear), no operation 2, and
   answers every request with a restart.
5. Install-time checks do not run on an installed system. secboot skips the
   hierarchy-ownership and NV-storage checks when `PostInstallChecks` is set
   (`efi/preinstall/checks.go:210-211`, `check_tpm.go:398`), and snapd's
   running-system check sets it, so `tpm-hierarchies-owned`,
   `insufficient-tpm-storage`, `clear-tpm` and `clear-tpm-simple` cannot occur in
   this flow.

## Covered: states and the issues snapd reports

| State | snapd issue | snapd actions | How the case gets there | Case |
| --- | --- | --- | --- | --- |
| TPM cleared or replaced | `running-in-vm` only; `require-reprovision` comes from the failed unseal | `proceed` | `clear-tpm-state` on the stopped clone | `tpm-clear-recovery-reprovision` and the repair paths below |
| TPM missing | `no-suitable-tpm2-device`, support `unavailable` | none | the stopped clone's `<tpm>` device is removed (`no-tpm`) | `tpm-missing-device-unavailable` |
| TPM disabled | `tpm-device-disabled` | `enable-and-clear-tpm-via-firmware`, `reboot-to-fw-settings` | `tpm2_hierarchycontrol` | `tpm-disabled-enable-and-clear-reprovision` |
| TPM locked out | `tpm-device-lockout-locked-out` | `clear-tpm-via-firmware`, `enable-and-clear-tpm-via-firmware`, `reboot-to-fw-settings` | `tpm2_dictionarylockout` and a wrong authorization | `tpm-lockout-clear-reprovision` |
| PCR 4 does not replay | `no-suitable-pcr-bank` | `reboot-to-fw-settings`, `contact-oem` | `tpm2_pcrextend` on PCR 4 | `tpm-pcr-bank-firmware-settings-reprovision` |
| Firmware setup left with "Continue" | `tpm-pcr-unusable` | `contact-oem` | the user restarts into OVMF's setup and picks Continue, which boots in the same firmware session | `tpm-pcr-unusable-firmware-continue-reprovision` |
| Firmware request queued | `reboot-required` | `reboot` | follows the disabled and lockout cases once the request is queued | the same two cases |
| Pre-OS authorization by an enrolled digest | `pre-os-secure-boot-auth-by-enrolled-digests` | `proceed` | a SHA-256 `db` entry for an injected pre-OS driver, dispatched with `Driver####`; `db` keeps its CA entries | `tpm-pre-os-digest-proceed` |
| Weak Secure Boot algorithm | `weak-secure-boot-algorithms-detected` | `proceed` | an RSA-1024 CA signs the injected pre-OS driver; shim and grub keep their vendor signatures | `tpm-weak-secure-boot-proceed` |
| SysPrep application | `sys-prep-applications-present` | `proceed` | a CA in `db` and an application it signed, dispatched through `SysPrep0001` and `SysPrepOrder` | `tpm-sysprep-application-proceed` |

The cleared-TPM case does not exercise a check kind: with the TPM cleared the
availability check is clean, `running-in-vm` is the only issue, and
`require-reprovision` comes from the failed boot-time unseal.

The dialog shows one issue at a time, so the pre-OS cases answer every proceed
panel in turn (`Answer Repair Prompts`) instead of assuming a single one.

`no-suitable-pcr-bank` is reached because the event log stops replaying to PCR 4,
not because a bank is missing. A bank the firmware never allocated is not reachable
under OVMF: the active banks are the firmware's (`Tcg2Pei.c:358-443`) and
`TCG2_CONFIGURATION` stores only the TPM device selection (`Tcg2ConfigNvData.h`).

The "Continue" case records a behaviour of OVMF 2025.11-3ubuntu7.3 that a user can
hit: Continue in the firmware setup returns to the boot menu and boots in the same
firmware session, and snapd's check then reports `tpm-pcr-unusable`. secboot maps
a boot-manager-code PCR error to that kind (`checks_context.go:586-590`); which
PCR event the same-session boot adds was not traced. The application hides
`contact-oem`, so the dialog says "Hardware-backed encryption could not be
repaired" with no solution. A restart starts a clean session and the repair then
runs as usual. The other firmware cases leave the setup with its Reset entry.

## Covered: repair paths on a cleared TPM

| Case | What it adds |
| --- | --- |
| `tpm-existing-pin-reprovision`, `tpm-existing-passphrase-reprovision` | a PIN or passphrase enrolled before the clear is removed ("Any PIN and passphrase will be removed"); the next boot needs none. The runner enrolls it before the case through the guest helper (snapd's API as root) |
| `tpm-passphrase-before-repair-reboot`, `tpm-pin-after-repair-reboot` | a passphrase added through the application's page before the first repaired restart, a PIN added after it; each is then asked at boot and unlocks it |
| `tpm-recovery-key-expiry` | a generated recovery key is expired, the repair is retried and the repaired boot works |
| `tpm-repair-cancel` | cancelling leaves the machine as snapd reported it: the banner stays and snapd still requires reprovisioning |
| `tpm-repair-power-cut` | the host cuts the clone's power after the old keyslots are renamed and the new recovery key is added, before the replacement TPM key is sealed. The next boot rolls back: the retried change fails with `missing reprovision context`, the baseline keyslot names are back, the original recovery key unlocks both devices and the interrupted attempt's key unlocks neither. A second repair completes and keeps a working new key |

## snapd actions

| Action | Verdict | Where |
| --- | --- | --- |
| `proceed` | executed | the VM warning and every pre-OS panel |
| `enable-and-clear-tpm-via-firmware` | executed | TPM disabled: the button "Enable and clear TPM on restart", after "I understand the risk" |
| `clear-tpm-via-firmware` | executed | TPM locked out: "Clear TPM on restart", after "I understand the risk" |
| `reboot` | executed | the "Restart is required." panel: Continue, then "Restart now" |
| `reboot-to-fw-settings` | executed | PCR bank: Continue, "Restart now", F2 repeatedly at startup, "EFI Firmware Setup", Reset |
| `contact-oem` | executed in snapd's answer only | the application never shows contact actions; the panel reads "Try the solution below or contact IT support." |
| `shutdown` | blocked, hardware row 3 | OVMF answers every request with a restart; snapd emits it only after a power-off request |
| `enable-tpm-via-firmware` | blocked, hardware row 3 | offered only when the firmware reports PPI operation 2; OVMF does not |
| `contact-os-vendor` | blocked, hardware row 6 | belongs to `no-kernel-iommu`, a host security check that secboot skips under virtualization |
| `clear-tpm`, `clear-tpm-simple` | source-inapplicable | install-time kinds only |

## Not covered, with the reason

On the hardware sheet:

| Kind | Reason |
| --- | --- |
| `shutdown-required` | emitted only after a power-off request (`checks_context.go:685-687`); OVMF asks for a restart |
| `no-kernel-iommu` | host security checks are skipped in a VM; row 6 |
| `invalid-secure-boot-mode` | a Secure Boot mode, not a TPM state. The application has a panel for it, but the catalog has no fixture that leaves the VM firmware out of deployed mode; row 4 |

Not reachable on this target:

| Kind | Reason |
| --- | --- |
| `efi-variable-access` | needs an efivarfs access error on a firmware variable read (`check_efi.go:33-42`, `efi.go:48-56`); the only recipes that produce one (`efivar-eio`, `mask-sysfs-efi`) plant a bind mount or a canned reply, which the suite excludes |
| `measured-boot` | `ReadEventLog` fails only when the TCG2 log is absent (`checks.go:238-241`); OVMF publishes it whenever a TPM2 is detected (`Tcg2Dxe.c:3056-3060`) |
| `tpm-command-failed` | needs a TPM error response (`checks_context.go:487-496`); swtpm returns none |
| `invalid-tpm-response` | needs a malformed response (`checks_context.go:497-499`); only a canned reply produces one |
| `tpm-communication` | needs a transport failure (`checks_context.go:500-502`) |
| `tpm-device-failure` | `ErrTPMFailure` needs the TPM to report failure mode from its partial self-test (`check_tpm.go:285-299`); swtpm does not |
| `action-failed` | produced only when a PPI or clear-TPM action fails (`checks_context.go:670-678`, `:709-715`); OVMF carried out every request the cases queued |
| `insufficient-dma-protection`, `host-security` | host security checks are skipped in a VM |
| `absolute-present` | needs a firmware Absolute agent, which QEMU does not provide |
| `no-hardware-root-of-trust` | firmware property; QEMU exposes no Boot Guard or PSB root of trust |

This source never emits them to a running system:

| Kind | Reason |
| --- | --- |
| `tpm-hierarchies-owned`, `insufficient-tpm-storage` | install-time checks, skipped after installation (see step 5 above) |
| `system-not-efi` | `ErrSystemNotEFI` is returned only when efivarfs is unavailable (`check_efi.go:33-37`); the clone boots through OVMF |
| `unsupported-platform` | secboot's own classifier records that the host-security check fires first (`checks_context.go:506-513`) |
| `unexpected-action` | the app applies only an action the dialog offered (`disk_encryption_providers.dart:1127-1130`) and secboot compares it with the cached context (`checks_context.go:639-664`) |
| `internal-error` | needs an unclassified secboot failure; every known trigger fabricates the daemon's view |
| `invalid-argument` | the application sends only the kind snapd offered, so the argument path is unreachable |
| `missing-argument` | declared in snapd, never constructed |
| `addon-drivers-present` | always a warning in snapd, never an error, so never an issue panel |

The inventory also tracks check statuses, auto-repair results, recommendations,
support values, features, requirements and authentication modes; each row's
verdict and reason is in the manifest.

## Last full run

`fde_suite --full --keep-going`, run `full2-20261118`, 2026-11-18 from 19:40 to 21:07
IST, on the pins above (rehearsal lane: not store evidence). It replaces
`full-20261118` (17:46 to 19:16 IST), whose preflight never found the application:
it looked for a process named `desktop-security-center`, the process is
`security_center`, and the check passed when nothing matched. The check now fails
with `gui-not-running` when no such process runs, and every case of this run passed
it.

| | |
| --- | --- |
| Cases | 16 of 16 pass; 84 minutes of captured case time, one clone each |
| Inventory | 68 values: 27 executed, 30 blocked, 11 source-inapplicable |
| Outcome | `INCOMPLETE`, by design: the 30 blocked values are the hardware-sheet and not-reachable rows above |
| snapd test mode | none declared, none executed |
| Repairs | 14 cases finished a repair. None of the repaired boots fell back to the recovery key (the clone would never answer, so the case would fail at its wait for the boot) and the credential checks held |
| Product findings | none: the NV-handle collision did not show in 14 completed repairs |

A grep of the whole run directory for a recovery-key pattern finds no text file.
That covers `output.xml`, which `log.html` is built from; Robot compresses the
strings inside `log.html`, so a grep of that file alone proves little. The run
directory is private (0700, files 0600): the raw captures and videos show the keys,
so do not share any of them, `edited/full-run.mp4` included. The edited video has 16
masked intervals, one per `sensitive-start` marker (12 cases have one, the expiry and
power-cut cases two, the cancel and TPM-missing cases none); they cover the repair
dialog's new recovery key. The boot-prompt unlock typing (`Unlock Encrypted Boot`, 727 s
of the run) lies outside them. Two samples of the edited video: a pixel probe found all
16 intervals black below the speed labels (luma maximum 16 at three points in each)
and no group of five digits in OCR of eight frames around each interval, from 3 s
before the start to 3 s after the end; an OCR of the whole video at one frame per
second (804 frames) found a five-digit run in 23 frames, none inside a mask and none
key-like: the run name on the title card, a snap revision or a kernel timestamp in the
shutdown log, or a MAC address in the firmware boot menu. So no key showed during the
unmasked unlock typing, as far as OCR at that rate can tell; a key on screen for under
a second would not show. `edited/full-run.raw.mp4` is the unmasked source.

## Running

Commands, fixtures and secrets are in `README.md`. A full run reports `INCOMPLETE`
while any `blocked` row remains, which is the case on every VM.
