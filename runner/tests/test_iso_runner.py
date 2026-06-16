from __future__ import annotations

import asyncio
from pathlib import Path
from textwrap import dedent
from unittest.mock import AsyncMock, MagicMock, patch

import libvirt  # type: ignore[import-untyped]
import pytest

from ubuntu_gui_testing_runner.iso_runner import LibvirtIsoRunner


def _make_conn(existing_domains: list[str] | None = None) -> MagicMock:
    """Build a mock libvirt connection for ISO runner tests."""
    conn = MagicMock()

    existing = existing_domains or []

    def lookup(name: str) -> MagicMock:
        if name in existing:
            return MagicMock()
        raise libvirt.libvirtError("not found")

    conn.lookupByName.side_effect = lookup

    # Pool setup
    pool = MagicMock()
    volume = MagicMock()
    volume.path.return_value = "/pool/test-disk.qcow2"
    pool.createXML.return_value = volume
    conn.storagePoolLookupByName.return_value = pool
    pool.isActive.return_value = 1

    return conn


def _iso_domain_xml(iso_path: str) -> str:
    return dedent(f"""\
        <domain type="kvm">
          <name>ugt-test-basic-2026-05-29</name>
          <os firmware="efi">
            <type arch="x86_64" machine="q35">hvm</type>
            <boot dev="cdrom"/>
            <boot dev="hd"/>
          </os>
          <on_reboot>destroy</on_reboot>
          <devices>
            <disk type="file" device="disk">
              <source file="/pool/test-disk.qcow2"/>
              <target dev="vda" bus="virtio"/>
            </disk>
            <disk type="file" device="cdrom">
              <source file="{iso_path}"/>
              <target dev="sda" bus="sata"/>
            </disk>
          </devices>
        </domain>
    """)


def test_post_install_xml_removes_cdrom_source(tmp_path: Path) -> None:
    conn = _make_conn()

    iso_file = tmp_path / "test.iso"
    iso_file.write_text("")
    iso_path = str(iso_file.resolve())

    # The transient domain that createXML returns
    transient_domain = MagicMock()
    transient_domain.XMLDesc.return_value = _iso_domain_xml(iso_path)
    conn.createXML.return_value = transient_domain

    # The persistent domain that defineXML returns
    persistent_domain = MagicMock()
    conn.defineXML.return_value = persistent_domain

    with patch("libvirt.open", return_value=conn):
        runner = LibvirtIsoRunner(
            iso=str(iso_file),
            suite_name="test",
            test_name="basic",
            pool_dir=tmp_path,
        )
        try:
            # Check that defineXML was called with XML that no longer has
            # the cdrom source file
            defined_xml = conn.defineXML.call_args[0][0]
            assert iso_path not in defined_xml
        finally:
            runner.close()


def test_post_install_xml_changes_on_reboot_to_restart(tmp_path: Path) -> None:
    conn = _make_conn()

    iso_file = tmp_path / "test.iso"
    iso_file.write_text("")
    iso_path = str(iso_file.resolve())

    transient_domain = MagicMock()
    transient_domain.XMLDesc.return_value = _iso_domain_xml(iso_path)
    conn.createXML.return_value = transient_domain

    persistent_domain = MagicMock()
    conn.defineXML.return_value = persistent_domain

    with patch("libvirt.open", return_value=conn):
        runner = LibvirtIsoRunner(
            iso=str(iso_file),
            suite_name="test",
            test_name="basic",
            pool_dir=tmp_path,
        )
        try:
            defined_xml = conn.defineXML.call_args[0][0]
            assert "<on_reboot>restart</on_reboot>" in defined_xml
        finally:
            runner.close()


def test_post_install_xml_removes_cdrom_boot_entry(tmp_path: Path) -> None:
    conn = _make_conn()

    iso_file = tmp_path / "test.iso"
    iso_file.write_text("")
    iso_path = str(iso_file.resolve())

    transient_domain = MagicMock()
    transient_domain.XMLDesc.return_value = _iso_domain_xml(iso_path)
    conn.createXML.return_value = transient_domain

    persistent_domain = MagicMock()
    conn.defineXML.return_value = persistent_domain

    with patch("libvirt.open", return_value=conn):
        runner = LibvirtIsoRunner(
            iso=str(iso_file),
            suite_name="test",
            test_name="basic",
            pool_dir=tmp_path,
        )
        try:
            defined_xml = conn.defineXML.call_args[0][0]
            assert 'boot dev="cdrom"' not in defined_xml
        finally:
            runner.close()


