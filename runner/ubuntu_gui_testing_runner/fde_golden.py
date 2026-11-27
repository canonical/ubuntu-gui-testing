"""Make TPM-FDE domains that run EFI code before the OS."""

from __future__ import annotations

import argparse
import logging
import os
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import libvirt  # type: ignore[import-untyped]

from ubuntu_gui_testing_runner.constants import (
    DEFAULT_ARTIFACTS_DIR,
    DEFAULT_CONNECTION_URI,
    DEFAULT_POOL_DIR,
    DEFAULT_POOL_NAME,
)
from ubuntu_gui_testing_runner.image_runner import LibvirtImageRunner

LOGGER = logging.getLogger(__name__)

STAGING_SUITE_DIR: Final = Path(__file__).resolve().parents[1] / "fixtures/fde-golden"
STAGING_TEST_NAME: Final = "Fde-Golden-Install-Efi"

UGT_DB_OWNER_GUID: Final = "c0fe7e57-0000-4000-8000-0000000000d6"
EFI_APPLICATION: Final = 10
EFI_BOOT_SERVICE_DRIVER: Final = 11
FILE_ALIGNMENT: Final = 0x200
IMAGE_BASE: Final = 0x100000
SECTION_ALIGNMENT: Final = 0x1000
SIZE_OF_IMAGE: Final = 0x2000
SIZE_OF_HEADERS: Final = FILE_ALIGNMENT
NUMBER_OF_RVA_AND_SIZES: Final = 16
IMAGE_SCN_CNT_CODE: Final = 0x20
IMAGE_SCN_MEM_EXECUTE: Final = 0x20000000
IMAGE_SCN_MEM_READ: Final = 0x40000000
X64_RETURN_EFI_SUCCESS: Final = b"\x31\xc0\xc3"


@dataclass(frozen=True)
class FirmwareState:
    """Describe an EFI program, how it loads and how it is trusted."""

    subsystem: int
    rsa_bits: int | None  # With no key size, the firmware trusts the file's hash.
    ca_common_name: str
    seed_path: str  # Full path on ubuntu-seed; use forward slashes.
    efibootmgr_mode: Literal["--driver", "--sysprep"]
    boot_entry_label: str


FIRMWARE_STATES: Final = {
    "preos-digest-sb": FirmwareState(
        EFI_BOOT_SERVICE_DRIVER,
        None,
        "",
        "/EFI/ugt/digest.efi",
        "--driver",
        "UGT Pre-OS Digest Driver",
    ),
    "preos-weak-sb": FirmwareState(
        EFI_BOOT_SERVICE_DRIVER,
        1024,
        "UGT Weak RSA-1024 CA",
        "/EFI/ugt/weak.efi",
        "--driver",
        "UGT Weak Signed Driver",
    ),
    "sysprep-app": FirmwareState(
        EFI_APPLICATION,
        2048,
        "UGT SysPrep Test CA",
        "/EFI/sysprep/sysprep.efi",
        "--sysprep",
        "UGT SysPrep Application",
    ),
}


def build_minimal_efi_image(subsystem: int) -> bytes:
    """Return a small EFI program that returns success."""
    dos = b"MZ" + bytes(0x3A) + struct.pack("<I", 0x40)
    coff = b"PE\0\0" + struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, 240, 0x22)
    optional = struct.pack(
        "<HBBIIIII", 0x20B, 0, 0, FILE_ALIGNMENT, 0, 0, 0x1000, 0x1000
    )
    optional += struct.pack(
        "<QIIHHHHHHIIIIHHQQQQII",
        IMAGE_BASE,
        SECTION_ALIGNMENT,
        FILE_ALIGNMENT,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        SIZE_OF_IMAGE,
        SIZE_OF_HEADERS,
        0,
        subsystem,
        0,
        0,
        0,
        0,
        0,
        0,
        NUMBER_OF_RVA_AND_SIZES,
    )
    optional += bytes(NUMBER_OF_RVA_AND_SIZES * 8)
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
        IMAGE_SCN_CNT_CODE | IMAGE_SCN_MEM_EXECUTE | IMAGE_SCN_MEM_READ,
    )
    headers = (dos + coff + optional + section).ljust(SIZE_OF_HEADERS, b"\0")
    return headers + X64_RETURN_EFI_SUCCESS.ljust(FILE_ALIGNMENT, b"\0")


