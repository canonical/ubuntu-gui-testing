# TPM-FDE reprovisioning suite

Drives the installed Security Center through snapd's real TPM-FDE repair flow in
one throwaway clone per case. snapd, polkit and the application are the real
ones; only the clone's disk, TPM and firmware state are changed, either before
it boots or, for the TPM-state cases, with the TPM's own commands while it runs.
Nothing sits between the application and snapd: no proxy, no `--dry-run`.

`COVERAGE.md` lists every TPM state and snapd action and the case or hardware
row that covers it. `HARDWARE.md` is the run sheet for the part only a physical
PC can show.

## Lanes

Every report states which lane it came from.

| lane | Security Center | snapd | counts as |
| --- | --- | --- | --- |
| rehearsal (now) | branch tip with the version gate lowered to 2.78, side-loaded over the store snap as revision `x1`, `shutdown` plug connected by hand | edge channel build `2.78+g260.e4a83bb` | bug findings; the report says "REHEARSAL ... not store evidence" |
| store (when it exists) | `snap refresh` from a store channel | store channel with snapd 2.79 or later | evidence |
| hardware (before a promotion) | the build being promoted | the same | evidence for real machines, by hand (`HARDWARE.md`) |

The rehearsal gate patch exists only in a throwaway clone of the application
(`feature_service.dart`, `'2.79'` to `'2.78'`); the branch is untouched.

## What a case proves

Each repair-completing case asserts that snapd recorded a new `fde-reprovision` change
that reached `Done`; the page reports working hardware-backed encryption with no
reprovision recommendation; the clone restarts and unlocks without the recovery key; the
new key unlocks both devices and the old key is rejected; the authentication
mode is the one the case chose; the repair banner is gone.

The cancellation and unavailable-hardware cases instead check unchanged boot
identity, authentication, and repair history, with the original recovery key
still unlocking both encrypted devices.

The power-cut case asserts the interruption itself: the host cuts power as soon
as snapd's handler replaces its private stage file, so the attempt has already
renamed the old keyslots and added the new recovery key but never sealed the
replacement TPM key. On the next boot snapd retries that task, restores the old
keyslots, and fails the change with `missing reprovision context`. The case
requires exactly one new change, spawned before the cut and finished after the
new boot, the baseline keyslot names back in place, the original recovery key
unlocking both devices, the interrupted attempt's saved key unlocking nothing,
and a second repair then completing with a working new key.

snapd can answer the first post-boot `snapshot` with a `snapd-error` while its
retry is still converting the interrupted keyslots, so the boot wait retries
`snapd-error` and transport timeouts and still fails at once on trust,
authentication and malformed-response failures.

A green Robot log is the only proof. A screenshot of a dialog is not.

## Prerequisites

- A stopped, consistent TPM-FDE source domain named by the fixture catalog's
  `source-domain` and by the manifest's `pins.baseline`. The rehearsal lane
  uses `ugt-fde-golden-2604-edge-20261118`: Ubuntu 26.04.1 installed from the
  ISO by the upstream installer case (`resolute.tpm-fde-no-passphrase`,
  hardware-backed encryption, no PIN), snapd refreshed to the edge channel
  with the daemon running from the snap (never `apt upgrade` in the guest: a
  newer snapd deb outranks the snap and snapd re-executes into the deb), the
  snapd deb held, `tpm2-tools`, and the Security Center build side-loaded as
  `x1`. Its disk, NVRAM and TPM state must be preserved together.
  Fixture preflight checks that the snapd socket is served by
  `snapd.service`'s own process, that the application runs as the desktop
  user without `--dry-run` or another non-production argument, and that
  the data and save devices exist and are LUKS-encrypted. It reports the
  running snapd's version and binary hash and the application's snap
  revision, and `Preflight Fde Fixture` compares them with the fixture's
  `snapd_version`, `snapd_executable_sha256` and `security_center_revision`.
  Nothing compares them with the manifest's pins. It does not check the
  `shutdown` connection, which the app's restart (a logind call) needs.
