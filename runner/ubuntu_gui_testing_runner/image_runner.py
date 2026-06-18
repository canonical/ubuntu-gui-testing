from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as ET
import libvirt  # type: ignore[import-untyped]

from ubuntu_gui_testing_runner.base import (
    _BaseLibvirtRunner,
    resolve_latest_domain,
)
from ubuntu_gui_testing_runner.constants import (
    DEFAULT_IMAGE_DOMAIN_TEMPLATE,
    DEFAULT_OVERLAY_TEMPLATE,
    DEFAULT_SWTPM_STATE_DIR,
    DOMAIN_METADATA_NAMESPACE,
    RECOVERY_KEY_METADATA_KEY,
)

LOGGER = logging.getLogger(__name__)


class LibvirtImageRunner(_BaseLibvirtRunner):
    """Create a VM from an existing domain's qcow2 image and NVRAM state."""

    def __init__(
        self,
        suite_name: str,
        test_name: str,
        source_domain: str | None = None,
        source_domain_prefix: str | None = None,
        domain_template: Path | None = None,
        overlay_template: Path | None = None,
        mount_source_domain: str | None = None,
        **kwargs: Any,
    ) -> None:
        if (source_domain is None) == (source_domain_prefix is None):
            raise ValueError(
                "Exactly one of 'source_domain' or 'source_domain_prefix' "
                "must be provided"
            )
        self._source_domain = source_domain
        self._source_domain_prefix = source_domain_prefix
        self.source_domain_name: str = source_domain or ""
        self.recovery_key: str | None = None
        self.mount_source_domain = mount_source_domain

        self.overlay_template_path = (
            overlay_template.resolve()
            if overlay_template is not None
            else DEFAULT_OVERLAY_TEMPLATE
        )
        self.domain_template_path = (
            domain_template.resolve()
            if domain_template is not None
            else DEFAULT_IMAGE_DOMAIN_TEMPLATE
        )

        super().__init__(suite_name=suite_name, test_name=test_name, **kwargs)

    def _setup(self) -> None:
        self._extract_source_paths()
        self._create_overlay()
        self._copy_nvram()
        self._create_domain()
        self._copy_tpm_state()

    def _extract_source_paths(self) -> None:
        """Extract disk image and NVRAM paths from the source domain XML."""
        if self._source_domain_prefix is not None:
            self.source_domain_name = resolve_latest_domain(
                self.conn, self._source_domain_prefix
            )
        try:
            source = self.conn.lookupByName(self.source_domain_name)
        except libvirt.libvirtError as err:
            raise RuntimeError(
                f"Source domain '{self.source_domain_name}' not found"
            ) from err

        xml = ET.fromstring(source.XMLDesc(0))

        # Find the primary disk image (first virtio disk)
        devices = xml.find("devices")
        if devices is None:
            raise RuntimeError(
                f"No devices found in source domain '{self.source_domain_name}'"
            )

        image_path: str | None = None
        for disk in devices.findall("disk"):
            if disk.get("device") == "disk":
                source_elem = disk.find("source")
                if source_elem is not None:
                    image_path = source_elem.get("file")
                    break

        if image_path is None:
            raise RuntimeError(
                f"No disk image found in source domain '{self.source_domain_name}'"
            )
        self.image_path = Path(image_path)

        # Find the NVRAM path
        os_elem = xml.find("os")
        nvram_elem = os_elem.find("nvram") if os_elem is not None else None
        nvram_path = nvram_elem.text if nvram_elem is not None else None
        if nvram_path is None:
            # Try the source attribute for newer libvirt XML formats
            nvram_path = nvram_elem.get("source") if nvram_elem is not None else None

        if nvram_path is None:
            raise RuntimeError(
                f"No NVRAM path found in source domain '{self.source_domain_name}'"
            )
        self.nvram_path = Path(nvram_path)

        # Find the TPM state directory via the source domain's UUID
        uuid_elem = xml.find("uuid")
        self.source_tpm_state_dir: Path | None
        if uuid_elem is not None and uuid_elem.text:
            self.source_tpm_state_dir = DEFAULT_SWTPM_STATE_DIR / uuid_elem.text
        else:
            self.source_tpm_state_dir = None

        metadata = xml.find("metadata")
        if metadata is None:
            LOGGER.info(
                "No metadata block found in source domain '%s' XML",
                self.source_domain_name,
            )
            return

        key_tag = f"{{{DOMAIN_METADATA_NAMESPACE}}}{RECOVERY_KEY_METADATA_KEY}"
        elem = metadata.find(f".//{key_tag}")
        if elem is None:
            LOGGER.info(
                "No recovery key metadata found in source domain '%s'",
                self.source_domain_name,
            )
            return

        recovery_key = "" if elem.text is None else elem.text.strip()
        if not recovery_key:
            LOGGER.warning(
                "Recovery key metadata in source domain '%s' is empty",
                self.source_domain_name,
            )
            return

        self.recovery_key = recovery_key
        LOGGER.info(
            "Loaded recovery key metadata from source domain '%s'",
            self.source_domain_name,
        )

    def _create_overlay(self) -> None:
        """Create qcow2 overlays backed by the original image."""
        volume_xml = self._render_template(
            self.overlay_template_path,
            {"name": self.disk_volume_name, "backing_image": str(self.image_path)},
        )
        self._disk_volume = self.pool.createXML(volume_xml, 0)

        if self.mount_source_domain is None:
            return

        usb_volume_xml = self._render_template(
            self.overlay_template_path,
            {
                "name": self.usb_disk_volume_name,
                "backing_image": str(self.image_path),
            },
        )
        self._usb_disk_volume = self.pool.createXML(usb_volume_xml, 0)

    def _copy_nvram(self) -> None:
        """Copy the NVRAM file into the pool, leaving the original untouched."""
        dest = self.pool_dir / self.nvram_volume_name
        shutil.copy2(self.nvram_path, dest)
        self.pool.refresh(0)

    def _copy_tpm_state(self) -> None:
        """Copy the TPM state from the source domain to the new domain."""
        if self.source_tpm_state_dir is None or not self.source_tpm_state_dir.exists():
            LOGGER.info("No TPM state to copy from source domain")
            return

        new_uuid = self.domain.UUIDString()
        dest_tpm_dir = DEFAULT_SWTPM_STATE_DIR / new_uuid
        shutil.copytree(self.source_tpm_state_dir, dest_tpm_dir)
        LOGGER.info(
            "Copied TPM state from '%s' to '%s'",
            self.source_tpm_state_dir,
            dest_tpm_dir,
        )

    def _create_domain(self) -> None:
        """Define a domain that boots directly from the overlay disk."""
        domain_xml = self._render_template(
            self.domain_template_path,
            {
                "name": self.domain_name,
                "disk": str(self.pool_dir / self.disk_volume_name),
                "usb_disk": self._usb_disk_xml(),
                "nvram": str(self.pool_dir / self.nvram_volume_name),
            },
        )
        self._domain = self.conn.defineXML(domain_xml)

        if self._domain is None:
            raise RuntimeError(f"Unable to define domain '{self.domain_name}'")

    def _usb_disk_xml(self) -> str:
        if self.mount_source_domain is None:
            return ""

        usb_disk = self.pool_dir / self.usb_disk_volume_name
        target_dev = self._usb_disk_target_dev()
        return f"""    <disk type="file" device="disk">
      <driver name="qemu" type="qcow2" discard="unmap"/>
      <source file="{usb_disk}"/>
      <target dev="{target_dev}" bus="usb"/>
    </disk>"""

    def _usb_disk_target_dev(self) -> str:
        if self.mount_source_domain is None:
            return "sda"

        # Libvirt needs the whole-disk target (e.g. sda), while Robot gets the
        # partition path to mount (e.g. /dev/sda5).
        return Path(self.mount_source_domain).name.rstrip("0123456789")

    async def _run_yarf(
        self, suite: str, test: str, vsock_cid: int, vnc_port: int
    ) -> int:
        robot_variables = {"CID": str(vsock_cid)}
        if self.mount_source_domain is not None:
            robot_variables["DEVICE"] = self.mount_source_domain
        if self.recovery_key:
            robot_variables["RECOVERY_KEY"] = self.recovery_key
            LOGGER.info(
                "Starting YARF with recovery key variable for source domain '%s'",
                self.source_domain_name,
            )
        else:
            LOGGER.info(
                "Starting YARF without recovery key variable for source domain '%s'",
                self.source_domain_name,
            )
        yarf_process = await self._spawn_yarf(
            suite,
            test,
            vnc_port,
            robot_variables=robot_variables,
        )
        try:
            returncode = await yarf_process.wait()
            LOGGER.info("YARF process exited with code %s", returncode)
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

    def close(self) -> None:
        # Clean up the copied TPM state directory
        if self._domain is not None and not self.keep:
            tpm_dir = DEFAULT_SWTPM_STATE_DIR / self._domain.UUIDString()
            if tpm_dir.exists():
                try:
                    shutil.rmtree(tpm_dir)
                except OSError:
                    LOGGER.exception(
                        "Failed to delete TPM state directory '%s'", tpm_dir
                    )
        super().close()
