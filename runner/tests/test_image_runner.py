from __future__ import annotations

import asyncio
from pathlib import Path
from textwrap import dedent
from unittest.mock import AsyncMock, MagicMock, patch

import libvirt  # type: ignore[import-untyped]
import pytest

from ubuntu_gui_testing_runner.image_runner import LibvirtImageRunner

SOURCE_DOMAIN_XML = dedent("""\
    <domain type="kvm">
      <name>source</name>
      <uuid>aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee</uuid>
      <os firmware="efi">
        <type arch="x86_64" machine="q35">hvm</type>
        <nvram>/pool/source-VARS.fd</nvram>
      </os>
      <devices>
        <disk type="file" device="disk">
          <driver name="qemu" type="qcow2"/>
          <source file="/pool/source.qcow2"/>
          <target dev="vda" bus="virtio"/>
        </disk>
      </devices>
    </domain>
""")

SOURCE_DOMAIN_XML_NO_DISK = dedent("""\
    <domain type="kvm">
      <name>source</name>
      <uuid>aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee</uuid>
      <os firmware="efi">
        <type arch="x86_64" machine="q35">hvm</type>
        <nvram>/pool/source-VARS.fd</nvram>
      </os>
      <devices>
      </devices>
    </domain>
""")

SOURCE_DOMAIN_XML_NO_NVRAM = dedent("""\
    <domain type="kvm">
      <name>source</name>
      <uuid>aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee</uuid>
      <os firmware="efi">
        <type arch="x86_64" machine="q35">hvm</type>
      </os>
      <devices>
        <disk type="file" device="disk">
          <source file="/pool/source.qcow2"/>
          <target dev="vda" bus="virtio"/>
        </disk>
      </devices>
    </domain>
""")

SOURCE_DOMAIN_XML_WITH_RECOVERY_KEY = dedent("""\
        <domain type="kvm">
            <name>source</name>
            <uuid>aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee</uuid>
            <metadata>
                <ugt:ugt xmlns:ugt="https://canonical.com/ubuntu-gui-testing">
                    <ugt:recovery-key>12345-67890-11111-22222-33333-44444-55555-66666</ugt:recovery-key>
                </ugt:ugt>
            </metadata>
            <os firmware="efi">
                <type arch="x86_64" machine="q35">hvm</type>
                <nvram>/pool/source-VARS.fd</nvram>
            </os>
            <devices>
                <disk type="file" device="disk">
                    <source file="/pool/source.qcow2"/>
                    <target dev="vda" bus="virtio"/>
                </disk>
            </devices>
        </domain>
""")

SOURCE_DOMAIN_XML_WITH_EMPTY_RECOVERY_KEY = dedent("""\
        <domain type="kvm">
            <name>source</name>
            <uuid>aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee</uuid>
            <metadata>
                <ugt:ugt xmlns:ugt="https://canonical.com/ubuntu-gui-testing">
                    <ugt:recovery-key>   </ugt:recovery-key>
                </ugt:ugt>
            </metadata>
            <os firmware="efi">
                <type arch="x86_64" machine="q35">hvm</type>
                <nvram>/pool/source-VARS.fd</nvram>
            </os>
            <devices>
                <disk type="file" device="disk">
                    <source file="/pool/source.qcow2"/>
                    <target dev="vda" bus="virtio"/>
                </disk>
            </devices>
        </domain>
""")


def _make_conn(
    source_xml: str = SOURCE_DOMAIN_XML,
    source_exists: bool = True,
) -> MagicMock:
    conn = MagicMock()

    source_domain = MagicMock()
    source_domain.XMLDesc.return_value = source_xml
    source_domain.isActive.return_value = 0

    def lookup(name: str) -> MagicMock:
        if name == "source" and source_exists:
            return source_domain
        raise libvirt.libvirtError("not found")

    conn.lookupByName.side_effect = lookup

    pool = MagicMock()
    volume = MagicMock()
    volume.path.return_value = "/pool/test-overlay.qcow2"
    pool.createXML.return_value = volume
    pool.isActive.return_value = 1
    conn.storagePoolLookupByName.return_value = pool

    defined_domain = MagicMock()
    defined_domain.UUIDString.return_value = "11111111-2222-3333-4444-555555555555"
    conn.defineXML.return_value = defined_domain

    return conn


def test_raises_when_source_domain_not_found(tmp_path: Path) -> None:
    conn = _make_conn(source_exists=False)

    with (
        patch("libvirt.open", return_value=conn),
        pytest.raises(RuntimeError, match="not found"),
    ):
        LibvirtImageRunner(
            source_domain="source",
            suite_name="test",
            test_name="basic",
            pool_dir=tmp_path,
        )


