from __future__ import annotations

import asyncio
import logging
import shutil
import socket
import time
from pathlib import Path
from typing import Any, Final

import defusedxml.ElementTree as ET
import libvirt  # type: ignore[import-untyped]

from ubuntu_gui_testing_runner.base import (
    _BaseLibvirtRunner,
)
from ubuntu_gui_testing_runner.constants import (
    DEFAULT_IMAGE_DOMAIN_TEMPLATE,
    DEFAULT_OVERLAY_TEMPLATE,
    DEFAULT_SWTPM_STATE_DIR,
    DOMAIN_METADATA_NAMESPACE,
    RECOVERY_KEY_METADATA_KEY,
)
from ubuntu_gui_testing_runner.fde import (
    AUTH_ENROLLMENT,
    FdeFixture,
    FdeGuest,
    FdeGuestError,
    FdeGuestTimeout,
)
from ubuntu_gui_testing_runner.fde_capture import (
    CaptureError,
    CaptureSupervisor,
)
from ubuntu_gui_testing_runner.fde_host import (
    HOST_PREPARATIONS,
    prepare_clone_host_state,
    prepare_plain_ovmf_domain_xml,
)

LOGGER = logging.getLogger(__name__)

FDE_BOOT_TIMEOUT: Final = 600.0
FDE_SHUTDOWN_TIMEOUT: Final = 120.0
FDE_ENROLL_TIMEOUT: Final = 360.0
FDE_ATTEMPT_TIMEOUT: Final = 30.0
FDE_POLL_INTERVAL: Final = 5.0


