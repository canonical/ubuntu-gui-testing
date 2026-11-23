#!/usr/bin/python3
"""Root helper executed inside one disposable TPM-FDE test guest.

It is written for a throwaway virtual machine cloned for a single test case
and does not check that it is on one. It performs fixture setup, fault
recipes (four use the TPM's own tools; the rest plant mounts, stand-in device
nodes or canned replies), and independent postcondition checks. All
user-facing repair work goes through the graphical application, never through
this helper.

The helper prints exactly one JSON object on stdout:

    {"ok": true, "result": {...}}
    {"ok": false, "code": "...", "message": "..."}

Secrets such as recovery keys are only returned when explicitly requested by an
operation, and never appear in messages, logs, or process arguments.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import stat
import struct
import subprocess
import sys
import time
from typing import Any

SNAPD_SOCKET = "/run/snapd.socket"
SNAPD_UNIT = "snapd.service"
SNAPD_TESTING_DROPIN = "/etc/systemd/system/snapd.service.d/zz-ugt-snappy-testing.conf"
# The process is the Flutter binary (bin/security_center), not the snap name.
GUI_EXECUTABLE = "security_center"
GUI_FORBIDDEN_ARGUMENTS = ("--dry-run", "--test-fde-repair", "--fake-service")
# The reprovision handler saves its accepted check result here with a private
# atomic rename, immediately before it enters the state-locked TPM sealing path.
PREINSTALL_CHECK_PATH = "/var/lib/snapd/save/preinstall"
# One stage wait is bounded so a dropped host link cannot leave a helper polling.
STAGE_WAIT_LIMIT = 60.0
STAGE_POLL_INTERVAL = 0.02
RECOVERY_KEY = re.compile(r"\A[0-9]{5}(?:-[0-9]{5}){7}\Z")
# cryptsetup(8) documents status 2 as "no permission (bad passphrase)"; only
# this C-locale diagnostic, printed for a key no keyslot accepts, means rejection.
CRYPTSETUP_WRONG_KEY_STATUS = 2
CRYPTSETUP_WRONG_KEY_MESSAGE = "No key available with this passphrase."
DEFAULT_TIMEOUT = 60
CHANGE_TIMEOUT = 300
# ReplacePlatformKey creates this change kind for every enrollment request.
REPLACE_PLATFORM_KEY_CHANGE = "fde-replace-platform-key"

EFI_SYSFS_DIR = "/sys/firmware/efi"
EVENT_LOG_PATH = "/sys/kernel/security/tpm0/binary_bios_measurements"
IMAGE_SECURITY_DATABASE_GUID = "d719b2cb-3d3a-4596-a3bc-dad00e67656f"
SECURE_BOOT_DB_PATH = f"{EFI_SYSFS_DIR}/efivars/db-{IMAGE_SECURITY_DATABASE_GUID}"
# efivarfs prefixes a variable's data with its 4-byte attribute bitmask.
EFI_VARIABLE_ATTRIBUTES_SIZE = 4
# TCG log records the pre-OS measurements op reads.
EVENT_TYPE_BOOT_SERVICES_APPLICATION = 0x80000003
EVENT_TYPE_VARIABLE_DRIVER_CONFIG = 0x80000001
EVENT_TYPE_VARIABLE_AUTHORITY = 0x800000E0
SECURE_BOOT_POLICY_PCR = 7
SPEC_EVENT_TYPE = 0x03
SPEC_ID_SIGNATURE = b"Spec ID Event03\0"
# Offsets inside a Spec ID Event03 record: signature, platform class,
# version/uintn bytes, algorithm count, then (algorithm, size) pairs.
SPEC_ALGORITHM_COUNT = len(SPEC_ID_SIGNATURE) + 8
SPEC_ALGORITHM_TABLE = SPEC_ALGORITHM_COUNT + 4
SHA1_DIGEST_SIZE = 20
EVENT_HEADER = struct.Struct("<II")
WORD = struct.Struct("<I")
ALGORITHM = struct.Struct("<H")
# Each EFI_SIGNATURE_DATA entry opens with the GUID that owns the signature.
OWNER_GUID_SIZE = 16
# EFI_SIGNATURE_LIST: type GUID, then list, header and signature sizes.
SIGNATURE_LIST_HEADER = struct.Struct("<III")
IMAGE_LOCATION = struct.Struct("<QQQQ")
DEVICE_PATH_NODE = struct.Struct("<BBH")
DEVICE_PATH_FILE_NODE = (4, 4)
DEVICE_PATH_END = 0x7F
TPM_DEVICE_PATHS = ("/dev/tpm0", "/dev/tpmrm0")
PPI_REQUEST_PATH = "/sys/class/tpm/tpm0/ppi/request"
MUTATION_STATE_DIR = "/run/ugt-fde/mutations"
PPI_REQUEST_BLOCKER = "/run/ugt-fde/ppi-request-blocked"
SB_GUID = "8be4df61-93ca-11d2-aa0d-00e098032b8c"
BOOT_OPTION_SUPPORT = f"{EFI_SYSFS_DIR}/efivars/BootOptionSupport-{SB_GUID}"
BOOT_OPTION_SUPPORT_SYSPREP = 0x10


class HelperError(RuntimeError):
    """A named failure that the host can attribute to a real cause."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._unix_path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._unix_path)
        self.sock = sock


def _tool(name: str) -> str:
    """Resolve a guest tool to an absolute path through PATH."""
    resolved = shutil.which(name)
    if resolved is None:
        raise HelperError("missing-tool", f"{name} is not installed")
    return resolved


def _run(command: list[str], timeout: float = DEFAULT_TIMEOUT) -> str:
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, never a shell
            command,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as error:
        raise HelperError("missing-tool", f"{command[0]} is not installed") from error
    except subprocess.TimeoutExpired as error:
        raise HelperError("timeout", f"{command[0]} did not finish") from error
    if completed.returncode != 0:
        raise HelperError(
            "command-failed",
            f"{command[0]} exited with status {completed.returncode}",
        )
    return completed.stdout.decode("utf-8", "replace")


def _run_expecting_failure(
    command: list[str], timeout: float = DEFAULT_TIMEOUT
) -> None:
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, never a shell
            command,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise HelperError("timeout", f"{command[0]} did not finish") from error
    if completed.returncode == 0:
        raise HelperError(
            "unexpected-success",
            f"{command[0]} succeeded where the real hardware state requires failure",
        )


