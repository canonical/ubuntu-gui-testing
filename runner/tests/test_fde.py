"""Machinery checks for the private FDE fixture and guest channel.

These tests never touch a virtual machine. They prove the boundaries that keep a
real run inside its declared fixture: private configuration, allowlisted guest
operations, and responses that cannot leak credentials into logs or errors.
"""

from __future__ import annotations

import json
import os
import shlex
import stat
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, BinaryIO, cast

import paramiko
import pytest

from ubuntu_gui_testing_runner import fde
from ubuntu_gui_testing_runner.fde import (
    FdeConfigError,
    FdeFixture,
    FdeGuest,
    FdeGuestError,
    FdeGuestTimeout,
    _load_identity,
    _parse_helper_response,
)

SECRET = "11111-22222"


def _rewrite(config: Path, **changes: object) -> Path:
    data = json.loads(config.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    config.write_text(json.dumps(data), encoding="utf-8")
    config.chmod(0o600)
    return config


def test_load_accepts_private_configuration(fde_config: Path) -> None:
    fixture = FdeFixture.load(fde_config)

    assert fixture.path == fde_config.resolve()
    assert fixture.auth_mode == "passphrase"
    assert fixture.lane == "production"
    assert fixture.is_production_lane
    assert fixture.security_center_revision == "42"
    assert fixture.secret("recovery_key") == SECRET


def test_fixture_repr_never_contains_secret_values(fde_config: Path) -> None:
    fixture = FdeFixture.load(fde_config)

    assert SECRET not in repr(fixture)
    assert SECRET not in str(fixture)


@pytest.mark.parametrize("revision", ["0", "42", "x1", "x2", "x237"])
def test_load_preserves_snap_revision(fde_config: Path, revision: str) -> None:
    _rewrite(fde_config, security_center_revision=revision)

    assert FdeFixture.load(fde_config).security_center_revision == revision


@pytest.mark.parametrize("version", ["2", "2.68.3", "2.78+g237.1f728a2"])
def test_load_preserves_snapd_version(fde_config: Path, version: str) -> None:
    _rewrite(fde_config, snapd_version=version)

    assert FdeFixture.load(fde_config).snapd_version == version


@pytest.mark.parametrize(
    "revision",
    ["", " ", "x", "x0", "x01", "01", "-1", "x2;true", "x2\n", "x\x002"],
)
def test_load_rejects_malformed_snap_revision(fde_config: Path, revision: str) -> None:
    _rewrite(fde_config, security_center_revision=revision)

    with pytest.raises(FdeConfigError, match="security_center_revision"):
        FdeFixture.load(fde_config)


@pytest.mark.parametrize(
    "version",
    [
        "",
        " ",
        "latest/edge",
        "2.78+",
        "2.78+g237..1f728a2",
        "2.78;true",
        "2.78\n",
        "\t2.78",
        "2.\x0078",
    ],
)
def test_load_rejects_malformed_snapd_version(fde_config: Path, version: str) -> None:
    _rewrite(fde_config, snapd_version=version)

    with pytest.raises(FdeConfigError, match="snapd_version"):
        FdeFixture.load(fde_config)


def test_load_rejects_configuration_readable_by_other_users(
    fde_config: Path,
) -> None:
    fde_config.chmod(0o640)

    with pytest.raises(FdeConfigError, match="other users"):
        FdeFixture.load(fde_config)


def test_load_rejects_group_readable_secret_file(fde_config: Path) -> None:
    data = json.loads(fde_config.read_text(encoding="utf-8"))
    Path(data["login_password_file"]).chmod(0o644)

    with pytest.raises(FdeConfigError, match="other users"):
        FdeFixture.load(fde_config)


def test_load_rejects_raw_recovery_key_in_configuration(fde_config: Path) -> None:
    _rewrite(fde_config, recovery_key=SECRET)

    with pytest.raises(FdeConfigError, match="unknown fields"):
        FdeFixture.load(fde_config)


def test_load_rejects_missing_required_field(fde_config: Path) -> None:
    _rewrite(fde_config, snapd_executable_sha256=None)

    with pytest.raises(FdeConfigError, match="missing fields"):
        FdeFixture.load(fde_config)


@pytest.mark.parametrize("digest", ["", "0" * 63, "0" * 65, "g" * 64, "A" * 64])
def test_load_rejects_malformed_executable_hash(fde_config: Path, digest: str) -> None:
    _rewrite(fde_config, snapd_executable_sha256=digest)

    with pytest.raises(FdeConfigError, match="snapd_executable_sha256"):
        FdeFixture.load(fde_config)


def test_load_rejects_pin_auth_mode_without_pin_file(fde_config: Path) -> None:
    _rewrite(fde_config, **{"auth-mode": "pin"})

    with pytest.raises(FdeConfigError, match="pin_file"):
        FdeFixture.load(fde_config)


def test_load_rejects_non_decimal_security_center_revision(
    fde_config: Path,
) -> None:
    _rewrite(fde_config, **{"security-center-revision": "latest/edge"})

    with pytest.raises(FdeConfigError, match="decimal"):
        FdeFixture.load(fde_config)


def test_load_rejects_unknown_lane(fde_config: Path) -> None:
    _rewrite(fde_config, lane="production-ish")

    with pytest.raises(FdeConfigError, match="lane"):
        FdeFixture.load(fde_config)


def test_secret_rejects_unknown_name(fde_config: Path) -> None:
    fixture = FdeFixture.load(fde_config)

    with pytest.raises(FdeConfigError, match="unknown fixture secret"):
        fixture.secret("root_password")


def test_guest_rejects_operation_outside_the_allowlist(fde_config: Path) -> None:
    guest = FdeGuest(FdeFixture.load(fde_config), cid=3)

    with pytest.raises(FdeGuestError, match="unsupported guest operation"):
        guest.request("sh -c 'rm -rf /'")

    guest.close()


def test_helper_failure_reports_named_code(fde_config: Path) -> None:
    with pytest.raises(FdeGuestError) as raised:
        _parse_helper_response(
            "fault", json.dumps({"ok": False, "code": "unsupported-platform"})
        )

    assert "unsupported-platform" in str(raised.value)


def test_helper_output_never_leaks_into_errors() -> None:
    with pytest.raises(FdeGuestError) as raised:
        _parse_helper_response("check", f"leaked {SECRET} not json")

    assert SECRET not in str(raised.value)


def test_helper_result_is_returned() -> None:
    result = _parse_helper_response(
        "snapshot", json.dumps({"ok": True, "result": {"boot_id": "abc"}})
    )

    assert result == {"boot_id": "abc"}


def test_prepare_defaults_to_no_preparation(fde_config: Path) -> None:
    assert FdeFixture.load(fde_config).prepare == ()


def test_prepare_accepts_the_clear_tpm_state_step(fde_config: Path) -> None:
    import json

    data = json.loads(fde_config.read_text())
    data["prepare"] = ["clear-tpm-state"]
    fde_config.write_text(json.dumps(data))
    fde_config.chmod(0o600)
    assert FdeFixture.load(fde_config).prepare == ("clear-tpm-state",)


def test_prepare_rejects_an_unknown_step(fde_config: Path) -> None:
    import json

    import pytest

    data = json.loads(fde_config.read_text())
    data["prepare"] = ["format-disk"]
    fde_config.write_text(json.dumps(data))
    fde_config.chmod(0o600)
    with pytest.raises(FdeConfigError, match="prepare supports only"):
        FdeFixture.load(fde_config)


class _FakeChannel:
    """A channel that answers once, then reports the helper's exit status."""

    def __init__(self, output: bytes, status: int) -> None:
        self._output = output
        self.exit_status = status

    def settimeout(self, _timeout: float) -> None:
        pass

    def exec_command(self, _command: str) -> None:
        pass

    def sendall(self, _payload: bytes) -> None:
        pass

    def shutdown_write(self) -> None:
        pass

    def recv(self, _size: int) -> bytes:
        output, self._output = self._output, b""
        return output

    def recv_exit_status(self) -> int:
        return self.exit_status

    def close(self) -> None:
        pass


# -1 is Paramiko's missing exit status; the envelope still carries the cause.
@pytest.mark.parametrize("status", [1, -1])
def test_failed_helper_envelope_survives_a_nonzero_exit(status: int) -> None:
    from types import SimpleNamespace

    envelope = json.dumps(
        {"ok": False, "code": "unsupported-platform", "message": "no suitable TPM"}
    )
    channel = _FakeChannel(envelope.encode(), status=status)
    guest = cast(Any, object.__new__(FdeGuest))
    guest._transport = SimpleNamespace(open_session=lambda timeout: channel)
    guest._fixture = SimpleNamespace(secret=lambda name: "pw")

    output = guest._run_as_root(["check"], "check", 5.0)

    with pytest.raises(FdeGuestError) as raised:
        _parse_helper_response("check", output)
    assert raised.value.code == "unsupported-platform"
    assert "no suitable TPM" in str(raised.value)


def test_blank_helper_output_reports_the_exit_status() -> None:
    from types import SimpleNamespace

    channel = _FakeChannel(b"", status=3)
    guest = cast(Any, object.__new__(FdeGuest))
    guest._transport = SimpleNamespace(open_session=lambda timeout: channel)
    guest._fixture = SimpleNamespace(secret=lambda name: "pw")

    with pytest.raises(FdeGuestError, match="status 3"):
        guest._run_as_root(["check"], "check", 5.0)


def test_failed_install_is_not_treated_as_success() -> None:
    from types import SimpleNamespace

    channel = _FakeChannel(b"", status=1)
    guest = cast(Any, object.__new__(FdeGuest))
    guest._transport = SimpleNamespace(open_session=lambda timeout: channel)
    guest._fixture = SimpleNamespace(secret=lambda name: "pw")

    with pytest.raises(FdeGuestError, match="status 1"):
        guest._run_as_root(["/usr/bin/install"], "preflight", 5.0, expect_json=False)


def test_error_envelope_carries_its_code() -> None:
    with pytest.raises(FdeGuestError) as raised:
        _parse_helper_response(
            "fault",
            json.dumps({"ok": False, "code": "tpm-command-failed", "message": "no"}),
        )
    assert raised.value.code == "tpm-command-failed"


class _RecordingChannel(_FakeChannel):
    """A channel that keeps the shell command it was asked to run."""

    def __init__(self, output: bytes, status: int) -> None:
        super().__init__(output, status)
        self.command = ""

    def exec_command(self, command: str) -> None:
        self.command = command


def test_sudo_prompt_survives_shell_quoting() -> None:
    """The empty sudo prompt must stay an argument, not vanish into whitespace.

    ``sudo -p`` takes the next word as its prompt. Emitting the empty prompt
    unquoted left ``sudo -S -p  /run/ugt-fde/fde_guest.py``, so sudo read the
    helper path as the prompt and ran no command at all.
    """
    from types import SimpleNamespace

    channel = _RecordingChannel(b'{"ok": true, "result": {}}', status=0)
    guest = cast(Any, object.__new__(FdeGuest))
    guest._transport = SimpleNamespace(open_session=lambda timeout: channel)
    guest._fixture = SimpleNamespace(secret=lambda name: "pw")

    guest._run_as_root(["/usr/bin/id", "-u"], "check", 5.0)

    arguments = shlex.split(channel.command)
    assert arguments[:4] == ["sudo", "-S", "-p", ""]
    assert arguments[4:] == ["/usr/bin/id", "-u"]


@pytest.fixture(scope="module")
def host_key() -> paramiko.PKey:
    return paramiko.RSAKey.generate(1024)


@pytest.fixture
def pinned_config(fde_config: Path, host_key: paramiko.PKey) -> Path:
    """The fixture configuration with a parseable known-hosts pin."""
    fixture = FdeFixture.load(fde_config)
    fixture.ssh_known_hosts.write_text(
        f"{fixture.ssh_host_alias} {host_key.get_name()} {host_key.get_base64()}\n",
        encoding="utf-8",
    )
    return fde_config


class _FakeSocket:
    def __init__(self, connect_error: BaseException | None = None) -> None:
        self._connect_error = connect_error
        self.closed = False

    def settimeout(self, _timeout: float) -> None:
        pass

    def connect(self, _address: object) -> None:
        if self._connect_error is not None:
            raise self._connect_error

    def close(self) -> None:
        self.closed = True


class _FakeTransport:
    """A transport whose handshake, host key and authentication are scripted."""

    def __init__(
        self,
        server_key: paramiko.PKey | BaseException,
        handshake_error: BaseException | None = None,
        auth_error: BaseException | None = None,
        active_after_auth: bool = True,
        banner: bytes | None = None,
        saved_exception: BaseException | None = None,
    ) -> None:
        self._server_key = server_key
        self._handshake_error = handshake_error
        self._auth_error = auth_error
        self._active_after_auth = active_after_auth
        self._banner = banner
        self._saved_exception = saved_exception
        self.auth_handler: SimpleNamespace | None = None
        self.active = True
        self.authenticated = False
        self.closed = False

    def start_client(self, timeout: float) -> None:
        if self._handshake_error is not None:
            self.active = False
            raise self._handshake_error

    def get_remote_server_key(self) -> paramiko.PKey:
        if isinstance(self._server_key, BaseException):
            raise self._server_key
        return self._server_key

    def auth_publickey(self, _user: str, _identity: object) -> list[str]:
        # Paramiko learns the banner while authenticating and keeps it after
        # the link closes.
        self.auth_handler = SimpleNamespace(banner=self._banner)
        self.active = self._active_after_auth
        if self._auth_error is not None:
            raise self._auth_error
        self.authenticated = True
        return []

    def set_keepalive(self, _interval: int) -> None:
        pass

    def get_banner(self) -> bytes | None:
        if not self.active or self.auth_handler is None:
            return None
        return cast(bytes | None, self.auth_handler.banner)

    def is_active(self) -> bool:
        return self.active

    def is_authenticated(self) -> bool:
        return self.authenticated

    def get_exception(self) -> BaseException | None:
        return self._saved_exception

    def close(self) -> None:
        self.closed = True
        self.active = False


def _dialer(
    monkeypatch: pytest.MonkeyPatch, config: Path, sock: _FakeSocket, transport: Any
) -> FdeGuest:
    """A guest whose vsock and SSH transport are the given fakes."""
    vsock = SimpleNamespace(socket=lambda *_args: sock, AF_VSOCK=40, SOCK_STREAM=1)
    monkeypatch.setattr(fde, "socket", vsock)
    factory = transport if callable(transport) else (lambda _sock: transport)
    monkeypatch.setattr(paramiko, "Transport", factory)
    monkeypatch.setattr(fde, "_load_identity", lambda _path: "identity")
    monkeypatch.setattr(FdeGuest, "_deploy_helper", lambda _self, _timeout: None)
    return FdeGuest(FdeFixture.load(config), cid=3)


def _raised_while_handling(
    error: paramiko.SSHException, cause: BaseException
) -> paramiko.SSHException:
    """Paramiko raises some link failures as a bare SSHException in an except."""
    error.__context__ = cause
    return error


def _banner_eof() -> paramiko.SSHException:
    return _raised_while_handling(
        paramiko.SSHException("Error reading SSH protocol banner"), EOFError()
    )


_AUTH_REFUSALS = [
    paramiko.AuthenticationException("Authentication failed."),
    paramiko.BadAuthenticationType("Bad authentication type", ["password"]),
]


def test_connected_guest_keeps_its_authenticated_transport(
    monkeypatch: pytest.MonkeyPatch, pinned_config: Path, host_key: paramiko.PKey
) -> None:
    sock = _FakeSocket()
    transport = _FakeTransport(host_key)
    guest = _dialer(monkeypatch, pinned_config, sock, transport)

    guest._connect(5.0)

    assert transport.authenticated
    assert not transport.closed
    assert not sock.closed


def test_unreachable_vsock_is_transient_and_closes_the_socket(
    monkeypatch: pytest.MonkeyPatch, pinned_config: Path, host_key: paramiko.PKey
) -> None:
    sock = _FakeSocket(ConnectionResetError())
    guest = _dialer(monkeypatch, pinned_config, sock, _FakeTransport(host_key))

    with pytest.raises(FdeGuestTimeout):
        guest._connect(5.0)

    assert sock.closed


@pytest.mark.parametrize(
    "error",
    [EOFError(), ConnectionResetError(), TimeoutError(), _banner_eof()],
    ids=["eof", "reset", "timeout", "banner-eof"],
)
def test_link_loss_during_handshake_is_transient(
    monkeypatch: pytest.MonkeyPatch,
    pinned_config: Path,
    host_key: paramiko.PKey,
    error: BaseException,
) -> None:
    sock = _FakeSocket()
    transport = _FakeTransport(host_key, handshake_error=error)
    guest = _dialer(monkeypatch, pinned_config, sock, transport)

    with pytest.raises(FdeGuestTimeout):
        guest._connect(5.0)

    assert transport.closed
    assert sock.closed


def test_handshake_cut_short_by_the_deadline_is_transient(
    monkeypatch: pytest.MonkeyPatch, pinned_config: Path
) -> None:
    # start_client returns silently when its deadline passes mid-handshake.
    transport = _FakeTransport(paramiko.SSHException("No existing session"))
    guest = _dialer(monkeypatch, pinned_config, _FakeSocket(), transport)

    with pytest.raises(FdeGuestTimeout):
        guest._connect(5.0)

    assert transport.closed


@pytest.mark.parametrize(
    "error",
    [
        paramiko.ssh_exception.IncompatiblePeer("no matching cipher"),
        paramiko.SSHException("Bad host key from server"),
    ],
    ids=["incompatible", "bad-host-key-signature"],
)
def test_handshake_refusal_is_permanent(
    monkeypatch: pytest.MonkeyPatch,
    pinned_config: Path,
    host_key: paramiko.PKey,
    error: BaseException,
) -> None:
    sock = _FakeSocket()
    transport = _FakeTransport(host_key, handshake_error=error)
    guest = _dialer(monkeypatch, pinned_config, sock, transport)

    with pytest.raises(FdeGuestError) as raised:
        guest._connect(5.0)

    assert not isinstance(raised.value, FdeGuestTimeout)
    assert transport.closed
    assert sock.closed


def test_host_key_mismatch_is_permanent_and_closes_the_transport(
    monkeypatch: pytest.MonkeyPatch, pinned_config: Path
) -> None:
    sock = _FakeSocket()
    transport = _FakeTransport(paramiko.RSAKey.generate(1024))
    guest = _dialer(monkeypatch, pinned_config, sock, transport)

    with pytest.raises(FdeGuestError, match="host key") as raised:
        guest._connect(5.0)

    assert not isinstance(raised.value, FdeGuestTimeout)
    assert not transport.authenticated
    assert transport.closed
    assert sock.closed


@pytest.mark.parametrize(
    "error",
    _AUTH_REFUSALS,
    ids=["rejected", "publickey-disabled"],
)
def test_authentication_failure_is_permanent(
    monkeypatch: pytest.MonkeyPatch,
    pinned_config: Path,
    host_key: paramiko.PKey,
    error: BaseException,
) -> None:
    sock = _FakeSocket()
    transport = _FakeTransport(host_key, auth_error=error)
    guest = _dialer(monkeypatch, pinned_config, sock, transport)

    with pytest.raises(FdeGuestError) as raised:
        guest._connect(5.0)

    assert not isinstance(raised.value, FdeGuestTimeout)
    assert transport.closed
    assert sock.closed


@pytest.mark.parametrize(
    "error",
    _AUTH_REFUSALS,
    ids=["rejected", "publickey-disabled"],
)
def test_authentication_refusal_survives_a_closed_link(
    monkeypatch: pytest.MonkeyPatch,
    pinned_config: Path,
    host_key: paramiko.PKey,
    error: BaseException,
) -> None:
    sock = _FakeSocket()
    transport = _FakeTransport(host_key, auth_error=error, active_after_auth=False)
    guest = _dialer(monkeypatch, pinned_config, sock, transport)

    with pytest.raises(FdeGuestError) as raised:
        guest._connect(5.0)

    assert not isinstance(raised.value, FdeGuestTimeout)
    assert transport.closed
    assert sock.closed


def test_boot_time_login_refusal_is_transient(
    monkeypatch: pytest.MonkeyPatch, pinned_config: Path, host_key: paramiko.PKey
) -> None:
    sock = _FakeSocket()
    transport = _FakeTransport(
        host_key,
        auth_error=paramiko.AuthenticationException("Authentication failed."),
        banner=(
            b'"System is booting up. Unprivileged users are not permitted to log '
            b'in yet."\n'
        ),
    )
    guest = _dialer(monkeypatch, pinned_config, sock, transport)

    with pytest.raises(FdeGuestTimeout, match="not accepting logins"):
        guest._connect(5.0)

    assert transport.closed
    assert sock.closed


def test_boot_banner_survives_a_closed_link(
    monkeypatch: pytest.MonkeyPatch, pinned_config: Path, host_key: paramiko.PKey
) -> None:
    sock = _FakeSocket()
    transport = _FakeTransport(
        host_key,
        auth_error=paramiko.AuthenticationException("Authentication failed."),
        active_after_auth=False,
        banner=b'"System is booting up."\n',
    )
    guest = _dialer(monkeypatch, pinned_config, sock, transport)

    with pytest.raises(FdeGuestTimeout, match="not accepting logins"):
        guest._connect(5.0)

    assert transport.closed
    assert sock.closed


def test_link_loss_during_authentication_is_transient(
    monkeypatch: pytest.MonkeyPatch, pinned_config: Path, host_key: paramiko.PKey
) -> None:
    transport = _FakeTransport(
        host_key, auth_error=ConnectionResetError(), active_after_auth=False
    )
    guest = _dialer(monkeypatch, pinned_config, _FakeSocket(), transport)

    with pytest.raises(FdeGuestTimeout):
        guest._connect(5.0)

    assert transport.closed


def test_link_loss_reported_as_authentication_failure_is_transient(
    monkeypatch: pytest.MonkeyPatch, pinned_config: Path, host_key: paramiko.PKey
) -> None:
    transport = _FakeTransport(
        host_key,
        auth_error=paramiko.AuthenticationException(
            "Authentication failed: transport shut down or saw EOF"
        ),
        active_after_auth=False,
        saved_exception=EOFError(),
    )
    guest = _dialer(monkeypatch, pinned_config, _FakeSocket(), transport)

    with pytest.raises(FdeGuestTimeout):
        guest._connect(5.0)

    assert transport.closed


def test_transport_constructor_failure_closes_the_socket(
    monkeypatch: pytest.MonkeyPatch, pinned_config: Path
) -> None:
    def refuse(_sock: object) -> None:
        raise ValueError("constructor failed")

    sock = _FakeSocket()
    guest = _dialer(monkeypatch, pinned_config, sock, refuse)

    with pytest.raises(ValueError, match="constructor failed"):
        guest._connect(5.0)

    assert sock.closed


@pytest.mark.parametrize(
    "known_hosts",
    ["fde-baseline ssh-ed25519 not*base64\n", None],
    ids=["malformed", "unreadable"],
)
def test_unusable_known_hosts_is_permanent_and_closes_the_transport(
    monkeypatch: pytest.MonkeyPatch,
    pinned_config: Path,
    host_key: paramiko.PKey,
    known_hosts: str | None,
) -> None:
    sock = _FakeSocket()
    transport = _FakeTransport(host_key)
    guest = _dialer(monkeypatch, pinned_config, sock, transport)
    pinned = FdeFixture.load(pinned_config).ssh_known_hosts
    if known_hosts is None:
        pinned.unlink()
        pinned.mkdir()
    else:
        pinned.write_text(known_hosts, encoding="utf-8")

    with pytest.raises(FdeGuestError, match="known-hosts") as raised:
        guest._connect(5.0)

    assert not isinstance(raised.value, FdeGuestTimeout)
    assert not transport.authenticated
    assert transport.closed
    assert sock.closed


@pytest.mark.parametrize("name", ["id", "missing"])
def test_unusable_identity_is_permanent(fde_config: Path, name: str) -> None:
    # The fixture identity holds "key", which no key loader accepts.
    with pytest.raises(FdeGuestError, match="identity") as raised:
        _load_identity(fde_config.parent / name)

    assert not isinstance(raised.value, FdeGuestTimeout)


def test_unusable_identity_closes_the_transport(
    monkeypatch: pytest.MonkeyPatch, pinned_config: Path, host_key: paramiko.PKey
) -> None:
    sock = _FakeSocket()
    transport = _FakeTransport(host_key)
    guest = _dialer(monkeypatch, pinned_config, sock, transport)
    monkeypatch.setattr(fde, "_load_identity", _load_identity)

    with pytest.raises(FdeGuestError, match="identity"):
        guest._connect(5.0)

    assert transport.closed
    assert sock.closed


def test_link_loss_while_deploying_the_helper_is_transient_and_disconnects(
    monkeypatch: pytest.MonkeyPatch, pinned_config: Path, host_key: paramiko.PKey
) -> None:
    deploy = FdeGuest._deploy_helper
    transport = _FakeTransport(host_key)
    guest = _dialer(monkeypatch, pinned_config, _FakeSocket(), transport)
    monkeypatch.setattr(FdeGuest, "_deploy_helper", deploy)

    def dropped(_self: FdeGuest, _operation: str) -> None:
        raise EOFError

    monkeypatch.setattr(FdeGuest, "_require_sftp", dropped)

    with pytest.raises(FdeGuestTimeout):
        guest._connect(5.0)

    assert transport.closed
    assert guest._transport is None


class _DeadTransport:
    """A transport whose link dropped: no channel opens and it is inactive."""

    def __init__(
        self,
        active: bool,
        error: BaseException,
        saved: BaseException | None = None,
    ) -> None:
        self.active = active
        self._error = error
        self._saved = saved

    def open_session(self, timeout: float) -> None:
        raise self._error

    def is_active(self) -> bool:
        return self.active

    def get_exception(self) -> BaseException | None:
        return self._saved

    def close(self) -> None:
        self.active = False


def _command_guest(transport: object) -> Any:
    guest = cast(Any, object.__new__(FdeGuest))
    guest._transport = transport
    guest._sftp = None
    guest._fixture = SimpleNamespace(secret=lambda name: "pw")
    return guest


@pytest.mark.parametrize(
    ("error", "saved"),
    [
        (EOFError(), None),
        (ConnectionResetError(), None),
        # open_session reports a dead transport bare and keeps the cause.
        (paramiko.SSHException("SSH session not active"), EOFError()),
    ],
    ids=["eof", "reset", "inactive-session"],
)
def test_dropped_link_while_opening_a_command_is_transient(
    error: BaseException, saved: BaseException | None
) -> None:
    guest = _command_guest(_DeadTransport(active=False, error=error, saved=saved))

    with pytest.raises(FdeGuestTimeout):
        guest._run_as_root(["check"], "snapshot", 5.0)


def test_dead_transport_without_a_link_cause_is_permanent() -> None:
    error = paramiko.SSHException("Unable to open channel.")
    guest = _command_guest(_DeadTransport(active=False, error=error))

    with pytest.raises(FdeGuestError) as raised:
        guest._run_as_root(["check"], "snapshot", 5.0)

    assert not isinstance(raised.value, FdeGuestTimeout)


def test_refused_command_channel_on_a_live_link_is_permanent() -> None:
    error = paramiko.ChannelException(1, "Administratively prohibited")
    guest = _command_guest(_DeadTransport(active=True, error=error))

    with pytest.raises(FdeGuestError) as raised:
        guest._run_as_root(["check"], "snapshot", 5.0)

    assert not isinstance(raised.value, FdeGuestTimeout)


def test_socket_error_on_a_live_link_is_permanent() -> None:
    guest = _command_guest(_DeadTransport(active=True, error=OSError("local")))

    with pytest.raises(FdeGuestError) as raised:
        guest._run_as_root(["check"], "snapshot", 5.0)

    assert not isinstance(raised.value, FdeGuestTimeout)


@pytest.mark.parametrize("expect_json", [True, False])
def test_session_ending_without_an_exit_status_is_transient(expect_json: bool) -> None:
    # Paramiko reports -1 on a still-active transport when sshd sends
    # exit-signal (shutdown's SIGTERM) or closes the channel without a status.
    channel = _FakeChannel(b"", status=-1)
    transport = SimpleNamespace(
        open_session=lambda timeout: channel, is_active=lambda: True
    )
    guest = _command_guest(transport)

    with pytest.raises(FdeGuestTimeout, match="exit status"):
        guest._run_as_root(["check"], "snapshot", 5.0, expect_json=expect_json)


class _LocalSftpFile:
    """An open staged file that records its mode whenever bytes land in it."""

    def __init__(self, sftp: _LocalSftp, fd: int) -> None:
        self._sftp = sftp
        self._fd = fd

    def __enter__(self) -> _LocalSftpFile:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def chmod(self, mode: int) -> None:
        self._sftp.fail("chmod")
        os.fchmod(self._fd, mode)

    def read(self, size: int) -> bytes:
        self._sftp.fail("read")
        return os.read(self._fd, size)

    def write(self, data: bytes) -> None:
        self._sftp.write_modes.append(stat.S_IMODE(os.fstat(self._fd).st_mode))
        if self._sftp.fail_at == "write":
            os.write(self._fd, data[: len(data) // 2])
        self._sftp.fail("write")
        os.write(self._fd, data)

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1


class _LocalSftp:
    """Stages into a local directory the way sftp-server does on the guest.

    sftp-server creates files and directories under the usual 022 umask: a new
    file is readable by others until chmod, and a new directory is traversable
    unless created private. Absolute guest paths map inside home. fail_at makes
    one step fail; once closed, every step fails like a closed SFTP channel.
    """

    def __init__(
        self, home: Path, error: BaseException | None = None, fail_at: str = ""
    ) -> None:
        self.home = home
        self.error = error
        self.fail_at = fail_at
        self.write_modes: list[int] = []
        # The parent directory's mode whenever a file is created in it.
        self.open_dir_modes: list[int] = []
        self.made_dirs: list[str] = []
        self.closed = False

    def fail(self, step: str) -> None:
        if self.closed:
            raise OSError("Socket is closed")
        if step == self.fail_at:
            assert self.error is not None
            raise self.error

    def _local(self, path: str) -> Path:
        return self.home / path.lstrip("/")

    def mkdir(self, path: str, mode: int = 0o777) -> None:
        self.fail("mkdir")
        target = self._local(path)
        target.mkdir()
        target.chmod(mode & ~0o022)
        self.made_dirs.append(path)

    def stat(self, path: str) -> os.stat_result:
        self.fail("stat")
        return self._local(path).stat()

    def open(self, path: str, mode: str = "r") -> _LocalSftpFile:
        target = self._local(path)
        if "w" not in mode:
            self.fail("open-read")
            return _LocalSftpFile(self, os.open(target, os.O_RDONLY))
        self.fail("open")
        created = not target.exists()
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        if created:
            os.fchmod(fd, 0o644)  # whatever this process's umask is
            self.open_dir_modes.append(stat.S_IMODE(target.parent.stat().st_mode))
        return _LocalSftpFile(self, fd)

    def putfo(self, source: BinaryIO, path: str) -> None:
        # Paramiko's putfo writes through open(path, "wb").
        with self.open(path, "wb") as remote:
            remote.write(source.read())

    def chmod(self, path: str, mode: int) -> None:
        self.fail("chmod")
        os.chmod(self._local(path), mode)

    def remove(self, path: str) -> None:
        self.fail("remove")
        self._local(path).unlink()

    def rmdir(self, path: str) -> None:
        self.fail("rmdir")
        self._local(path).rmdir()

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def guest_home(tmp_path: Path) -> Path:
    """A home directory that others may traverse, as on the guest."""
    home = tmp_path / "home"
    home.mkdir()
    home.chmod(0o755)
    return home


def _helper_must_not_run(*_args: object, **_kwargs: object) -> str:
    raise AssertionError("the helper ran without a staged request")


def _staging_guest(
    sftp: _LocalSftp,
    helper: Callable[..., str] = _helper_must_not_run,
    active: bool = True,
) -> Any:
    transport = SimpleNamespace(
        is_active=lambda: active, get_exception=lambda: None, close=lambda: None
    )
    guest = _command_guest(transport)
    guest._sftp = sftp
    guest._connect = lambda _timeout: None
    guest._run_as_root = helper
    return guest


def test_staged_request_is_private_before_its_secret_is_written(
    guest_home: Path,
) -> None:
    sftp = _LocalSftp(guest_home)
    seen: list[tuple[int, int, str]] = []

    def helper(command: list[str], operation: str, timeout: float) -> str:
        staged = guest_home / command[command.index("--input") + 1]
        directory_mode = stat.S_IMODE(staged.parent.stat().st_mode)
        file_mode = stat.S_IMODE(staged.stat().st_mode)
        seen.append((directory_mode, file_mode, staged.read_text()))
        return json.dumps({"ok": True, "result": {"data": "match"}})

    guest = _staging_guest(sftp, helper)

    assert guest.request("check-key", {"key": SECRET}) == {"data": "match"}
    assert guest.request("check-key", {"key": SECRET}) == {"data": "match"}
    # The secret file is created inside a private directory and is private
    # before any byte lands in it.
    assert sftp.open_dir_modes == [0o700, 0o700]
    assert sftp.write_modes == [0o600, 0o600]
    assert [entry[:2] for entry in seen] == [(0o700, 0o600)] * 2
    assert all(SECRET in entry[2] for entry in seen)
    first, second = sftp.made_dirs
    assert first != second
    assert list(guest_home.iterdir()) == []
    assert not sftp.closed


@pytest.mark.parametrize("step", ["mkdir", "open", "chmod", "write"])
def test_failed_staging_never_exposes_or_strands_the_secret(
    guest_home: Path, step: str
) -> None:
    # sftp-server answers a failed mkdir, open, fsetstat or write with
    # SSH2_FX_FAILURE.
    sftp = _LocalSftp(guest_home, OSError("Failure"), fail_at=step)
    guest = _staging_guest(sftp)

    with pytest.raises(FdeGuestError, match="cannot stage") as raised:
        guest.request("check-key", {"key": SECRET})

    assert not isinstance(raised.value, FdeGuestTimeout)
    assert sftp.write_modes == ([0o600] if step == "write" else [])
    # The closed stand-in refuses removal, so cleanup ran before disconnecting.
    assert list(guest_home.iterdir()) == []
    assert sftp.closed
    assert guest._transport is None


@pytest.mark.parametrize(
    ("active", "error", "transient"),
    [
        (True, paramiko.ChannelException(1, "Administratively prohibited"), False),
        (False, EOFError(), True),
    ],
    ids=["refused", "dropped"],
)
def test_failed_command_removes_the_staged_secret_before_disconnecting(
    guest_home: Path, active: bool, error: BaseException, transient: bool
) -> None:
    sftp = _LocalSftp(guest_home)
    guest = _command_guest(_DeadTransport(active=active, error=error))
    guest._sftp = sftp
    guest._connect = lambda _timeout: None

    with pytest.raises(FdeGuestError) as raised:
        guest.request("check-key", {"key": SECRET})

    assert isinstance(raised.value, FdeGuestTimeout) is transient
    assert sftp.open_dir_modes == [0o700]
    assert sftp.write_modes == [0o600]
    # The closed stand-in refuses removal, so cleanup ran before disconnecting.
    assert list(guest_home.iterdir()) == []
    assert sftp.closed
    assert guest._sftp is None
    assert guest._transport is None


@pytest.mark.parametrize(
    ("active", "error", "transient"),
    [
        (True, PermissionError(13, "Permission denied"), False),
        (True, FileNotFoundError(2, "No such file"), False),
        (True, paramiko.SSHException("Garbage packet received"), False),
        # SFTP may see the closed channel before the transport turns inactive.
        (
            True,
            _raised_while_handling(
                paramiko.SSHException("Server connection dropped: "), EOFError()
            ),
            True,
        ),
        (False, EOFError(), True),
        (False, OSError("Socket is closed"), True),
        # The guest answered; the link dropping afterwards changes nothing.
        (False, PermissionError(13, "Permission denied"), False),
        (False, FileNotFoundError(2, "No such file"), False),
    ],
    ids=[
        "permission",
        "missing",
        "live-ssh-error",
        "dropped",
        "eof",
        "closed",
        "permission-then-drop",
        "missing-then-drop",
    ],
)
def test_staging_failure_is_transient_only_on_a_dropped_link(
    tmp_path: Path, active: bool, error: BaseException, transient: bool
) -> None:
    guest = _staging_guest(_LocalSftp(tmp_path, error, fail_at="open"), active=active)

    with pytest.raises(FdeGuestError) as raised:
        guest.request("snapshot")

    assert isinstance(raised.value, FdeGuestTimeout) is transient


def _installing_guest(
    sftp: _LocalSftp, installs: list[str], active: bool = True
) -> Any:
    """A guest whose root install command copies the staged helper locally."""

    def install(
        command: list[str], operation: str, timeout: float, expect_json: bool = True
    ) -> str:
        source, target = sftp._local(command[-2]), sftp._local(command[-1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        installs.append(command[-1])
        return ""

    return _staging_guest(sftp, install, active)


def _install_remote_helper(sftp: _LocalSftp, content: bytes) -> Path:
    installed = sftp._local(fde._HELPER_REMOTE)
    installed.parent.mkdir(parents=True)
    installed.write_bytes(content)
    return installed


@pytest.mark.parametrize("remote", ["current", "same-size", "longer", "missing"])
def test_helper_is_redeployed_unless_its_content_matches(
    guest_home: Path, remote: str
) -> None:
    local = fde._HELPER_SOURCE.read_bytes()
    variants: dict[str, bytes | None] = {
        "current": local,
        "same-size": bytes([local[0] ^ 1]) + local[1:],
        "longer": local + b"\n",
        "missing": None,
    }
    sftp = _LocalSftp(guest_home)
    content = variants[remote]
    if content is not None:
        _install_remote_helper(sftp, content)
    installs: list[str] = []

    _installing_guest(sftp, installs)._deploy_helper(5.0)

    assert installs == ([] if remote == "current" else [fde._HELPER_REMOTE])
    assert sftp._local(fde._HELPER_REMOTE).read_bytes() == local


@pytest.mark.parametrize("step", ["open-read", "read"])
def test_unreadable_helper_is_redeployed(guest_home: Path, step: str) -> None:
    sftp = _LocalSftp(guest_home, PermissionError(13, "Permission denied"), step)
    _install_remote_helper(sftp, fde._HELPER_SOURCE.read_bytes())
    installs: list[str] = []

    _installing_guest(sftp, installs)._deploy_helper(5.0)

    assert installs == [fde._HELPER_REMOTE]


def test_link_loss_while_comparing_the_helper_is_transient(guest_home: Path) -> None:
    sftp = _LocalSftp(guest_home, EOFError(), fail_at="read")
    _install_remote_helper(sftp, fde._HELPER_SOURCE.read_bytes())
    installs: list[str] = []

    with pytest.raises(FdeGuestTimeout):
        _installing_guest(sftp, installs, active=False)._deploy_helper(5.0)

    assert installs == []


def test_guest_allowlist_matches_helper_operations() -> None:
    """A helper operation the host refuses could never run, and vice versa."""
    from ubuntu_gui_testing_runner import fde, fde_guest

    assert frozenset(fde_guest.OPERATIONS) == fde.OPERATIONS


def test_a_new_fault_recipe_must_be_classified_as_real_or_planted() -> None:
    """Real recipes run TPM commands; the rest plant a mount or canned reply."""
    from ubuntu_gui_testing_runner import fde, fde_guest

    planted = {
        "mask-sysfs-efi",
        "mask-measurements",
        "null-tpm-device",
        "tpm-eio",
        "tpm-reply-error",
        "tpm-reply-failure",
        "efivar-eio",
        "break-secureboot-var",
        "block-ppi-request",
    }

    assert set(fde_guest._FAULT_RECIPES) == fde.REAL_TPM_RECIPES | planted
    assert not fde.REAL_TPM_RECIPES & planted


def test_prepare_accepts_auth_enrollment(fde_config: Path) -> None:
    _rewrite(fde_config, prepare=["enroll-auth"])

    fixture = FdeFixture.load(fde_config)

    assert fixture.prepare == ("enroll-auth",)
    assert fixture.auth_mode == "passphrase"


def test_prepare_accepts_enrollment_then_a_stopped_clone_fault(
    fde_config: Path,
) -> None:
    _rewrite(fde_config, prepare=["enroll-auth", "sysprep-app"])

    assert FdeFixture.load(fde_config).prepare == ("enroll-auth", "sysprep-app")


def test_prepare_rejects_enrollment_without_authentication(
    fde_config: Path,
) -> None:
    _rewrite(fde_config, auth_mode="none", prepare=["enroll-auth"])

    with pytest.raises(FdeConfigError, match="auth_mode 'pin' or 'passphrase'"):
        FdeFixture.load(fde_config)


@pytest.mark.parametrize("step", ["clear-tpm-state", "plain-ovmf"])
def test_prepare_allows_enrollment_before_a_stopped_clone_fault(
    fde_config: Path, step: str
) -> None:
    _rewrite(fde_config, prepare=["enroll-auth", step])

    assert FdeFixture.load(fde_config).prepare == ("enroll-auth", step)


def test_prepare_rejects_a_repeated_step(fde_config: Path) -> None:
    _rewrite(fde_config, prepare=["sysprep-app", "sysprep-app"])

    with pytest.raises(FdeConfigError, match="must not repeat"):
        FdeFixture.load(fde_config)
