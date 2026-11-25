from __future__ import annotations

import json
import shutil
import ssl
import struct
import uuid
from pathlib import Path

import pytest

from ubuntu_gui_testing_runner.fde_golden import (
    AUTH_STATES,
    EFI_APPLICATION,
    EFI_BOOT_SERVICE_DRIVER,
    ENROLL_TEST,
    HOST_STATES,
    PLAIN_OVMF_CODE,
    PLAIN_OVMF_VARS,
    STATES,
    SUITE,
    TEST,
    SeedPartition,
    _run,
    build_efi,
    load_option,
    load_option_variables,
    minimal_efi_image,
    with_plain_ovmf,
    without_tpm,
)

PART = SeedPartition(
    2, 2048, 2457600, uuid.UUID("0fc63daf-8483-4772-8e79-3d69d8477de4")
)
SYSTEM_VIRT_FIRMWARE = Path("/usr/lib/python3/dist-packages/virt/firmware").is_dir()


def test_parses_seed_partition() -> None:
    assert SeedPartition.parse(f"2 2048 2457600 {PART.unique_guid}\n") == PART


@pytest.mark.parametrize("text", ["", "2 2048 2457600", "x 2048 2457600 " + "0" * 32])
def test_rejects_malformed_seed_partition(text: str) -> None:
    with pytest.raises(ValueError):
        SeedPartition.parse(text)


@pytest.mark.parametrize("subsystem", [EFI_APPLICATION, EFI_BOOT_SERVICE_DRIVER])
def test_minimal_efi_image_sets_subsystem(subsystem: int) -> None:
    image = minimal_efi_image(subsystem)
    pe_offset = struct.unpack_from("<I", image, 0x3C)[0]
    assert image[:2] == b"MZ"
    assert image[pe_offset : pe_offset + 4] == b"PE\0\0"
    # Subsystem sits 68 bytes into the PE32+ optional header.
    assert struct.unpack_from("<H", image, pe_offset + 24 + 68)[0] == subsystem


def test_load_option_points_at_file_on_seed() -> None:
    option = load_option("UGT Driver", "/EFI/ugt/x.efi", PART)
    attributes, path_length = struct.unpack_from("<IH", option)
    description = "UGT Driver\0".encode("utf-16-le")
    device_path = option[6 + len(description) :]

    assert attributes == 1
    assert option[6 : 6 + len(description)] == description
    assert len(device_path) == path_length
    assert device_path[:4] == bytes((4, 1, 42, 0))
    assert struct.unpack_from("<IQQ16s", device_path, 4) == (
        2,
        2048,
        2457600,
        PART.unique_guid.bytes_le,
    )
    assert "\\EFI\\ugt\\x.efi\0".encode("utf-16-le") in device_path
    assert device_path.endswith(bytes((0x7F, 0xFF, 4, 0)))


def test_variables_set_option_and_order_for_sysprep() -> None:
    variables = load_option_variables(STATES["sysprep-app"], PART)["variables"]
    assert [v["name"] for v in variables] == ["SysPrep0001", "SysPrepOrder"]
    assert variables[1]["data"] == "0100"


@pytest.mark.parametrize("test", [TEST, ENROLL_TEST])
def test_suite_contains_the_test(test: str) -> None:
    # YARF copies only --suite to a temporary directory, so the suite must be
    # the parent that holds common/ and select the test by name.
    robot = SUITE / test.lower() / f"{test.lower()}.robot"
    assert robot.is_file()
    assert (SUITE / "common/guest-shell.resource").is_file()


@pytest.mark.skipif(
    not (SYSTEM_VIRT_FIRMWARE and shutil.which("sbsign")),
    reason="needs python3-virt-firmware and sbsigntool",
)
@pytest.mark.parametrize("state", sorted(STATES))
def test_build_efi_produces_db_entry_the_firmware_accepts(
    state: str, tmp_path: Path
) -> None:
    efi, db_args = build_efi(STATES[state], tmp_path)
    vars_file = tmp_path / "VARS.fd"
    shutil.copy("/usr/share/OVMF/OVMF_VARS_4M.ms.fd", vars_file)
    json_file = tmp_path / "vars.json"
    json_file.write_text(json.dumps(load_option_variables(STATES[state], PART)))

    _run(
        [
            "virt-fw-vars",
            "--inplace",
            str(vars_file),
            *db_args,
            "--set-json",
            str(json_file),
        ]
    )
    dump = tmp_path / "dump.json"
    _run(["virt-fw-vars", "-i", str(vars_file), "--output-json", str(dump)])
    stored = {v["name"]: v["data"] for v in json.loads(dump.read_text())["variables"]}

    option = load_option(STATES[state].description, STATES[state].seed_path, PART)
    assert stored[f"{STATES[state].variable}0001"] == option.hex()
    assert stored[f"{STATES[state].variable}Order"] == "0100"
    if STATES[state].rsa_bits is None:
        trusted = db_args[2]
    else:
        trusted = ssl.PEM_cert_to_DER_cert(Path(db_args[2]).read_text()).hex()
    assert trusted in stored["db"]
    assert efi.is_file()


DOMAIN_XML = """<domain><os firmware="efi"><firmware>\
<feature enabled="yes" name="enrolled-keys"/>\
<feature enabled="yes" name="secure-boot"/>\
</firmware><loader readonly="yes" secure="yes" type="pflash">\
/usr/share/OVMF/OVMF_CODE_4M.ms.fd</loader>\
<nvram template="/usr/share/OVMF/OVMF_VARS_4M.ms.fd">/x.fd</nvram></os>\
<devices><disk/><tpm model="tpm-crb"/></devices></domain>"""


def test_without_tpm_keeps_other_devices() -> None:
    xml = without_tpm(DOMAIN_XML)
    assert "<tpm" not in xml
    assert "<disk" in xml
    with pytest.raises(ValueError):
        without_tpm(xml)


def test_plain_ovmf_drops_secure_boot() -> None:
    xml = with_plain_ovmf(DOMAIN_XML)
    assert f">{PLAIN_OVMF_CODE}</loader>" in xml
    assert 'secure="no"' in xml
    assert 'enabled="yes"' not in xml
    assert f'<nvram template="{PLAIN_OVMF_VARS}">/x.fd</nvram>' in xml


def test_host_and_guest_state_names_are_distinct() -> None:
    names = [*HOST_STATES, *STATES, *AUTH_STATES]
    assert len(names) == len(set(names))