def test_raises_when_create_domain_returns_none(tmp_path: Path) -> None:
    conn = _make_conn()
    conn.createXML.return_value = None

    iso_file = tmp_path / "test.iso"
    iso_file.write_text("")

    with (
        patch("libvirt.open", return_value=conn),
        pytest.raises(RuntimeError, match="Unable to create domain"),
    ):
        LibvirtIsoRunner(
            iso=str(iso_file),
            suite_name="test",
            test_name="basic",
            pool_dir=tmp_path,
        )


def test_raises_when_define_domain_returns_none(tmp_path: Path) -> None:
    conn = _make_conn()

    iso_file = tmp_path / "test.iso"
    iso_file.write_text("")
    iso_path = str(iso_file.resolve())

    transient_domain = MagicMock()
    transient_domain.XMLDesc.return_value = _iso_domain_xml(iso_path)
    conn.createXML.return_value = transient_domain
    conn.defineXML.return_value = None

    with (
        patch("libvirt.open", return_value=conn),
        pytest.raises(RuntimeError, match="Unable to define domain"),
    ):
        LibvirtIsoRunner(
            iso=str(iso_file),
            suite_name="test",
            test_name="basic",
            pool_dir=tmp_path,
        )


def test_close_destroys_and_undefines_domain_when_keep_is_false(tmp_path: Path) -> None:
    conn = _make_conn()

    iso_file = tmp_path / "test.iso"
    iso_file.write_text("")
    iso_path = str(iso_file.resolve())

    transient_domain = MagicMock()
    transient_domain.XMLDesc.return_value = _iso_domain_xml(iso_path)
    conn.createXML.return_value = transient_domain

    persistent_domain = MagicMock()
    persistent_domain.isActive.return_value = 1
    conn.defineXML.return_value = persistent_domain

    with patch("libvirt.open", return_value=conn):
        runner = LibvirtIsoRunner(
            iso=str(iso_file),
            suite_name="test",
            test_name="basic",
            keep=False,
            pool_dir=tmp_path,
        )
        runner.close()

    persistent_domain.shutdown.assert_not_called()
    persistent_domain.destroy.assert_called_once()
    persistent_domain.undefine.assert_called_once()


def test_close_preserves_resources_when_keep_is_true(tmp_path: Path) -> None:
    conn = _make_conn()

    iso_file = tmp_path / "test.iso"
    iso_file.write_text("")
    iso_path = str(iso_file.resolve())

    transient_domain = MagicMock()
    transient_domain.XMLDesc.return_value = _iso_domain_xml(iso_path)
    conn.createXML.return_value = transient_domain

    persistent_domain = MagicMock()
    conn.defineXML.return_value = persistent_domain

    with patch("libvirt.open", return_value=conn):
        runner = LibvirtIsoRunner(
            iso=str(iso_file),
            suite_name="test",
            test_name="basic",
            keep=True,
            pool_dir=tmp_path,
        )
        runner.close()

    persistent_domain.destroy.assert_not_called()
    persistent_domain.undefine.assert_not_called()


def _make_keep_runner(tmp_path: Path, persistent_domain: MagicMock) -> LibvirtIsoRunner:
    """Build a keep=True ISO runner backed by the given persistent domain."""
    conn = _make_conn()

    iso_file = tmp_path / "test.iso"
    iso_file.write_text("")
    iso_path = str(iso_file.resolve())

    transient_domain = MagicMock()
    transient_domain.XMLDesc.return_value = _iso_domain_xml(iso_path)
    conn.createXML.return_value = transient_domain
    conn.defineXML.return_value = persistent_domain

    with patch("libvirt.open", return_value=conn):
        return LibvirtIsoRunner(
            iso=str(iso_file),
            suite_name="test",
            test_name="basic",
            keep=True,
            pool_dir=tmp_path,
        )