- A private `pydeps` directory of symlinks to the system `defusedxml` and
  libvirt Python modules (`~/.local/share/ugt-fde/pydeps`): the yarf venv has
  neither and `TpmFde.py` fails to import without them.
- A private `TMPDIR` (`~/.local/share/ugt-fde/tmp`) when `/tmp` is a small
  quota-limited tmpfs: a full `/tmp` fails the run before the first step.
- A private fixture JSON per state, mode 0600, under
  `~/.local/share/ugt-fde/fixture/`. The fixture names secret files; the runner
  refuses one that is group- or world-readable.
- The storage pool `ugt-fde-canonical` at
  `~/.local/share/ugt-fde/pool-canonical`, large enough for one clone.

## Run one case

```bash
cd /path/to/ubuntu-gui-testing
umask 077
env -u XDG_CONFIG_HOME TMPDIR=$HOME/.local/share/ugt-fde/tmp \
  PATH=$PWD/.venv-yarf/bin:$PATH \
  PYTHONPATH=$PWD/runner:$HOME/.local/share/ugt-fde/pydeps \
  runner/.venv/bin/python -m ubuntu_gui_testing_runner.fde_suite \
  --manifest tests/desktop-security-center/desktop-security-center-reprovision/tpm-fde-cases.json \
  --fixtures "$HOME/.local/share/ugt-fde/fixture-catalog.json" \
  --artifacts-dir "$HOME/.local/share/ugt-fde/runs/<run-id>" \
  --case <case-id>
```

Case ids are in `tpm-fde-cases.json`. Use a new `<run-id>` for each try, one case
at a time, and do not type into the VM while it runs. `env -u XDG_CONFIG_HOME`
keeps libvirt's session state where the clone runner reads it. The lower-level
single-case runner (`python -m ubuntu_gui_testing_runner --suite
tests/desktop-security-center/ --test desktop-security-center-reprovision.<case
file stem> --robot-test "<case name>" --source-domain
ugt-fde-golden-2604-edge-20261118 --connection-uri qemu:///session
--swtpm-state-dir "$HOME/.config/libvirt/qemu/swtpm" --pool-name
ugt-fde-canonical --pool-dir "$HOME/.local/share/ugt-fde/pool-canonical"
--fde-config "$HOME/.local/share/ugt-fde/fixture/<fixture>.json"`) takes the
same inputs one at a time; `--test` is the dotted path of the `.robot` file below
`--suite`, and Yarf prepends the directory's own suite name, so never repeat it.
`--fde-config` requires `--robot-test`.

Run the whole set with the aggregate entrypoint below; one clone per case,
never two cases in one clone. That run's `report.md` and `coverage.json` record
each case's directory and result.

## Automated run with one combined video

The aggregate entrypoint expands the reviewed case manifest, runs each case on
its own clone through the single-case runner above, captures each clone's
display from power-on, and produces one chaptered video whose every idle
interval is audited at four seconds or less after encoding. A full run is one
command:

```bash
cd /path/to/ubuntu-gui-testing
runner/.venv/bin/python -m ubuntu_gui_testing_runner.fde_suite \
  --manifest tests/desktop-security-center/desktop-security-center-reprovision/tpm-fde-cases.json \
  --fixtures "$HOME/.local/share/ugt-fde/fixture-catalog.json" \
  --artifacts-dir "$HOME/.local/share/ugt-fde/runs/<run-id>" \
  --full --keep-going
```

That command performs the clone, GUI drive, display capture, edit, encoded
audit and report without an operator step between cases. It does not install
or upgrade snapd or Security Center, and it does not create the stopped source
domain, the private fixture catalog or its secret files; those are prerequisites
below. `--keep-going` runs the remaining cases after a case fails, so one
broken state does not hide the rest of the matrix.

