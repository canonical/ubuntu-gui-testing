"""Derive TPM-FDE goldens whose firmware runs extra pre-OS code.

Each derived golden is a kept clone of a source golden with one extra EFI
binary on ubuntu-seed, the matching db entry and a Driver#### or SysPrep####
load option. Pass it as --source-domain to run a pre-OS case.

The binary is copied by a short suite in the booted clone, because the runner
already boots clones and talks to them over SSH. The firmware variables are
written afterwards on the stopped clone's NVRAM with virt-fw-vars
(python3-virt-firmware).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import struct
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import libvirt  # type: ignore[import-untyped]

from ubuntu_gui_testing_runner.constants import (
    DEFAULT_CONNECTION_URI,
    DEFAULT_POOL_DIR,
    DEFAULT_POOL_NAME,
)
from ubuntu_gui_testing_runner.image_runner import LibvirtImageRunner

LOGGER = logging.getLogger(__name__)

SUITE: Final = Path(__file__).resolve().parents[2] / "tests/desktop-security-center"
TEST: Final = "Fde-Golden-Install-Efi"
PARTITION_FILE: Final = "seed-partition.txt"

EFI_GLOBAL_VARIABLE_GUID: Final = "8be4df61-93ca-11d2-aa0d-00e098032b8c"
UGT_DB_OWNER_GUID: Final = "c0fe7e57-0000-4000-8000-0000000000d6"
NV_BS_RT: Final = 0x7
LOAD_OPTION_ACTIVE: Final = 0x1
EFI_APPLICATION: Final = 10
EFI_BOOT_SERVICE_DRIVER: Final = 11
FILE_ALIGNMENT: Final = 0x200


@dataclass(frozen=True)
class FirmwareState:
    """One pre-OS firmware state: what runs, how db trusts it, how it loads."""

    subsystem: int
    rsa_bits: int | None  # None: trust the binary by its SHA-256 hash in db
    common_name: str
    seed_path: str  # absolute path on ubuntu-seed, with forward slashes
    variable: str  # "Driver" or "SysPrep"
    description: str


STATES: Final = {
    "preos-digest-sb": FirmwareState(
        EFI_BOOT_SERVICE_DRIVER,
        None,
        "",
        "/EFI/ugt/digest.efi",
        "Driver",
        "UGT Pre-OS Digest Driver",
    ),
    "preos-weak-sb": FirmwareState(
        EFI_BOOT_SERVICE_DRIVER,
        1024,
        "UGT Weak RSA-1024 CA",
        "/EFI/ugt/weak.efi",
        "Driver",
        "UGT Weak Signed Driver",
    ),
    "sysprep-app": FirmwareState(
        EFI_APPLICATION,
        2048,
        "UGT SysPrep Test CA",
        "/EFI/sysprep/sysprep.efi",
        "SysPrep",
        "UGT SysPrep Application",
    ),
}


@dataclass(frozen=True)
class SeedPartition:
    """Where ubuntu-seed sits on the clone's disk, for the load option."""

    number: int
    start_lba: int
    size_lba: int
    unique_guid: uuid.UUID

    @classmethod
    def parse(cls, text: str) -> SeedPartition:
        """Parse "NUMBER START SIZE PARTUUID" as printed by the guest suite."""
        fields = text.split()
        if len(fields) != 4:
            raise ValueError(f"Expected 4 fields for ubuntu-seed, got {text!r}")
        return cls(int(fields[0]), int(fields[1]), int(fields[2]), uuid.UUID(fields[3]))


def minimal_efi_image(subsystem: int) -> bytes:
    """Return a minimal PE32+ EFI image whose entry point returns success."""
    dos = b"MZ" + bytes(0x3A) + struct.pack("<I", 0x40)
    coff = b"PE\0\0" + struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, 240, 0x22)
    optional = struct.pack(
        "<HBBIIIII", 0x20B, 0, 0, FILE_ALIGNMENT, 0, 0, 0x1000, 0x1000
    )
    optional += struct.pack(
        "<QIIHHHHHHIIIIHHQQQQII",
        0x100000,  # image base
        0x1000,  # section alignment
        FILE_ALIGNMENT,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0x2000,  # image size
        FILE_ALIGNMENT,  # headers size
        0,
        subsystem,
        0,
        0,
        0,
        0,
        0,
        0,
        16,  # data directories
    )
    optional += bytes(16 * 8)
    section = struct.pack(
        "<8sIIIIIIHHI",
        b".text",
        3,
        0x1000,
        FILE_ALIGNMENT,
        FILE_ALIGNMENT,
        0,
        0,
        0,
        0,
        0x60000020,  # code, execute, read
    )
    headers = (dos + coff + optional + section).ljust(FILE_ALIGNMENT, b"\0")
    return headers + b"\x31\xc0\xc3".ljust(FILE_ALIGNMENT, b"\0")  # xor eax,eax; ret


def load_option(description: str, seed_path: str, part: SeedPartition) -> bytes:
    """Encode an active EFI_LOAD_OPTION for a file on a GPT partition."""
    hard_drive = struct.pack(
        "<BBHIQQ16sBB",
        4,  # media device path
        1,  # hard drive
        42,
        part.number,
        part.start_lba,
        part.size_lba,
        part.unique_guid.bytes_le,
        2,  # GPT partition signature
        2,  # GUID signature type
    )
    path = (seed_path.replace("/", "\\") + "\0").encode("utf-16-le")
    file_node = struct.pack("<BBH", 4, 4, 4 + len(path)) + path
    device_path = hard_drive + file_node + bytes((0x7F, 0xFF, 4, 0))
    return (
        struct.pack("<IH", LOAD_OPTION_ACTIVE, len(device_path))
        + (description + "\0").encode("utf-16-le")
        + device_path
    )