def test_raises_when_source_has_no_disk_image(tmp_path: Path) -> None:
    conn = _make_conn(source_xml=SOURCE_DOMAIN_XML_NO_DISK)

    with (
        patch("libvirt.open", return_value=conn),
        pytest.raises(RuntimeError, match="No disk image found"),
    ):
        LibvirtImageRunner(
            source_domain="source",
            suite_name="test",
            test_name="basic",
            pool_dir=tmp_path,
        )


def test_raises_when_source_has_no_nvram(tmp_path: Path) -> None:
    conn = _make_conn(source_xml=SOURCE_DOMAIN_XML_NO_NVRAM)

    with (
        patch("libvirt.open", return_value=conn),
        pytest.raises(RuntimeError, match="No NVRAM path found"),
    ):
        LibvirtImageRunner(
            source_domain="source",
            suite_name="test",
            test_name="basic",
            pool_dir=tmp_path,
        )


def test_copies_nvram_to_pool_directory(tmp_path: Path) -> None:
    # Create a fake NVRAM source file
    nvram_source = tmp_path / "source-VARS.fd"
    nvram_source.write_bytes(b"nvram-data")

    # Patch the source XML to use our tmp_path NVRAM
    source_xml = SOURCE_DOMAIN_XML.replace("/pool/source-VARS.fd", str(nvram_source))
    conn = _make_conn(source_xml=source_xml)

    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()

    with patch("libvirt.open", return_value=conn):
        runner = LibvirtImageRunner(
            source_domain="source",
            suite_name="test",
            test_name="basic",
            pool_dir=pool_dir,
        )
        try:
            nvram_dest = pool_dir / runner.nvram_volume_name
            assert nvram_dest.exists()
            assert nvram_dest.read_bytes() == b"nvram-data"
        finally:
            runner.close()


def test_copies_tpm_state_when_source_exists(tmp_path: Path) -> None:
    # Create fake source TPM state
    source_tpm_dir = tmp_path / "swtpm" / "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    source_tpm_dir.mkdir(parents=True)
    (source_tpm_dir / "tpm2-00.permall").write_bytes(b"tpm-state")

    # Create a fake NVRAM source
    nvram_source = tmp_path / "source-VARS.fd"
    nvram_source.write_bytes(b"nvram-data")

    source_xml = SOURCE_DOMAIN_XML.replace("/pool/source-VARS.fd", str(nvram_source))
    conn = _make_conn(source_xml=source_xml)

    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()

    with patch("libvirt.open", return_value=conn):
        runner = LibvirtImageRunner(
            source_domain="source",
            suite_name="test",
            test_name="basic",
            pool_dir=pool_dir,
            swtpm_state_dir=tmp_path / "swtpm",
        )
        dest_tpm_dir = tmp_path / "swtpm" / "11111111-2222-3333-4444-555555555555"
        try:
            assert (dest_tpm_dir / "tpm2-00.permall").read_bytes() == b"tpm-state"
        finally:
            runner.close()
        assert not dest_tpm_dir.exists()
        assert source_tpm_dir.exists()


def test_skips_tpm_copy_when_source_has_no_tpm_state(tmp_path: Path) -> None:
    # No TPM directory exists for the source UUID
    nvram_source = tmp_path / "source-VARS.fd"
    nvram_source.write_bytes(b"nvram-data")

    source_xml = SOURCE_DOMAIN_XML.replace("/pool/source-VARS.fd", str(nvram_source))
    conn = _make_conn(source_xml=source_xml)

    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()

    swtpm_dir = tmp_path / "swtpm"
    swtpm_dir.mkdir()

    with (
        patch("libvirt.open", return_value=conn),
        patch(
            "ubuntu_gui_testing_runner.image_runner.DEFAULT_SWTPM_STATE_DIR",
            swtpm_dir,
        ),
    ):
        runner = LibvirtImageRunner(
            source_domain="source",
            suite_name="test",
            test_name="basic",
            pool_dir=pool_dir,
        )
        try:
            # Should not raise; TPM copy is simply skipped
            dest_tpm_dir = swtpm_dir / "11111111-2222-3333-4444-555555555555"
            assert not dest_tpm_dir.exists()
        finally:
            runner.close()


def test_extracts_recovery_key_from_source_metadata(tmp_path: Path) -> None:
    nvram_source = tmp_path / "source-VARS.fd"
    nvram_source.write_bytes(b"nvram-data")

    source_xml = SOURCE_DOMAIN_XML_WITH_RECOVERY_KEY.replace(
        "/pool/source-VARS.fd", str(nvram_source)
    )
    conn = _make_conn(source_xml=source_xml)

    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()

    with patch("libvirt.open", return_value=conn):
        runner = LibvirtImageRunner(
            source_domain="source",
            suite_name="test",
            test_name="basic",
            pool_dir=pool_dir,
        )
        try:
            assert (
                runner.recovery_key == "12345-67890-11111-22222-33333-44444-55555-66666"
            )
        finally:
            runner.close()


