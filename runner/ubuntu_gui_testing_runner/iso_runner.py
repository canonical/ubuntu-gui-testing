from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import tostring as xml_tostring
from xml.sax.saxutils import escape

import defusedxml.ElementTree as ET
import libvirt  # type: ignore[import-untyped]

from ubuntu_gui_testing_runner.base import (
    _BaseLibvirtRunner,
)
from ubuntu_gui_testing_runner.constants import (
    DEFAULT_ISO_DOMAIN_TEMPLATE,
    DEFAULT_TEST_PASSWORD,
    DEFAULT_TEST_USERNAME,
    DEFAULT_VOLUME_TEMPLATE,
    DOMAIN_METADATA_NAMESPACE,
    DOMAIN_METADATA_ROOT,
    RECOVERY_KEY_FILENAME,
    RECOVERY_KEY_METADATA_KEY,
)
from ubuntu_gui_testing_runner.ssh import collect_installer_logs

LOGGER = logging.getLogger(__name__)


class LibvirtIsoRunner(_BaseLibvirtRunner):
    """Create a VM from an ISO and run a test suite."""

    def __init__(
        self,
        iso: str,
        suite_name: str,
        test_name: str,
        domain_template: Path | None = None,
        volume_template: Path | None = None,
        test_username: str = DEFAULT_TEST_USERNAME,
        test_password: str = DEFAULT_TEST_PASSWORD,
        **kwargs: Any,
    ) -> None:
        self.iso_path = str(Path(iso).resolve())
        self.test_username = test_username
        self.test_password = test_password

        self.volume_template_path = (
            volume_template.resolve()
            if volume_template is not None
            else DEFAULT_VOLUME_TEMPLATE
        )
        self.domain_template_path = (
            domain_template.resolve()
            if domain_template is not None
            else DEFAULT_ISO_DOMAIN_TEMPLATE
        )

        super().__init__(suite_name=suite_name, test_name=test_name, **kwargs)

    def _setup(self) -> None:
        self._create_volume()
        self._create_domain()

    def _create_volume(self) -> None:
        disk_volume_xml = self._render_template(
            self.volume_template_path, {"name": self.disk_volume_name}
        )
        self._disk_volume = self.pool.createXML(disk_volume_xml, 0)

    def _create_domain(self) -> None:
        # Phase 1: Create a transient domain that boots from the ISO with
        # on_reboot=destroy.  When the installer finishes and triggers a
        # reboot the domain will shut down instead of rebooting, giving us
        # a signal that installation is complete.
        domain_xml = self._render_template(
            self.domain_template_path,
            {
                "name": self.domain_name,
                "iso": self.iso_path,
                "disk": self.disk_volume.path(),
                "nvram": str(self.pool_dir / self.nvram_volume_name),
            },
        )
        initial_domain = self.conn.createXML(domain_xml)
        if initial_domain is None:
            raise RuntimeError(f"Unable to create domain '{self.domain_name}'")

        # Phase 2: Define a persistent domain for the post-install boot.
        # Remove the cdrom source and boot entry so it boots from disk,
        # and change on_reboot to restart for normal operation.
        xml = ET.fromstring(initial_domain.XMLDesc(0))

        devices = xml.find("devices")
        if devices is not None:
            for disk in devices.findall("disk"):
                if disk.get("device") == "cdrom":
                    source = disk.find("source")
                    if source is not None and source.get("file") == self.iso_path:
                        disk.remove(source)

        os_elem = xml.find("os")
        if os_elem is not None:
            boot = os_elem.find("boot")
            if boot is not None and boot.get("dev") == "cdrom":
                os_elem.remove(boot)

        on_reboot = xml.find("on_reboot")
        if on_reboot is not None and on_reboot.text == "destroy":
            on_reboot.text = "restart"
        final_xml = xml_tostring(xml, encoding="unicode")

        self._domain = self.conn.defineXML(final_xml)

        if self._domain is None:
            raise RuntimeError(f"Unable to define domain '{self.domain_name}'")

    async def _run_yarf(
        self, suite: str, test: str, vsock_cid: int, vnc_port: int
    ) -> int:
        """Run YARF across the install-then-reboot lifecycle.

        The installer runs inside the transient domain (phase 1).  When it
        triggers a reboot, on_reboot=destroy shuts the domain down.  We
        detect this via _handle_reboot, which then starts the persistent
        domain (phase 2, boots from disk).  YARF continues driving the
        post-install test suite against the freshly installed system.

        If YARF exits before the reboot (e.g. test failure during install),
        we cancel the reboot watcher and return early.
        """
        yarf_process = await self._spawn_yarf(
            suite,
            test,
            vnc_port,
            robot_variables={
                **self.robot_variables,
                "CID": str(vsock_cid),
            },
        )
        try:
            async with asyncio.TaskGroup() as tg:
                yarf_task = tg.create_task(yarf_process.wait())
                reboot_task = tg.create_task(self._handle_reboot())
                done, _ = await asyncio.wait(
                    {yarf_task, reboot_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                # YARF exited before the reboot — likely a test failure
                if yarf_task in done:
                    code = yarf_task.result()
                    LOGGER.info("YARF process exited during install with code %s", code)
                    reboot_task.cancel()
                    return code

                # Reboot detected — domain restarted from disk; wait for
                # YARF to finish the post-install test suite.
                returncode = await yarf_task
                LOGGER.info("YARF process exited after reboot with code %s", returncode)
                return returncode
        finally:
            if yarf_process.returncode is None:
                LOGGER.info("Terminating YARF process")
                yarf_process.terminate()
                try:
                    await asyncio.wait_for(yarf_process.wait(), timeout=5.0)
                except TimeoutError:
                    LOGGER.warning("YARF process did not terminate, killing it")
                    yarf_process.kill()
                    await yarf_process.wait()
            self._store_recovery_key_as_metadata()
            collect_installer_logs(
                guest_cid=vsock_cid,
                test_username=self.test_username,
                test_password=self.test_password,
                artifacts_dir=self.artifacts_path,
            )

    def _store_recovery_key_as_metadata(self) -> None:
        """Read recovery key from artifacts and persist it as libvirt metadata."""
        recovery_key_path = self.artifacts_path / RECOVERY_KEY_FILENAME
        if not recovery_key_path.exists():
            LOGGER.info("Recovery key file '%s' not found", recovery_key_path)
            return

        recovery_key = recovery_key_path.read_text(encoding="utf-8").strip()
        if not recovery_key:
            LOGGER.warning("Recovery key file '%s' is empty", recovery_key_path)
            return

        metadata_xml = (
            f"<{DOMAIN_METADATA_ROOT}>"
            f"<{RECOVERY_KEY_METADATA_KEY}>{escape(recovery_key)}</{RECOVERY_KEY_METADATA_KEY}>"
            f"</{DOMAIN_METADATA_ROOT}>"
        )
        try:
            self.domain.setMetadata(
                libvirt.VIR_DOMAIN_METADATA_ELEMENT,
                metadata_xml,
                DOMAIN_METADATA_ROOT,
                DOMAIN_METADATA_NAMESPACE,
                libvirt.VIR_DOMAIN_AFFECT_CONFIG,
            )
        except libvirt.libvirtError:
            LOGGER.exception(
                "Failed to store recovery key as metadata for domain '%s'",
                self.domain_name,
            )
            return
        LOGGER.info("Stored recovery key as metadata for domain '%s'", self.domain_name)

    async def _handle_reboot(self) -> None:
        """Poll until the transient domain shuts down, then start the persistent one."""
        while self.domain.isActive():
            await asyncio.sleep(1)
        self.domain.create()