def load_option_variables(state: FirmwareState, part: SeedPartition) -> dict[str, Any]:
    """Return the virt-fw-vars JSON that sets the load option and its order."""
    option = load_option(state.description, state.seed_path, part)
    return {
        "version": 2,
        "variables": [
            {
                "name": f"{state.variable}0001",
                "guid": EFI_GLOBAL_VARIABLE_GUID,
                "attr": NV_BS_RT,
                "data": option.hex(),
            },
            {
                "name": f"{state.variable}Order",
                "guid": EFI_GLOBAL_VARIABLE_GUID,
                "attr": NV_BS_RT,
                "data": struct.pack("<H", 1).hex(),
            },
        ],
    }


def _run(command: list[str]) -> str:
    try:
        # Argument list from this module only, never a shell string.
        result = subprocess.run(  # noqa: S603
            command, check=True, capture_output=True, text=True
        )
    except subprocess.CalledProcessError as err:
        raise RuntimeError(f"{command[0]} failed: {err.stderr.strip()}") from err
    return result.stdout


def authenticode_sha256(efi: Path) -> str:
    """Return the Authenticode SHA-256 of an EFI binary as hex."""
    # The system python3 has python3-virt-firmware and python3-pefile; the
    # runner's venv does not.
    script = (
        "import sys, pefile;"
        "from virt.peutils.pesign import pe_authenticode_hash;"
        "print(pe_authenticode_hash(pefile.PE(sys.argv[1])).hex())"
    )
    return _run(["/usr/bin/python3", "-I", "-c", script, str(efi)]).strip()


def build_efi(state: FirmwareState, workdir: Path) -> tuple[Path, list[str]]:
    """Write the EFI binary for a state; return it and the virt-fw-vars db args."""
    unsigned = workdir / "unsigned.efi"
    unsigned.write_bytes(minimal_efi_image(state.subsystem))
    if state.rsa_bits is None:
        return unsigned, [
            "--add-db-hash",
            UGT_DB_OWNER_GUID,
            authenticode_sha256(unsigned),
        ]

    key, cert, signed = workdir / "ca.key", workdir / "ca.crt", workdir / "signed.efi"
    _run(
        [
            "openssl", "req", "-x509", "-newkey", f"rsa:{state.rsa_bits}", "-sha256",
            "-nodes", "-days", "3650", "-subj", f"/CN={state.common_name}",
            "-keyout", str(key), "-out", str(cert),
        ]
    )  # fmt: skip
    _run(
        [
            "sbsign",
            "--key",
            str(key),
            "--cert",
            str(cert),
            "--output",
            str(signed),
            str(unsigned),
        ]
    )
    _run(["sbverify", "--cert", str(cert), str(signed)])
    return signed, ["--add-db", UGT_DB_OWNER_GUID, str(cert)]


def derive(
    source_domain: str,
    state_name: str,
    name: str,
    connection_uri: str = DEFAULT_CONNECTION_URI,
    pool_name: str = DEFAULT_POOL_NAME,
    pool_dir: Path = DEFAULT_POOL_DIR,
) -> None:
    """Create the derived golden `name` from `source_domain` in `state_name`."""
    state = STATES[state_name]
    conn = libvirt.open(connection_uri)
    try:
        try:
            conn.lookupByName(name)
        except libvirt.libvirtError:
            pass
        else:
            raise RuntimeError(
                f"Domain '{name}' already exists; remove it or pick another name"
            )

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            efi, db_args = build_efi(state, workdir)
            os.environ["UGT_EFI_FILE"] = str(efi)
            os.environ["UGT_SEED_PATH"] = state.seed_path
            with LibvirtImageRunner(
                source_domain=source_domain,
                # Names the clone and its volumes, which keep this name after
                # the rename, so each derived golden gets its own.
                suite_name=name,
                test_name=TEST,
                keep=True,
                artifacts_dir=workdir / "artifacts",
                connection_uri=connection_uri,
                pool_name=pool_name,
                pool_dir=pool_dir,
            ) as runner:
                if runner.run(suite=str(SUITE), test=TEST) != 0:
                    raise RuntimeError(
                        "Copying the EFI binary failed; "
                        f"clone '{runner.domain_name}' was kept"
                    )
                clone = runner.domain_name
                nvram = runner.pool_dir / runner.nvram_volume_name
                partition_file = runner.artifacts_path / PARTITION_FILE
            # The runner has shut the kept clone down, so its NVRAM is safe to edit.
            part = SeedPartition.parse(partition_file.read_text(encoding="utf-8"))
            variables = workdir / "variables.json"
            variables.write_text(
                json.dumps(load_option_variables(state, part)), encoding="utf-8"
            )
            _run(
                [
                    "virt-fw-vars",
                    "--inplace",
                    str(nvram),
                    *db_args,
                    "--set-json",
                    str(variables),
                ]
            )

        conn.lookupByName(clone).rename(name, 0)
    finally:
        conn.close()
    LOGGER.info("Derived golden '%s' (%s) from '%s'", name, state_name, source_domain)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source-domain", required=True, help="Golden to derive from")
    parser.add_argument("--state", required=True, choices=sorted(STATES))
    parser.add_argument("--name", required=True, help="Name of the derived golden")
    parser.add_argument("--connection-uri", default=DEFAULT_CONNECTION_URI)
    parser.add_argument("--pool-name", default=DEFAULT_POOL_NAME)
    parser.add_argument("--pool-dir", type=Path, default=DEFAULT_POOL_DIR)
    args = parser.parse_args()
    try:
        derive(
            args.source_domain,
            args.state,
            args.name,
            args.connection_uri,
            args.pool_name,
            args.pool_dir,
        )
    except RuntimeError as err:
        sys.exit(f"error: {err}")


if __name__ == "__main__":
    main()