def test_close_gracefully_shuts_down_domain_when_keep_is_true(tmp_path: Path) -> None:
    persistent_domain = MagicMock()
    # Active on the initial check, then powered off during the poll loop.
    persistent_domain.isActive.side_effect = [1, 0]

    runner = _make_keep_runner(tmp_path, persistent_domain)
    runner.close()

    persistent_domain.shutdown.assert_called_once()
    persistent_domain.destroy.assert_not_called()
    persistent_domain.undefine.assert_not_called()


def test_close_skips_shutdown_when_domain_already_inactive(tmp_path: Path) -> None:
    persistent_domain = MagicMock()
    persistent_domain.isActive.return_value = 0

    runner = _make_keep_runner(tmp_path, persistent_domain)
    runner.close()

    persistent_domain.shutdown.assert_not_called()
    persistent_domain.destroy.assert_not_called()
    persistent_domain.undefine.assert_not_called()


def test_close_forces_destroy_when_graceful_shutdown_times_out(
    tmp_path: Path,
) -> None:
    persistent_domain = MagicMock()
    # The guest never powers off, so every isActive check reports active.
    persistent_domain.isActive.return_value = 1

    runner = _make_keep_runner(tmp_path, persistent_domain)
    # Advance the monotonic clock past the deadline after one poll iteration
    # so the timeout branch fires without real sleeping.
    with (
        patch(
            "ubuntu_gui_testing_runner.base.time.monotonic",
            side_effect=[0.0, 0.0, 999.0],
        ),
        patch("ubuntu_gui_testing_runner.base.time.sleep"),
    ):
        runner.close()

    persistent_domain.shutdown.assert_called_once()
    persistent_domain.destroy.assert_called_once()
    persistent_domain.undefine.assert_not_called()


def test_close_forces_destroy_when_graceful_shutdown_errors(tmp_path: Path) -> None:
    persistent_domain = MagicMock()
    persistent_domain.isActive.return_value = 1
    persistent_domain.shutdown.side_effect = libvirt.libvirtError("boom")

    runner = _make_keep_runner(tmp_path, persistent_domain)
    runner.close()

    persistent_domain.shutdown.assert_called_once()
    persistent_domain.destroy.assert_called_once()
    persistent_domain.undefine.assert_not_called()


def _make_runner_for_lifecycle(tmp_path: Path) -> LibvirtIsoRunner:
    """Create an ISO runner suitable for lifecycle testing."""
    conn = _make_conn()

    iso_file = tmp_path / "test.iso"
    iso_file.write_text("")
    iso_path = str(iso_file.resolve())

    transient_domain = MagicMock()
    transient_domain.XMLDesc.return_value = _iso_domain_xml(iso_path)
    conn.createXML.return_value = transient_domain

    persistent_domain = MagicMock()
    persistent_domain.isActive.return_value = 1
    persistent_domain.XMLDesc.return_value = dedent("""\
        <domain type="kvm">
          <name>ugt-test-basic-2026-05-29</name>
          <devices>
            <graphics type="vnc" port="5900" autoport="yes"/>
            <vsock model="virtio">
              <cid auto="yes" address="3"/>
            </vsock>
          </devices>
        </domain>
    """)
    conn.defineXML.return_value = persistent_domain

    with patch("libvirt.open", return_value=conn):
        return LibvirtIsoRunner(
            iso=str(iso_file),
            suite_name="test",
            test_name="basic",
            pool_dir=tmp_path,
            artifacts_dir=tmp_path / "artifacts",
        )


def test_reboot_starts_persistent_domain_after_transient_shuts_down(
    tmp_path: Path,
) -> None:
    runner = _make_runner_for_lifecycle(tmp_path)
    try:
        # Simulate: domain is active on first check (stays in loop),
        # then inactive on next check (exits loop), then 1 for close()
        runner._domain = MagicMock()
        runner._domain.isActive.side_effect = [True, False, 1]
        runner._domain.create = MagicMock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            asyncio.run(runner._handle_reboot())

        runner._domain.create.assert_called_once()
    finally:
        runner.close()


