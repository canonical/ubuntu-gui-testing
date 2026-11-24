"""Derive TPM-FDE goldens in the states the end-to-end cases start from.

Each derived golden is a kept clone of a source golden, renamed. Pass it as
--source-domain to run a case from that state. There are three kinds:

- Pre-OS states (preos-*, sysprep-*) put one extra EFI binary on
  ubuntu-seed, with the matching db entry and a Driver#### or SysPrep####
  load option. A short suite copies the binary in the booted clone, because
  the runner already boots clones and talks to them over SSH. The firmware
  variables are then written on the stopped clone's NVRAM with virt-fw-vars
  (python3-virt-firmware).
- Host states (clear-tpm-state, no-tpm, plain-ovmf) edit the clone's TPM
  state, domain XML or NVRAM on the host, without booting it.
- Enroll states (enroll-pin, enroll-passphrase) enroll a PIN or passphrase
  through snapd in the booted clone. The secret is read from --secret-file.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from xml.etree.ElementTree import tostring as xml_tostring

import defusedxml.ElementTree as ET
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
ENROLL_TEST: Final = "Fde-Golden-Enroll-Auth"
# Enroll states and the snapd authentication mode each one enrolls.
AUTH_STATES: Final = {"enroll-pin": "pin", "enroll-passphrase": "passphrase"}

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
    "sysprep-weak-sb": FirmwareState(
        EFI_APPLICATION,
        1024,
        "UGT Weak RSA-1024 CA",
        "/EFI/sysprep/weak.efi",
        "SysPrep",
        "UGT Weak Signed SysPrep",
    ),
    "sysprep-digest-sb": FirmwareState(
        EFI_APPLICATION,
        None,
        "",
        "/EFI/sysprep/digest.efi",
        "SysPrep",
        "UGT Digest Authorized SysPrep",
    ),
}


PLAIN_OVMF_CODE: Final = "/usr/share/OVMF/OVMF_CODE_4M.fd"
PLAIN_OVMF_VARS: Final = "/usr/share/OVMF/OVMF_VARS_4M.fd"


def without_tpm(domain_xml: str) -> str:
    """Return the domain XML with its TPM device removed."""
    xml = ET.fromstring(domain_xml)
    devices = xml.find("devices")
    tpm = xml.find("devices/tpm")
    if devices is None or tpm is None:
        raise ValueError("Domain has no TPM to remove")
    devices.remove(tpm)
    return xml_tostring(xml, encoding="unicode")


def with_plain_ovmf(domain_xml: str) -> str:
    """Return the domain XML booting OVMF without Secure Boot."""
    xml = ET.fromstring(domain_xml)
    loader = xml.find("os/loader")
    if loader is None:
        raise ValueError("Domain has no firmware loader to replace")
    loader.text = PLAIN_OVMF_CODE
    loader.set("secure", "no")
    # libvirt checks the loader against these firmware features.
    for feature in xml.findall("os/firmware/feature"):
        feature.set("enabled", "no")
    nvram = xml.find("os/nvram")
    if nvram is not None and "template" in nvram.attrib:
        nvram.set("template", PLAIN_OVMF_VARS)
    return xml_tostring(xml, encoding="unicode")


def _remove_tpm_state(runner: LibvirtImageRunner, domain: Any) -> None:
    shutil.rmtree(runner.swtpm_state_dir / domain.UUIDString(), ignore_errors=True)


def _clear_tpm_state(runner: LibvirtImageRunner, domain: Any) -> None:
    # Without saved state, swtpm starts the clone with a fresh, unowned TPM.
    _remove_tpm_state(runner, domain)


def _no_tpm(runner: LibvirtImageRunner, domain: Any) -> None:
    domain.connect().defineXML(without_tpm(domain.XMLDesc(0)))
    _remove_tpm_state(runner, domain)


def _plain_ovmf(runner: LibvirtImageRunner, domain: Any) -> None:
    shutil.copyfile(PLAIN_OVMF_VARS, runner.pool_dir / runner.nvram_volume_name)
    domain.connect().defineXML(with_plain_ovmf(domain.XMLDesc(0)))


# States made by editing the stopped clone on the host, without booting it.
HOST_STATES: Final = {
    "clear-tpm-state": _clear_tpm_state,
    "no-tpm": _no_tpm,
    "plain-ovmf": _plain_ovmf,
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
    secret_file: Path | None = None,
) -> None:
    """Create the derived golden `name` from `source_domain` in `state_name`.

    The enroll states read their PIN or passphrase from `secret_file`.
    """
    clones = _Clones(source_domain, name, connection_uri, pool_name, pool_dir)
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

        if state_name in HOST_STATES:
            clone = _derive_on_host(clones, state_name)
        elif state_name in AUTH_STATES:
            if secret_file is None:
                raise RuntimeError(f"State '{state_name}' needs --secret-file")
            clone = _derive_enrolled(clones, AUTH_STATES[state_name], secret_file)
        else:
            clone = _derive_preos(clones, STATES[state_name])
        conn.lookupByName(clone).rename(name, 0)
    finally:
        conn.close()
    LOGGER.info("Derived golden '%s' (%s) from '%s'", name, state_name, source_domain)


@dataclass(frozen=True)
class _Clones:
    """Makes kept clones of the source golden for one derived golden."""

    source_domain: str
    # Names the clone and its volumes, which keep this name after the
    # rename, so each derived golden gets its own.
    name: str
    connection_uri: str
    pool_name: str
    pool_dir: Path

    def runner(self, test: str, workdir: Path) -> LibvirtImageRunner:
        """Create a kept clone; the runner makes it on construction."""
        return LibvirtImageRunner(
            source_domain=self.source_domain,
            suite_name=self.name,
            test_name=test,
            keep=True,
            artifacts_dir=workdir / "artifacts",
            connection_uri=self.connection_uri,
            pool_name=self.pool_name,
            pool_dir=self.pool_dir,
        )


def _run_kept(runner: LibvirtImageRunner, test: str) -> None:
    """Boot the kept clone, run the test against it and shut it down."""
    if runner.run(suite=str(SUITE), test=test) != 0:
        raise RuntimeError(f"{test} failed; clone '{runner.domain_name}' was kept")


def _derive_on_host(clones: _Clones, state_name: str) -> str:
    """Edit a kept, never-started clone; return its name."""
    with tempfile.TemporaryDirectory() as tmp:
        runner = clones.runner(state_name, Path(tmp))
        with runner:
            domain = runner.conn.lookupByName(runner.domain_name)
            HOST_STATES[state_name](runner, domain)
        return str(runner.domain_name)


def _derive_enrolled(clones: _Clones, auth_mode: str, secret_file: Path) -> str:
    """Enroll a PIN or passphrase in a booted clone; return its name."""
    secret = secret_file.read_text(encoding="utf-8").rstrip("\n")
    if not secret:
        raise RuntimeError(f"Secret file '{secret_file}' is empty")
    with tempfile.TemporaryDirectory() as tmp:
        body = Path(tmp) / "auth.json"
        body.write_text(
            json.dumps(
                {"action": "replace-platform-key", "auth-mode": auth_mode,
                 auth_mode: secret}
            ),
            encoding="utf-8",
        )  # fmt: skip
        os.environ["UGT_AUTH_BODY_FILE"] = str(body)
        os.environ["UGT_AUTH_MODE"] = auth_mode
        runner = clones.runner(ENROLL_TEST, Path(tmp))
        with runner:
            _run_kept(runner, ENROLL_TEST)
        return str(runner.domain_name)


def _derive_preos(clones: _Clones, state: FirmwareState) -> str:
    """Copy an EFI binary in a booted clone, then set its db and load option."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        efi, db_args = build_efi(state, workdir)
        os.environ["UGT_EFI_FILE"] = str(efi)
        os.environ["UGT_SEED_PATH"] = state.seed_path
        runner = clones.runner(TEST, workdir)
        with runner:
            _run_kept(runner, TEST)
        # The runner has shut the kept clone down, so its NVRAM is safe to edit.
        partition_file = runner.artifacts_path / PARTITION_FILE
        part = SeedPartition.parse(partition_file.read_text(encoding="utf-8"))
        variables = workdir / "variables.json"
        variables.write_text(
            json.dumps(load_option_variables(state, part)), encoding="utf-8"
        )
        nvram = runner.pool_dir / runner.nvram_volume_name
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
        return str(runner.domain_name)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source-domain", required=True, help="Golden to derive from")
    parser.add_argument(
        "--state", required=True, choices=sorted([*STATES, *HOST_STATES, *AUTH_STATES])
    )
    parser.add_argument(
        "--secret-file",
        type=Path,
        help="File holding the PIN or passphrase for the enroll states",
    )
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
            args.secret_file,
        )
    except RuntimeError as err:
        sys.exit(f"error: {err}")


if __name__ == "__main__":
    main()