def _run_command(command: list[str]) -> str:
    try:
        # No shell runs here, so file names cannot become commands.
        result = subprocess.run(  # noqa: S603
            command, check=True, capture_output=True, text=True, timeout=60
        )
    except subprocess.CalledProcessError as err:
        raise RuntimeError(f"{command[0]} failed: {err.stderr.strip()}") from err
    except subprocess.TimeoutExpired as err:
        raise RuntimeError(f"{command[0]} did not finish within 60 seconds") from err
    return result.stdout


def compute_authenticode_sha256(efi_path: Path) -> str:
    """Return the EFI file's Authenticode hash as hexadecimal text."""
    # Only the system Python has the libraries needed to hash EFI files.
    script = (
        "import sys, pefile;"
        "from virt.peutils.pesign import pe_authenticode_hash;"
        "print(pe_authenticode_hash(pefile.PE(sys.argv[1])).hex())"
    )
    return _run_command(["/usr/bin/python3", "-I", "-c", script, str(efi_path)]).strip()


def build_trusted_efi(state: FirmwareState, work_dir: Path) -> tuple[Path, list[str]]:
    """Build the EFI file; return it with the virt-fw-vars arguments that trust it."""
    unsigned_efi = work_dir / "unsigned.efi"
    unsigned_efi.write_bytes(build_minimal_efi_image(state.subsystem))
    if state.rsa_bits is None:
        return unsigned_efi, [
            "--add-db-hash",
            UGT_DB_OWNER_GUID,
            compute_authenticode_sha256(unsigned_efi),
        ]

    key_path = work_dir / "ca.key"
    cert_path = work_dir / "ca.crt"
    signed_efi = work_dir / "signed.efi"
    _run_command(
        [
            "openssl", "req", "-x509", "-newkey", f"rsa:{state.rsa_bits}", "-sha256",
            "-nodes", "-days", "3650", "-subj", f"/CN={state.ca_common_name}",
            "-keyout", str(key_path), "-out", str(cert_path),
        ]
    )  # fmt: skip
    _run_command(
        [
            "sbsign",
            "--key",
            str(key_path),
            "--cert",
            str(cert_path),
            "--output",
            str(signed_efi),
            str(unsigned_efi),
        ]
    )
    _run_command(["sbverify", "--cert", str(cert_path), str(signed_efi)])
    return signed_efi, ["--add-db", UGT_DB_OWNER_GUID, str(cert_path)]


def _install_efi_in_guest(
    runner: LibvirtImageRunner, efi_path: Path, state: FirmwareState
) -> None:
    suite_variables = {
        "UGT_EFI_FILE": str(efi_path),
        "UGT_SEED_PATH": state.seed_path,
        "UGT_EFI_LABEL": state.boot_entry_label,
        "UGT_EFI_MODE": state.efibootmgr_mode,
    }
    previous_values = {name: os.environ.get(name) for name in suite_variables}
    recovery_key = runner.recovery_key
    try:
        os.environ.update(suite_variables)
        # Keep the key out of the command line; this suite does not need it.
        runner.recovery_key = None
        exit_code = runner.run(suite=str(STAGING_SUITE_DIR), test=STAGING_TEST_NAME)
    finally:
        runner.recovery_key = recovery_key
        for name, value in previous_values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    if exit_code != 0:
        raise RuntimeError(f"Staging the EFI binary failed (exit {exit_code})")


