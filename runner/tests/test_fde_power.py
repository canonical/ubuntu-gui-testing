"""Unit tests for the guarded host-side power cut."""

from __future__ import annotations

import subprocess
import time
from typing import Any
from unittest.mock import Mock

import pytest

from ubuntu_gui_testing_runner import fde_power

CLONE_UUID = "11111111-2222-3333-4444-555555555555"
SOURCE_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
FOREIGN_UUID = "99999999-8888-7777-6666-555555555555"
CONNECTION_URI = "qemu:///session"
VSOCK_CID = 3
VNC_PORT = 5901


def _dumpxml(cid: int, vnc_port: int = VNC_PORT, uuid_value: str = CLONE_UUID) -> str:
    return (
        f"<domain><uuid>{uuid_value}</uuid><devices>"
        f"<graphics type='vnc' port='{vnc_port}' autoport='yes'/>"
        f"<vsock model='virtio'><cid auto='yes' address='{cid}'/></vsock>"
        "</devices></domain>"
    )


# libvirt assigns an automatic CID and VNC port only while the domain runs.
_SHUT_OFF_DUMPXML = (
    f"<domain><uuid>{CLONE_UUID}</uuid><devices>"
    "<graphics type='vnc' port='-1' autoport='yes'/>"
    "<vsock model='virtio'><cid auto='yes'/></vsock>"
    "</devices></domain>"
)


class _Virsh:
    """Scripted virsh responses that record every command."""

    def __init__(
        self,
        *,
        states: list[str] | None = None,
        vsock_cid: int = VSOCK_CID,
        dumpxml: str | None = None,
    ) -> None:
        self.states = states or ["running"]
        self.dumpxml = dumpxml if dumpxml is not None else _dumpxml(vsock_cid)
        self.shut_off_dumpxml = _SHUT_OFF_DUMPXML
        self.reported_state: str | None = None
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, connection_uri: str, *arguments: str) -> str:
        self.calls.append((connection_uri, *arguments))
        command = arguments[0]
        if command == "dumpxml":
            state = self.reported_state or self.states[0]
            return self.shut_off_dumpxml if state == "shut off" else self.dumpxml
        if command == "domstate":
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            self.reported_state = state
            return state
        if command == "destroy":
            return ""
        if command == "start":
            return ""
        raise AssertionError(f"unexpected virsh command {command}")

    @property
    def destroyed(self) -> bool:
        return any(call[1] == "destroy" for call in self.calls)


@pytest.fixture
def virsh() -> _Virsh:
    return _Virsh()


