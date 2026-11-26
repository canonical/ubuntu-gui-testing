from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from xml.etree.ElementTree import Element as _XmlElement

import defusedxml.ElementTree as ET
import libvirt  # type: ignore[import-untyped]

from ubuntu_gui_testing_runner.base import domain_name_prefix

LOGGER = logging.getLogger(__name__)


def delete_previous_runs(
    *,
    suite_name: str,
    test_name: str,
    connection_uri: str,
    pool_name: str,
    swtpm_state_dir: Path,
    pool_dir: Path,
) -> None:
    """Delete kept domains and VM state from previous runs of one test."""
    try:
        conn = libvirt.open(connection_uri)
    except libvirt.libvirtError as exc:
        raise RuntimeError(
            f"Unable to open libvirt connection '{connection_uri}'"
        ) from exc
    if conn is None:
        raise RuntimeError(f"Unable to open libvirt connection '{connection_uri}'")

    pool: libvirt.virStoragePool | None = None
    try:
        try:
            pool = conn.storagePoolLookupByName(pool_name)
            pool.refresh(0)
        except libvirt.libvirtError:
            LOGGER.exception("Failed to refresh storage pool '%s'", pool_name)

        prefix = domain_name_prefix(suite_name, test_name)
        pattern = re.compile(rf"^{re.escape(prefix)}-\d{{8}}T\d{{6}}Z(?:-\d+)?$")

        for domain in conn.listAllDomains():
            name = str(domain.name())
            if pattern.match(name) is None:
                continue
            _delete_domain_resources(domain, swtpm_state_dir, pool_dir)

        if pool is not None:
            try:
                pool.refresh(0)
            except libvirt.libvirtError:
                LOGGER.exception("Failed to refresh storage pool '%s'", pool_name)
    finally:
        try:
            conn.close()
        except libvirt.libvirtError:
            LOGGER.exception("Failed to close libvirt connection")


def _delete_domain_resources(
    domain: libvirt.virDomain,
    swtpm_state_dir: Path,
    pool_dir: Path,
) -> None:
    name = str(domain.name())
    LOGGER.info("Deleting previous domain '%s'", name)

    paths: set[Path] = set()
    uuid: str | None = None
    try:
        xml = ET.fromstring(domain.XMLDesc(0))
        uuid_elem = xml.find("uuid")
        if uuid_elem is not None and uuid_elem.text:
            uuid = uuid_elem.text.strip()
        paths.update(_resource_paths(xml))
    except (ET.ParseError, libvirt.libvirtError):
        LOGGER.exception("Failed to inspect previous domain '%s'", name)

    try:
        if domain.isActive() == 1:
            domain.destroy()
    except libvirt.libvirtError:
        LOGGER.exception("Failed to destroy previous domain '%s'", name)

    try:
        domain.undefineFlags(libvirt.VIR_DOMAIN_UNDEFINE_NVRAM)
    except libvirt.libvirtError:
        LOGGER.exception("Failed to undefine previous domain '%s'", name)

    for path in paths:
        _delete_file(path, pool_dir)

    if uuid:
        _delete_tpm_state(swtpm_state_dir / uuid)


def _resource_paths(xml: _XmlElement) -> set[Path]:
    paths: set[Path] = set()

    for disk in xml.findall("./devices/disk"):
        if disk.get("device") != "disk":
            continue
        source = disk.find("source")
        file_path = None if source is None else source.get("file")
        if file_path is None:
            continue
        path = Path(file_path)
        if path.suffix.lower() == ".qcow2":
            paths.add(path)

    nvram = xml.find("./os/nvram")
    if nvram is not None:
        nvram_path = (
            nvram.text.strip() if nvram.text is not None else nvram.get("source")
        )
        if nvram_path:
            paths.add(Path(nvram_path))

    return {path for path in paths if path.suffix.lower() != ".iso"}


def _delete_file(path: Path, pool_dir: Path) -> None:
    if path.suffix.lower() == ".iso":
        LOGGER.info("Refusing to delete ISO file '%s'", path)
        return

    try:
        resolved = path.resolve(strict=False)
        pool_resolved = pool_dir.resolve(strict=False)
    except (OSError, RuntimeError):
        LOGGER.exception("Failed to resolve previous run file '%s'", path)
        return

    if not _is_relative_to(resolved, pool_resolved):
        LOGGER.info(
            "Skipping deletion of '%s' because it is outside pool dir '%s'",
            path,
            pool_dir,
        )
        return

    try:
        resolved.unlink(missing_ok=True)
    except OSError:
        LOGGER.exception("Failed to delete previous run file '%s'", resolved)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _delete_tpm_state(path: Path) -> None:
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError:
        LOGGER.exception("Failed to delete previous TPM state directory '%s'", path)