def create_pre_os_domain(
    source_domain: str,
    state_name: str,
    new_domain_name: str,
    connection_uri: str = DEFAULT_CONNECTION_URI,
    pool_name: str = DEFAULT_POOL_NAME,
    pool_dir: Path = DEFAULT_POOL_DIR,
    *,
    artifacts_dir: Path = DEFAULT_ARTIFACTS_DIR,
) -> None:
    """Copy a stopped source domain; keep any clone and logs on failure."""
    state = FIRMWARE_STATES[state_name]
    conn = libvirt.open(connection_uri)
    if conn is None:
        raise RuntimeError(f"Unable to open libvirt connection '{connection_uri}'")
    try:
        try:
            conn.lookupByName(new_domain_name)
        except libvirt.libvirtError as err:
            if err.get_error_code() != libvirt.VIR_ERR_NO_DOMAIN:
                raise
        else:
            raise RuntimeError(
                f"Domain '{new_domain_name}' already exists; "
                "remove it or pick another name"
            )

        if conn.lookupByName(source_domain).isActive() != 0:
            raise RuntimeError(f"Source domain '{source_domain}' must be stopped")

        artifacts_dir = artifacts_dir.resolve()
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        staging_artifacts_dir = Path(
            tempfile.mkdtemp(prefix="fde-golden-", dir=artifacts_dir)
        )
        LOGGER.info("EFI staging artifacts: %s", staging_artifacts_dir)
        clone_name: str | None = None
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                work_dir = Path(temp_dir)
                efi_path, db_trust_args = build_trusted_efi(state, work_dir)
                runner = LibvirtImageRunner(
                    source_domain=source_domain,
                    # Each clone needs its own disk files, even after it is renamed.
                    suite_name=new_domain_name,
                    test_name=STAGING_TEST_NAME,
                    keep=True,
                    artifacts_dir=staging_artifacts_dir,
                    connection_uri=connection_uri,
                    pool_name=pool_name,
                    pool_dir=pool_dir,
                )
                with runner:
                    clone_name = runner.domain_name
                    _install_efi_in_guest(runner, efi_path, state)

                nvram_path = runner.pool_dir / runner.nvram_volume_name
                clone_domain = conn.lookupByName(clone_name)
                if clone_domain.isActive() != 0:
                    raise RuntimeError(f"Clone '{clone_name}' is still active")
                _run_command(
                    ["virt-fw-vars", "--inplace", str(nvram_path), *db_trust_args]
                )
            clone_domain.rename(new_domain_name, 0)
        except (RuntimeError, OSError, libvirt.libvirtError) as err:
            kept_clone_note = (
                f"; clone '{clone_name}' was kept" if clone_name is not None else ""
            )
            raise RuntimeError(
                f"{err}{kept_clone_note}; artifacts: {staging_artifacts_dir}"
            ) from err
    finally:
        conn.close()
    LOGGER.info(
        "Created '%s' (%s) from '%s'", new_domain_name, state_name, source_domain
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source-domain", required=True, help="Stopped domain to copy")
    parser.add_argument("--state", required=True, choices=sorted(FIRMWARE_STATES))
    parser.add_argument("--name", required=True, help="Name of the new domain")
    parser.add_argument("--connection-uri", default=DEFAULT_CONNECTION_URI)
    parser.add_argument("--pool-name", default=DEFAULT_POOL_NAME)
    parser.add_argument("--pool-dir", type=Path, default=DEFAULT_POOL_DIR)
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=DEFAULT_ARTIFACTS_DIR,
        help="Directory for the staging logs",
    )
    args = parser.parse_args()
    try:
        create_pre_os_domain(
            args.source_domain,
            args.state,
            args.name,
            args.connection_uri,
            args.pool_name,
            args.pool_dir,
            artifacts_dir=args.artifacts_dir,
        )
    except (RuntimeError, OSError, libvirt.libvirtError) as err:
        sys.exit(f"error: {err}")


if __name__ == "__main__":
    main()
