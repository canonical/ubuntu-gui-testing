from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock, patch

import libvirt  # type: ignore[import-untyped]
import pytest

from ubuntu_gui_testing_runner.previous import delete_previous_runs


def _domain(name: str, xml: str, *, active: int = 0) -> MagicMock:
    domain = MagicMock()
    domain.name.return_value = name
    domain.XMLDesc.return_value = xml
    domain.isActive.return_value = active
    domain.UUIDString.return_value = "11111111-2222-3333-4444-555555555555"
    return domain


def _domain_xml(disk: Path, nvram: Path, iso: Path) -> str:
    return dedent(f"""\
        <domain type="kvm">
          <name>ugt-desktop-installer-resolute.entire-disk-20260702T120000Z</name>
          <uuid>11111111-2222-3333-4444-555555555555</uuid>
          <os firmware="efi">
            <type arch="x86_64" machine="q35">hvm</type>
            <nvram>{nvram}</nvram>
          </os>
          <devices>
            <disk type="file" device="disk">
              <driver name="qemu" type="qcow2"/>
              <source file="{disk}"/>
              <target dev="vda" bus="virtio"/>
            </disk>
            <disk type="file" device="cdrom">
              <source file="{iso}"/>
              <target dev="sda" bus="sata"/>
            </disk>
          </devices>
        </domain>
    """)


def test_delete_previous_runs_deletes_matching_domain_resources(tmp_path: Path) -> None:
    disk = tmp_path / "old.qcow2"
    disk.write_bytes(b"disk")
    nvram = tmp_path / "old-VARS.fd"
    nvram.write_bytes(b"nvram")
    iso = tmp_path / "ubuntu.iso"
    iso.write_bytes(b"iso")
    tpm_dir = tmp_path / "swtpm" / "11111111-2222-3333-4444-555555555555"
    tpm_dir.mkdir(parents=True)
    (tpm_dir / "tpm2-00.permall").write_bytes(b"tpm")

    matching = _domain(
        "ugt-desktop-installer-resolute.entire-disk-20260702T120000Z",
        _domain_xml(disk, nvram, iso),
        active=1,
    )
    ignored = _domain(
        "ugt-other-suite-test-20260702T120000Z",
        _domain_xml(tmp_path / "other.qcow2", tmp_path / "other.fd", iso),
    )
    conn = MagicMock()
    conn.listAllDomains.return_value = [matching, ignored]
    pool = MagicMock()
    conn.storagePoolLookupByName.return_value = pool

    with patch("libvirt.open", return_value=conn):
        delete_previous_runs(
            suite_name="desktop-installer",
            test_name="resolute.entire-disk",
            connection_uri="qemu:///session",
            pool_name="ubuntu-gui-testing",
            swtpm_state_dir=tmp_path / "swtpm",
            pool_dir=tmp_path,
        )

    matching.destroy.assert_called_once()
    matching.undefineFlags.assert_called_once_with(libvirt.VIR_DOMAIN_UNDEFINE_NVRAM)
    matching.undefine.assert_not_called()
    ignored.destroy.assert_not_called()
    ignored.undefine.assert_not_called()
    assert not disk.exists()
    assert not nvram.exists()
    assert not tpm_dir.exists()
    assert iso.exists()
    pool.refresh.assert_called()
    conn.close.assert_called_once()