def _snapd(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    return _snapd_envelope(method, path, body, timeout)[1]


def _snapd_envelope(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, Any, str | None]:
    connection = _UnixHTTPConnection(SNAPD_SOCKET, timeout=timeout)
    try:
        payload = None
        headers = {}
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read()
    except OSError as error:
        raise HelperError(
            "snapd-unreachable", "cannot reach the snapd socket"
        ) from error
    finally:
        connection.close()

    try:
        envelope = json.loads(raw or b"{}")
    except json.JSONDecodeError as error:
        raise HelperError(
            "snapd-malformed", "snapd returned a non-JSON response"
        ) from error
    if response.status >= 400:
        result = envelope.get("result") or {}
        message = result.get("message") if isinstance(result, dict) else None
        raise HelperError(
            "snapd-error",
            str(message or f"snapd returned status {response.status}")[:300],
        )
    change = envelope.get("change")
    return (
        response.status,
        envelope.get("result"),
        change if isinstance(change, str) and change else None,
    )


def _snapd_async(
    method: str,
    path: str,
    body: dict[str, Any],
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[Any, str]:
    """Submit an asynchronous snapd action and return its change identifier."""
    _, result, change = _snapd_envelope(method, path, body, timeout)
    if change is None:
        raise HelperError("snapd-malformed", "snapd returned no change identifier")
    return result, change


def _wait_change(change_id: str, timeout: float = CHANGE_TIMEOUT) -> dict[str, Any]:
    """Wait, within a fixed deadline, for one snapd change to finish."""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise HelperError("timeout", f"snapd change {change_id} did not finish")
        change = _snapd(
            "GET",
            f"/v2/changes/{change_id}",
            timeout=min(DEFAULT_TIMEOUT, remaining),
        )
        if not isinstance(change, dict):
            raise HelperError("snapd-malformed", "snapd change result is not an object")
        status = str(change.get("status") or "")
        if status == "Done":
            return {str(key): value for key, value in change.items()}
        if status in ("Error", "Undone"):
            raise HelperError(
                "change-failed", f"snapd change {change_id} ended in {status}"
            )
        time.sleep(min(1.0, remaining))


def _boot_id() -> str:
    return _read("/proc/sys/kernel/random/boot_id").strip()


def _boot_started_at() -> int:
    """Return the kernel's boot wall-clock time, which orders a later change."""
    for line in _read("/proc/stat").splitlines():
        if line.startswith("btime "):
            value = line.split()[1]
            if value.isdigit():
                return int(value)
    raise HelperError("unreadable", "/proc/stat has no boot time")


def _stat_identity(path: str) -> dict[str, Any] | None:
    """Report a file's replacement identity without reading its contents."""
    try:
        info = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise HelperError("unreadable", f"cannot inspect {path}") from error
    return {
        "inode": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
        "mode": stat.S_IMODE(info.st_mode),
        "regular": stat.S_ISREG(info.st_mode),
    }


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError as error:
        raise HelperError("unreadable", f"cannot read {path}") from error


def _read_bytes(path: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as error:
        raise HelperError("unreadable", f"cannot read {path}") from error


def _socket_inode(path: str) -> str:
    for line in _read("/proc/net/unix").splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 7 and fields[-1] == path:
            return fields[6]
    raise HelperError("snapd-unreachable", "snapd socket is not listening")


def _socket_owner_pids(path: str) -> set[int]:
    inode = _socket_inode(path)
    target = f"socket:[{inode}]"
    owners: set[int] = set()
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        descriptor_dir = f"/proc/{entry}/fd"
        try:
            descriptors = os.listdir(descriptor_dir)
        except OSError:
            continue
        for descriptor in descriptors:
            try:
                if os.readlink(f"{descriptor_dir}/{descriptor}") == target:
                    owners.add(int(entry))
                    break
            except OSError:
                continue
    return owners


def _snapd_main_pid() -> int:
    raw = _run(["systemctl", "show", "-p", "MainPID", "--value", SNAPD_UNIT]).strip()
    if not raw.isdigit() or int(raw) <= 0:
        raise HelperError("snapd-stopped", "snapd.service has no main process")
    return int(raw)


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError as error:
        raise HelperError("unreadable", f"cannot read {path}") from error
    return digest.hexdigest()


def _running_executable(pid: int) -> tuple[str, str]:
    """Return the path and sha256 of the binary pid runs.

    snapd re-executes into its snap when that is not older than the deb, so
    /usr/lib/snapd/snapd says nothing about the daemon that answers the API.
    """
    link = f"/proc/{pid}/exe"
    try:
        path = os.readlink(link)
    except OSError as error:
        raise HelperError("unreadable", f"cannot resolve {link}") from error
    return path, _file_sha256(link)


def _app_revision(snap_name: str) -> str:
    # A missing snap is a 404 that _snapd reports as snapd-error.
    info = _snapd("GET", f"/v2/snaps/{snap_name}")
    if not isinstance(info, dict) or info.get("revision") is None:
        raise HelperError("snapd-malformed", "snap info result has no revision")
    return str(info["revision"])


def _storage_status() -> dict[str, Any]:
    result = _snapd("GET", "/v2/system-info/storage-encrypted")
    if not isinstance(result, dict):
        raise HelperError(
            "snapd-malformed", "storage-encrypted result is not an object"
        )
    return result


def _running_system_check() -> dict[str, Any]:
    result = _snapd("GET", "/v2/systems?running=true")
    if not isinstance(result, dict) or "storage-encryption" not in result:
        raise HelperError("snapd-malformed", "running system result has no encryption")
    return result


def _system_volumes() -> dict[str, Any]:
    volumes = _snapd("GET", "/v2/system-volumes")
    if not isinstance(volumes, dict):
        raise HelperError("snapd-malformed", "system volumes result is not an object")
    return volumes


def _keyslot_auth_mode(volumes: dict[str, Any]) -> str:
    modes: set[str] = set()
    for volume in (volumes.get("by-container-role") or {}).values():
        for slot in (volume.get("keyslots") or {}).values():
            if slot.get("type") != "platform":
                continue
            # A role is a "+"-joined token list such as "run+recover".
            if not any("run" in role.split("+") for role in slot.get("roles") or []):
                continue
            modes.add(str(slot.get("auth-mode") or "none"))
    if len(modes) > 1:
        raise HelperError(
            "inconsistent-auth", "platform keyslots disagree on auth mode"
        )
    return modes.pop() if modes else "none"


def _keyslot_names(volumes: dict[str, Any]) -> dict[str, list[str]]:
    """Name every keyslot per container role, including a repair's temporary ones."""
    return {
        str(role): sorted(str(name) for name in (volume.get("keyslots") or {}))
        for role, volume in (volumes.get("by-container-role") or {}).items()
    }


def _change_fields(change: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(change.get("id")),
        "kind": change.get("kind"),
        "status": change.get("status"),
        "ready": bool(change.get("ready")),
        "err": change.get("err"),
        "spawn_time": change.get("spawn-time"),
        "ready_time": change.get("ready-time"),
    }


def _in_progress_changes() -> list[dict[str, Any]]:
    result = _snapd("GET", "/v2/changes?select=in-progress")
    return [_change_fields(change) for change in result or []]


def _gui_processes() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        process_dir = f"/proc/{name}"
        try:
            with open(f"{process_dir}/cmdline", "rb") as handle:
                raw = handle.read().decode("utf-8", "replace")
            uid = os.stat(process_dir).st_uid
        except (FileNotFoundError, ProcessLookupError):
            continue  # The process exited after listdir.
        except OSError as error:
            raise HelperError("unreadable", f"cannot inspect {process_dir}") from error
        if not raw:
            continue
        arguments = [part for part in raw.split("\x00") if part]
        if not arguments:
            continue
        if os.path.basename(arguments[0]) != GUI_EXECUTABLE:
            continue
        entries.append({"pid": int(name), "uid": uid, "arguments": arguments[1:]})
    return entries


def _last_change(kind: str) -> dict[str, Any] | None:
    changes = _snapd("GET", "/v2/changes?select=all") or []
    matches = [change for change in changes if change.get("kind") == kind]
    if not matches:
        return None
    # select=all comes from a map; ids are increasing decimal strings.
    change = max(matches, key=lambda match: int(match.get("id")))
    return _change_fields(change)


def _assert_gui_is_a_real_desktop_user(desktop_user: str) -> int:
    desktop_uid = int(_run(["id", "-u", desktop_user]).strip())
    processes = _gui_processes()
    if not processes:
        raise HelperError(
            "gui-not-running", "the application under test is not running"
        )
    for process in processes:
        if process["uid"] == 0:
            raise HelperError(
                "gui-as-root", "the application under test is running as root"
            )
        for argument in process["arguments"]:
            if argument.split("=")[0] in GUI_FORBIDDEN_ARGUMENTS:
                raise HelperError(
                    "gui-not-production",
                    "the application under test runs with a non-production argument",
                )
        if process["uid"] != desktop_uid:
            raise HelperError(
                "gui-wrong-user",
                "the application under test runs outside the desktop user",
            )
    return desktop_uid


def _crypt_device_ready(device: str) -> bool:
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, never a shell
            [_tool("cryptsetup"), "isLuks", device],
            capture_output=True,
            timeout=DEFAULT_TIMEOUT,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise HelperError("missing-tool", "cryptsetup is unavailable") from error
    return completed.returncode == 0


def _recovery_key_bytes(text: str) -> bytes:
    """Decode a dashed recovery key into the 16 raw bytes its LUKS slot holds.

    Each 5-digit group is one little-endian uint16, as secboot encodes it.
    """
    groups = text.split("-") if RECOVERY_KEY.match(text) else []
    values = [int(group) for group in groups]
    if len(values) != 8 or any(value > 0xFFFF for value in values):
        raise HelperError("invalid-key", "the key is not a recovery key")
    return b"".join(value.to_bytes(2, "little") for value in values)


def _key_unlocks(device: str, completed: subprocess.CompletedProcess[bytes]) -> bool:
    """Read one `cryptsetup open --test-passphrase` run as unlock or rejection.

    Any outcome other than success or a wrong key raises, so an operational
    failure can never pass for a revoked key.
    """
    if completed.returncode == 0:
        return True
    diagnostics = [
        line.strip()
        for line in completed.stderr.decode("utf-8", "replace").splitlines()
        if line.strip()
    ]
    if (
        completed.returncode == CRYPTSETUP_WRONG_KEY_STATUS
        and CRYPTSETUP_WRONG_KEY_MESSAGE in diagnostics
    ):
        return False
    detail = diagnostics[-1] if diagnostics else "no diagnostic"
    message = (
        f"cryptsetup could not test the key on {device} "
        f"(status {completed.returncode}): {detail}"
    )
    raise HelperError("command-failed", message[:300])


def _mount_table() -> list[tuple[str, str]]:
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError as error:
        raise HelperError("unreadable", "cannot read the mount table") from error
    table: list[tuple[str, str]] = []
    for line in lines:
        fields = line.split()
        if len(fields) < 7:
            continue
        mount_point = fields[4]
        for octal, plain in (("\\040", " "), ("\\011", "\t"), ("\\134", "\\")):
            mount_point = mount_point.replace(octal, plain)
        table.append((mount_point, fields[fields.index("-") + 1]))
    return table


def _fstype_of(path: str) -> str | None:
    """Return the filesystem type serving `path`, or None without a mount."""
    best: tuple[int, str] | None = None
    for mount_point, fstype in _mount_table():
        if path != mount_point and not path.startswith(mount_point.rstrip("/") + "/"):
            continue
        if best is None or len(mount_point) > best[0]:
            best = (len(mount_point), fstype)
    return best[1] if best is not None else None


def _mutation_record_path(recipe: str) -> str:
    return os.path.join(MUTATION_STATE_DIR, recipe + ".json")


def _recorded_mounts(recipe: str) -> list[dict[str, str]] | None:
    try:
        with open(_mutation_record_path(recipe), encoding="utf-8") as handle:
            record = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as error:
        raise HelperError("unreadable", "a recorded mutation is unreadable") from error
    mounts = record.get("mounts") if isinstance(record, dict) else None
    if not isinstance(mounts, list):
        raise HelperError("unreadable", "a recorded mutation is malformed")
    return mounts


def _store_mounts(recipe: str, mounts: list[dict[str, str]]) -> None:
    os.makedirs(MUTATION_STATE_DIR, mode=0o700, exist_ok=True)
    staging = _mutation_record_path(recipe) + ".new"
    with open(staging, "w", encoding="utf-8") as handle:
        json.dump({"recipe": recipe, "mounts": mounts}, handle)
    os.replace(staging, _mutation_record_path(recipe))


def _apply_mounts(recipe: str, mounts: list[tuple[str, list[list[str]]]]) -> None:
    """Apply each mount and record it before the next, so a revert is exact."""
    recorded: list[dict[str, str]] = []
    for target, commands in mounts:
        original = _fstype_of(target)
        if original is None:
            raise HelperError("mutation-not-applied", f"{target} has no backing mount")
        for command in commands:
            _run(command)
        planted = _fstype_of(target)
        if planted is None or planted == original:
            raise HelperError(
                "mutation-not-applied", f"the mount at {target} did not change"
            )
        recorded.append(
            {"target": target, "fstype": planted, "original_fstype": original}
        )
        _store_mounts(recipe, recorded)


def _undo_mounts(recipe: str) -> list[str]:
    """Unmount exactly what this recipe mounted, and nothing else."""
    recorded = _recorded_mounts(recipe)
    if not recorded:
        return []
    undone: list[str] = []
    for mount in recorded:
        target = mount["target"]
        if _fstype_of(target) != mount["fstype"]:
            raise HelperError(
                "mutation-drift", f"{target} is not the mutation that was applied"
            )
        _run(["umount", target])
        undone.append(target)
    with contextlib.suppress(OSError):
        os.unlink(_mutation_record_path(recipe))
    return undone


def operation_preflight(parameters: dict[str, Any]) -> dict[str, Any]:
    desktop_user = _string(parameters, "desktop_user")
    data_device = _string(parameters, "data_device")
    save_device = _string(parameters, "save_device")

    main_pid = _snapd_main_pid()
    owners = _socket_owner_pids(SNAPD_SOCKET)
    if main_pid not in owners:
        raise HelperError(
            "snapd-daemon-mismatch",
            "the socket is served by a process other than snapd.service",
        )

    executable_path, executable_hash = _running_executable(main_pid)
    version = (_snapd("GET", "/v2/system-info") or {}).get("version")
    revision = _app_revision("desktop-security-center")
    desktop_uid = _assert_gui_is_a_real_desktop_user(desktop_user)

    for device in (data_device, save_device):
        if not os.path.exists(device):
            raise HelperError("device-missing", f"encrypted device {device} is absent")
        if not _crypt_device_ready(device):
            raise HelperError("device-not-encrypted", f"device {device} is not LUKS")

    return {
        "boot_id": _boot_id(),
        "snapd_pid": main_pid,
        "snapd_version": version,
        "snapd_executable_path": executable_path,
        "snapd_executable_sha256": executable_hash,
        "security_center_revision": revision,
        "desktop_uid": desktop_uid,
        "auth_mode": _keyslot_auth_mode(_system_volumes()),
        "storage": _storage_status(),
        "changes": _in_progress_changes(),
    }


def operation_snapshot(_: dict[str, Any]) -> dict[str, Any]:
    volumes = _system_volumes()
    return {
        "boot_id": _boot_id(),
        "boot_started_at": _boot_started_at(),
        "wall_time": time.time(),
        "auth_mode": _keyslot_auth_mode(volumes),
        "keyslots": _keyslot_names(volumes),
        "storage": _storage_status(),
        "changes": _in_progress_changes(),
        "last_reprovision": _last_change("fde-reprovision"),
    }


def operation_repair_progress(parameters: dict[str, Any]) -> dict[str, Any]:
    """Report passive reprovision-stage evidence without taking snapd's lock.

    The reprovision handler holds snapd's global state lock while it mutates
    keyslots and seals, so no /v2 request can be answered during the window a
    power cut must interrupt. This operation only reads the kernel's boot time
    and the private check-result file's replacement identity, so it keeps
    answering throughout that window.

    With `wait` seconds and the last identity the host saw as `changed_from`
    (null for an absent file), it re-reads only that identity and returns as
    soon as it differs, so a replacement is reported within milliseconds
    instead of one request round trip later.
    """
    wait = parameters.get("wait", 0)
    if isinstance(wait, bool) or not isinstance(wait, (int, float)):
        raise HelperError("invalid-argument", "parameter 'wait' must be a number")
    if not 0 <= wait <= STAGE_WAIT_LIMIT:
        raise HelperError(
            "invalid-argument",
            f"parameter 'wait' must be between 0 and {STAGE_WAIT_LIMIT:g} seconds",
        )
    if wait and "changed_from" not in parameters:
        raise HelperError(
            "invalid-argument", "a stage wait needs the 'changed_from' identity"
        )
    changed_from = parameters.get("changed_from")
    if changed_from is not None and not isinstance(changed_from, dict):
        raise HelperError(
            "invalid-argument", "parameter 'changed_from' must be an object or null"
        )

    deadline = time.monotonic() + wait
    identity = _stat_identity(PREINSTALL_CHECK_PATH)
    while wait and identity == changed_from and time.monotonic() < deadline:
        time.sleep(STAGE_POLL_INTERVAL)
        identity = _stat_identity(PREINSTALL_CHECK_PATH)
    return {
        "boot_id": _boot_id(),
        "boot_started_at": _boot_started_at(),
        "wall_time": time.time(),
        "check_result": identity,
    }


def _running_system_recheck() -> dict[str, Any]:
    # A plain GET re-runs the checks in a fresh context and drops every issue
    # the user already proceeded past; an empty fix action re-checks in the
    # cached context the dialog is using.
    result = _snapd(
        "POST", "/v2/systems", {"action": "fix-encryption-support", "fix-action": ""}
    )
    if not isinstance(result, dict) or "storage-encryption" not in result:
        raise HelperError("snapd-malformed", "running system result has no encryption")
    return result


def operation_check(parameters: dict[str, Any]) -> dict[str, Any]:
    recheck = parameters.get("recheck", False)
    if not isinstance(recheck, bool):
        raise HelperError("invalid-argument", "parameter 'recheck' must be a boolean")
    return {
        "boot_id": _boot_id(),
        "systems": _running_system_recheck() if recheck else _running_system_check(),
        "storage": _storage_status(),
        "changes": _in_progress_changes(),
        "last_reprovision": _last_change("fde-reprovision"),
    }


def operation_fault(parameters: dict[str, Any]) -> dict[str, Any]:
    recipe = _string(parameters, "recipe")
    handler = _FAULT_RECIPES.get(recipe)
    if handler is None:
        raise HelperError(
            "unsupported-platform",
            f"fault recipe {recipe!r} is not reproducible on this platform",
        )
    return {"recipe": recipe, "verified": handler()}


def _snapd_namespace() -> list[str]:
    """Prefix a command so it runs in snapd's mount namespace.

    snapd's checks read devices and firmware variables from its own namespace,
    so a tamper applied outside it is invisible to the check under test.
    """
    return ["nsenter", "-t", str(_snapd_main_pid()), "-m", "--"]


def _ns_run(command: list[str], timeout: float = DEFAULT_TIMEOUT) -> str:
    return _run([*_snapd_namespace(), *command], timeout)


def _ns_run_expecting_failure(command: list[str]) -> None:
    _run_expecting_failure([*_snapd_namespace(), *command])


def _bind(source: str, target: str) -> None:
    _ns_run(["mount", "--bind", source, target])


def _size(path: str) -> int:
    try:
        return os.stat(path).st_size
    except OSError:
        return -1


def _tpm_dir() -> str:
    return os.path.realpath("/sys/class/tpm/tpm0")


def _snapd_memory() -> str:
    # Reading /proc/PID/mem at offset 0 fails with EIO, so binding it over a
    # device turns every read of that device into a transport error.
    return f"/proc/{_snapd_main_pid()}/mem"


def _staging(name: str) -> str:
    os.makedirs(MUTATION_STATE_DIR, mode=0o700, exist_ok=True)
    return os.path.join(MUTATION_STATE_DIR, name)


def _fault_disable_endorsement_hierarchy() -> str:
    _run(["tpm2_hierarchycontrol", "-C", "e", "ehEnable", "clear"])
    _run_expecting_failure(["tpm2_readpublic", "-C", "e"])
    return "endorsement-hierarchy-unavailable"


def _fault_disable_owner_hierarchy() -> str:
    _run(["tpm2_hierarchycontrol", "-C", "o", "shEnable", "clear"])
    _run_expecting_failure(["tpm2_readpublic", "-C", "o"])
    return "owner-hierarchy-disabled"


def _fault_dictionary_lockout() -> str:
    _run(
        [
            "tpm2_dictionarylockout",
            "-s",
            "-n",
            "1",
            "-t",
            "1",
            "-l",
            "300",
            "-p",
            "",
        ]
    )
    _run_expecting_failure(
        ["tpm2_dictionarylockout", "--clear-lockout", "-p", "notthepass"]
    )
    _run_expecting_failure(["tpm2_dictionarylockout", "--clear-lockout", "-p", ""])
    return "lockout-triggered"


def _fault_extend_pcr4() -> str:
    before = _run(["tpm2_pcrread", "sha256:4"])
    _run(["tpm2_pcrextend", "4:sha256=" + "00" * 32])
    after = _run(["tpm2_pcrread", "sha256:4"])
    if before == after:
        raise HelperError("fault-not-applied", "PCR 4 did not change")
    return "pcr4-extended"


def _fault_hide_efi_sysfs() -> str:
    _ns_run(["mount", "-t", "tmpfs", "tmpfs", EFI_SYSFS_DIR])
    fstype = _ns_run(["findmnt", "-n", "-T", EFI_SYSFS_DIR, "-o", "FSTYPE"])
    if fstype.strip() != "tmpfs":
        raise HelperError("fault-not-applied", "EFI sysfs is still visible")
    return "efi-sysfs-hidden"


def _fault_hide_measurements() -> str:
    _bind("/dev/null", EVENT_LOG_PATH)
    if _size(EVENT_LOG_PATH) != 0:
        raise HelperError("fault-not-applied", "measurements are still readable")
    return "measurements-hidden"


def _fault_null_tpm_device() -> str:
    for node in TPM_DEVICE_PATHS:
        backup = node + ".real"
        if not os.path.exists(backup):
            os.rename(node, backup)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(node)
        os.mknod(node, 0o600 | stat.S_IFCHR, os.makedev(1, 5))
    if os.stat(TPM_DEVICE_PATHS[0]).st_rdev != os.makedev(1, 5):
        raise HelperError("fault-not-applied", "TPM device is not the null device")
    return "tpm-device-null"


def _fault_tpm_transport_error() -> str:
    for node in TPM_DEVICE_PATHS:
        _bind(_snapd_memory(), node)
    if _size(TPM_DEVICE_PATHS[0]) != 0:
        raise HelperError("fault-not-applied", "TPM node still reports a size")
    return "tpm-transport-eio"


def _fault_tpm_reply(return_code: int, name: str) -> str:
    # A plain file bound over the TPM nodes plays back canned replies: each write
    # advances the file offset, so the next read returns the bytes after the
    # command. go-tpm2 probes a device it has not seen once with GetCapability.
    failure = struct.pack(">HII", 0x8001, 10, return_code)
    probe = struct.pack(">HIIBIIII", 0x8001, 27, 0, 0, 6, 1, 0x105, 0x49424D00)
    payload = bytes(11) + failure + bytes(1) + probe + bytes(11) + failure
    reply = _staging("tpm-reply")
    with open(reply, "wb") as handle:
        handle.write(payload)
    for node in TPM_DEVICE_PATHS:
        _bind(reply, node)
    if _size(TPM_DEVICE_PATHS[0]) != len(payload):
        raise HelperError("fault-not-applied", "TPM reply is not bound")
    return name


def _fault_efi_variable_eio() -> str:
    variable = os.path.join(EFI_SYSFS_DIR, "efivars", "SecureBoot-" + SB_GUID)
    if not os.path.exists(variable):
        raise HelperError(
            "unsupported-platform", "the SecureBoot EFI variable does not exist"
        )
    _bind(_snapd_memory(), variable)
    if _size(variable) != 0:
        raise HelperError("fault-not-applied", "EFI variable still reports a size")
    return "efi-variable-eio"


def _fault_break_secureboot_variable() -> str:
    variable = os.path.join(EFI_SYSFS_DIR, "efivars", "SecureBoot-" + SB_GUID)
    broken = _staging("SecureBoot.broken")
    with open(broken, "wb") as handle:
        handle.write(b"\0\0\0\0")
    if os.path.exists(variable):
        _bind(broken, variable)
        if _size(variable) != 4:
            raise HelperError("fault-not-applied", "SecureBoot variable is unchanged")
        return "secureboot-variable-broken"

    # Without the variable the firmware is not in deployed mode, so overlay
    # efivars with a copy of itself plus one malformed entry.
    overlay = _staging("efivars")
    os.makedirs(overlay, mode=0o700, exist_ok=True)
    with contextlib.suppress(OSError):
        shutil.copytree(
            os.path.join(EFI_SYSFS_DIR, "efivars"), overlay, dirs_exist_ok=True
        )
    with open(os.path.join(overlay, "SecureBoot-" + SB_GUID), "wb") as handle:
        handle.write(b"\0\0\0\0")
    _bind(overlay, os.path.join(EFI_SYSFS_DIR, "efivars"))
    return "secureboot-variable-missing"


def _fault_block_ppi_request() -> str:
    request = os.path.join(_tpm_dir(), "ppi", "request")
    _ns_run(["mount", "--bind", request, request])
    _ns_run(["mount", "-o", "remount,ro,bind", request])
    options = _ns_run(["findmnt", "-n", "-o", "OPTIONS", request])
    if "ro" not in options.strip().split(","):
        raise HelperError("fault-not-applied", "PPI request is still writable")
    return "ppi-request-read-only"


_FAULT_RECIPES: dict[str, Any] = {
    "disable-endorsement-hierarchy": _fault_disable_endorsement_hierarchy,
    "disable-owner-hierarchy": _fault_disable_owner_hierarchy,
    "dictionary-lockout": _fault_dictionary_lockout,
    "extend-pcr4": _fault_extend_pcr4,
    "mask-sysfs-efi": _fault_hide_efi_sysfs,
    "mask-measurements": _fault_hide_measurements,
    "null-tpm-device": _fault_null_tpm_device,
    "tpm-eio": _fault_tpm_transport_error,
    "tpm-reply-error": lambda: _fault_tpm_reply(0x100, "tpm-reply-error"),
    "tpm-reply-failure": lambda: _fault_tpm_reply(0x101, "tpm-reply-failure"),
    "efivar-eio": _fault_efi_variable_eio,
    "break-secureboot-var": _fault_break_secureboot_variable,
    "block-ppi-request": _fault_block_ppi_request,
}


def operation_check_key(parameters: dict[str, Any]) -> dict[str, Any]:
    key = _recovery_key_bytes(_string(parameters, "key"))
    result: dict[str, Any] = {}
    for name in ("data", "save"):
        device = _string(parameters, name + "_device")
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, never a shell
                [
                    _tool("cryptsetup"),
                    "open",
                    "--test-passphrase",
                    "--batch-mode",
                    "--key-file=-",
                    device,
                    "ugt-test-" + name,
                ],
                input=key,
                capture_output=True,
                timeout=DEFAULT_TIMEOUT,
                check=False,
                env={**os.environ, "LC_ALL": "C"},  # untranslated diagnostics
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as error:
            raise HelperError("missing-tool", "cryptsetup is unavailable") from error
        result[name] = _key_unlocks(device, completed)
    return result


def operation_restart_snapd(_: dict[str, Any]) -> dict[str, Any]:
    _run(["systemctl", "restart", SNAPD_UNIT], timeout=120)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            version = (_snapd("GET", "/v2/system-info", timeout=10) or {}).get(
                "version"
            )
        except HelperError:
            time.sleep(1)
            continue
        return {"restarted": True, "snapd_version": version, "boot_id": _boot_id()}
    raise HelperError("snapd-unreachable", "snapd did not answer after the restart")


def operation_enable_test_mode(_: dict[str, Any]) -> dict[str, Any]:
    """Let real snapd run its checks inside this virtual machine.

    Without snapd's own testing switch, secboot rejects a virtual machine
    before any other check, so a mutated firmware state can never surface.
    The switch permits the virtual machine only; every check still runs
    against the real firmware, TPM and TCG log.
    """
    os.makedirs(os.path.dirname(SNAPD_TESTING_DROPIN), mode=0o755, exist_ok=True)
    with open(SNAPD_TESTING_DROPIN, "w", encoding="utf-8") as handle:
        handle.write("[Service]\nEnvironment=SNAPPY_TESTING=1\n")
    os.chmod(SNAPD_TESTING_DROPIN, 0o644)
    _run(["systemctl", "daemon-reload"], timeout=60)
    result = operation_restart_snapd({})
    environment = _run(
        ["systemctl", "show", "-p", "Environment", "--value", SNAPD_UNIT],
        timeout=60,
    ).strip()
    if "SNAPPY_TESTING=1" not in environment:
        raise HelperError("snapd-not-testing", "snapd did not pick up SNAPPY_TESTING")
    return {**result, "testing": True}


def operation_generate_competing_key(_: dict[str, Any]) -> dict[str, Any]:
    result = _snapd("POST", "/v2/systems", {"action": "generate-recovery-key"})
    key = (result or {}).get("recovery-key")
    if not isinstance(key, str) or not key:
        raise HelperError("snapd-malformed", "snapd returned no recovery key")
    # The key is deliberately discarded: this operation only proves that a
    # competing client consumes the one-shot key slot.
    return {"generated": True}


def operation_enroll_auth(parameters: dict[str, Any]) -> dict[str, Any]:
    """Enroll a real PIN or passphrase through snapd before a fault."""
    auth_mode = _string(parameters, "auth_mode")
    body: dict[str, Any] = {"action": "replace-platform-key", "auth-mode": auth_mode}
    if auth_mode == "pin":
        body["pin"] = _string(parameters, "pin")
    elif auth_mode == "passphrase":
        body["passphrase"] = _string(parameters, "passphrase")
    else:
        raise HelperError("invalid-argument", "auth_mode must be 'pin' or 'passphrase'")

    _, change_id = _snapd_async("POST", "/v2/system-volumes", body)
    change = _wait_change(change_id)
    if change.get("kind") != REPLACE_PLATFORM_KEY_CHANGE:
        raise HelperError(
            "snapd-malformed", f"snapd change {change_id} has an unexpected kind"
        )
    actual = _keyslot_auth_mode(_system_volumes())
    if actual != auth_mode:
        raise HelperError(
            "enrollment-mismatch",
            "snapd reports authentication mode "
            f"{actual!r} after enrolling {auth_mode!r}",
        )
    return {"auth_mode": actual, "change": change_id, "status": "Done"}


def operation_reboot(_: dict[str, Any]) -> dict[str, Any]:
    _run(
        [
            "systemd-run",
            "--on-active=2",
            "--unit=ugt-fde-reboot",
            "/usr/bin/systemctl",
            "reboot",
        ]
    )
    return {"scheduled": "reboot", "boot_id": _boot_id()}


def operation_shutdown(_: dict[str, Any]) -> dict[str, Any]:
    _run(
        [
            "systemd-run",
            "--on-active=2",
            "--unit=ugt-fde-shutdown",
            "/usr/bin/systemctl",
            "poweroff",
        ]
    )
    return {"scheduled": "shutdown", "boot_id": _boot_id()}


def operation_read_saved_key(parameters: dict[str, Any]) -> dict[str, Any]:
    path = _string(parameters, "path")
    home = _string(parameters, "home")
    if not path.startswith(home.rstrip("/") + "/"):
        raise HelperError(
            "invalid-path", "the saved key must be inside the fixture home"
        )
    if os.path.islink(path):
        raise HelperError("invalid-path", "the saved key path must not be a symlink")
    value = _read(path).strip()
    if not RECOVERY_KEY.match(value):
        raise HelperError("invalid-key", "the saved file is not a recovery key")
    return {"key": value}


def operation_assert_auth(parameters: dict[str, Any]) -> dict[str, Any]:
    expected = _string(parameters, "expected")
    actual = _keyslot_auth_mode(_system_volumes())
    return {"auth_mode": actual, "expected": expected, "matches": actual == expected}


def operation_pre_os_measurements(parameters: dict[str, Any]) -> dict[str, Any]:
    """Report the firmware images this boot measured before the OS started.

    snapd's pre-OS checks read this same TCG log, so the reported image paths
    name exactly what real snapd can classify: an injected application that is
    absent here was never launched by the firmware.
    """
    events = _tcg_events(_read_bytes(EVENT_LOG_PATH))
    applications = [
        _measured_image_path(data)
        for _, event_type, data in events
        if event_type == EVENT_TYPE_BOOT_SERVICES_APPLICATION
    ]
    paths = [path for path in applications if path]
    return {
        "applications": paths,
        "events": len(events),
        "authorities": _measured_authorities(
            events, include_payload=bool(parameters.get("authority_payloads"))
        ),
        "secure_boot_db": _signature_database(_efi_variable(SECURE_BOOT_DB_PATH)),
        "secure_boot_config": _secure_boot_config_events(events),
        "boot_option_support": _boot_option_support(),
    }


def _measured_authorities(
    events: list[tuple[int, int, bytes]],
    *,
    include_payload: bool = False,
) -> list[dict[str, Any]]:
    """Name the db signatures this firmware measured to authorise images.

    Each authority event carries a UEFI_VARIABLE_DATA: the verified variable's
    GUID and UTF-16 name, then its data, which is the EFI_SIGNATURE_DATA entry
    the firmware matched -- the owner GUID followed by the certificate or
    digest. Hashing the signature data without the owner lets a test compare it
    with the certificate the fixture enrolled, and the owner names which
    database entry authorised it.
    """
    authorities: list[dict[str, Any]] = []
    for pcr, event_type, data in events:
        if event_type != EVENT_TYPE_VARIABLE_AUTHORITY:
            continue
        if len(data) < 32:
            raise HelperError("malformed-measurements", "authority event is truncated")
        name_units, data_length = struct.unpack_from("<QQ", data, 16)
        name_bytes = name_units * 2
        entry_start = 32 + name_bytes
        if data_length < OWNER_GUID_SIZE or entry_start + data_length > len(data):
            raise HelperError(
                "malformed-measurements", "authority event data is truncated"
            )
        signed = data[entry_start : entry_start + data_length]
        payload = signed[OWNER_GUID_SIZE:]
        entry = {
            "pcr": pcr,
            "variable": data[32 : 32 + name_bytes].decode("utf-16-le"),
            "owner": _guid_text(signed[:OWNER_GUID_SIZE]),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }
        if include_payload:
            entry["payload_hex"] = payload.hex()
        authorities.append(entry)
    return authorities


def _efi_variable(path: str) -> bytes:
    """Read an efivarfs variable, dropping its attribute bitmask."""
    raw = _read_bytes(path)
    if len(raw) < EFI_VARIABLE_ATTRIBUTES_SIZE:
        raise HelperError("malformed-measurements", "EFI variable is truncated")
    return raw[EFI_VARIABLE_ATTRIBUTES_SIZE:]


def _signature_database(raw: bytes) -> list[dict[str, Any]]:
    """Name every EFI_SIGNATURE_DATA entry in a signature database.

    snapd reads this same variable to decide whether a measured authority is
    trusted, so listing it shows what the firmware and the OS agree on.
    """
    entries: list[dict[str, Any]] = []
    offset = 0
    while offset < len(raw):
        header_end = offset + 16 + SIGNATURE_LIST_HEADER.size
        if header_end > len(raw):
            raise HelperError("malformed-measurements", "signature list is truncated")
        list_size, header_size, signature_size = SIGNATURE_LIST_HEADER.unpack_from(
            raw, offset + 16
        )
        end = offset + list_size
        if list_size < 16 + SIGNATURE_LIST_HEADER.size or end > len(raw):
            raise HelperError(
                "malformed-measurements", "signature list size is invalid"
            )
        if signature_size == 0:
            offset = end
            continue
        if signature_size < OWNER_GUID_SIZE:
            raise HelperError(
                "malformed-measurements", "signature data size is invalid"
            )
        type_guid = _guid_text(raw[offset : offset + 16])
        position = header_end + header_size
        while position + signature_size <= end:
            data = raw[position + OWNER_GUID_SIZE : position + signature_size]
            entries.append(
                {
                    "type": type_guid,
                    "owner": _guid_text(raw[position : position + OWNER_GUID_SIZE]),
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
            position += signature_size
        offset = end
    return entries


def _secure_boot_config_events(
    events: list[tuple[int, int, bytes]],
) -> list[dict[str, str]]:
    """Name the secure boot variables this firmware measured into PCR 7."""
    configs: list[dict[str, str]] = []
    for pcr, event_type, data in events:
        if (
            pcr != SECURE_BOOT_POLICY_PCR
            or event_type != EVENT_TYPE_VARIABLE_DRIVER_CONFIG
        ):
            continue
        if len(data) < 32:
            raise HelperError(
                "malformed-measurements", "secure boot config event is truncated"
            )
        name_units, _ = struct.unpack_from("<QQ", data, 16)
        name_bytes = name_units * 2
        if 32 + name_bytes > len(data):
            raise HelperError(
                "malformed-measurements", "secure boot config name is truncated"
            )
        configs.append(
            {
                "name": data[32 : 32 + name_bytes].decode("utf-16-le"),
                "guid": _guid_text(data[:16]),
            }
        )
    return configs


def _guid_text(raw: bytes) -> str:
    """Format a mixed-endian EFI GUID as its canonical text form."""
    first, second, third = struct.unpack_from("<IHH", raw)
    return f"{first:08x}-{second:04x}-{third:04x}-{raw[8:10].hex()}-{raw[10:16].hex()}"


def _boot_option_support() -> dict[str, Any]:
    """Report which optional boot behaviours this firmware declares."""
    raw = _read_bytes(BOOT_OPTION_SUPPORT)
    if len(raw) < 4 + WORD.size:
        raise HelperError("malformed-measurements", "BootOptionSupport is truncated")
    (value,) = WORD.unpack_from(raw, 4)
    return {
        "value": value,
        "sysprep": bool(value & BOOT_OPTION_SUPPORT_SYSPREP),
    }


def _tcg_events(raw: bytes) -> list[tuple[int, int, bytes]]:
    """Parse a TCG event log into (PCR, event type, event data) records.

    The log opens with a TPM 1.2 style record holding the Spec ID event, whose
    digest size table defines every later record, and continues with
    TCG_PCR_EVENT2 records.
    """
    spec_start = EVENT_HEADER.size + SHA1_DIGEST_SIZE + WORD.size
    if len(raw) < spec_start:
        raise HelperError("malformed-measurements", "truncated spec ID event")
    _, event_type = EVENT_HEADER.unpack_from(raw, 0)
    if event_type != SPEC_EVENT_TYPE:
        raise HelperError(
            "malformed-measurements", "the log does not start with a spec ID event"
        )
    (spec_size,) = WORD.unpack_from(raw, EVENT_HEADER.size + SHA1_DIGEST_SIZE)
    spec_end = spec_start + spec_size
    if spec_end > len(raw):
        raise HelperError("malformed-measurements", "truncated spec ID event")
    sizes = _digest_sizes(raw[spec_start:spec_end])

    records: list[tuple[int, int, bytes]] = []
    offset = spec_end
    while offset < len(raw):
        if offset + EVENT_HEADER.size + WORD.size > len(raw):
            raise HelperError("malformed-measurements", "truncated event header")
        pcr, event_type = EVENT_HEADER.unpack_from(raw, offset)
        offset += EVENT_HEADER.size
        (digest_count,) = WORD.unpack_from(raw, offset)
        offset += WORD.size
        for _ in range(digest_count):
            if offset + ALGORITHM.size > len(raw):
                raise HelperError("malformed-measurements", "truncated digest")
            (algorithm,) = ALGORITHM.unpack_from(raw, offset)
            offset += ALGORITHM.size
            size = sizes.get(algorithm)
            if size is None:
                raise HelperError(
                    "malformed-measurements",
                    f"unknown digest algorithm {algorithm:#06x}",
                )
            if offset + size > len(raw):
                raise HelperError("malformed-measurements", "truncated digest")
            offset += size
        if offset + WORD.size > len(raw):
            raise HelperError("malformed-measurements", "truncated event size")
        (data_size,) = WORD.unpack_from(raw, offset)
        offset += WORD.size
        if offset + data_size > len(raw):
            raise HelperError("malformed-measurements", "truncated event data")
        records.append((pcr, event_type, raw[offset : offset + data_size]))
        offset += data_size
    return records


def _digest_sizes(spec: bytes) -> dict[int, int]:
    """Read the algorithm digest size table from a Spec ID Event03 record."""
    if not spec.startswith(SPEC_ID_SIGNATURE):
        raise HelperError(
            "malformed-measurements", "unsupported event log specification"
        )
    if len(spec) < SPEC_ALGORITHM_TABLE:
        raise HelperError("malformed-measurements", "truncated spec ID event")
    (count,) = WORD.unpack_from(spec, SPEC_ALGORITHM_COUNT)
    if len(spec) < SPEC_ALGORITHM_TABLE + 4 * count:
        raise HelperError("malformed-measurements", "truncated digest table")
    sizes: dict[int, int] = {}
    for index in range(count):
        algorithm, size = struct.unpack_from(
            "<HH", spec, SPEC_ALGORITHM_TABLE + 4 * index
        )
        sizes[algorithm] = size
    if not sizes:
        raise HelperError("malformed-measurements", "empty digest table")
    return sizes


def _measured_image_path(data: bytes) -> str:
    """Extract the file path node of a measured UEFI image, or an empty string."""
    if len(data) < IMAGE_LOCATION.size:
        return ""
    _, _, _, path_length = IMAGE_LOCATION.unpack_from(data, 0)
    if path_length > len(data) - IMAGE_LOCATION.size:
        return ""
    path = data[IMAGE_LOCATION.size : IMAGE_LOCATION.size + path_length]
    offset = 0
    while offset + DEVICE_PATH_NODE.size <= len(path):
        node_type, sub_type, node_length = DEVICE_PATH_NODE.unpack_from(path, offset)
        if node_length < DEVICE_PATH_NODE.size or offset + node_length > len(path):
            return ""
        if node_type == DEVICE_PATH_END:
            return ""
        if (node_type, sub_type) == DEVICE_PATH_FILE_NODE:
            text = path[offset + DEVICE_PATH_NODE.size : offset + node_length]
            return text.decode("utf-16-le", "replace").rstrip("\0")
        offset += node_length
    return ""


OPERATIONS = {
    "preflight": operation_preflight,
    "snapshot": operation_snapshot,
    "repair-progress": operation_repair_progress,
    "check": operation_check,
    "fault": operation_fault,
    "check-key": operation_check_key,
    "restart-snapd": operation_restart_snapd,
    "enable-test-mode": operation_enable_test_mode,
    "generate-competing-key": operation_generate_competing_key,
    "enroll-auth": operation_enroll_auth,
    "reboot": operation_reboot,
    "shutdown": operation_shutdown,
    "read-saved-key": operation_read_saved_key,
    "assert-auth": operation_assert_auth,
    "pre-os-measurements": operation_pre_os_measurements,
}


def _string(parameters: dict[str, Any], name: str) -> str:
    value = parameters.get(name)
    if not isinstance(value, str) or not value:
        raise HelperError("invalid-argument", f"parameter {name!r} must be a string")
    return value


def main(argv: list[str]) -> int:
    if os.geteuid() != 0:
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "not-root",
                    "message": "the helper must run as root",
                }
            )
        )
        return 1

    if len(argv) != 3 or argv[1] != "--input":
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "invalid-argument",
                    "message": "usage: fde_guest.py --input <request.json>",
                }
            )
        )
        return 1

    try:
        with open(argv[2], encoding="utf-8") as handle:
            request = json.load(handle)
    except (OSError, json.JSONDecodeError):
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "invalid-argument",
                    "message": "the request could not be read",
                }
            )
        )
        return 1
    finally:
        with contextlib.suppress(OSError):
            os.unlink(argv[2])

    operation = request.get("operation")
    parameters = request.get("parameters") or {}
    handler = OPERATIONS.get(str(operation))
    if handler is None or not isinstance(parameters, dict):
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "unsupported-operation",
                    "message": "the requested operation is not allowlisted",
                }
            )
        )
        return 1

    try:
        result = handler(parameters)
    except HelperError as error:
        print(json.dumps({"ok": False, "code": error.code, "message": error.message}))
        return 1
    except Exception as error:  # noqa: BLE001 - one JSON envelope on stdout
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "internal-error",
                    "message": type(error).__name__,
                }
            )
        )
        return 1

    print(json.dumps({"ok": True, "result": result}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
