"""Private TPM-FDE fixture configuration and authenticated guest command channel.

The fixture file and the files it references hold test-only credentials for a
disposable virtual machine. They are validated for owner-only permissions and
read lazily, so a secret never reaches Robot variables, process arguments, or
logs. Every guest operation runs the trusted helper as root over SSH on the
guest's vsock channel, while the graphical application under test keeps running
as the ordinary desktop user.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import secrets
import shlex
import socket
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import paramiko

OPERATIONS: Final = frozenset(
    {
        "preflight",
        "snapshot",
        "repair-progress",
        "check",
        "fault",
        "check-key",
        "restart-snapd",
        "enable-test-mode",
        "pre-os-measurements",
        "generate-competing-key",
        "reboot",
        "shutdown",
        "read-saved-key",
        "assert-auth",
        "enroll-auth",
    }
)

# Recipes that change the TPM with the TPM's own commands. Every other fault
# recipe plants a bind mount or a canned reply, which a real user never sees.
REAL_TPM_RECIPES: Final = frozenset(
    {
        "disable-endorsement-hierarchy",
        "disable-owner-hierarchy",
        "dictionary-lockout",
        "extend-pcr4",
    }
)

AUTH_MODES: Final = frozenset({"none", "pin", "passphrase"})
LANES: Final = frozenset({"production", "faultinject"})

_SSH_PORT: Final = 22
# SSH reachable while the guest is still powering up or already going down.
_TRANSIENT_LOGIN_BANNERS: Final = (
    "System is booting up",
    "System is going down",
)
_HELPER_SOURCE: Final = Path(__file__).with_name("fde_guest.py")
_HELPER_REMOTE: Final = "/run/ugt-fde/fde_guest.py"
_REMOTE_STAGING: Final = ".ugt-fde"
_SUDO = ("sudo", "-S", "-p", "")
_GUEST_PYTHON: Final = "/usr/bin/python3"

_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_SNAP_REVISION = re.compile(r"\A(?:0|x?[1-9][0-9]*)\Z")
_VERSION = re.compile(
    r"\A[0-9]+(?:\.[0-9]+)*(?:[+~-][0-9A-Za-z]+(?:[.+~-][0-9A-Za-z]+)*)?\Z"
)
_DEVICE_PATH = re.compile(r"\A/")

_REQUIRED_FIELDS: Final = (
    "ssh_user",
    "desktop_user",
    "ssh_identity",
    "ssh_known_hosts",
    "ssh_host_alias",
    "login_password_file",
    "recovery_key_file",
    "security_center_revision",
    "snapd_version",
    "snapd_executable_sha256",
    "auth_mode",
    "data_device",
    "save_device",
)
_OPTIONAL_FIELDS: Final = (
    "pin_file",
    "passphrase_file",
    "lane",
    "prepare",
)
AUTH_ENROLLMENT: Final = "enroll-auth"
PREPARATIONS: Final = frozenset(
    {
        AUTH_ENROLLMENT,
        "clear-tpm-state",
        "no-tpm",
        "plain-ovmf",
        "sysprep-app",
        "sysprep-weak-sb",
        "sysprep-digest-sb",
        "preos-digest-sb",
        "preos-weak-sb",
    }
)

_SECRET_FIELDS: Final = {
    "login_password": "login_password_file",
    "recovery_key": "recovery_key_file",
    "pin": "pin_file",
    "passphrase": "passphrase_file",
}

_FIELD_RENAME = {
    "security-center-revision": "security_center_revision",
    "snapd-version": "snapd_version",
    "snapd-executable-sha256": "snapd_executable_sha256",
    "auth-mode": "auth_mode",
    "data-device": "data_device",
    "save-device": "save_device",
    "ssh-user": "ssh_user",
    "desktop-user": "desktop_user",
    "ssh-identity": "ssh_identity",
    "ssh-known-hosts": "ssh_known_hosts",
    "ssh-host-alias": "ssh_host_alias",
    "login-password-file": "login_password_file",
    "recovery-key-file": "recovery_key_file",
    "pin-file": "pin_file",
    "passphrase-file": "passphrase_file",
}


class FdeConfigError(ValueError):
    """The TPM-FDE fixture configuration is unsafe or malformed."""


class FdeGuestError(RuntimeError):
    """A guest operation failed. Messages never include command output."""

    def __init__(self, operation: str, detail: str, code: str | None = None) -> None:
        super().__init__(f"guest operation {operation!r} failed: {detail}")
        self.operation = operation
        self.code = code


class FdeGuestTimeout(FdeGuestError):
    """The guest was unreachable, dropped its link, or missed its deadline.

    These are the failures a reboot causes, so a caller may reconnect.
    Trust, authentication and helper failures are never this type.
    """


def _require_private_file(path: Path, label: str) -> Path:
    try:
        info = path.stat()
    except OSError as error:
        raise FdeConfigError(f"{label} must be a readable file") from error
    if not stat.S_ISREG(info.st_mode):
        raise FdeConfigError(f"{label} must be a regular file")
    if info.st_uid != os.geteuid():
        raise FdeConfigError(f"{label} must be owned by the current user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise FdeConfigError(f"{label} must not be accessible by other users")
    return path


def _require_readable_file(path: Path, label: str) -> Path:
    try:
        info = path.stat()
    except OSError as error:
        raise FdeConfigError(f"{label} must be a readable file") from error
    if not stat.S_ISREG(info.st_mode):
        raise FdeConfigError(f"{label} must be a regular file")
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise FdeConfigError(f"{label} must not be writable by other users")
    return path


@dataclass(frozen=True)
class FdeFixture:
    """A validated, private TPM-FDE test target description."""

    path: Path
    ssh_user: str
    desktop_user: str
    ssh_identity: Path
    ssh_known_hosts: Path
    ssh_host_alias: str
    login_password_file: Path
    recovery_key_file: Path
    security_center_revision: str
    snapd_version: str
    snapd_executable_sha256: str
    auth_mode: str
    data_device: str
    save_device: str
    pin_file: Path | None = None
    passphrase_file: Path | None = None
    lane: str = "production"
    prepare: tuple[str, ...] = ()

    @property
    def is_production_lane(self) -> bool:
        return self.lane == "production"

    @classmethod
    def load(cls, path: Path) -> FdeFixture:
        config_path = Path(path)
        source = _require_private_file(config_path.resolve(), "FDE configuration")

        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FdeConfigError(
                "FDE configuration must be valid UTF-8 JSON"
            ) from error
        if not isinstance(raw, dict):
            raise FdeConfigError("FDE configuration must be a JSON object")

        config = {
            _FIELD_RENAME.get(str(key), str(key)): value for key, value in raw.items()
        }
        unknown = sorted(set(config) - set(_REQUIRED_FIELDS) - set(_OPTIONAL_FIELDS))
        if unknown:
            raise FdeConfigError(
                "FDE configuration has unknown fields: " + ", ".join(unknown)
            )
        missing = [name for name in _REQUIRED_FIELDS if name not in config]
        if missing:
            raise FdeConfigError(
                "FDE configuration is missing fields: " + ", ".join(missing)
            )

        values: dict[str, Any] = {}
        for name in _REQUIRED_FIELDS:
            values[name] = _require_string(config[name], name)
        for name in _OPTIONAL_FIELDS:
            if name not in config:
                continue
            if name == "prepare":
                values[name] = _require_preparations(config[name])
            else:
                values[name] = _require_string(config[name], name)

        for name in ("ssh_identity", "ssh_known_hosts"):
            values[name] = Path(_require_string(config[name], name)).resolve()

        if values["ssh_known_hosts"] == values["ssh_identity"]:
            raise FdeConfigError("known-hosts file must differ from the SSH identity")

        _require_private_file(values["ssh_identity"], "SSH identity")
        _require_readable_file(values["ssh_known_hosts"], "known-hosts file")

        for name in (
            "login_password_file",
            "recovery_key_file",
            "pin_file",
            "passphrase_file",
        ):
            if name not in values:
                continue
            values[name] = _require_private_file(
                Path(values[name]).resolve(), name.replace("_", " ")
            )

        auth_mode = values["auth_mode"]
        if auth_mode not in AUTH_MODES:
            raise FdeConfigError(
                "auth_mode must be one of: " + ", ".join(sorted(AUTH_MODES))
            )
        if auth_mode == "pin" and "pin_file" not in values:
            raise FdeConfigError("auth_mode 'pin' requires pin_file")
        if auth_mode == "passphrase" and "passphrase_file" not in values:
            raise FdeConfigError("auth_mode 'passphrase' requires passphrase_file")

        lane = values.get("lane", "production")
        if lane not in LANES:
            raise FdeConfigError("lane must be one of: " + ", ".join(sorted(LANES)))

        prepare = values.get("prepare", ())
        if len(prepare) != len(set(prepare)):
            raise FdeConfigError("prepare must not repeat a step")
        if AUTH_ENROLLMENT in prepare and auth_mode == "none":
            raise FdeConfigError(
                "prepare 'enroll-auth' requires auth_mode 'pin' or 'passphrase'"
            )

        if not _SNAP_REVISION.match(config["security_center_revision"]):
            raise FdeConfigError(
                "security_center_revision must be a decimal or local snap revision"
            )
        if not _VERSION.match(config["snapd_version"]):
            raise FdeConfigError(
                "snapd_version must be a dotted release or development version"
            )
        if not _SHA256.match(values["snapd_executable_sha256"]):
            raise FdeConfigError(
                "snapd_executable_sha256 must be 64 lowercase hex digits"
            )

        for name in ("data_device", "save_device"):
            if not _DEVICE_PATH.match(values[name]):
                raise FdeConfigError(f"{name} must be an absolute guest device path")
        if values["data_device"] == values["save_device"]:
            raise FdeConfigError("data_device and save_device must differ")

        return cls(path=source, **values)

    def secret(self, name: str) -> str:
        """Read a fixture secret from its private file without logging it."""
        field_name = _SECRET_FIELDS.get(name)
        if field_name is None:
            raise FdeConfigError(f"unknown fixture secret {name!r}")
        secret_path: Path | None = getattr(self, field_name)
        if secret_path is None:
            raise FdeConfigError(f"fixture secret {name!r} is not configured")
        try:
            value = secret_path.read_text(encoding="utf-8")
        except OSError as error:
            raise FdeConfigError(f"fixture secret {name!r} is unreadable") from error
        value = value.rstrip("\n")
        if not value or "\x00" in value:
            raise FdeConfigError(f"fixture secret {name!r} is empty or malformed")
        return value


def _require_preparations(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise FdeConfigError("prepare must be a non-empty list")
    steps = []
    for step in value:
        if not isinstance(step, str) or step not in PREPARATIONS:
            raise FdeConfigError(
                "prepare supports only: " + ", ".join(sorted(PREPARATIONS))
            )
        steps.append(step)
    return tuple(steps)


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FdeConfigError(f"{name} must be a non-empty string")
    return value.strip()


class FdeGuest:
    """Run allowlisted root operations inside one disposable FDE guest."""

    def __init__(self, fixture: FdeFixture, cid: int) -> None:
        self._fixture = fixture
        self._cid = cid
        self._transport: paramiko.Transport | None = None
        self._sftp: paramiko.SFTPClient | None = None

    def __enter__(self) -> FdeGuest:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._sftp is not None:
            self._sftp.close()
            self._sftp = None
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def request(
        self,
        operation: str,
        parameters: dict[str, object] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, object]:
        if operation not in OPERATIONS:
            raise FdeGuestError(operation, "unsupported guest operation")
        if parameters is not None and not isinstance(parameters, dict):
            raise FdeGuestError(operation, "parameters must be a mapping")

        self._connect(timeout)
        payload = json.dumps(
            {"operation": operation, "parameters": parameters or {}},
            ensure_ascii=False,
        ).encode("utf-8")
        staging_dir = f"{_REMOTE_STAGING}-{secrets.token_hex(16)}"
        remote_payload = f"{staging_dir}/request.json"
        try:
            try:
                self._stage_request(operation, staging_dir, remote_payload, payload)
                output = self._run_as_root(
                    [_GUEST_PYTHON, _HELPER_REMOTE, "--input", remote_payload],
                    operation,
                    timeout,
                )
            finally:
                self._remove_staging(staging_dir, remote_payload)
        except BaseException:
            # Only after cleanup: a closed channel cannot remove the secret.
            self.close()
            raise

        return _parse_helper_response(operation, output)

    def _stage_request(
        self, operation: str, directory: str, path: str, payload: bytes
    ) -> None:
        try:
            sftp = self._require_sftp(operation)
            # Parameters can carry secrets: the file is created inside a new
            # private directory and made private while still empty.
            sftp.mkdir(directory, mode=0o700)
            with sftp.open(path, "wb") as staged:
                staged.chmod(0o600)
                staged.write(payload)
        except (EOFError, OSError, paramiko.SSHException) as error:
            raise _channel_error(
                operation, "cannot stage the request", error, self._transport
            ) from error

    def _connect(self, timeout: float) -> None:
        if self._transport is not None and self._transport.is_authenticated():
            return
        self.close()

        with contextlib.ExitStack() as cleanup:
            try:
                sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
                cleanup.callback(sock.close)
                sock.settimeout(timeout)
                sock.connect((self._cid, _SSH_PORT))
            except OSError as error:
                raise FdeGuestTimeout(
                    "connect", "guest vsock is unreachable"
                ) from error
            transport = paramiko.Transport(sock)
            cleanup.callback(transport.close)
            self._authenticate(transport, timeout)
            cleanup.pop_all()
        self._transport = transport

        try:
            self._deploy_helper(timeout)
        except BaseException:
            # A later request must not reuse a channel without a helper.
            self.close()
            raise

    def _authenticate(self, transport: paramiko.Transport, timeout: float) -> None:
        try:
            transport.start_client(timeout=timeout)
        except (EOFError, OSError, paramiko.SSHException) as error:
            raise _channel_error(
                "connect", "guest SSH handshake failed", error, transport
            ) from error
        try:
            server_key = transport.get_remote_server_key()
        except paramiko.SSHException as error:
            # start_client returns silently when its deadline ends the handshake.
            raise FdeGuestTimeout(
                "connect", "guest SSH handshake did not finish"
            ) from error
        self._verify_host_key(server_key)
        identity = _load_identity(self._fixture.ssh_identity)
        try:
            transport.auth_publickey(self._fixture.ssh_user, identity)
        except (EOFError, OSError, paramiko.SSHException) as error:
            banner = _login_banner(transport)
            if any(marker in banner for marker in _TRANSIENT_LOGIN_BANNERS):
                # pam_nologin refuses logins while the guest boots or shuts
                # down; that refusal is transient, unlike a rejected key.
                raise FdeGuestTimeout(
                    "connect", "guest is not accepting logins yet"
                ) from error
            raise _channel_error(
                "connect", "guest SSH authentication failed", error, transport
            ) from error
        transport.set_keepalive(30)

    def _verify_host_key(self, server_key: paramiko.PKey) -> None:
        try:
            host_keys = paramiko.HostKeys(str(self._fixture.ssh_known_hosts))
        except (OSError, ValueError, paramiko.hostkeys.InvalidHostKey) as error:
            raise FdeGuestError("connect", "known-hosts file is unreadable") from error
        entry = host_keys.lookup(self._fixture.ssh_host_alias)
        if not entry:
            raise FdeGuestError(
                "connect", "known-hosts file has no entry for the fixture alias"
            )
        expected = entry.get(server_key.get_name())
        if expected is None or expected != server_key:
            raise FdeGuestError("connect", "guest host key does not match the fixture")

    def _deploy_helper(self, timeout: float) -> None:
        local = _HELPER_SOURCE.read_bytes()
        try:
            sftp = self._require_sftp("preflight")
            if self._helper_is_current(sftp, local):
                return
            sftp.putfo(io.BytesIO(local), _REMOTE_STAGING)
            sftp.chmod(_REMOTE_STAGING, 0o600)
        except (EOFError, OSError, paramiko.SSHException) as error:
            raise _channel_error(
                "preflight", "cannot stage the guest helper", error, self._transport
            ) from error

        output = self._run_as_root(
            [
                "/usr/bin/install",
                "-D",
                "-m",
                "0755",
                _REMOTE_STAGING,
                _HELPER_REMOTE,
            ],
            "preflight",
            timeout,
            expect_json=False,
        )
        if output.strip():
            raise FdeGuestError("preflight", "cannot install the guest helper")

        with contextlib.suppress(EOFError, OSError, paramiko.SSHException):
            self._require_sftp("preflight").remove(_REMOTE_STAGING)

    def _helper_is_current(self, sftp: paramiko.SFTPClient, local: bytes) -> bool:
        try:
            if sftp.stat(_HELPER_REMOTE).st_size != len(local):
                return False
            with sftp.open(_HELPER_REMOTE, "rb") as remote:
                return remote.read(len(local) + 1) == local
        except OSError:
            # Missing or unreadable: redeploying reports a dropped link.
            return False

    def _run_as_root(
        self,
        command: list[str],
        operation: str,
        timeout: float,
        expect_json: bool = True,
    ) -> str:
        transport = self._transport
        if transport is None:
            raise FdeGuestError(operation, "guest channel is not connected")
        channel: paramiko.Channel | None = None
        try:
            channel = transport.open_session(timeout=timeout)
            channel.settimeout(timeout)
            channel.exec_command(
                " ".join(shlex.quote(part) for part in (*_SUDO, *command))
            )
            channel.sendall((self._fixture.secret("login_password") + "\n").encode())
            channel.shutdown_write()

            stdout = _read_channel(channel, timeout, operation)
            channel.recv_exit_status()
            status = channel.exit_status
        except TimeoutError as error:
            raise FdeGuestTimeout(
                operation, "no response before the deadline"
            ) from error
        except (EOFError, OSError, paramiko.SSHException) as error:
            raise _channel_error(
                operation, "guest command channel failed", error, transport
            ) from error
        finally:
            if channel is not None:
                channel.close()

        # Paramiko reports -1 when sshd sent no exit status: the command died by
        # a signal, as at shutdown, or the link dropped. The transport may be live.
        if status == -1 and not stdout.strip():
            raise FdeGuestTimeout(operation, "session ended without an exit status")
        if not expect_json:
            if status != 0:
                raise FdeGuestError(operation, f"command exited with status {status}")
            return stdout
        # A failed helper still prints its typed envelope, which carries the
        # cause; only a silent failure leaves the exit status as the evidence.
        if status != 0 and not stdout.strip():
            raise FdeGuestError(operation, f"helper exited with status {status}")
        return stdout

    def _require_sftp(self, operation: str) -> paramiko.SFTPClient:
        if self._sftp is not None:
            return self._sftp
        transport = self._transport
        if transport is None:
            raise FdeGuestError(operation, "guest channel is not connected")
        sftp = paramiko.SFTPClient.from_transport(transport)
        if sftp is None:
            raise FdeGuestError(operation, "guest SFTP channel is unavailable")
        self._sftp = sftp
        return sftp

    def _remove_staging(self, directory: str, path: str) -> None:
        if self._sftp is None:
            return
        # The helper deletes the file it read, but never its directory.
        with contextlib.suppress(EOFError, OSError, paramiko.SSHException):
            self._sftp.remove(path)
        with contextlib.suppress(EOFError, OSError, paramiko.SSHException):
            self._sftp.rmdir(directory)


def _channel_error(
    operation: str,
    detail: str,
    error: BaseException,
    transport: paramiko.Transport | None,
) -> FdeGuestError:
    if transport is not None and _link_dropped(error, transport):
        return FdeGuestTimeout(operation, f"{detail}: guest link dropped")
    return FdeGuestError(operation, detail)


def _link_dropped(error: BaseException, transport: paramiko.Transport) -> bool:
    """Whether error is the guest link going away, as it does across a reboot.

    Remote refusals (authentication, host key, SFTP status, channel open)
    arrive as typed errors or on a live transport. A dropped link shows up
    as an EOF, or as a socket error once the transport has stopped.
    """
    cause: BaseException | None = error
    if type(error) is paramiko.SSHException:
        # Paramiko re-raises link failures bare, either while handling them
        # (banner, SFTP) or after keeping them for get_exception().
        cause = error.__context__
    if isinstance(cause, EOFError):
        return True
    if isinstance(cause, (FileNotFoundError, PermissionError)):
        # SFTP's no-such-file and permission-denied statuses: the guest answered.
        return False
    if transport.is_active():
        return False
    saved = transport.get_exception()
    if isinstance(saved, (EOFError, OSError)):
        # Paramiko reports a link that died during authentication as an
        # AuthenticationException, keeping the socket error in saved.
        return True
    if cause is None:
        cause = saved
    return isinstance(cause, (EOFError, OSError))


def _login_banner(transport: paramiko.Transport) -> str:
    """The server's login banner, which outlives the link closing."""
    banner = transport.get_banner()
    if banner is None:
        # paramiko hides the banner once the transport stops, but keeps it on
        # the auth handler, and the guest closes the link after refusing a
        # login while it boots.
        handler = getattr(transport, "auth_handler", None)
        banner = getattr(handler, "banner", None)
    if isinstance(banner, bytes):
        return banner.decode("utf-8", "replace")
    return banner or ""