class LibvirtImageRunner(_BaseLibvirtRunner):
    """Create a VM from an existing domain's qcow2 image and NVRAM state."""

    def __init__(
        self,
        source_domain: str,
        suite_name: str,
        test_name: str,
        domain_template: Path | None = None,
        overlay_template: Path | None = None,
        mount_source_domain: str | None = None,
        swtpm_state_dir: Path | None = None,
        fde_config: Path | None = None,
        capture: bool = True,
        **kwargs: Any,
    ) -> None:
        self.source_domain_name = source_domain
        self.capture = capture
        self.capture_supervisor: CaptureSupervisor | None = None
        self.marker_file: Path | None = None
        # The case's own evidence directory. Yarf's output goes into a child
        # directory, so the capture and markers must not follow that change.
        self.case_artifacts: Path | None = None
        self.fde_vnc_port: int | None = None
        self.recovery_key: str | None = None
        self.mount_source_domain = mount_source_domain
        self.swtpm_state_dir = (
            swtpm_state_dir.resolve()
            if swtpm_state_dir is not None
            else DEFAULT_SWTPM_STATE_DIR
        )
        self.fde_config = fde_config.resolve() if fde_config is not None else None
        self.source_uuid: str | None = None
        self.source_has_tpm = False

        # A clone is mutated by exactly one selected case, so a fixture that
        # describes a whole run cannot send a second case into the same guest.
        if self.fde_config is not None and not kwargs.get("robot_test"):
            raise RuntimeError(
                "An FDE configuration requires a single selected Robot case"
            )
        self.fde_fixture = (
            FdeFixture.load(self.fde_config) if self.fde_config is not None else None
        )

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
        self._enroll_clone_authentication()
        self._prepare_fde_host_state()
        self._prepare_tpm_state()
        self._prepare_no_tpm_state()

    def _extract_source_paths(self) -> None:
        """Extract disk image and NVRAM paths from the source domain XML."""
        try:
            source = self.conn.lookupByName(self.source_domain_name)
        except libvirt.libvirtError as err:
            raise RuntimeError(
                f"Source domain '{self.source_domain_name}' not found"
            ) from err

        if source.isActive() != 0:
            raise RuntimeError(
                f"Source domain '{self.source_domain_name}' must be stopped"
            )

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
        self.source_uuid = (
            uuid_elem.text.strip() if uuid_elem is not None and uuid_elem.text else None
        )
        self.source_tpm_state_dir: Path | None
        if self.source_uuid is not None:
            self.source_tpm_state_dir = self.swtpm_state_dir / self.source_uuid
        else:
            self.source_tpm_state_dir = None
        self.source_has_tpm = devices.find("tpm") is not None

        if self.fde_config is not None:
            self._require_fde_baseline()

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

    def _require_fde_baseline(self) -> None:
        """Refuse a clone that cannot carry a consistent TPM-FDE disk and TPM."""
        if not self.source_has_tpm:
            raise RuntimeError(
                f"FDE source domain '{self.source_domain_name}' has no TPM device"
            )
        if self.source_tpm_state_dir is None or not self.source_tpm_state_dir.is_dir():
            raise RuntimeError(
                f"FDE source domain '{self.source_domain_name}' has no TPM state in "
                f"'{self.swtpm_state_dir}'"
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
        # copy2 keeps the source mode, and a read-only export would stop QEMU
        # opening the clone's NVRAM read-write at domain start.
        dest.chmod(0o600)
        self.pool.refresh(0)

    def _copy_tpm_state(self) -> None:
        """Copy the TPM state from the source domain to the new domain."""
        if self.source_tpm_state_dir is None or not self.source_tpm_state_dir.exists():
            LOGGER.info("No TPM state to copy from source domain")
            return

        new_uuid = self.domain.UUIDString()
        dest_tpm_dir = self.swtpm_state_dir / new_uuid
        shutil.copytree(self.source_tpm_state_dir, dest_tpm_dir)
        LOGGER.info(
            "Copied TPM state from '%s' to '%s'",
            self.source_tpm_state_dir,
            dest_tpm_dir,
        )

    def _prepare_tpm_state(self) -> None:
        """Apply declared clone preparations before the clone first boots.

        Removing the cloned TPM state must happen while the clone is stopped,
        which is only guaranteed here: a mid-run clear would also drop the
        graphical session that observes the product under test.
        """
        if self.fde_fixture is None or not self.fde_fixture.prepare:
            return
        self._require_clone_stopped()
        clone_dir = self.swtpm_state_dir / self.domain.UUIDString()
        for step in self.fde_fixture.prepare:
            if step == "clear-tpm-state":
                permall = clone_dir / "tpm2" / "tpm2-00.permall"
                if not permall.is_file():
                    raise RuntimeError(f"Clone TPM state is missing at '{permall}'")
                permall.unlink()
                LOGGER.info("Cleared the cloned TPM state at '%s'", permall)

    def _prepare_no_tpm_state(self) -> None:
        """Drop the stopped clone's TPM only after any healthy enrollment boot."""
        if self.fde_fixture is None or "no-tpm" not in self.fde_fixture.prepare:
            return
        self._require_clone_stopped()
        self._require_clone_not_source()
        expected_uuid = self.domain.UUIDString()
        root = ET.fromstring(self.domain.XMLDesc(0))
        devices = root.find("devices")
        if devices is None:
            raise RuntimeError(f"Clone '{self.domain_name}' has no devices to edit")
        tpm_devices = devices.findall("tpm")
        if not tpm_devices:
            raise RuntimeError(
                f"Clone '{self.domain_name}' has no TPM device to remove"
            )
        for tpm in tpm_devices:
            devices.remove(tpm)
        self._domain = self.conn.defineXML(ET.tostring(root, encoding="unicode"))
        if self._domain is None or self._domain.UUIDString() != expected_uuid:
            raise RuntimeError(
                f"Unable to redefine domain '{self.domain_name}' without its TPM"
            )
        LOGGER.info("Removed the TPM device from clone '%s'", self.domain_name)

    def _require_clone_not_source(self) -> None:
        """Refuse to mutate the source domain through its clone's handle."""
        if self.domain_name == self.source_domain_name:
            raise RuntimeError(
                f"Refusing to mutate source domain '{self.source_domain_name}'"
            )
        if (
            self.source_uuid is not None
            and self.domain.UUIDString() == self.source_uuid
        ):
            raise RuntimeError(
                f"Refusing to mutate clone '{self.domain_name}' with the source UUID"
            )

    def _prepare_fde_host_state(self) -> None:
        """Mutate the stopped clone's firmware or EFI system partition.

        These are the parts of the machine a user cannot change from the
        running OS: Secure Boot keys, the firmware variable store, and the
        applications the firmware launches before the OS boots.
        """
        if self.fde_fixture is None:
            return
        steps = self.fde_fixture.prepare
        if not any(step in HOST_PREPARATIONS for step in steps):
            return
        self._require_clone_stopped()
        prepare_clone_host_state(
            steps,
            Path(self.disk_volume.path()),
            self.pool_dir / self.nvram_volume_name,
        )
        if self._plain_ovmf_domain_deferred():
            self._redefine_plain_ovmf_domain()
        LOGGER.info("Prepared the clone's firmware state: %s", ", ".join(steps))

    def _enroll_clone_authentication(self) -> None:
        """Boot the clone once to enroll authentication, then stop it."""
        fixture = self.fde_fixture
        if fixture is None or AUTH_ENROLLMENT not in fixture.prepare:
            return
        self._require_clone_stopped()
        LOGGER.info(
            "Booting clone '%s' to enroll %s authentication",
            self.domain_name,
            fixture.auth_mode,
        )
        self.domain.create()
        guest = FdeGuest(fixture, self._clone_vsock_cid())
        try:
            self._wait_for_fde_guest(guest)
            parameters: dict[str, object] = {"auth_mode": fixture.auth_mode}
            parameters[fixture.auth_mode] = fixture.secret(fixture.auth_mode)
            result = guest.request(
                "enroll-auth", parameters, timeout=FDE_ENROLL_TIMEOUT
            )
            if result.get("auth_mode") != fixture.auth_mode:
                raise RuntimeError(
                    "snapd did not enroll the fixture's requested authentication"
                )
            guest.request("shutdown", timeout=FDE_ATTEMPT_TIMEOUT)
        finally:
            guest.close()
        self._wait_for_clone_stopped()

    def _clone_vsock_cid(self) -> int:
        _, cid = self._extract_domain_runtime_info(self.domain.XMLDesc(0))
        if cid is None:
            raise RuntimeError(
                f"VSOCK CID information is not available for clone '{self.domain_name}'"
            )
        return cid

    def _wait_for_fde_guest(self, guest: FdeGuest) -> None:
        """Wait, within one deadline, until snapd answers through the guest."""
        deadline = time.monotonic() + FDE_BOOT_TIMEOUT
        last_error: FdeGuestError | None = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    f"Clone '{self.domain_name}' did not become reachable in time"
                ) from last_error
            try:
                guest.request("snapshot", timeout=min(FDE_ATTEMPT_TIMEOUT, remaining))
                return
            except FdeGuestTimeout as error:
                last_error = error
            except FdeGuestError as error:
                # snapd owns its socket and can lag the SSH login during boot.
                if error.code != "snapd-unreachable":
                    raise
                last_error = error
            guest.close()
            time.sleep(min(FDE_POLL_INTERVAL, remaining))

    def _wait_for_clone_stopped(self) -> None:
        """Wait for a requested guest shutdown, with a fixed deadline."""
        deadline = time.monotonic() + FDE_SHUTDOWN_TIMEOUT
        while True:
            if self.domain.isActive() == 0:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    f"Clone '{self.domain_name}' did not shut down cleanly in time"
                )
            time.sleep(min(FDE_POLL_INTERVAL, remaining))

    def _require_clone_stopped(self) -> None:
        """Refuse to mutate a clone that is still running."""
        if self.domain.isActive() != 0:
            raise RuntimeError(f"Refusing to mutate running clone '{self.domain_name}'")

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
        if (
            self.fde_fixture is not None
            and "plain-ovmf" in self.fde_fixture.prepare
            and not self._plain_ovmf_domain_deferred()
        ):
            # The clone boots without Secure Boot so the firmware variables are
            # readable but not authenticated: a real, user-reachable state.
            domain_xml = prepare_plain_ovmf_domain_xml(domain_xml)
        self._domain = self.conn.defineXML(domain_xml)

        if self._domain is None:
            raise RuntimeError(f"Unable to define domain '{self.domain_name}'")

    def _plain_ovmf_domain_deferred(self) -> bool:
        """Return whether plain OVMF must wait until enrollment finished."""
        fixture = self.fde_fixture
        return (
            fixture is not None
            and "plain-ovmf" in fixture.prepare
            and AUTH_ENROLLMENT in fixture.prepare
        )

    def _redefine_plain_ovmf_domain(self) -> None:
        """Redefine the stopped clone as plain OVMF while keeping its identity."""
        self._require_clone_stopped()
        expected_uuid = self.domain.UUIDString()
        domain_xml = prepare_plain_ovmf_domain_xml(self.domain.XMLDesc(0))
        self._domain = self.conn.defineXML(domain_xml)
        if self._domain is None or self._domain.UUIDString() != expected_uuid:
            raise RuntimeError(
                f"Unable to redefine domain '{self.domain_name}' with its identity"
            )

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

        if self.fde_config is not None:
            fixture = self.fde_fixture
            if fixture is None:
                raise RuntimeError("FDE configuration is not loaded")
            if self.fde_vnc_port is not None and vnc_port != self.fde_vnc_port:
                raise RuntimeError(
                    f"clone display is on port {vnc_port}, but the capture pinned "
                    f"{self.fde_vnc_port}; the recording would not be the target"
                )
            case_artifacts = self._case_artifacts()
            marker_file = case_artifacts / "markers.jsonl"
            marker_file.touch(mode=0o600)
            self.marker_file = marker_file
            # Only private file paths and clone identity reach Robot. Credentials
            # and the recovery key stay inside the fixture and its private files.
            robot_variables.update(
                {
                    "FDE_CONFIG": str(self.fde_config),
                    "FDE_DOMAIN_UUID": self.domain.UUIDString(),
                    "FDE_SOURCE_UUID": str(self.source_uuid),
                    "FDE_CONNECTION_URI": self.connection_uri,
                    # A power-cut case restarts the clone and must prove it
                    # came back on the port Yarf keeps driving.
                    "FDE_VNC_PORT": str(vnc_port),
                    "FDE_SWTPM_STATE_DIR": str(self.swtpm_state_dir),
                    "FDE_SOURCE_DOMAIN": self.source_domain_name,
                    "FDE_DOMAIN_NVRAM": str(self.pool_dir / self.nvram_volume_name),
                    "FDE_PREPARE": ",".join(fixture.prepare),
                    "FDE_MARKER_FILE": str(marker_file),
                }
            )
            LOGGER.info(
                "Starting YARF for FDE case '%s' on clone '%s'",
                self.robot_test,
                self.domain_name,
            )
        elif self.recovery_key:
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
            video = self._save_log_video()
            if video is not None:
                LOGGER.info("Saved Yarf log video to '%s'", video)
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

    async def _run(self, suite: str, test: str) -> int:
        """Capture the clone display from power-on, then run Yarf against it."""
        self._pin_fde_display_port()
        self._begin_capture()
        try:
            return await super()._run(suite, test)
        finally:
            self._end_capture()

    def _pin_fde_display_port(self) -> None:
        """Give the clone a known VNC port so capture can precede power-on.

        Firmware, the encrypted-boot prompt and recovery shells only exist as
        pixels before the OS or Yarf is running. An autoport is assigned too
        late to record them, so the clone's display listener is pinned now.
        """
        if self.fde_config is None or not self.capture:
            return
        tree = ET.fromstring(self.domain.XMLDesc(0))
        devices = tree.find("devices")
        graphics = (
            devices.find("graphics[@type='vnc']") if devices is not None else None
        )
        if graphics is None:
            raise RuntimeError(
                f"clone domain '{self.domain_name}' has no VNC display to capture"
            )
        if self.domain.isActive() != 0:
            # The display already exists; capture the port it was given.
            assigned = graphics.get("port")
            if assigned is None or not assigned.isdigit():
                raise RuntimeError(
                    f"running clone '{self.domain_name}' has no usable VNC port"
                )
            self.fde_vnc_port = int(assigned)
            LOGGER.info(
                "Clone is already running; capturing its VNC port %s",
                self.fde_vnc_port,
            )
            return
        self._require_clone_stopped()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        graphics.set("autoport", "no")
        graphics.set("port", str(port))
        graphics.set("listen", "127.0.0.1")
        listen = graphics.find("listen")
        if listen is None:
            raise RuntimeError(
                f"clone domain '{self.domain_name}' has no VNC listen address"
            )
        listen.attrib.clear()
        listen.set("type", "address")
        listen.set("address", "127.0.0.1")
        xml = ET.tostring(tree, encoding="unicode")
        expected_uuid = self.domain.UUIDString()
        domain = self.conn.defineXML(xml)
        if domain is None or domain.UUIDString() != expected_uuid:
            raise RuntimeError(
                f"Unable to redefine domain '{self.domain_name}' with a fixed display"
            )
        self._domain = domain
        self.fde_vnc_port = port
        LOGGER.info("Clone display pinned to VNC port %s for capture", port)

    def _case_artifacts(self) -> Path:
        """Return the case's own evidence directory, creating it on first use."""
        if self.case_artifacts is None:
            self.case_artifacts = self.artifacts_path
        self.case_artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
        return self.case_artifacts

    def _begin_capture(self) -> None:
        """Record the target display before the guest can reach firmware."""
        if self.fde_config is None or not self.capture or self.fde_vnc_port is None:
            return
        artifacts = self._case_artifacts()
        supervisor = CaptureSupervisor(
            "127.0.0.1",
            self.fde_vnc_port,
            artifacts / "capture",
            domain_running=lambda: (
                self._domain is not None and self._domain.isActive() == 1
            ),
        )
        self.capture_supervisor = supervisor
        LOGGER.info("Capturing the clone display on VNC port %s", self.fde_vnc_port)

    def _end_capture(self) -> None:
        supervisor = self.capture_supervisor
        if supervisor is None:
            return
        self.capture_supervisor = None
        artifacts = self._case_artifacts()
        try:
            supervisor.stop()
        except CaptureError as error:
            LOGGER.error("Display capture failed: %s", error)
            raise
        finally:
            index = artifacts / "capture-index.json"
            supervisor.write_index(index)
            LOGGER.info("Wrote capture index to '%s'", index)

    def close(self) -> None:
        # Stop and undefine the domain first: its swtpm process may still write
        # to the state directory. Deleting the directory underneath a running
        # swtpm makes libtpms enter failure mode and can poison later cases.
        clone_uuid = self._domain.UUIDString() if self._domain is not None else None
        super().close()
        if clone_uuid is not None and not self.keep:
            tpm_dir = self.swtpm_state_dir / clone_uuid
            if tpm_dir.exists():
                try:
                    shutil.rmtree(tpm_dir)
                except OSError:
                    LOGGER.exception(
                        "Failed to delete TPM state directory '%s'", tpm_dir
                    )