def test_copies_recovery_key_metadata_to_clone(tmp_path: Path) -> None:
    nvram_source = tmp_path / "source-VARS.fd"
    nvram_source.write_bytes(b"nvram-data")

    source_xml = SOURCE_DOMAIN_XML_WITH_RECOVERY_KEY.replace(
        "/pool/source-VARS.fd", str(nvram_source)
    )
    conn = _make_conn(source_xml=source_xml)

    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()

    with patch("libvirt.open", return_value=conn):
        runner = LibvirtImageRunner(
            source_domain="source",
            suite_name="test",
            test_name="basic",
            pool_dir=pool_dir,
        )
        try:
            conn.defineXML.return_value.setMetadata.assert_called_once_with(
                libvirt.VIR_DOMAIN_METADATA_ELEMENT,
                "<ugt><recovery-key>12345-67890-11111-22222-33333-44444-55555-66666</recovery-key></ugt>",
                "ugt",
                "https://canonical.com/ubuntu-gui-testing",
                libvirt.VIR_DOMAIN_AFFECT_CONFIG,
            )
        finally:
            runner.close()


def test_clone_without_recovery_key_gets_no_metadata(tmp_path: Path) -> None:
    nvram_source = tmp_path / "source-VARS.fd"
    nvram_source.write_bytes(b"nvram-data")
    conn = _make_conn(
        source_xml=SOURCE_DOMAIN_XML.replace("/pool/source-VARS.fd", str(nvram_source))
    )

    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()

    with patch("libvirt.open", return_value=conn):
        runner = LibvirtImageRunner(
            source_domain="source",
            suite_name="test",
            test_name="basic",
            pool_dir=pool_dir,
        )
        try:
            conn.defineXML.return_value.setMetadata.assert_not_called()
        finally:
            runner.close()


def test_run_yarf_passes_recovery_key_variable_when_present(tmp_path: Path) -> None:
    nvram_source = tmp_path / "source-VARS.fd"
    nvram_source.write_bytes(b"nvram-data")

    source_xml = SOURCE_DOMAIN_XML_WITH_RECOVERY_KEY.replace(
        "/pool/source-VARS.fd", str(nvram_source)
    )
    conn = _make_conn(source_xml=source_xml)

    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()

    with patch("libvirt.open", return_value=conn):
        runner = LibvirtImageRunner(
            source_domain="source",
            suite_name="test",
            test_name="basic",
            pool_dir=pool_dir,
        )
        try:
            mock_process = AsyncMock()
            mock_process.wait = AsyncMock(return_value=0)
            mock_process.returncode = 0
            with patch.object(
                runner, "_spawn_yarf", return_value=mock_process
            ) as spawn:
                asyncio.run(runner._run_yarf("suite", "test", 3, 5901))

            spawn.assert_called_once_with(
                "suite",
                "test",
                5901,
                robot_variables={
                    "CID": "3",
                    "RECOVERY_KEY": "12345-67890-11111-22222-33333-44444-55555-66666",
                },
            )
        finally:
            runner.close()


def test_run_yarf_passes_device_when_mount_source_domain_is_enabled(
    tmp_path: Path,
) -> None:
    nvram_source = tmp_path / "source-VARS.fd"
    nvram_source.write_bytes(b"nvram-data")

    source_xml = SOURCE_DOMAIN_XML.replace("/pool/source-VARS.fd", str(nvram_source))
    conn = _make_conn(source_xml=source_xml)

    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()

    with patch("libvirt.open", return_value=conn):
        runner = LibvirtImageRunner(
            source_domain="source",
            suite_name="test",
            test_name="basic",
            pool_dir=pool_dir,
            mount_source_domain="/dev/sdb",
        )
        try:
            mock_process = AsyncMock()
            mock_process.wait = AsyncMock(return_value=0)
            mock_process.returncode = 0
            with patch.object(
                runner, "_spawn_yarf", return_value=mock_process
            ) as spawn:
                asyncio.run(runner._run_yarf("suite", "test", 3, 5901))

            spawn.assert_called_once_with(
                "suite",
                "test",
                5901,
                robot_variables={"CID": "3", "DEVICE": "/dev/sdb"},
            )
        finally:
            runner.close()


