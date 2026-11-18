# Ubuntu GUI Testing Runner

Test runner that manages libvirt virtual machines for GUI test execution using [YARF](https://github.com/canonical/yarf).

## Usage

### From an ISO

Boot a VM from an ISO and run the test suite:

```bash
ubuntu-gui-testing-runner \
  --suite tests/desktop-installer \
  --test resolute.entire-disk \
  --iso ~/images/ubuntu-26.04-desktop-amd64.iso
```

### From an existing domain

Clone an existing libvirt domain (using a qcow2 overlay) and run the test suite against it:

```bash
ubuntu-gui-testing-runner \
  --suite tests/firefox-example \
  --test firefox-example-basic \
  --source-domain ugt-desktop-installer-resolute.entire-disk-20260601T120000Z
```

### From the latest matching domain

Clone the most recent domain whose name starts with a given prefix. Domains are
named `ugt-<suite>-<test>-<UTC timestamp>` (e.g. `...-20260601T120000Z`); the
fixed-width timestamp is lexicographically sortable, so the newest matching
domain is selected automatically:

```bash
ubuntu-gui-testing-runner \
  --suite tests/firefox-example \
  --test firefox-example-basic \
  --source-domain-prefix ugt-desktop-installer-resolute.entire-disk
```

### From an existing domain with source disk mounted as USB

When cloning from an existing domain, you can optionally attach a second overlay
of the same source image as a USB disk. This is useful for tests that need to
mount or unlock a secondary device.

```bash
ubuntu-gui-testing-runner \
  --suite tests/snap-tpmctl \
  --test snap-tpmctl-mount \
  --source-domain ugt-desktop-installer-resolute.entire-disk-2026-06-01 \
  --mount-source-domain /dev/sda5
```

If `--mount-source-domain` is passed without a value, the default device is
`/dev/sda`.

### Options

| Flag | Description |
| - | - |
| `--suite` | Path to the test suite (required) |
| `--test` | Name of the test to run (required) |
| `--iso` | Path to an ISO for installation |
| `--source-domain` | Existing libvirt domain to clone from |
| `--mount-source-domain [DEVICE]` | Attach a second overlay of the source domain as a USB disk and pass `DEVICE` to Robot variables |
| `--source-domain-prefix` | Clone the most recent domain whose name starts with this prefix |
| `--keep` | Keep the VM and resources after the run |
| `--delete-previous` | Delete domains and VM state from previous kept runs of the same suite/test before starting; ISOs are never deleted |
| `--connection-uri` | Libvirt connection URI (default: `qemu:///session`) |
| `--pool-name` | Storage pool name (default: `ubuntu-gui-testing`) |
| `--pool-dir` | Storage pool directory (default: `/pool`) |
| `--artifacts-dir` | Directory for test artifacts (default: `./artifacts`) |
| `--swtpm-state-dir` | Path to swtpm state (default: `~/.config/libvirt/qemu/swtpm`) |
| `--test-username` | Guest SSH username (default: `ubuntu`) |
| `--test-password` | Guest SSH password (default: `ubuntu`) |
| `--domain-template` | Override domain XML template |
| `--pool-template` | Override pool XML template |
| `--volume-template` | Override volume XML template |
| `--overlay-template` | Override overlay volume XML template |

Exactly one of `--iso`, `--source-domain`, or `--source-domain-prefix` must be
provided.

## Development

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
cd runner
uv sync --group dev
```

### Quality checks

```bash
uv run ruff format .
uv run ruff check .
uv run mypy .
uv run pytest tests/
```