def test_delete_previous_runs_supports_nvram_source_attribute(tmp_path: Path) -> None:
    disk = tmp_path / "old.qcow2"
    disk.write_bytes(b"disk")
    nvram = tmp_path / "old-VARS.fd"
    nvram.write_bytes(b"nvram")
    xml = dedent(f"""\
        <domain type="kvm">
          <uuid>11111111-2222-3333-4444-555555555555</uuid>
          <os firmware="efi">
            <nvram source="{nvram}"/>
          </os>
          <devices>
            <disk type="file" device="disk">
              <source file="{disk}"/>
            </disk>
          </devices>
        </domain>
    """)
    matching = _domain(
        "ugt-desktop-installer-resolute.entire-disk-20260702T120000Z-2",
        xml,
    )
    conn = MagicMock()
    conn.listAllDomains.return_value = [matching]
    conn.storagePoolLookupByName.side_effect = libvirt.libvirtError("no pool")

    with patch("libvirt.open", return_value=conn):
        delete_previous_runs(
            suite_name="desktop-installer",
            test_name="resolute.entire-disk",
            connection_uri="qemu:///session",
            pool_name="ubuntu-gui-testing",
            swtpm_state_dir=tmp_path / "swtpm",
            pool_dir=tmp_path,
        )

    matching.destroy.assert_not_called()
    matching.undefineFlags.assert_called_once_with(libvirt.VIR_DOMAIN_UNDEFINE_NVRAM)
    matching.undefine.assert_not_called()
    assert not disk.exists()
    assert not nvram.exists()


def test_delete_previous_runs_preserves_uppercase_iso_path(tmp_path: Path) -> None:
    disk = tmp_path / "old.qcow2"
    disk.write_bytes(b"disk")
    iso = tmp_path / "UBUNTU.ISO"
    iso.write_bytes(b"iso")
    xml = dedent(f"""\
        <domain type="kvm">
          <uuid>11111111-2222-3333-4444-555555555555</uuid>
          <os firmware="efi">
            <nvram>{iso}</nvram>
          </os>
          <devices>
            <disk type="file" device="disk">
              <source file="{disk}"/>
            </disk>
          </devices>
        </domain>
    """)
    matching = _domain(
        "ugt-desktop-installer-resolute.entire-disk-20260702T120000Z",
        xml,
    )
    conn = MagicMock()
    conn.listAllDomains.return_value = [matching]
    conn.storagePoolLookupByName.side_effect = libvirt.libvirtError("no pool")

    with patch("libvirt.open", return_value=conn):
        delete_previous_runs(
            suite_name="desktop-installer",
            test_name="resolute.entire-disk",
            connection_uri="qemu:///session",
            pool_name="ubuntu-gui-testing",
            swtpm_state_dir=tmp_path / "swtpm",
            pool_dir=tmp_path,
        )

    assert not disk.exists()
    assert iso.exists()


def test_delete_previous_runs_skips_files_outside_pool_dir(tmp_path: Path) -> None:
    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()
    outside_disk = tmp_path / "outside.qcow2"
    outside_disk.write_bytes(b"disk")
    nvram = pool_dir / "old-VARS.fd"
    nvram.write_bytes(b"nvram")
    xml = dedent(f"""\
        <domain type="kvm">
          <uuid>11111111-2222-3333-4444-555555555555</uuid>
          <os firmware="efi">
            <nvram>{nvram}</nvram>
          </os>
          <devices>
            <disk type="file" device="disk">
              <source file="{outside_disk}"/>
            </disk>
          </devices>
        </domain>
    """)
    matching = _domain(
        "ugt-desktop-installer-resolute.entire-disk-20260702T120000Z",
        xml,
    )
    conn = MagicMock()
    conn.listAllDomains.return_value = [matching]
    conn.storagePoolLookupByName.side_effect = libvirt.libvirtError("no pool")

    with patch("libvirt.open", return_value=conn):
        delete_previous_runs(
            suite_name="desktop-installer",
            test_name="resolute.entire-disk",
            connection_uri="qemu:///session",
            pool_name="ubuntu-gui-testing",
            swtpm_state_dir=tmp_path / "swtpm",
            pool_dir=pool_dir,
        )

    assert outside_disk.exists()
    assert not nvram.exists()


def test_delete_previous_runs_wraps_libvirt_open_error(tmp_path: Path) -> None:
    with (
        patch("libvirt.open", side_effect=libvirt.libvirtError("boom")),
        pytest.raises(RuntimeError, match="Unable to open libvirt connection"),
    ):
        delete_previous_runs(
            suite_name="desktop-installer",
            test_name="resolute.entire-disk",
            connection_uri="qemu:///session",
            pool_name="ubuntu-gui-testing",
            swtpm_state_dir=tmp_path / "swtpm",
            pool_dir=tmp_path,
        )