def test_verified_clone_rejects_the_source_identity_before_libvirt(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    monkeypatch.setattr(fde_power, "_virsh", virsh)

    with pytest.raises(fde_power.FdePowerError, match="source domain"):
        fde_power.verified_clone(SOURCE_UUID, SOURCE_UUID, CONNECTION_URI, VSOCK_CID)
    assert virsh.calls == []


@pytest.mark.parametrize(
    ("clone", "message"),
    [
        ("not-a-uuid", "FDE_DOMAIN_UUID"),
        ("{" + CLONE_UUID + "}", "FDE_DOMAIN_UUID"),
        (CLONE_UUID, "FDE_SOURCE_UUID"),
    ],
)
def test_verified_clone_requires_canonical_distinct_uuids(
    monkeypatch: pytest.MonkeyPatch,
    virsh: _Virsh,
    clone: str,
    message: str,
) -> None:
    monkeypatch.setattr(fde_power, "_virsh", virsh)
    source = "not-a-uuid" if message == "FDE_SOURCE_UUID" else SOURCE_UUID

    with pytest.raises(fde_power.FdePowerError, match=message):
        fde_power.verified_clone(clone, source, CONNECTION_URI, VSOCK_CID)
    assert virsh.calls == []


def test_verified_clone_requires_a_connection_uri(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    monkeypatch.setattr(fde_power, "_virsh", virsh)

    with pytest.raises(fde_power.FdePowerError, match="FDE_CONNECTION_URI"):
        fde_power.verified_clone(CLONE_UUID, SOURCE_UUID, "  ", VSOCK_CID)
    assert virsh.calls == []


def test_verified_clone_rejects_a_foreign_domain(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    virsh.dumpxml = _dumpxml(VSOCK_CID, uuid_value=FOREIGN_UUID)
    monkeypatch.setattr(fde_power, "_virsh", virsh)

    with pytest.raises(fde_power.FdePowerError, match="not the intended clone"):
        fde_power.verified_clone(CLONE_UUID, SOURCE_UUID, CONNECTION_URI, VSOCK_CID)
    assert not virsh.destroyed


def test_verified_clone_refuses_a_foreign_domain_on_another_vsock_cid(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    # A foreign domain UUID always resolves to itself; only its dumpxml CID
    # can prove that it is not the clone this case observes.
    virsh.dumpxml = _dumpxml(9)
    monkeypatch.setattr(fde_power, "_virsh", virsh)

    with pytest.raises(fde_power.FdePowerError, match="vsock CID 9"):
        fde_power.verified_clone(CLONE_UUID, SOURCE_UUID, CONNECTION_URI, VSOCK_CID)
    assert not virsh.destroyed


def test_clone_identity_comes_from_a_uuid_capable_lookup(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    # virsh domuuid takes a domain name or id, so it cannot resolve the UUID
    # the runner created; the identity has to come from the definition.
    monkeypatch.setattr(fde_power, "_virsh", virsh)

    fde_power.verified_clone(CLONE_UUID, SOURCE_UUID, CONNECTION_URI, VSOCK_CID)

    assert all(call[1] != "domuuid" for call in virsh.calls)
    assert virsh.calls[0] == (CONNECTION_URI, "dumpxml", CLONE_UUID)


def test_verified_clone_rejects_a_definition_that_reports_the_source(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    virsh.dumpxml = _dumpxml(VSOCK_CID, uuid_value=SOURCE_UUID)
    monkeypatch.setattr(fde_power, "_virsh", virsh)

    with pytest.raises(fde_power.FdePowerError, match="source domain"):
        fde_power.verified_clone(CLONE_UUID, SOURCE_UUID, CONNECTION_URI, VSOCK_CID)
    assert not virsh.destroyed


def test_verified_clone_requires_a_running_domain(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    virsh.states = ["paused"]
    monkeypatch.setattr(fde_power, "_virsh", virsh)

    with pytest.raises(fde_power.FdePowerError, match="expected 'running'"):
        fde_power.verified_clone(CLONE_UUID, SOURCE_UUID, CONNECTION_URI, VSOCK_CID)
    assert not virsh.destroyed


def test_power_off_rejects_a_source_identity_before_libvirt(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    monkeypatch.setattr(fde_power, "_virsh", virsh)
    clone = fde_power.ClonePower(CONNECTION_URI, SOURCE_UUID, SOURCE_UUID, VSOCK_CID)

    with pytest.raises(fde_power.FdePowerError, match="source domain"):
        fde_power.power_off_clone(clone)
    assert virsh.calls == []


def test_power_off_refuses_a_foreign_domain(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    virsh.dumpxml = _dumpxml(VSOCK_CID, uuid_value=FOREIGN_UUID)
    monkeypatch.setattr(fde_power, "_virsh", virsh)
    clone = fde_power.ClonePower(CONNECTION_URI, CLONE_UUID, SOURCE_UUID, VSOCK_CID)

    with pytest.raises(fde_power.FdePowerError, match="not the intended clone"):
        fde_power.power_off_clone(clone)
    assert not virsh.destroyed


def test_power_off_refuses_a_foreign_domain_on_another_vsock_cid(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    virsh.dumpxml = _dumpxml(9)
    monkeypatch.setattr(fde_power, "_virsh", virsh)
    clone = fde_power.ClonePower(CONNECTION_URI, CLONE_UUID, SOURCE_UUID, VSOCK_CID)

    with pytest.raises(fde_power.FdePowerError, match="vsock CID 9"):
        fde_power.power_off_clone(clone)
    assert not virsh.destroyed


def test_power_off_refuses_an_ambiguous_vsock_definition(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    virsh.dumpxml = (
        f"<domain><uuid>{CLONE_UUID}</uuid><devices><vsock><cid address='3'/></vsock>"
        "<vsock><cid address='4'/></vsock></devices></domain>"
    )
    monkeypatch.setattr(fde_power, "_virsh", virsh)
    clone = fde_power.ClonePower(CONNECTION_URI, CLONE_UUID, SOURCE_UUID, VSOCK_CID)

    with pytest.raises(fde_power.FdePowerError, match="defines 2 vsock CIDs"):
        fde_power.power_off_clone(clone)
    assert not virsh.destroyed


def test_power_off_refuses_a_malformed_vsock_cid(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    virsh.dumpxml = (
        f"<domain><uuid>{CLONE_UUID}</uuid>"
        "<devices><vsock><cid address='not-a-cid'/></vsock></devices></domain>"
    )
    monkeypatch.setattr(fde_power, "_virsh", virsh)
    clone = fde_power.ClonePower(CONNECTION_URI, CLONE_UUID, SOURCE_UUID, VSOCK_CID)

    with pytest.raises(fde_power.FdePowerError, match="malformed vsock CID"):
        fde_power.power_off_clone(clone)
    assert not virsh.destroyed


def test_power_off_refuses_a_domain_that_is_not_running(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    virsh.states = ["shut off"]
    monkeypatch.setattr(fde_power, "_virsh", virsh)
    clone = fde_power.ClonePower(CONNECTION_URI, CLONE_UUID, SOURCE_UUID, VSOCK_CID)

    with pytest.raises(fde_power.FdePowerError, match="not running"):
        fde_power.power_off_clone(clone)
    assert not virsh.destroyed


def test_power_off_destroys_only_the_verified_clone(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    virsh.states = ["running", "shut off"]
    monkeypatch.setattr(fde_power, "_virsh", virsh)
    clone = fde_power.ClonePower(CONNECTION_URI, CLONE_UUID, SOURCE_UUID, VSOCK_CID)

    assert fde_power.power_off_clone(clone) == "shut off"

    assert virsh.calls == [
        (CONNECTION_URI, "dumpxml", CLONE_UUID),
        (CONNECTION_URI, "domstate", CLONE_UUID),
        (CONNECTION_URI, "destroy", CLONE_UUID),
        (CONNECTION_URI, "domstate", CLONE_UUID),
    ]


def test_power_off_bounds_the_shut_off_confirmation(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    virsh.states = ["running"]
    monkeypatch.setattr(fde_power, "_virsh", virsh)
    monkeypatch.setattr(fde_power, "SHUTOFF_TIMEOUT", 2.0)
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(time, "sleep", sleep)
    clone = fde_power.ClonePower(CONNECTION_URI, CLONE_UUID, SOURCE_UUID, VSOCK_CID)

    with pytest.raises(fde_power.FdePowerError, match="did not report 'shut off'"):
        fde_power.power_off_clone(clone)
    assert virsh.destroyed


def test_virsh_runs_with_a_c_locale_and_bounded_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="running\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert fde_power._virsh(CONNECTION_URI, "domstate", CLONE_UUID) == "running"
    assert captured["command"] == [
        "virsh",
        "--connect",
        CONNECTION_URI,
        "domstate",
        CLONE_UUID,
    ]
    assert captured["kwargs"]["env"]["LC_ALL"] == "C"
    assert captured["kwargs"]["timeout"] == fde_power._VIRSH_TIMEOUT
    assert captured["kwargs"]["check"] is False


def test_virsh_reports_a_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=FileNotFoundError()))

    with pytest.raises(fde_power.FdePowerError, match="not installed"):
        fde_power._virsh(CONNECTION_URI, "domstate", CLONE_UUID)


def test_virsh_reports_a_command_failure_without_inventing_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        Mock(
            return_value=subprocess.CompletedProcess(
                [], 1, stdout="", stderr="error: failed to connect\n"
            )
        ),
    )

    with pytest.raises(fde_power.FdePowerError, match="failed to connect"):
        fde_power._virsh(CONNECTION_URI, "domstate", CLONE_UUID)


def test_virsh_reports_a_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        Mock(side_effect=subprocess.TimeoutExpired("virsh", 1)),
    )

    with pytest.raises(fde_power.FdePowerError, match="timed out"):
        fde_power._virsh(CONNECTION_URI, "domstate", CLONE_UUID)


def test_start_clone_rejects_a_source_identity_before_libvirt(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    monkeypatch.setattr(fde_power, "_virsh", virsh)
    clone = fde_power.ClonePower(CONNECTION_URI, SOURCE_UUID, SOURCE_UUID, VSOCK_CID)

    with pytest.raises(fde_power.FdePowerError, match="source domain"):
        fde_power.start_clone(clone, VNC_PORT)
    assert virsh.calls == []


def test_start_clone_refuses_a_foreign_domain(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    virsh.dumpxml = _dumpxml(VSOCK_CID, uuid_value=FOREIGN_UUID)
    monkeypatch.setattr(fde_power, "_virsh", virsh)
    clone = fde_power.ClonePower(CONNECTION_URI, CLONE_UUID, SOURCE_UUID, VSOCK_CID)

    with pytest.raises(fde_power.FdePowerError, match="not the intended clone"):
        fde_power.start_clone(clone, VNC_PORT)
    assert not any(call[1] == "start" for call in virsh.calls)


def test_start_clone_refuses_a_running_domain_on_another_vsock_cid(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    virsh.dumpxml = _dumpxml(9)
    monkeypatch.setattr(fde_power, "_virsh", virsh)
    clone = fde_power.ClonePower(CONNECTION_URI, CLONE_UUID, SOURCE_UUID, VSOCK_CID)

    with pytest.raises(fde_power.FdePowerError, match="vsock CID 9"):
        fde_power.start_clone(clone, VNC_PORT)
    assert not any(call[1] == "start" for call in virsh.calls)


def test_start_clone_refuses_a_restarted_clone_on_another_vsock_cid(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    # The guest channel is pinned to the observed CID, so a clone that came
    # back on another one must not be reported as started.
    virsh.states = ["shut off", "running"]
    virsh.dumpxml = _dumpxml(9)
    monkeypatch.setattr(fde_power, "_virsh", virsh)
    clone = fde_power.ClonePower(CONNECTION_URI, CLONE_UUID, SOURCE_UUID, VSOCK_CID)

    with pytest.raises(fde_power.FdePowerError, match="vsock CID 9"):
        fde_power.start_clone(clone, VNC_PORT)


def test_start_clone_refuses_a_restarted_clone_on_another_vnc_port(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    # Yarf keeps the VNC port it was started with, so a clone that came back
    # on another port must not receive the case's input.
    virsh.states = ["shut off", "running"]
    virsh.dumpxml = _dumpxml(VSOCK_CID, vnc_port=5902)
    monkeypatch.setattr(fde_power, "_virsh", virsh)
    clone = fde_power.ClonePower(CONNECTION_URI, CLONE_UUID, SOURCE_UUID, VSOCK_CID)

    with pytest.raises(fde_power.FdePowerError, match="VNC port 5902"):
        fde_power.start_clone(clone, VNC_PORT)


def test_start_clone_refuses_a_domain_that_is_not_shut_off(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    virsh.states = ["paused"]
    monkeypatch.setattr(fde_power, "_virsh", virsh)
    clone = fde_power.ClonePower(CONNECTION_URI, CLONE_UUID, SOURCE_UUID, VSOCK_CID)

    with pytest.raises(fde_power.FdePowerError, match="expected 'shut off'"):
        fde_power.start_clone(clone, VNC_PORT)
    assert not any(call[1] == "start" for call in virsh.calls)


def test_start_clone_returns_an_already_running_clone(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    virsh.states = ["running"]
    monkeypatch.setattr(fde_power, "_virsh", virsh)
    clone = fde_power.ClonePower(CONNECTION_URI, CLONE_UUID, SOURCE_UUID, VSOCK_CID)

    assert fde_power.start_clone(clone, VNC_PORT) == "running"
    assert not any(call[1] == "start" for call in virsh.calls)


def test_start_clone_starts_only_the_verified_clone(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    virsh.states = ["shut off", "running"]
    monkeypatch.setattr(fde_power, "_virsh", virsh)
    clone = fde_power.ClonePower(CONNECTION_URI, CLONE_UUID, SOURCE_UUID, VSOCK_CID)

    assert fde_power.start_clone(clone, VNC_PORT) == "running"
    assert virsh.calls == [
        (CONNECTION_URI, "dumpxml", CLONE_UUID),
        (CONNECTION_URI, "domstate", CLONE_UUID),
        (CONNECTION_URI, "start", CLONE_UUID),
        (CONNECTION_URI, "domstate", CLONE_UUID),
        (CONNECTION_URI, "dumpxml", CLONE_UUID),
    ]


def test_start_clone_bounds_the_running_confirmation(
    monkeypatch: pytest.MonkeyPatch, virsh: _Virsh
) -> None:
    virsh.states = ["shut off"]
    monkeypatch.setattr(fde_power, "_virsh", virsh)
    monkeypatch.setattr(fde_power, "SHUTOFF_TIMEOUT", 2.0)
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(time, "sleep", sleep)
    clone = fde_power.ClonePower(CONNECTION_URI, CLONE_UUID, SOURCE_UUID, VSOCK_CID)

    with pytest.raises(fde_power.FdePowerError, match="did not report 'running'"):
        fde_power.start_clone(clone, VNC_PORT)
    assert any(call[1] == "start" for call in virsh.calls)
