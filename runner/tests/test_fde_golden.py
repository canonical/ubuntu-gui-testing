from __future__ import annotations

import json
import shutil
import ssl
import struct
from pathlib import Path

import pytest

from ubuntu_gui_testing_runner.fde_golden import (
    EFI_APPLICATION,
    EFI_BOOT_SERVICE_DRIVER,
    FIRMWARE_STATES,
    STAGING_SUITE_DIR,
    STAGING_TEST_NAME,
    _run_command,
    build_minimal_efi_image,
    build_trusted_efi,
)

SYSTEM_VIRT_FIRMWARE = Path("/usr/lib/python3/dist-packages/virt/firmware").is_dir()
OVMF_VARS_TEMPLATE = Path("/usr/share/OVMF/OVMF_VARS_4M.ms.fd")


@pytest.mark.parametrize("subsystem", [EFI_APPLICATION, EFI_BOOT_SERVICE_DRIVER])
def test_minimal_efi_image_sets_subsystem(subsystem: int) -> None:
    image = build_minimal_efi_image(subsystem)
    pe_offset = struct.unpack_from("<I", image, 0x3C)[0]
    assert image[:2] == b"MZ"
    assert image[pe_offset : pe_offset + 4] == b"PE\0\0"
    optional_header_offset = pe_offset + 24
    assert struct.unpack_from("<H", image, optional_header_offset + 68)[0] == subsystem


def test_staging_suite_is_self_contained_outside_security_center() -> None:
    test_dir = STAGING_SUITE_DIR / STAGING_TEST_NAME.lower()
    security_center_dir = STAGING_SUITE_DIR.parents[2] / "tests/desktop-security-center"
    assert (test_dir / f"{test_dir.name}.robot").is_file()
    assert (STAGING_SUITE_DIR / "common/guest-shell.resource").is_file()
    assert not STAGING_SUITE_DIR.is_relative_to(security_center_dir)


@pytest.mark.skipif(
    not (
        SYSTEM_VIRT_FIRMWARE
        and OVMF_VARS_TEMPLATE.is_file()
        and all(
            shutil.which(tool)
            for tool in ("openssl", "sbsign", "sbverify", "virt-fw-vars")
        )
    ),
    reason="needs python3-virt-firmware, sbsigntool, OpenSSL and the OVMF template",
)
@pytest.mark.parametrize("state_name", sorted(FIRMWARE_STATES))
def test_trust_arguments_add_db_entry_to_nvram(state_name: str, tmp_path: Path) -> None:
    state = FIRMWARE_STATES[state_name]
    efi_path, db_trust_args = build_trusted_efi(state, tmp_path)
    vars_path = tmp_path / "VARS.fd"
    shutil.copy(OVMF_VARS_TEMPLATE, vars_path)

    _run_command(["virt-fw-vars", "--inplace", str(vars_path), *db_trust_args])
    dump_path = tmp_path / "dump.json"
    _run_command(
        ["virt-fw-vars", "-i", str(vars_path), "--output-json", str(dump_path)]
    )
    stored_variables = {
        variable["name"]: variable["data"]
        for variable in json.loads(dump_path.read_text())["variables"]
    }

    if state.rsa_bits is None:
        expected_db_entry = db_trust_args[2]
    else:
        certificate_pem = Path(db_trust_args[2]).read_text()
        expected_db_entry = ssl.PEM_cert_to_DER_cert(certificate_pem).hex()
    assert expected_db_entry in stored_variables["db"]
    assert efi_path.is_file()
