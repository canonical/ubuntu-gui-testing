from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from textwrap import dedent
from types import SimpleNamespace
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import defusedxml.ElementTree as ET
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

SOURCE_DOMAIN_XML_WITH_TPM = dedent("""\
    <domain type="kvm">
      <name>source</name>
      <uuid>aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee</uuid>
      <os firmware="efi">
        <type arch="x86_64" machine="q35">hvm</type>
        <nvram>/pool/source-VARS.fd</nvram>
      </os>
      <devices>
        <disk type="file" device="disk">
          <source file="/pool/source.qcow2"/>
          <target dev="vda" bus="virtio"/>
        </disk>
        <tpm model="tpm-crb">
          <backend type="emulator" version="2.0" persistent_state="yes"/>
        </tpm>
      </devices>
    </domain>
""")

_TPM_DEVICE_XML = dedent("""\
            <tpm model="tpm-crb">
              <backend type="emulator" version="2.0" persistent_state="yes"/>
            </tpm>
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


def test_rejects_running_source_without_creating_writable_clone(tmp_path: Path) -> None:
    nvram = tmp_path / "source-VARS.fd"
    nvram.write_bytes(b"original-nvram")
    conn = _make_conn(SOURCE_DOMAIN_XML.replace("/pool/source-VARS.fd", str(nvram)))
    source = conn.lookupByName("source")
    source.isActive.return_value = 1

    with (
        patch("libvirt.open", return_value=conn),
        pytest.raises(RuntimeError),
        LibvirtImageRunner(
            source_domain="source",
            suite_name="test",
            test_name="basic",
            pool_dir=tmp_path,
        ),
    ):
        pass

    conn.storagePoolLookupByName.return_value.createXML.assert_not_called()
    conn.defineXML.assert_not_called()
    source.destroy.assert_not_called()
    assert nvram.read_bytes() == b"original-nvram"


def _source_tpm_state(tmp_path: Path) -> Path:
    tpm_state = tmp_path / "swtpm" / "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    tpm_state.mkdir(parents=True)
    (tpm_state / "tpm2-00.permall").write_bytes(b"tpm-state")
    return tpm_state


def _fde_runner(
    tmp_path: Path,
    source_xml: str,
    **kwargs: Any,
) -> LibvirtImageRunner:
    nvram = tmp_path / "source-VARS.fd"
    nvram.write_bytes(b"nvram-data")
    pool_dir = tmp_path / "pool"
    pool_dir.mkdir(exist_ok=True)
    return LibvirtImageRunner(
        source_domain="source",
        suite_name="test",
        test_name="basic",
        pool_dir=pool_dir,
        **kwargs,
    )


def test_fde_mode_requires_a_single_selected_robot_case(
    tmp_path: Path, fde_config: Path
) -> None:
    conn = _make_conn(SOURCE_DOMAIN_XML_WITH_TPM)

    with patch("libvirt.open", return_value=conn), pytest.raises(RuntimeError):
        _fde_runner(tmp_path, SOURCE_DOMAIN_XML_WITH_TPM, fde_config=fde_config)

    conn.defineXML.assert_not_called()
    conn.storagePoolLookupByName.return_value.createXML.assert_not_called()


def test_fde_mode_rejects_source_without_tpm_device(
    tmp_path: Path, fde_config: Path
) -> None:
    conn = _make_conn(SOURCE_DOMAIN_XML)
    _source_tpm_state(tmp_path)

    with (
        patch("libvirt.open", return_value=conn),
        pytest.raises(RuntimeError, match="TPM device"),
    ):
        _fde_runner(
            tmp_path,
            SOURCE_DOMAIN_XML,
            fde_config=fde_config,
            robot_test="TPM clear recovery reprovision",
            swtpm_state_dir=tmp_path / "swtpm",
        )

    conn.defineXML.assert_not_called()
    conn.storagePoolLookupByName.return_value.createXML.assert_not_called()


def test_fde_mode_rejects_missing_source_tpm_state(
    tmp_path: Path, fde_config: Path
) -> None:
    conn = _make_conn(SOURCE_DOMAIN_XML_WITH_TPM)
    (tmp_path / "swtpm").mkdir()

    with (
        patch("libvirt.open", return_value=conn),
        pytest.raises(RuntimeError, match="TPM state"),
    ):
        _fde_runner(
            tmp_path,
            SOURCE_DOMAIN_XML_WITH_TPM,
            fde_config=fde_config,
            robot_test="TPM clear recovery reprovision",
            swtpm_state_dir=tmp_path / "swtpm",
        )

    conn.defineXML.assert_not_called()
    conn.storagePoolLookupByName.return_value.createXML.assert_not_called()


def test_fde_mode_copies_tpm_state_from_configured_directory(
    tmp_path: Path,
    fde_config: Path,
) -> None:
    conn = _make_conn(
        SOURCE_DOMAIN_XML_WITH_TPM.replace(
            "/pool/source-VARS.fd", str(tmp_path / "source-VARS.fd")
        )
    )
    _source_tpm_state(tmp_path)

    with patch("libvirt.open", return_value=conn):
        runner = _fde_runner(
            tmp_path,
            SOURCE_DOMAIN_XML_WITH_TPM,
            fde_config=fde_config,
            robot_test="TPM clear recovery reprovision",
            swtpm_state_dir=tmp_path / "swtpm",
        )
        try:
            clone_tpm_dir = tmp_path / "swtpm" / "11111111-2222-3333-4444-555555555555"
            assert (clone_tpm_dir / "tpm2-00.permall").read_bytes() == b"tpm-state"
        finally:
            runner.close()


def test_fde_mode_passes_only_private_configuration_to_robot(
    tmp_path: Path,
    fde_config: Path,
) -> None:
    source_xml = SOURCE_DOMAIN_XML_WITH_RECOVERY_KEY.replace(
        "</devices>", _TPM_DEVICE_XML + "</devices>"
    )
    conn = _make_conn(
        source_xml.replace("/pool/source-VARS.fd", str(tmp_path / "source-VARS.fd"))
    )
    _source_tpm_state(tmp_path)
    config = fde_config

    with patch("libvirt.open", return_value=conn):
        runner = _fde_runner(
            tmp_path,
            source_xml,
            fde_config=config,
            robot_test="TPM clear recovery reprovision",
            swtpm_state_dir=tmp_path / "swtpm",
            connection_uri="qemu:///session",
        )
        try:
            mock_process = AsyncMock()
            mock_process.wait = AsyncMock(return_value=0)
            mock_process.returncode = 0
            runner.artifacts_path = tmp_path / "artifacts"
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
                    "FDE_CONFIG": str(config),
                    "FDE_DOMAIN_NVRAM": ANY,
                    "FDE_DOMAIN_UUID": "11111111-2222-3333-4444-555555555555",
                    "FDE_PREPARE": "",
                    "FDE_SOURCE_DOMAIN": "source",
                    "FDE_SOURCE_UUID": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "FDE_CONNECTION_URI": "qemu:///session",
                    "FDE_VNC_PORT": "5901",
                    "FDE_SWTPM_STATE_DIR": str(tmp_path / "swtpm"),
                    "FDE_MARKER_FILE": ANY,
                },
            )
        finally:
            runner.close()


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
    # Exports can be read-only; QEMU needs the clone's NVRAM writable.
    nvram_source = tmp_path / "source-VARS.fd"
    nvram_source.write_bytes(b"nvram-data")
    nvram_source.chmod(0o400)

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
            assert nvram_dest.stat().st_mode & 0o200
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

    with (
        patch("libvirt.open", return_value=conn),
        patch(
            "ubuntu_gui_testing_runner.image_runner.DEFAULT_SWTPM_STATE_DIR",
            tmp_path / "swtpm",
        ),
    ):
        runner = LibvirtImageRunner(
            source_domain="source",
            suite_name="test",
            test_name="basic",
            pool_dir=pool_dir,
        )
        try:
            dest_tpm_dir = tmp_path / "swtpm" / "11111111-2222-3333-4444-555555555555"
            assert dest_tpm_dir.exists()
            assert (dest_tpm_dir / "tpm2-00.permall").read_bytes() == b"tpm-state"
        finally:
            runner.close()


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


def test_copies_tpm_state_from_configured_directory(tmp_path: Path) -> None:
    swtpm_dir = tmp_path / "swtpm"
    source_tpm_dir = swtpm_dir / "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    source_tpm_dir.mkdir(parents=True)
    (source_tpm_dir / "tpm2-00.permall").write_bytes(b"tpm-state")

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
            swtpm_state_dir=swtpm_dir,
        )
        dest_tpm_dir = swtpm_dir / "11111111-2222-3333-4444-555555555555"
        try:
            assert (dest_tpm_dir / "tpm2-00.permall").read_bytes() == b"tpm-state"
        finally:
            runner.close()

    # Cleanup removes only the clone's copy, from the same directory.
    assert not dest_tpm_dir.exists()
    assert (source_tpm_dir / "tpm2-00.permall").read_bytes() == b"tpm-state"


def test_tpm_state_is_removed_only_after_the_clone_stops(tmp_path: Path) -> None:
    events: list[str] = []

    class _Domain:
        def UUIDString(self) -> str:
            return _CLONE_UUID

        def isActive(self) -> int:
            return 1

        def destroy(self) -> None:
            events.append("destroy")

        def undefine(self) -> None:
            events.append("undefine")

    runner = object.__new__(LibvirtImageRunner)
    runner._domain = _Domain()
    runner.domain_name = "clone"
    runner.keep = False
    runner.swtpm_state_dir = tmp_path / "swtpm"
    runner._pool = None
    runner._disk_volume = None
    runner._usb_disk_volume = None
    runner._conn = None
    tpm_dir = runner.swtpm_state_dir / _CLONE_UUID
    tpm_dir.mkdir(parents=True)
    (tpm_dir / "tpm2-00.permall").write_bytes(b"tpm-state")

    real_rmtree = shutil.rmtree

    def remove_after_stop(path: Path) -> None:
        assert events == ["destroy", "undefine"]
        events.append("rmtree")
        real_rmtree(path)

    with patch(
        "ubuntu_gui_testing_runner.image_runner.shutil.rmtree",
        side_effect=remove_after_stop,
    ):
        runner.close()

    assert events == ["destroy", "undefine", "rmtree"]
    assert not tpm_dir.exists()


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
            runner.artifacts_path = tmp_path / "artifacts"
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
            runner.artifacts_path = tmp_path / "artifacts"
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
            assert '<target dev="sdb" bus="usb"/>' in domain_xml
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


def test_prepare_clears_the_cloned_tpm_state(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from ubuntu_gui_testing_runner.image_runner import LibvirtImageRunner

    runner = object.__new__(LibvirtImageRunner)
    setattr(  # noqa: B010 - a unit-test stub for a typed attribute
        runner, "fde_fixture", SimpleNamespace(prepare=("clear-tpm-state",))
    )
    runner.swtpm_state_dir = tmp_path
    runner._domain = SimpleNamespace(
        UUIDString=lambda: "clone-uuid", isActive=lambda: 0
    )
    permall = tmp_path / "clone-uuid" / "tpm2" / "tpm2-00.permall"
    permall.parent.mkdir(parents=True)
    permall.write_bytes(b"sealed")
    runner._prepare_tpm_state()
    assert not permall.exists()


def test_prepare_fails_when_the_cloned_tpm_state_is_absent(tmp_path: Path) -> None:
    from types import SimpleNamespace

    import pytest

    from ubuntu_gui_testing_runner.image_runner import LibvirtImageRunner

    runner = object.__new__(LibvirtImageRunner)
    setattr(  # noqa: B010 - a unit-test stub for a typed attribute
        runner, "fde_fixture", SimpleNamespace(prepare=("clear-tpm-state",))
    )
    runner.swtpm_state_dir = tmp_path
    runner._domain = SimpleNamespace(
        UUIDString=lambda: "clone-uuid", isActive=lambda: 0
    )
    with pytest.raises(RuntimeError, match="Clone TPM state is missing"):
        runner._prepare_tpm_state()


_ENROLLMENT_DOMAIN_XML = dedent("""\
    <domain type="kvm">
      <name>clone</name>
      <devices>
        <vsock model="virtio">
          <cid address="3"/>
        </vsock>
      </devices>
    </domain>
""")


def _enrollment_runner(
    *, prepare: tuple[str, ...] = ("enroll-auth",), auth_mode: str = "passphrase"
) -> LibvirtImageRunner:
    from types import SimpleNamespace

    runner = object.__new__(LibvirtImageRunner)
    setattr(  # noqa: B010 - a unit-test stub for a typed attribute
        runner,
        "fde_fixture",
        SimpleNamespace(
            prepare=prepare,
            auth_mode=auth_mode,
            secret=lambda name: {"pin": "1234", "passphrase": "fixture-secret"}[name],
        ),
    )
    runner.domain_name = "clone"
    return runner


class _FakeEnrollmentGuest:
    def __init__(self, fixture: Any, cid: int) -> None:
        self.fixture = fixture
        self.cid = cid
        self.requests: list[tuple[str, dict[str, Any] | None, float]] = []
        self.closed = False

    def request(
        self,
        operation: str,
        parameters: dict[str, Any] | None = None,
        timeout: float = 0,
    ) -> dict[str, Any]:
        self.requests.append((operation, parameters, timeout))
        if operation == "snapshot":
            return {"boot_id": "first-boot"}
        if operation == "enroll-auth":
            return {"auth_mode": self.fixture.auth_mode, "status": "Done"}
        if operation == "shutdown":
            return {"scheduled": "shutdown"}
        raise AssertionError(f"unexpected guest operation {operation}")

    def close(self) -> None:
        self.closed = True


def test_enrollment_boots_enrolls_then_waits_for_a_clean_shutdown() -> None:
    runner = _enrollment_runner()
    domain = MagicMock()
    domain.XMLDesc.return_value = _ENROLLMENT_DOMAIN_XML
    domain.isActive.side_effect = [0, 0]
    runner._domain = domain
    guests: list[_FakeEnrollmentGuest] = []

    def make_guest(fixture: Any, cid: int) -> _FakeEnrollmentGuest:
        guest = _FakeEnrollmentGuest(fixture, cid)
        guests.append(guest)
        return guest

    with patch("ubuntu_gui_testing_runner.image_runner.FdeGuest", make_guest):
        runner._enroll_clone_authentication()

    assert domain.create.call_count == 1
    assert len(guests) == 1
    guest = guests[0]
    assert guest.cid == 3
    assert [request[0] for request in guest.requests] == [
        "snapshot",
        "enroll-auth",
        "shutdown",
    ]
    assert guest.requests[1][1] == {
        "auth_mode": "passphrase",
        "passphrase": "fixture-secret",
    }
    assert guest.closed


def test_enrollment_failure_closes_the_guest_before_shutdown() -> None:
    runner = _enrollment_runner()
    domain = MagicMock()
    domain.XMLDesc.return_value = _ENROLLMENT_DOMAIN_XML
    domain.isActive.return_value = 0
    runner._domain = domain
    guests: list[_FakeEnrollmentGuest] = []

    class _FailingEnrollGuest(_FakeEnrollmentGuest):
        def request(
            self,
            operation: str,
            parameters: dict[str, Any] | None = None,
            timeout: float = 0,
        ) -> dict[str, Any]:
            self.requests.append((operation, parameters, timeout))
            if operation == "snapshot":
                return {"boot_id": "first-boot"}
            if operation == "enroll-auth":
                raise RuntimeError("snapd could not replace the platform key")
            raise AssertionError("shutdown must not follow a failed enrollment")

    def make_guest(fixture: Any, cid: int) -> _FailingEnrollGuest:
        guest = _FailingEnrollGuest(fixture, cid)
        guests.append(guest)
        return guest

    with (
        patch("ubuntu_gui_testing_runner.image_runner.FdeGuest", make_guest),
        pytest.raises(RuntimeError, match="could not replace the platform key"),
    ):
        runner._enroll_clone_authentication()

    assert [request[0] for request in guests[0].requests] == [
        "snapshot",
        "enroll-auth",
    ]
    assert guests[0].closed


def test_setup_enrolls_before_any_stopped_clone_preparation() -> None:
    runner = _enrollment_runner()
    calls: list[str] = []
    for name in (
        "_extract_source_paths",
        "_create_overlay",
        "_copy_nvram",
        "_create_domain",
        "_copy_tpm_state",
        "_enroll_clone_authentication",
        "_prepare_fde_host_state",
        "_prepare_tpm_state",
        "_prepare_no_tpm_state",
    ):
        setattr(runner, name, lambda name=name: calls.append(name))

    runner._setup()

    assert calls == [
        "_extract_source_paths",
        "_create_overlay",
        "_copy_nvram",
        "_create_domain",
        "_copy_tpm_state",
        "_enroll_clone_authentication",
        "_prepare_fde_host_state",
        "_prepare_tpm_state",
        "_prepare_no_tpm_state",
    ]


def test_setup_enrolls_then_clears_the_stopped_clones_tpm(tmp_path: Path) -> None:
    from types import SimpleNamespace

    runner = _enrollment_runner(prepare=("enroll-auth", "clear-tpm-state"))
    runner.swtpm_state_dir = tmp_path
    runner._domain = SimpleNamespace(
        UUIDString=lambda: "clone-uuid", isActive=lambda: 0
    )
    permall = tmp_path / "clone-uuid" / "tpm2" / "tpm2-00.permall"
    permall.parent.mkdir(parents=True)
    permall.write_bytes(b"sealed")
    calls: list[str] = []
    for name in (
        "_extract_source_paths",
        "_create_overlay",
        "_copy_nvram",
        "_create_domain",
        "_copy_tpm_state",
    ):
        setattr(runner, name, lambda name=name: calls.append(name))  # noqa: B010
    setattr(  # noqa: B010
        runner, "_enroll_clone_authentication", lambda: calls.append("enroll")
    )

    runner._setup()

    assert calls == [
        "_extract_source_paths",
        "_create_overlay",
        "_copy_nvram",
        "_create_domain",
        "_copy_tpm_state",
        "enroll",
    ]
    assert not permall.exists()


def test_enrollment_with_plain_ovmf_defines_secure_domain_first(
    tmp_path: Path,
) -> None:
    from ubuntu_gui_testing_runner.constants import DEFAULT_IMAGE_DOMAIN_TEMPLATE

    runner = _enrollment_runner(prepare=("enroll-auth", "plain-ovmf"))
    conn = MagicMock()
    conn.defineXML.return_value = MagicMock()
    setattr(runner, "_conn", conn)  # noqa: B010
    runner.pool_dir = tmp_path
    runner.disk_volume_name = "clone.qcow2"
    runner.nvram_volume_name = "clone-VARS.fd"
    runner.mount_source_domain = None
    runner.domain_template_path = DEFAULT_IMAGE_DOMAIN_TEMPLATE

    runner._create_domain()

    domain_xml = conn.defineXML.call_args.args[0]
    assert 'secure="yes"' in domain_xml
    assert "/usr/share/OVMF/OVMF_CODE_4M.ms.fd" in domain_xml


_DEFERRED_PLAIN_OVMF_XML = dedent("""\
    <domain type="kvm">
      <name>clone</name>
      <uuid>11111111-2222-3333-4444-555555555555</uuid>
      <os firmware="efi">
        <loader readonly="yes" secure="yes" type="pflash" format="raw">
          /usr/share/OVMF/OVMF_CODE_4M.ms.fd
        </loader>
        <nvram format="raw">/clone/VARS.fd</nvram>
      </os>
      <devices>
        <vsock model="virtio">
          <cid address="3"/>
        </vsock>
      </devices>
    </domain>
""")


def test_setup_defers_plain_ovmf_redefinition_until_after_enrollment(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from ubuntu_gui_testing_runner import image_runner
    from ubuntu_gui_testing_runner.fde_host import PLAIN_OVMF_CODE

    runner = _enrollment_runner(prepare=("enroll-auth", "plain-ovmf"))
    runner.pool_dir = tmp_path
    setattr(  # noqa: B010
        runner,
        "_disk_volume",
        SimpleNamespace(path=lambda: str(tmp_path / "disk.qcow2")),
    )
    runner.nvram_volume_name = "clone-VARS.fd"
    runner.swtpm_state_dir = tmp_path
    calls: list[str] = []
    defined_xml: list[str] = []

    def define(domain_xml: str) -> SimpleNamespace:
        defined_xml.append(domain_xml)
        calls.append("redefine")
        return SimpleNamespace(
            UUIDString=lambda: "11111111-2222-3333-4444-555555555555",
            isActive=lambda: 0,
        )

    setattr(runner, "_conn", SimpleNamespace(defineXML=define))  # noqa: B010
    runner._domain = SimpleNamespace(
        UUIDString=lambda: "11111111-2222-3333-4444-555555555555",
        isActive=lambda: 0,
        XMLDesc=lambda _flags: _DEFERRED_PLAIN_OVMF_XML,
    )
    for name in (
        "_extract_source_paths",
        "_create_overlay",
        "_copy_nvram",
        "_copy_tpm_state",
    ):
        setattr(runner, name, lambda name=name: calls.append(name))  # noqa: B010
    setattr(runner, "_create_domain", lambda: calls.append("create"))  # noqa: B010
    setattr(  # noqa: B010
        runner, "_enroll_clone_authentication", lambda: calls.append("enroll")
    )

    with patch.object(image_runner, "prepare_clone_host_state") as prepare:
        prepare.side_effect = lambda *_args: calls.append("host")
        runner._setup()

    assert calls == [
        "_extract_source_paths",
        "_create_overlay",
        "_copy_nvram",
        "create",
        "_copy_tpm_state",
        "enroll",
        "host",
        "redefine",
    ]
    assert len(defined_xml) == 1
    assert str(PLAIN_OVMF_CODE) in defined_xml[0]
    assert 'secure="yes"' not in defined_xml[0]
    assert "<uuid>11111111-2222-3333-4444-555555555555</uuid>" in defined_xml[0]
    assert 'address="3"' in defined_xml[0]


def test_setup_never_prepares_a_clone_whose_enrollment_failed() -> None:
    runner = _enrollment_runner()
    calls: list[str] = []
    setattr(runner, "_extract_source_paths", lambda: calls.append("paths"))  # noqa: B010
    setattr(runner, "_create_overlay", lambda: calls.append("overlay"))  # noqa: B010
    setattr(runner, "_copy_nvram", lambda: calls.append("nvram"))  # noqa: B010
    setattr(runner, "_create_domain", lambda: calls.append("domain"))  # noqa: B010
    setattr(runner, "_copy_tpm_state", lambda: calls.append("tpm-copy"))  # noqa: B010

    def fail() -> None:
        calls.append("enroll")
        raise RuntimeError("enrollment failed")

    setattr(runner, "_enroll_clone_authentication", fail)  # noqa: B010
    setattr(runner, "_prepare_fde_host_state", lambda: calls.append("host"))  # noqa: B010
    setattr(runner, "_prepare_tpm_state", lambda: calls.append("tpm-prep"))  # noqa: B010

    with pytest.raises(RuntimeError, match="enrollment failed"):
        runner._setup()

    assert calls == ["paths", "overlay", "nvram", "domain", "tpm-copy", "enroll"]


def test_enrollment_refuses_to_boot_a_running_clone() -> None:
    runner = _enrollment_runner()
    domain = MagicMock()
    domain.isActive.return_value = 1
    runner._domain = domain

    with pytest.raises(RuntimeError, match="running clone"):
        runner._enroll_clone_authentication()

    domain.create.assert_not_called()


def test_enrollment_is_skipped_without_the_enroll_step() -> None:
    runner = _enrollment_runner(prepare=("sysprep-app",))
    domain = MagicMock()
    runner._domain = domain

    runner._enroll_clone_authentication()

    domain.create.assert_not_called()
    domain.XMLDesc.assert_not_called()


def test_enrollment_boot_wait_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from ubuntu_gui_testing_runner import image_runner
    from ubuntu_gui_testing_runner.fde import FdeGuestTimeout

    monkeypatch.setattr(image_runner, "FDE_BOOT_TIMEOUT", 0.0)
    runner = _enrollment_runner()
    domain = MagicMock()
    domain.XMLDesc.return_value = _ENROLLMENT_DOMAIN_XML
    domain.isActive.return_value = 0
    runner._domain = domain
    guests: list[_FakeEnrollmentGuest] = []

    class _NeverReadyGuest(_FakeEnrollmentGuest):
        def request(
            self,
            operation: str,
            parameters: dict[str, Any] | None = None,
            timeout: float = 0,
        ) -> dict[str, Any]:
            self.requests.append((operation, parameters, timeout))
            raise FdeGuestTimeout(operation, "not yet")

    def make_guest(fixture: Any, cid: int) -> _NeverReadyGuest:
        guest = _NeverReadyGuest(fixture, cid)
        guests.append(guest)
        return guest

    with (
        patch("ubuntu_gui_testing_runner.image_runner.FdeGuest", make_guest),
        pytest.raises(RuntimeError, match="did not become reachable"),
    ):
        runner._enroll_clone_authentication()

    assert guests[0].closed
    assert [request[0] for request in guests[0].requests] == []


def test_enrollment_shutdown_wait_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from ubuntu_gui_testing_runner import image_runner

    monkeypatch.setattr(image_runner, "FDE_SHUTDOWN_TIMEOUT", 0.0)
    runner = _enrollment_runner()
    domain = MagicMock()
    domain.XMLDesc.return_value = _ENROLLMENT_DOMAIN_XML
    domain.isActive.side_effect = [0, 1]
    runner._domain = domain
    guests: list[_FakeEnrollmentGuest] = []

    def make_guest(fixture: Any, cid: int) -> _FakeEnrollmentGuest:
        guest = _FakeEnrollmentGuest(fixture, cid)
        guests.append(guest)
        return guest

    with (
        patch("ubuntu_gui_testing_runner.image_runner.FdeGuest", make_guest),
        pytest.raises(RuntimeError, match="did not shut down cleanly"),
    ):
        runner._enroll_clone_authentication()

    assert guests[0].closed


def test_prepare_refuses_to_clear_a_running_clones_tpm(tmp_path: Path) -> None:
    from types import SimpleNamespace

    runner = object.__new__(LibvirtImageRunner)
    setattr(  # noqa: B010 - a unit-test stub for a typed attribute
        runner, "fde_fixture", SimpleNamespace(prepare=("clear-tpm-state",))
    )
    runner.swtpm_state_dir = tmp_path
    runner.domain_name = "clone"
    runner._domain = SimpleNamespace(
        UUIDString=lambda: "clone-uuid", isActive=lambda: 1
    )
    permall = tmp_path / "clone-uuid" / "tpm2" / "tpm2-00.permall"
    permall.parent.mkdir(parents=True)
    permall.write_bytes(b"sealed")

    with pytest.raises(RuntimeError, match="running clone"):
        runner._prepare_tpm_state()

    assert permall.read_bytes() == b"sealed"


def test_prepare_refuses_to_mutate_a_running_clones_firmware() -> None:
    from types import SimpleNamespace

    from ubuntu_gui_testing_runner import image_runner

    runner = object.__new__(LibvirtImageRunner)
    setattr(  # noqa: B010 - a unit-test stub for a typed attribute
        runner, "fde_fixture", SimpleNamespace(prepare=("sysprep-app",))
    )
    runner.domain_name = "clone"
    runner._domain = SimpleNamespace(isActive=lambda: 1)

    with (
        patch.object(image_runner, "prepare_clone_host_state") as prepare,
        pytest.raises(RuntimeError, match="running clone"),
    ):
        runner._prepare_fde_host_state()

    prepare.assert_not_called()


_SOURCE_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_CLONE_UUID = "11111111-2222-3333-4444-555555555555"

_CLONE_DOMAIN_XML_WITH_TPM = dedent("""\
    <domain type="kvm">
      <name>clone</name>
      <uuid>11111111-2222-3333-4444-555555555555</uuid>
      <os firmware="efi">
        <type arch="x86_64" machine="q35">hvm</type>
        <nvram format="raw">/pool/clone-VARS.fd</nvram>
      </os>
      <devices>
        <disk type="file" device="disk">
          <driver name="qemu" type="qcow2"/>
          <source file="/pool/clone.qcow2"/>
          <target dev="vda" bus="virtio"/>
        </disk>
        <vsock model="virtio">
          <cid address="3"/>
        </vsock>
        <tpm model="tpm-crb">
          <backend type="emulator" version="2.0" persistent_state="yes"/>
        </tpm>
      </devices>
    </domain>
""")


class _FakeCloneDomain:
    """A defined clone that reflects the XML libvirt was given."""

    def __init__(self, xml: str, events: list[str] | None = None) -> None:
        self.xml = xml
        self.events = events
        self.create_count = 0

    def UUIDString(self) -> str:
        return _CLONE_UUID

    def isActive(self) -> int:
        return 0

    def XMLDesc(self, _flags: int) -> str:
        return self.xml

    def create(self) -> None:
        self.create_count += 1
        if self.events is not None:
            self.events.append("create")

    def destroy(self) -> None:
        pass

    def undefine(self) -> None:
        pass


def _no_tpm_runner(prepare: tuple[str, ...] = ("no-tpm",)) -> LibvirtImageRunner:
    runner = object.__new__(LibvirtImageRunner)
    setattr(  # noqa: B010 - a unit-test stub for a typed attribute
        runner, "fde_fixture", SimpleNamespace(prepare=prepare)
    )
    runner.domain_name = "clone"
    runner.source_domain_name = "source"
    runner.source_uuid = _SOURCE_UUID
    return runner


def test_prepare_no_tpm_removes_only_the_clones_tpm_device() -> None:
    runner = _no_tpm_runner()
    setattr(  # noqa: B010 - a unit-test stub for a typed attribute
        runner,
        "_domain",
        SimpleNamespace(
            UUIDString=lambda: _CLONE_UUID,
            isActive=lambda: 0,
            XMLDesc=lambda _flags: _CLONE_DOMAIN_XML_WITH_TPM,
        ),
    )
    defined_xml: list[str] = []

    def define(xml: str) -> SimpleNamespace:
        defined_xml.append(xml)
        return SimpleNamespace(UUIDString=lambda: _CLONE_UUID)

    setattr(  # noqa: B010 - a unit-test stub for a typed attribute
        runner,
        "_conn",
        SimpleNamespace(defineXML=define),
    )

    runner._prepare_no_tpm_state()

    assert len(defined_xml) == 1
    root = ET.fromstring(defined_xml[0])
    assert root.find("./devices/tpm") is None
    assert root.findtext("uuid") == _CLONE_UUID
    assert root.findtext("name") == "clone"
    assert root.findtext("./os/nvram") == "/pool/clone-VARS.fd"
    disk_source = root.find("./devices/disk/source")
    assert disk_source is not None
    assert disk_source.get("file") == "/pool/clone.qcow2"
    cid = root.find("./devices/vsock/cid")
    assert cid is not None
    assert cid.get("address") == "3"


def test_prepare_no_tpm_refuses_a_running_clone() -> None:
    runner = _no_tpm_runner()
    domain = MagicMock()
    domain.isActive.return_value = 1
    runner._domain = domain
    define = MagicMock()
    setattr(runner, "_conn", SimpleNamespace(defineXML=define))  # noqa: B010

    with pytest.raises(RuntimeError, match="running clone"):
        runner._prepare_no_tpm_state()

    domain.XMLDesc.assert_not_called()
    define.assert_not_called()


@pytest.mark.parametrize(
    ("clone_name", "clone_uuid"),
    [("source", _CLONE_UUID), ("clone", _SOURCE_UUID)],
)
def test_prepare_no_tpm_refuses_the_source_identity(
    clone_name: str, clone_uuid: str
) -> None:
    runner = _no_tpm_runner()
    runner.domain_name = clone_name
    domain = MagicMock()
    domain.isActive.return_value = 0
    domain.UUIDString.return_value = clone_uuid
    domain.XMLDesc.return_value = _CLONE_DOMAIN_XML_WITH_TPM
    runner._domain = domain
    define = MagicMock()
    setattr(runner, "_conn", SimpleNamespace(defineXML=define))  # noqa: B010

    with pytest.raises(RuntimeError, match="source"):
        runner._prepare_no_tpm_state()

    domain.XMLDesc.assert_not_called()
    define.assert_not_called()


def test_prepare_no_tpm_is_skipped_without_the_step() -> None:
    runner = _no_tpm_runner(prepare=("clear-tpm-state",))
    domain = MagicMock()
    runner._domain = domain

    runner._prepare_no_tpm_state()

    domain.XMLDesc.assert_not_called()


def _config_with_prepare(config: Path, prepare: list[str]) -> Path:
    data = json.loads(config.read_text(encoding="utf-8"))
    data["prepare"] = prepare
    config.write_text(json.dumps(data), encoding="utf-8")
    config.chmod(0o600)
    return config


def test_setup_enrolls_with_the_tpm_then_removes_it_after_shutdown(
    tmp_path: Path, fde_config: Path
) -> None:
    config = _config_with_prepare(fde_config, ["enroll-auth", "no-tpm"])
    source_xml = SOURCE_DOMAIN_XML_WITH_TPM.replace(
        "/pool/source-VARS.fd", str(tmp_path / "source-VARS.fd")
    )
    conn = _make_conn(source_xml)
    _source_tpm_state(tmp_path)
    events: list[str] = []
    defined: list[_FakeCloneDomain] = []

    def define(domain_xml: str) -> _FakeCloneDomain:
        # libvirt assigns the VSOCK CID when the domain is defined.
        domain = _FakeCloneDomain(
            domain_xml.replace('<cid auto="yes"/>', '<cid address="3"/>'), events
        )
        defined.append(domain)
        events.append("define")
        return domain

    conn.defineXML.side_effect = define
    guests: list[_FakeEnrollmentGuest] = []

    class _EventGuest(_FakeEnrollmentGuest):
        def request(
            self,
            operation: str,
            parameters: dict[str, Any] | None = None,
            timeout: float = 0,
        ) -> dict[str, Any]:
            events.append(operation)
            return super().request(operation, parameters, timeout)

    def make_guest(fixture: Any, cid: int) -> _EventGuest:
        guest = _EventGuest(fixture, cid)
        guests.append(guest)
        return guest

    with (
        patch("libvirt.open", return_value=conn),
        patch("ubuntu_gui_testing_runner.image_runner.FdeGuest", make_guest),
    ):
        _fde_runner(
            tmp_path,
            source_xml,
            fde_config=config,
            robot_test="TPM unavailable reprovision",
            swtpm_state_dir=tmp_path / "swtpm",
        )

    # The healthy enrollment boot carries a TPM; only the redefine after its
    # shutdown drops the device.
    assert events == [
        "define",
        "create",
        "snapshot",
        "enroll-auth",
        "shutdown",
        "define",
    ]
    assert len(defined) == 2
    first = ET.fromstring(defined[0].xml)
    second = ET.fromstring(defined[1].xml)
    assert first.find("./devices/tpm") is not None
    assert second.find("./devices/tpm") is None
    devices = first.find("devices")
    assert devices is not None
    tpm = devices.find("tpm")
    assert tpm is not None
    devices.remove(tpm)
    assert ET.tostring(first) == ET.tostring(second)

    source = conn.lookupByName("source")
    source.defineXML.assert_not_called()
    source.destroy.assert_not_called()
    assert ET.fromstring(source.XMLDesc(0)).find("./devices/tpm") is not None
    source_tpm = tmp_path / "swtpm" / _SOURCE_UUID / "tpm2-00.permall"
    assert source_tpm.read_bytes() == b"tpm-state"