def _read_channel(channel: paramiko.Channel, timeout: float, operation: str) -> str:
    chunks: list[bytes] = []
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FdeGuestTimeout(operation, "no response before the deadline")
        channel.settimeout(remaining)
        try:
            chunk = channel.recv(0xFFFF)
        except TimeoutError as error:
            raise FdeGuestTimeout(
                operation, "no response before the deadline"
            ) from error
        if not chunk:
            return b"".join(chunks).decode("utf-8", "replace")
        chunks.append(chunk)


def _parse_helper_response(operation: str, output: str) -> dict[str, object]:
    text = output.strip()
    if not text:
        raise FdeGuestError(operation, "helper produced no response")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise FdeGuestError(operation, "helper response was not JSON") from error
    if not isinstance(payload, dict):
        raise FdeGuestError(operation, "helper response was not an object")
    if not payload.get("ok"):
        code = payload.get("code")
        detail = payload.get("message") or code or "unspecified failure"
        raise FdeGuestError(
            operation, str(detail)[:400], code if isinstance(code, str) else None
        )
    result = payload.get("result")
    if not isinstance(result, dict):
        raise FdeGuestError(operation, "helper response has no result object")
    return result


def _load_identity(path: Path) -> paramiko.PKey:
    try:
        return paramiko.PKey.from_path(path)
    # cryptography raises ValueError for malformed keys and TypeError for an
    # encrypted key, which needs a password the fixture never supplies.
    except (
        OSError,
        ValueError,
        TypeError,
        paramiko.SSHException,
        paramiko.pkey.UnknownKeyType,
    ) as error:
        raise FdeGuestError("connect", "SSH identity is unreadable") from error