Use `--case <case-id>` for a repeatable partial run instead of `--full`.
`--validate` checks the manifest and the fixture catalog without creating a VM.
`--full` selects every case in the manifest and can only report success when
every required inventory value executed; it reports `INCOMPLETE` while a
`blocked` or `required` value remains. A partial `--case` selection is always
reported as `PARTIAL`.

Each run writes:

- `cases/<case-id>/` — the Robot output, `capture-index.json`, `markers.jsonl`
  and the raw private PNG frames (`capture/`)
- `edited/full-run.mp4` — the combined video with burned speed labels and
  chapters. The canvas is the largest display mode captured in the run (the
  desktop's 1280x800 here), so firmware frames are scaled or padded rather than
  shrinking the application text. The first seconds carry a footer with the run
  id, snapd version, Security Center revision and the executed test-mode count.
  Every interval opened by a sensitive-region marker is masked with an opaque
  frame plus a non-secret label. A mask longer than four seconds is
  time-compressed like idle time, so the privacy block itself cannot sit on
  screen above the idle limit; its speed and real elapsed wait are folded into
  the privacy label, with no second label drawn over the mask.
- `edited/edit-map.json` — every source interval mapped onto the edited
  timeline, including each accelerated wait and its speed. A short all-black
  frame delivered when the capture connection resumes is a transport
  placeholder: its time remains mapped, but it is not sampled and does not
  count as a screen transition.
- `edited/timing-audit.json` — measured encoded duration, per-idle-interval and
  redaction audit from the finished file, not from the plan
- `coverage.json` and `report.md` — executed, failed, and still-required values;
  the report lists every executed case that enabled snapd's test mode

The public manifest lives at
`tests/desktop-security-center/desktop-security-center-reprovision/tpm-fde-cases.json`.
The private catalog maps fixture names to configuration files, the source
domain and the pool; it never contains credentials.

### snapd test mode

No manifest case uses snapd's build-tagged VM test switch. A production snapd
in a virtual machine reports `running-in-vm` first and reports the later issues
(the pre-OS digest path, the sysprep and weak-Secure-Boot application phases,
no TPM device) only after the user answers that warning, so these cases answer
it in the app, as a user does, and then read snapd's state with the helper's
`recheck` option, which keeps the answer in snapd's check context. A plain
check would start a new context and drop it.

The `snapd-test-mode: true` manifest field and the `enable-test-mode` helper
operation remain for a case that cannot reach its state this way. That case is
declared, counted apart in `coverage.json` and printed in `report.md` under
**snapd test mode**, and is never evidence of a production-configuration run.

## Coverage dispositions

The manifest gives every declared value one disposition:

- `executed` — a named case asserts it and names its evidence;
- `required` — applicable but not yet executed; a full run cannot pass;
- `blocked` — a specific missing prerequisite (physical firmware, installation
  phase, a state the VM cannot create);
- `source-inapplicable` — this source never emits it; the reason cites why;
- `api-negative` — refused through the daemon API, never counted as GUI proof.

A missing fixture or a skip never turns a required value into a pass.


## Fixtures

`prepare` selects the clone mutation and is validated against a fixed set:

| state | `prepare` |
|---|---|
| cleared TPM, `running-in-vm` only | `["clear-tpm-state"]` |
| missing TPM, no available repair action | `["no-tpm"]` |
| Secure Boot off on SB-capable firmware | `["plain-ovmf"]` |
| `sys-prep-applications-present` | `["sysprep-app"]` |
| `weak-secure-boot-algorithms-detected` | `["preos-weak-sb"]` |
| `pre-os-secure-boot-auth-by-enrolled-digests` | `["preos-digest-sb"]` |

Keep `snapd_version`, `snapd_executable_sha256`, `data_device`, `save_device`
and `security_center_revision` unchanged when deriving a fixture; preflight
asserts them against the clone. `snapd_executable_sha256` is the hash of the
binary the snapd process is running (`/proc/<pid>/exe`), which is the snap's
binary once snapd has re-executed into it, not the deb's `/usr/lib/snapd/snapd`.

`tpm-missing-device-unavailable` removes only the stopped clone's TPM device,
after any healthy enrollment boot. The source domain and TPM state remain
unchanged. As in the firmware cases, the app answers the virtual-machine
warning first; the TPM check then still observes the actual missing hardware.
The case checks snapd's empty action list, the unavailable-repair dialog, no
unsafe proceed/repair action, unchanged repair history and usable credentials.

### Authentication cases

| dotted suffix after `desktop-security-center-reprovision.` | fixture authentication | sequence |
|---|---|---|
| `tpm-clear-recovery-reprovision` | `auth_mode=none` | repair, then boot without a credential |
| `tpm-existing-pin-reprovision` | `auth_mode=pin`, `pin_file` | enroll the PIN before clearing the TPM; repair removes it |
| `tpm-existing-passphrase-reprovision` | `auth_mode=passphrase`, `passphrase_file` | enroll the passphrase before clearing the TPM; repair removes it |
| `tpm-pin-after-repair-reboot` | `auth_mode=none`, `pin_file` | repair and boot, add the PIN through the UI, then boot with it |
| `tpm-passphrase-before-repair-reboot` | `auth_mode=none`, `passphrase_file` | repair, add the passphrase through the UI, then use it for the first reboot |
| `tpm-repair-power-cut` | `auth_mode=none` | interrupt a confirmed repair with a host power cut, prove the rollback, then repair again |

The two pre-enrolled cases use `prepare: ["enroll-auth", "clear-tpm-state"]`.
The runner boots the healthy clone, enrolls the selected authentication through
real snapd, verifies it, shuts down, and only then applies the fault. The other
four cases use `prepare: ["clear-tpm-state"]`. Every secret file is mode 0600.
The post-repair cases type only their chosen PIN or passphrase at the boot prompt,
never the recovery key, and independently verify the resulting authentication mode.

The power-cut case drives libvirt only for the clone the runner created: the
observer reads the handler's stage file over the guest channel, refuses any
domain that is not that clone, and the restart requires the clone to return on
the vsock CID and VNC port Yarf already uses. It never edits snapd state, the
TPM, or the source domain.

### TPM-state cases

All four start from the cleared-TPM clone (the recovery-key boot that makes
snapd record `require-reprovision`). The first three change the TPM with its own
command before "Start repair": the application answers the virtual-machine
warning, snapd reports the new issue, and the case takes the dialog's solution.
The fourth reaches its issue by a user action in the firmware.

| dotted suffix | real state | solution taken | firmware step |
|---|---|---|---|
| `tpm-disabled-enable-and-clear-reprovision` | `tpm2_hierarchycontrol` disables the endorsement hierarchy: `tpm-device-disabled` | "Enable and clear TPM on restart" (after "I understand the risk"), then "Restart" and "Restart now" | OVMF asks to confirm the TPM request: press F12 at "Press F12" |
| `tpm-lockout-clear-reprovision` | `tpm2_dictionarylockout` and one wrong lockout authorization lock the TPM: `tpm-device-lockout-locked-out` | "Clear TPM on restart" (after "I understand the risk"), then "Restart" and "Restart now" | the same F12 confirmation |
| `tpm-pcr-bank-firmware-settings-reprovision` | `tpm2_pcrextend` on PCR 4: `no-suitable-pcr-bank` | "Enable PCR banks manually", "Continue", "Restart now" | press F2 repeatedly at startup (OVMF's boot menu opens), pick "EFI Firmware Setup", then "Reset" |
| `tpm-pcr-unusable-firmware-continue-reprovision` | the machine restarts into OVMF's setup and the user picks "Continue": `tpm-pcr-unusable` | none; the dialog says "Hardware-backed encryption could not be repaired" and the case closes it with Escape | the same F2 visit, leaving with "Continue" and Escape at the boot menu; a plain restart then gives a clean session for the repair |

After the firmware step each case unlocks the recovery-key boot and runs the
plain repair described under "What a case proves". The PCR-bank case ends the
visit with "Reset" because "Continue" boots in the same firmware session and snapd
then reports `tpm-pcr-unusable` with only `contact-oem`, which the fourth case
asserts. snapd also offers `contact-oem` next to the PCR-bank solution; the
application never shows contact actions, so that dialog lists one solution.

## Secrets

- Fixture secrets live in files named by the fixture JSON, mode 0600, outside
  the repository.
- Robot logs every keyword argument and every OCR text it reads, so each window
  where a recovery key is on screen uses a quiet block from `Start Repair`
  until the key panel is gone. Quiet blocks suppress messages, not keyword
  arguments or failure status. Text lookups use `Match Text Without Echo`, and
  `Type Fixture Secret` reads credentials internally, never as Robot arguments.
  `Close All` restores the caller's log level if a case fails inside the block.
- `artifacts/` is ignored by git. It still holds OCR text and the run video, so
  treat it as private and do not upload it.
- The combined video masks every marked recovery-key panel before the dialog
  paints it, but the raw `capture/` PNG frames remain private and unmasked.
  Keep the whole run directory private; never share raw frames or OCR output.
  The mask ends only after the dialog-only warning disappears, because the
  page behind a successful repair also contains "Recovery key" and fuzzy OCR
  would otherwise report the closed dialog as still open. When the mask is
  time-compressed, its label also states the real elapsed wait and speed.
- The saved recovery key file is written inside the clone, not on the host.

The older check-key and replace-recovery-key suites still pass keys as Robot
arguments and can expose them in their logs. They are not part of this
reprovision suite, and this work does not claim to redact their artifacts.

## Reading a run

`artifacts/fde-<id>/` holds `output.xml`, `log.html` and Yarf's `video.webm`.
FDE runs use a private umask; the verified run's files are mode 0600. Check the
summary line `1 test, 1 passed, 0 failed`, then the case's own
assertions in `log.html`.

Yarf's `video.webm` encodes logged screenshots at 5 frames per second, not
wall-clock time; a five-minute key-expiry wait need not add any video frames.
The aggregate `edited/full-run.mp4` is different: it records the target display
on the host monotonic clock, preserves every interval, and accelerates each idle
interval to at most four seconds. Use `edited/timing-audit.json` for that run's
source duration, speed factor and measured output per interval. Video duration
alone still does not prove how long a wait ran.

## Troubleshooting

- `Source domain '<name>' not found`: the golden lives in `qemu:///session`; an
  inherited `XDG_CONFIG_HOME` points libvirt at the wrong configuration
  directory. Run with `env -u XDG_CONFIG_HOME`.
- `No keyword with name 'Type Fixture Secret' found` or a missing
  `TpmFde.Close All`: `TpmFde.py` failed to import. Put the private `pydeps`
  directory on `PYTHONPATH`.
- A run that fails before its first step with a write error under `/tmp`: the
  tmpfs quota is full. Set `TMPDIR` to the private directory.
- QEMU fails to open a volume with EACCES: `--pool-name` and `--pool-dir` must
  agree, because the pool is looked up by name.
- Inspect leftover domains before cleanup; never remove an unrelated domain or
  the golden. The runner owns the disposable clone it creates.
- A run with `--keep` keeps the clone's domain *and* its pool volume, so the
  next run of the same case stops at `storage volume ... exists already`.
  Undefine the kept domain with `--nvram` and delete that case's volume from
  `vol-list` before rerunning.
- All-black frames about every 55 to 60 seconds while the screen is static are
  the capture connection reconnecting (`capture-disconnected` then
  `capture-retry-connected` in `capture-index.json`), not a blank guest.
- A boot after a repair that asks for the recovery key is a product failure
  (snapd can reuse a TPM NV handle after a clear). Record the change id; do not
  retry it away.
- Before a run, `virsh --connect qemu:///session list --all`: a killed run can
  leave a clone, and only clones the suite started may be removed.