def test_mount_source_domain_uses_matching_usb_target(
    tmp_path: Path,
) -> None:
    nvram_source = tmp_path / "source-VARS.fd"
    nvram_source.write_bytes(b"nvram-data")

    source_xml = SOURCE_DOMAIN_XML.replace("/pool/source-VARS.fd", str(nvram_source))
    conn = _make_conn(source_xml=source_xml)

    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()

    with patch("libvirt.open", return_value=conn):
        runner = LibvirtImageRunner(
            source_domain="source",
            suite_name="test",
            test_name="basic",
            pool_dir=pool_dir,
            mount_source_domain="/dev/sdb1",
        )
        try:
            domain_xml = conn.defineXML.call_args.args[0]
            assert '<target dev="sdb" bus="usb"' in domain_xml
        finally:
            runner.close()


def test_logs_when_recovery_key_metadata_missing(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    nvram_source = tmp_path / "source-VARS.fd"
    nvram_source.write_bytes(b"nvram-data")

    source_xml = SOURCE_DOMAIN_XML.replace("/pool/source-VARS.fd", str(nvram_source))
    conn = _make_conn(source_xml=source_xml)

    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()

    with patch("libvirt.open", return_value=conn), caplog.at_level("INFO"):
        runner = LibvirtImageRunner(
            source_domain="source",
            suite_name="test",
            test_name="basic",
            pool_dir=pool_dir,
        )
        try:
            assert runner.recovery_key is None
            assert (
                "No metadata block found in source domain 'source' XML" in caplog.text
            )
        finally:
            runner.close()


def test_logs_when_recovery_key_metadata_empty(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    nvram_source = tmp_path / "source-VARS.fd"
    nvram_source.write_bytes(b"nvram-data")

    source_xml = SOURCE_DOMAIN_XML_WITH_EMPTY_RECOVERY_KEY.replace(
        "/pool/source-VARS.fd", str(nvram_source)
    )
    conn = _make_conn(source_xml=source_xml)

    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()

    with patch("libvirt.open", return_value=conn), caplog.at_level("WARNING"):
        runner = LibvirtImageRunner(
            source_domain="source",
            suite_name="test",
            test_name="basic",
            pool_dir=pool_dir,
        )
        try:
            assert runner.recovery_key is None
            assert (
                "Recovery key metadata in source domain 'source' is empty"
                in caplog.text
            )
        finally:
            runner.close()


def _runner(tmp_path: Path, source_xml: str, conn: MagicMock | None = None, **kwargs):  # type: ignore[no-untyped-def]
    nvram_source = tmp_path / "source-VARS.fd"
    nvram_source.write_bytes(b"nvram-data")
    conn = conn or _make_conn(
        source_xml=source_xml.replace("/pool/source-VARS.fd", str(nvram_source))
    )
    pool_dir = tmp_path / "pool"
    pool_dir.mkdir(exist_ok=True)
    with patch("libvirt.open", return_value=conn):
        return conn, LibvirtImageRunner(
            source_domain="source",
            suite_name="test",
            test_name="basic",
            pool_dir=pool_dir,
            **kwargs,
        )


def test_refuses_running_source_domain(tmp_path: Path) -> None:
    conn = _make_conn()
    conn.lookupByName("source").isActive.return_value = 1
    with pytest.raises(RuntimeError, match="is running"):
        _runner(tmp_path, SOURCE_DOMAIN_XML, conn)


def test_clone_keeps_source_firmware_and_tpm(tmp_path: Path) -> None:
    source_xml = SOURCE_DOMAIN_XML.replace(
        "<nvram>",
        '<firmware><feature enabled="no" name="secure-boot"/></firmware>'
        '<loader readonly="yes" type="pflash">/usr/share/OVMF/OVMF_CODE_4M.fd</loader>'
        "<nvram>",
    ).replace("</devices>", '<tpm model="tpm-crb"/></devices>')
    conn, runner = _runner(tmp_path, source_xml)
    try:
        defined = conn.defineXML.call_args.args[0]
        assert ">/usr/share/OVMF/OVMF_CODE_4M.fd</loader>" in defined
        assert "OVMF_CODE_4M.ms.fd" not in defined
        assert '<feature enabled="no" name="secure-boot"' in defined
        assert 'enabled="yes"' not in defined
        assert "<tpm" in defined
    finally:
        runner.close()


def test_clone_has_no_tpm_when_source_has_none(tmp_path: Path) -> None:
    conn, runner = _runner(tmp_path, SOURCE_DOMAIN_XML)
    try:
        defined = conn.defineXML.call_args.args[0]
        assert "<tpm" not in defined
        # No loader in the source: the template's Secure Boot loader stays.
        assert "OVMF_CODE_4M.ms.fd" in defined
    finally:
        runner.close()
