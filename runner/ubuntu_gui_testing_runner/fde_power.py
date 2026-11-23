"""Host-side power control for exactly one disposable TPM-FDE clone.

This module drives libvirt through its documented ``virsh`` CLI. Every lookup
is pinned to the clone UUID the runner created, and the golden source UUID is
refused. The clone's libvirt definition must also expose the vsock CID the
case observes, so an echoed but foreign UUID cannot make a power cut reach
another domain. libvirt assigns the CID and the VNC port only while the clone
runs, so a restarted clone must come back on both before the case talks to it
again.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Final

_VIRSH_TIMEOUT: Final = 60.0
SHUTOFF_TIMEOUT: Final = 30.0
POLL_INTERVAL: Final = 1.0

_RUNNING: Final = "running"
_SHUT_OFF: Final = "shut off"


class FdePowerError(RuntimeError):
    """Host-side power control failed or refused an unsafe target."""


@dataclass(frozen=True)
class ClonePower:
    """A verified disposable clone, its observed CID, and its source domain."""

    connection_uri: str
    domain_uuid: str
    source_uuid: str
    vsock_cid: int


def _parse_uuid(value: str, name: str) -> str:
    text = value.strip()
    try:
        parsed = uuid.UUID(text)
    except ValueError as error:
        raise FdePowerError(f"{name} is not a canonical UUID") from error
    if str(parsed) != text.lower():
        raise FdePowerError(f"{name} is not a canonical UUID")
    return str(parsed)


def _virsh(connection_uri: str, *arguments: str) -> str:
    """Run one virsh command with a bounded deadline and stable messages."""
    command = ["virsh", "--connect", connection_uri, *arguments]
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, never a shell
            command,
            capture_output=True,
            text=True,
            timeout=_VIRSH_TIMEOUT,
            env={**os.environ, "LC_ALL": "C"},
            check=False,
        )
    except FileNotFoundError as error:
        raise FdePowerError("virsh is not installed on the test host") from error
    except subprocess.TimeoutExpired as error:
        raise FdePowerError(f"virsh {arguments[0]} timed out") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
        raise FdePowerError(f"virsh {arguments[0]} failed: {detail}")
    return completed.stdout.strip()


def _require_clone_uuid(clone: ClonePower, root: ET.Element) -> None:
    """Require the definition reached by the clone UUID to be that domain.

    The identity is read from the fetched definition because ``virsh domuuid``
    accepts a domain name or id only: given a UUID it fails to resolve the
    domain, which no amount of retrying can fix.
    """
    observed = (root.findtext("./uuid") or "").strip().lower()
    if observed == clone.source_uuid:
        raise FdePowerError("refusing to control the golden source domain")
    if observed != clone.domain_uuid:
        raise FdePowerError(
            f"domain {clone.domain_uuid} resolved to {observed or 'no uuid'}, "
            "which is not the intended clone"
        )


def _reject_source_identity(clone: ClonePower) -> None:
    """Refuse the golden source before any libvirt call."""
    if clone.domain_uuid == clone.source_uuid:  # pragma: no cover - clone_target
        raise FdePowerError("refusing to control the golden source domain")


def _require_intended_clone(clone: ClonePower) -> None:
    _reject_source_identity(clone)
    live = _live_definition(clone)
    _require_clone_uuid(clone, live)
    _require_observed_vsock_cid(clone, live)


def _live_definition(clone: ClonePower) -> ET.Element:
    """Parse the domain's current libvirt definition.

    virsh dumpxml is local libvirt output for the domain named by the verified
    UUID, not remote input, so the standard parser is used here.
    """
    xml = _virsh(clone.connection_uri, "dumpxml", clone.domain_uuid)
    try:
        return ET.fromstring(xml.encode("utf-8"))  # noqa: S314 - local libvirt dumpxml
    except ET.ParseError as error:
        raise FdePowerError(
            f"cannot parse the libvirt definition of domain {clone.domain_uuid}"
        ) from error


def _require_observed_vsock_cid(clone: ClonePower, root: ET.Element) -> None:
    """Require the running domain to use the vsock CID the case observes.

    A definition always reports its own UUID, so the identity read from it
    cannot prove the domain behind it is this runner's clone. The case's guest
    channel is pinned to the CID libvirt assigned when the runner started the
    clone, so that CID is the second identity check before any destructive
    call.
    """
    cids: list[int] = []
    for element in root.findall("./devices/vsock/cid"):
        address = element.get("address")
        if address is None:
            raise FdePowerError(
                f"domain {clone.domain_uuid} has no assigned vsock CID; "
                "refusing to control a domain that is not the observed clone"
            )
        if not address.isdigit():
            raise FdePowerError(
                f"domain {clone.domain_uuid} has a malformed vsock CID definition"
            )
        cids.append(int(address))
    if len(cids) != 1:
        raise FdePowerError(
            f"domain {clone.domain_uuid} defines {len(cids)} vsock CIDs; "
            "refusing to control a domain that is not the observed clone"
        )
    if cids[0] != clone.vsock_cid:
        raise FdePowerError(
            f"domain {clone.domain_uuid} uses vsock CID {cids[0]}, "
            f"but this case observes CID {clone.vsock_cid}"
        )


def _domain_vnc_port(clone: ClonePower, root: ET.Element) -> int:
    ports = [
        graphics.get("port", "")
        for graphics in root.findall("./devices/graphics")
        if graphics.get("type") == "vnc"
    ]
    if len(ports) != 1 or not ports[0].isdigit():
        raise FdePowerError(
            f"domain {clone.domain_uuid} does not expose exactly one VNC port"
        )
    return int(ports[0])


def _domain_state(clone: ClonePower) -> str:
    return _virsh(clone.connection_uri, "domstate", clone.domain_uuid).strip()


def verified_clone(
    domain_uuid: str, source_uuid: str, connection_uri: str, vsock_cid: int
) -> ClonePower:
    """Return the clone only when it exists, runs, and is not the source."""
    clone = clone_target(domain_uuid, source_uuid, connection_uri, vsock_cid)
    state = _domain_state(clone)
    if state != _RUNNING:
        raise FdePowerError(
            f"clone {clone.domain_uuid} is {state!r}, "
            f"expected {_RUNNING!r} before arming"
        )
    return clone


def clone_target(
    domain_uuid: str, source_uuid: str, connection_uri: str, vsock_cid: int
) -> ClonePower:
    """Return the clone identity only when it resolves and is not the source."""
    clone_uuid = _parse_uuid(domain_uuid, "FDE_DOMAIN_UUID")
    source = _parse_uuid(source_uuid, "FDE_SOURCE_UUID")
    if isinstance(vsock_cid, bool) or not isinstance(vsock_cid, int) or vsock_cid <= 0:
        raise FdePowerError("the observed vsock CID must be a positive integer")
    uri = connection_uri.strip()
    if not uri:
        raise FdePowerError("FDE_CONNECTION_URI is required to control the clone")
    if clone_uuid == source:
        raise FdePowerError("refusing to control the golden source domain")

    clone = ClonePower(uri, clone_uuid, source, vsock_cid)
    _require_intended_clone(clone)
    return clone


def power_off_clone(clone: ClonePower) -> str:
    """Cut power to the verified clone and prove it reported shut off.

    The identity and running state are checked again immediately before the
    destructive call, so a stale or foreign domain is never destroyed.
    """
    _reject_source_identity(clone)
    live = _live_definition(clone)
    _require_clone_uuid(clone, live)
    state = _domain_state(clone)
    if state != _RUNNING:
        raise FdePowerError(
            f"clone {clone.domain_uuid} is {state!r}; refusing to report "
            "a power cut for a domain that is not running"
        )
    _require_observed_vsock_cid(clone, live)

    _virsh(clone.connection_uri, "destroy", clone.domain_uuid)

    deadline = time.monotonic() + SHUTOFF_TIMEOUT
    while True:
        state = _domain_state(clone)
        if state == _SHUT_OFF:
            return state
        if time.monotonic() >= deadline:
            raise FdePowerError(
                f"clone {clone.domain_uuid} did not report {_SHUT_OFF!r} within "
                f"{SHUTOFF_TIMEOUT}s after destroy (state {state!r})"
            )
        time.sleep(POLL_INTERVAL)


def start_clone(clone: ClonePower, vnc_port: int) -> str:
    """Start the clone again after a power cut and prove the case reaches it.

    A shut-off clone has no vsock CID or VNC port, so only its UUID is checked
    before start: it is the UUID that ran on the observed CID when the case
    armed the cut. Once running, the clone must be back on that CID, which the
    guest channel uses, and on ``vnc_port``, which Yarf drives, or the case
    could reach another domain.
    """
    _reject_source_identity(clone)
    live = _live_definition(clone)
    _require_clone_uuid(clone, live)
    state = _domain_state(clone)
    if state == _SHUT_OFF:
        _virsh(clone.connection_uri, "start", clone.domain_uuid)
        state = _wait_until_running(clone)
        live = _live_definition(clone)
    elif state != _RUNNING:
        raise FdePowerError(
            f"clone {clone.domain_uuid} is {state!r}; expected {_SHUT_OFF!r} "
            "before starting it again"
        )
    _require_observed_vsock_cid(clone, live)
    observed_port = _domain_vnc_port(clone, live)
    if observed_port != vnc_port:
        raise FdePowerError(
            f"clone {clone.domain_uuid} runs on VNC port {observed_port}, "
            f"but Yarf drives port {vnc_port}"
        )
    return state


def _wait_until_running(clone: ClonePower) -> str:
    deadline = time.monotonic() + SHUTOFF_TIMEOUT
    while True:
        state = _domain_state(clone)
        if state == _RUNNING:
            return state
        if time.monotonic() >= deadline:
            raise FdePowerError(
                f"clone {clone.domain_uuid} did not report {_RUNNING!r} within "
                f"{SHUTOFF_TIMEOUT}s after start (state {state!r})"
            )
        time.sleep(POLL_INTERVAL)


__all__ = [
    "ClonePower",
    "FdePowerError",
    "POLL_INTERVAL",
    "clone_target",
    "power_off_clone",
    "start_clone",
    "verified_clone",
]
