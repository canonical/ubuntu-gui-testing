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
  --source-domain ugt-desktop-installer-resolute.entire-disk-2026-06-01
```

### Options

| Flag | Description |
| - | - |
| `--suite` | Path to the test suite (required) |
| `--test` | Name of the test to run (required) |
| `--robot-variable NAME:VALUE` | Robot variable passed to YARF; repeatable |
| `--iso` | Path to an ISO for installation |
| `--source-domain` | Existing libvirt domain to clone from |
| `--keep` | Keep the VM and resources after the run |
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

Either `--iso` or `--source-domain` must be provided.

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
