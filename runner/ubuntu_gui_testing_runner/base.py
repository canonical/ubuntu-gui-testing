from __future__ import annotations

import asyncio
import logging
import os
import time
from abc import abstractmethod
from datetime import date
from pathlib import Path

import defusedxml.ElementTree as ET
import libvirt  # type: ignore[import-untyped]

from ubuntu_gui_testing_runner.constants import (
    DEFAULT_ARTIFACTS_DIR,
    DEFAULT_CONNECTION_URI,
    DEFAULT_POOL_DIR,
    DEFAULT_POOL_NAME,
    DEFAULT_POOL_TEMPLATE,
    GRACEFUL_SHUTDOWN_POLL_INTERVAL,
    GRACEFUL_SHUTDOWN_TIMEOUT,
)
from ubuntu_gui_testing_runner.runner import Runner

LOGGER = logging.getLogger(__name__)


class _BaseLibvirtRunner(Runner):
    """Common infrastructure for libvirt-based runners."""

    def __init__(
        self,
        suite_name: str,
        test_name: str,
        pool_template: Path | None = None,
        artifacts_dir: Path | None = None,
        keep: bool = False,
        connection_uri: str = DEFAULT_CONNECTION_URI,
        pool_name: str = DEFAULT_POOL_NAME,
        pool_dir: Path = DEFAULT_POOL_DIR,
    ) -> None:
        self.connection_uri = connection_uri
        self.pool_name = pool_name
        self.pool_dir = pool_dir.resolve()
        self.keep = keep

        self.pool_template_path = (
            pool_template.resolve()
            if pool_template is not None
            else DEFAULT_POOL_TEMPLATE
        )
        self.artifacts_path = (
            artifacts_dir.resolve()
            if artifacts_dir is not None
            else DEFAULT_ARTIFACTS_DIR.resolve()
        )

        self._conn: libvirt.virConnect | None = None
        self._pool: libvirt.virStoragePool | None = None
        self._disk_volume: libvirt.virStorageVol | None = None
        self._domain: libvirt.virDomain | None = None

        try:
            self._open_connection()
            self.domain_name = self._generate_domain_name(suite_name, test_name)
            self.disk_volume_name = f"{self.domain_name}.qcow2"
            self.nvram_volume_name = f"{self.domain_name}-VARS.fd"
            self._ensure_pool()
            self._setup()
        except Exception:
            self.close()
            raise

    @abstractmethod
    def _setup(self) -> None:
        """Create volumes and define the domain. Subclasses implement this."""

    @property
    def conn(self) -> libvirt.virConnect:
        if self._conn is None:
            raise RuntimeError("Libvirt connection is not initialized")
        return self._conn

    @property
    def pool(self) -> libvirt.virStoragePool:
        if self._pool is None:
            raise RuntimeError("Storage pool is not initialized")
        return self._pool

    @property
    def disk_volume(self) -> libvirt.virStorageVol:
        if self._disk_volume is None:
            raise RuntimeError("Disk volume is not initialized")
        return self._disk_volume

    @property
    def domain(self) -> libvirt.virDomain:
        if self._domain is None:
            raise RuntimeError("Domain is not initialized")
        return self._domain

    def __enter__(self) -> _BaseLibvirtRunner:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._pool is not None:
            self._pool.refresh(0)

        if self.keep:
            if self._domain is not None:
                self._shutdown_domain()
            LOGGER.info(
                "Keeping domain '%s' and associated resources as requested",
                self.domain_name,
            )
        else:
            if self._domain is not None:
                self._destroy_domain()

            if self._disk_volume is not None:
                try:
                    self._disk_volume.delete()
                except libvirt.libvirtError:
                    LOGGER.exception(
                        "Failed to delete disk volume '%s'", self.disk_volume_name
                    )

            if self._pool is not None:
                try:
                    nvram_volume = self._pool.storageVolLookupByName(
                        self.nvram_volume_name
                    )
                    nvram_volume.delete()
                except libvirt.libvirtError:
                    LOGGER.exception(
                        "Failed to delete NVRAM volume '%s'", self.nvram_volume_name
                    )

            if self._domain is not None:
                try:
                    self._domain.undefine()
                except libvirt.libvirtError:
                    LOGGER.exception("Failed to undefine domain '%s'", self.domain_name)

        if self._conn is not None:
            try:
                self._conn.close()
            except libvirt.libvirtError:
                LOGGER.exception("Failed to close libvirt connection")

        self._domain = None
        self._disk_volume = None
        self._pool = None
        self._conn = None

    def _shutdown_domain(self) -> None:
        """Power off the domain, gracefully first then forcefully on timeout.

        Requests an ACPI shutdown and polls until the domain becomes
        inactive.  If it does not power off within
        ``GRACEFUL_SHUTDOWN_TIMEOUT`` seconds, it is forcefully destroyed.
        Any libvirt error degrades to a forced destroy so teardown can
        always proceed.
        """
        try:
            if self.domain.isActive() != 1:
                return
        except libvirt.libvirtError:
            LOGGER.exception("Failed to query state of domain '%s'", self.domain_name)
            return

        LOGGER.info("Requesting graceful shutdown of domain '%s'", self.domain_name)
        try:
            self.domain.shutdown()
        except libvirt.libvirtError:
            LOGGER.exception(
                "Failed to request graceful shutdown of domain '%s'", self.domain_name
            )
            self._destroy_domain()
            return

        deadline = time.monotonic() + GRACEFUL_SHUTDOWN_TIMEOUT
        while time.monotonic() < deadline:
            try:
                if self.domain.isActive() != 1:
                    LOGGER.info("Domain '%s' shut down gracefully", self.domain_name)
                    return
            except libvirt.libvirtError:
                LOGGER.exception(
                    "Failed to query state of domain '%s'", self.domain_name
                )
                return
            time.sleep(GRACEFUL_SHUTDOWN_POLL_INTERVAL)

        LOGGER.warning(
            "Domain '%s' did not shut down within %ss, forcing destroy",
            self.domain_name,
            GRACEFUL_SHUTDOWN_TIMEOUT,
        )
        self._destroy_domain()

    def _destroy_domain(self) -> None:
        try:
            if self.domain.isActive() == 1:
                self.domain.destroy()
        except libvirt.libvirtError:
            LOGGER.exception("Failed to destroy domain '%s'", self.domain_name)

    async def _run(self, suite: str, test: str) -> int:
        """Start the domain and log key runtime connectivity properties."""
        LOGGER.info("Starting suite '%s' test '%s'", suite, test)
        if self.domain.isActive() == 0:
            self.domain.create()

        domain_xml = self.domain.XMLDesc(0)
        vnc_port, vsock_cid = self._extract_domain_runtime_info(domain_xml)

        LOGGER.info("Domain '%s' started", self.domain_name)
        if vnc_port is None:
            raise RuntimeError("VNC port information is not available in domain XML")
        if vnc_port < 5900:
            raise RuntimeError(f"VNC port {vnc_port} is below 5900")
        LOGGER.info("VNC port: %s", vnc_port)

        if vsock_cid is None:
            raise RuntimeError("VSOCK CID information is not available in domain XML")
        LOGGER.info("VSOCK CID: %s", vsock_cid)

        return await self._run_yarf(suite, test, vsock_cid, vnc_port)

    @abstractmethod
    async def _run_yarf(
        self, suite: str, test: str, vsock_cid: int, vnc_port: int
    ) -> int:
        """Run the yarf process. Subclasses implement specific lifecycle."""

    def run(self, suite: str, test: str) -> int:
        return asyncio.run(self._run(suite, test))

    def _generate_domain_name(self, suite_name: str, test_name: str) -> str:
        base = f"ugt-{suite_name}-{test_name}-{date.today().isoformat()}"
        if not self._domain_exists(base):
            return base
        run = 2
        while self._domain_exists(f"{base}-{run}"):
            run += 1
        return f"{base}-{run}"

    def _domain_exists(self, name: str) -> bool:
        try:
            self.conn.lookupByName(name)
            return True
        except libvirt.libvirtError:
            return False

    def _open_connection(self) -> None:
        self._conn = libvirt.open(self.connection_uri)
        if self._conn is None:
            raise RuntimeError(
                f"Unable to open libvirt connection '{self.connection_uri}'"
            )

    def _ensure_pool(self) -> None:
        try:
            self._pool = self.conn.storagePoolLookupByName(self.pool_name)
        except libvirt.libvirtError as err:
            pool_xml = self._render_template(
                self.pool_template_path,
                {"pool_name": self.pool_name, "pool_path": str(self.pool_dir)},
            )
            self._pool = self.conn.storagePoolDefineXML(pool_xml, 0)
            if self._pool is None:
                raise RuntimeError(
                    f"Unable to define storage pool '{self.pool_name}'"
                ) from err
            self._pool.build(0)
            self._pool.create(0)
            self._pool.setAutostart(True)

        if self.pool.isActive() != 1:
            self.pool.create(0)

        self.pool.refresh(0)

    async def _spawn_yarf(
        self,
        suite: str,
        test: str,
        vnc_port: int,
        robot_variables: dict[str, str],
    ) -> asyncio.subprocess.Process:
        command = [
            "yarf",
            "--platform=Vnc",
            suite,
            "--outdir",
            str(self.artifacts_path),
            "--",
        ]
        for name, value in robot_variables.items():
            command.extend(["--variable", f"{name}:{value}"])
        command.extend(["--suite", test])
        env = os.environ.copy()
        env["VNC_PORT"] = str(vnc_port - 5900)
        process = await asyncio.create_subprocess_exec(*command, env=env)
        return process

    @staticmethod
    def _render_template(path: Path, replacements: dict[str, str]) -> str:
        xml = path.read_text(encoding="utf-8")
        for key, value in replacements.items():
            xml = xml.replace(f"{{{key}}}", value)
        return xml

    @staticmethod
    def _extract_domain_runtime_info(domain_xml: str) -> tuple[int | None, int | None]:
        root = ET.fromstring(domain_xml)

        vnc_port: int | None = None
        for graphics in root.findall("./devices/graphics"):
            if graphics.get("type") == "vnc":
                port = graphics.get("port")
                vnc_port = int(port) if port is not None else None
                break

        vsock = root.find("./devices/vsock/cid")
        address = None if vsock is None else vsock.get("address")
        vsock_cid = None if address is None else int(address)

        return vnc_port, vsock_cid