def test_run_yarf_collects_logs_after_normal_reboot(
    tmp_path: Path,
) -> None:
    runner = _make_runner_for_lifecycle(tmp_path)
    try:
        # Mock _spawn_yarf to return a process that finishes after reboot
        mock_process = AsyncMock()
        mock_process.wait = AsyncMock(return_value=0)
        mock_process.returncode = 0

        # Mock _handle_reboot to complete immediately (simulates reboot)
        # and mock _spawn_yarf
        with (
            patch.object(runner, "_spawn_yarf", return_value=mock_process),
            patch.object(runner, "_handle_reboot", return_value=None),
            patch(
                "ubuntu_gui_testing_runner.iso_runner.collect_installer_logs"
            ) as mock_collect,
        ):
            asyncio.run(runner._run_yarf("suite", "test", 3, 5900))

        mock_collect.assert_called_once_with(
            guest_cid=3,
            test_username=runner.test_username,
            test_password=runner.test_password,
            artifacts_dir=runner.artifacts_path,
        )
    finally:
        runner.close()


def test_run_yarf_cancels_reboot_watcher_if_yarf_exits_early(
    tmp_path: Path,
) -> None:
    runner = _make_runner_for_lifecycle(tmp_path)
    try:
        # Mock _spawn_yarf to return a process that exits immediately
        mock_process = AsyncMock()
        mock_process.wait = AsyncMock(return_value=1)
        mock_process.returncode = 1

        # _handle_reboot never completes (simulates no reboot occurred)
        async def hang_forever() -> None:
            await asyncio.sleep(999)

        with (
            patch.object(runner, "_spawn_yarf", return_value=mock_process),
            patch.object(runner, "_handle_reboot", side_effect=hang_forever),
            patch(
                "ubuntu_gui_testing_runner.iso_runner.collect_installer_logs"
            ) as mock_collect,
        ):
            asyncio.run(runner._run_yarf("suite", "test", 3, 5900))

        # Logs are still collected even on early exit
        mock_collect.assert_called_once()
    finally:
        runner.close()


def test_run_yarf_terminates_process_if_still_running(
    tmp_path: Path,
) -> None:
    runner = _make_runner_for_lifecycle(tmp_path)
    try:
        mock_process = AsyncMock()
        # returncode is None => process still running when finally runs
        mock_process.returncode = None
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock(return_value=0)

        # _handle_reboot completes first (reboot detected), then
        # yarf_task also completes (wait returns)
        with (
            patch.object(runner, "_spawn_yarf", return_value=mock_process),
            patch.object(runner, "_handle_reboot", new_callable=AsyncMock),
            patch("ubuntu_gui_testing_runner.iso_runner.collect_installer_logs"),
        ):
            # After _run_yarf, since returncode is None, terminate is called
            asyncio.run(runner._run_yarf("suite", "test", 3, 5900))

        mock_process.terminate.assert_called_once()
    finally:
        runner.close()


def test_store_recovery_key_as_metadata(tmp_path: Path) -> None:
    runner = _make_runner_for_lifecycle(tmp_path)
    try:
        runner.artifacts_path.mkdir(parents=True, exist_ok=True)
        recovery_key_path = runner.artifacts_path / "recovery-key.txt"
        recovery_key_path.write_text(
            "12345-67890-11111-22222-33333-44444-55555-66666\n", encoding="utf-8"
        )
        set_metadata_mock = MagicMock()
        runner.domain.setMetadata = set_metadata_mock

        runner._store_recovery_key_as_metadata()

        set_metadata_mock.assert_called_once_with(
            libvirt.VIR_DOMAIN_METADATA_ELEMENT,
            "<ugt><recovery-key>12345-67890-11111-22222-33333-44444-55555-66666</recovery-key></ugt>",
            "ugt",
            "https://canonical.com/ubuntu-gui-testing",
            libvirt.VIR_DOMAIN_AFFECT_CONFIG,
        )
    finally:
        runner.close()


def test_store_recovery_key_as_metadata_no_file(tmp_path: Path) -> None:
    runner = _make_runner_for_lifecycle(tmp_path)
    try:
        runner.artifacts_path.mkdir(parents=True, exist_ok=True)
        set_metadata_mock = MagicMock()
        runner.domain.setMetadata = set_metadata_mock

        runner._store_recovery_key_as_metadata()

        set_metadata_mock.assert_not_called()
    finally:
        runner.close()
