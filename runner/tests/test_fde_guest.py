"""Harness tests for the in-guest TPM-FDE helper.

These stub the snapd socket and cryptsetup boundaries and race /proc with
disposable child processes; they are not E2E or VM validation.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import struct
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from typing import Any
from unittest.mock import Mock

import pytest

from ubuntu_gui_testing_runner import fde_guest

# secboot crypt.go test vector and its raw little-endian uint16 bytes.
SECBOOT_KEY = "61665-00531-54469-09783-47273-19035-40077-28287"
SECBOOT_KEY_BYTES = bytes.fromhex("e1f01302c5d43726a9b85b4a8d9c7f6e")
# cryptsetup's C-locale diagnostic for a wrong key, printed with exit status 2.
NO_KEY = "No key available with this passphrase."
# Prints once its exec completes, so /proc shows its final cmdline.
CHILD = "import signal; print(flush=True); signal.pause()"


def _stub_snapd(
    monkeypatch: pytest.MonkeyPatch, responses: dict[str, Any]
) -> list[str]:
    requested: list[str] = []

    def fake(method: str, path: str, body: Any = None, timeout: float = 0) -> Any:
        requested.append(f"{method} {path}")
        return responses[path]

    monkeypatch.setattr(fde_guest, "_snapd", fake)
    return requested


def _forbid_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(command: list[str], timeout: float = 0) -> str:
        raise AssertionError(f"unexpected command {command}")

    monkeypatch.setattr(fde_guest, "_run", forbidden)


@pytest.mark.parametrize("revision", ["123", "x2"])
def test_app_revision_comes_from_snapd_api(
    monkeypatch: pytest.MonkeyPatch, revision: str
) -> None:
    requested = _stub_snapd(
        monkeypatch,
        {"/v2/snaps/desktop-security-center": {"revision": revision}},
    )
    _forbid_cli(monkeypatch)

    assert fde_guest._app_revision("desktop-security-center") == revision
    assert requested == ["GET /v2/snaps/desktop-security-center"]


def _capture_cryptsetup(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: dict[str, tuple[int, str]] | None = None,
) -> list[dict[str, Any]]:
    """Stand in for cryptsetup: per-device exit status and C-locale stderr."""
    calls: list[dict[str, Any]] = []

    def fake_run(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append({"argv": command, "input": kwargs.get("input")})
        status, stderr = (outcomes or {}).get(command[-2], (0, ""))
        environment = kwargs.get("env") or os.environ
        locale = (
            environment.get("LC_ALL")
            or environment.get("LC_MESSAGES")
            or environment.get("LANG")
            or "C"
        )
        if locale not in ("C", "POSIX"):
            # gettext translates diagnostics outside the C locale; a stand-in.
            stderr = stderr.replace(NO_KEY, "Aucune clé disponible.")
        return subprocess.CompletedProcess(command, status, b"", stderr.encode())

    monkeypatch.setattr(fde_guest, "_tool", lambda name: "/usr/sbin/" + name)
    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def _check_key(key: str) -> dict[str, Any]:
    return fde_guest.operation_check_key(
        {"key": key, "data_device": "/dev/fake-data", "save_device": "/dev/fake-save"}
    )


def test_check_key_feeds_raw_recovery_key_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_cryptsetup(monkeypatch)

    assert _check_key(SECBOOT_KEY) == {"data": True, "save": True}

    assert [call["input"] for call in calls] == [SECBOOT_KEY_BYTES] * 2
    for call in calls:
        assert "--test-passphrase" in call["argv"]
        assert "--key-file=-" in call["argv"]
        assert not any(SECBOOT_KEY in argument for argument in call["argv"])


def test_check_key_accepts_group_upper_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_cryptsetup(monkeypatch)

    _check_key("-".join(["65535"] + ["00000"] * 7))

    assert calls[0]["input"] == b"\xff\xff" + b"\x00" * 14


@pytest.mark.parametrize(
    "key",
    [
        "-".join(["65536"] + ["00000"] * 7),
        "-".join(["99999"] * 8),
        "-".join(["00000"] * 7),
        "-".join(["00000"] * 9),
        "-".join(["0000"] + ["00000"] * 7),
        "-".join(["000000"] + ["00000"] * 6),
        "-".join(["0000a"] + ["00000"] * 7),
        "-".join(["００００１"] + ["00000"] * 7),
        "-".join(["00000"] * 8) + "\n",
        " ".join(["00000"] * 8),
    ],
)
def test_check_key_rejects_malformed_keys_without_echoing(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    calls = _capture_cryptsetup(monkeypatch)

    with pytest.raises(fde_guest.HelperError) as raised:
        _check_key(key)

    assert raised.value.code == "invalid-key"
    assert key not in raised.value.message
    assert calls == []


def test_check_key_reports_wrong_key_in_any_caller_locale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGUAGE", "fr")
    monkeypatch.setenv("LC_ALL", "fr_FR.UTF-8")
    _capture_cryptsetup(
        monkeypatch, {"/dev/fake-data": (2, NO_KEY), "/dev/fake-save": (2, NO_KEY)}
    )

    assert _check_key(SECBOOT_KEY) == {"data": False, "save": False}


@pytest.mark.parametrize(
    ("status", "stderr"),
    [
        (1, "Device /dev/fake-data is not a valid LUKS device."),
        (3, "Not enough available memory to open a keyslot."),
        (4, "Device /dev/fake-data does not exist or access denied."),
        (5, "Failed to acquire read lock on device /dev/fake-data."),
        (2, ""),
        (2, "Device /dev/fake-data is not a valid LUKS device."),
        (1, NO_KEY),
        (-9, ""),
    ],
    ids=[
        "not-luks",
        "out-of-memory",
        "wrong-device",
        "busy",
        "permission-without-diagnostic",
        "permission-other-diagnostic",
        "diagnostic-without-status-2",
        "killed",
    ],
)
def test_check_key_fails_closed_on_operational_errors(
    monkeypatch: pytest.MonkeyPatch, status: int, stderr: str
) -> None:
    calls = _capture_cryptsetup(monkeypatch, {"/dev/fake-data": (status, stderr)})

    with pytest.raises(fde_guest.HelperError) as raised:
        _check_key(SECBOOT_KEY)

    assert raised.value.code == "command-failed"
    assert "/dev/fake-data" in raised.value.message
    assert f"status {status}" in raised.value.message
    assert SECBOOT_KEY not in raised.value.message
    assert len(calls) == 1


def test_check_key_fails_closed_when_one_device_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_cryptsetup(
        monkeypatch,
        {
            "/dev/fake-data": (2, NO_KEY),
            "/dev/fake-save": (4, "Device /dev/fake-save is not compatible."),
        },
    )

    with pytest.raises(fde_guest.HelperError) as raised:
        _check_key(SECBOOT_KEY)

    assert "/dev/fake-save" in raised.value.message


def _volumes(*slots: dict[str, Any]) -> dict[str, Any]:
    return {
        "by-container-role": {
            "system-data": {
                "keyslots": {f"slot-{i}": slot for i, slot in enumerate(slots)}
            }
        }
    }


def test_auth_mode_reads_run_plus_recover_platform_slot() -> None:
    volumes = _volumes(
        {"type": "platform", "roles": ["run+recover"], "auth-mode": "pin"},
        {"type": "platform", "roles": ["recover"], "auth-mode": "none"},
        {"type": "recovery"},
    )

    assert fde_guest._keyslot_auth_mode(volumes) == "pin"


def test_auth_mode_ignores_non_run_tokens() -> None:
    volumes = _volumes(
        {"type": "platform", "roles": ["run+recover"], "auth-mode": "pin"},
        {"type": "platform", "roles": ["rerun"], "auth-mode": "passphrase"},
        {"type": "plainkey", "roles": ["run"], "auth-mode": "passphrase"},
    )

    assert fde_guest._keyslot_auth_mode(volumes) == "pin"


def test_keyslot_names_list_every_slot_per_container_role() -> None:
    platform = {"type": "platform", "roles": ["run+recover"], "auth-mode": "none"}
    volumes = {
        "by-container-role": {
            "system-data": {
                "keyslots": {
                    "default-recovery": {"type": "recovery"},
                    "snapd-reprovision-default": platform,
                    "default": platform,
                }
            },
            "system-save": {"keyslots": {"default-fallback": platform}},
        }
    }

    assert fde_guest._keyslot_names(volumes) == {
        "system-data": ["default", "default-recovery", "snapd-reprovision-default"],
        "system-save": ["default-fallback"],
    }


def test_last_change_picks_highest_numeric_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def change(change_id: str, kind: str = "fde-reprovision") -> dict[str, Any]:
        return {
            "id": change_id,
            "kind": kind,
            "status": "Done",
            "ready": True,
            "err": None,
            "summary": "ignored",
        }

    _stub_snapd(
        monkeypatch,
        {
            "/v2/changes?select=all": [
                change("9"),
                change("42", kind="refresh-snap"),
                change("10"),
                change("2"),
            ]
        },
    )

    assert fde_guest._last_change("fde-reprovision") == {
        "id": "10",
        "kind": "fde-reprovision",
        "status": "Done",
        "ready": True,
        "err": None,
        "spawn_time": None,
        "ready_time": None,
    }


def test_last_change_none_without_match(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_snapd(monkeypatch, {"/v2/changes?select=all": []})

    assert fde_guest._last_change("fde-reprovision") is None


def test_change_fields_preserve_authoritative_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_snapd(
        monkeypatch,
        {
            "/v2/changes?select=all": [
                {
                    "id": "12",
                    "kind": "fde-reprovision",
                    "status": "Done",
                    "ready": True,
                    "err": None,
                    "spawn-time": "2026-01-01T00:00:10Z",
                    "ready-time": "2026-01-01T00:00:40Z",
                }
            ]
        },
    )

    assert fde_guest._last_change("fde-reprovision") == {
        "id": "12",
        "kind": "fde-reprovision",
        "status": "Done",
        "ready": True,
        "err": None,
        "spawn_time": "2026-01-01T00:00:10Z",
        "ready_time": "2026-01-01T00:00:40Z",
    }


def test_boot_id_is_canonical_uuid_without_newline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = {"/proc/sys/kernel/random/boot_id": "c864350f-922a-4fd8-897e-d97df0686657\n"}
    monkeypatch.setattr(fde_guest, "_read", proc.__getitem__)

    assert fde_guest._boot_id() == "c864350f-922a-4fd8-897e-d97df0686657"


def test_boot_started_at_comes_from_proc_stat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        fde_guest,
        "_read",
        lambda _path: "cpu  1 2 3\nbtime 1767225600\nprocesses 9\n",
    )

    assert fde_guest._boot_started_at() == 1767225600


def test_boot_started_at_requires_the_btime_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fde_guest, "_read", lambda _path: "cpu  1 2 3\n")

    with pytest.raises(fde_guest.HelperError) as raised:
        fde_guest._boot_started_at()
    assert raised.value.code == "unreadable"


def test_stat_identity_reports_private_regular_file(tmp_path: Any) -> None:
    path = tmp_path / "preinstall"
    path.write_text("result", encoding="utf-8")
    path.chmod(0o600)

    identity = fde_guest._stat_identity(str(path))

    assert identity is not None
    assert identity["regular"] is True
    assert identity["mode"] == 0o600
    assert identity["size"] == 6
    assert identity["inode"] == path.stat().st_ino
    assert identity["mtime_ns"] == path.stat().st_mtime_ns
    assert identity["ctime_ns"] == path.stat().st_ctime_ns


def test_stat_identity_is_absent_without_the_file(tmp_path: Any) -> None:
    assert fde_guest._stat_identity(str(tmp_path / "missing")) is None


def test_stat_identity_reports_a_non_regular_path(tmp_path: Any) -> None:
    identity = fde_guest._stat_identity(str(tmp_path))

    assert identity is not None
    assert identity["regular"] is False


def test_repair_progress_is_passive_and_boot_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = {
        "inode": 9,
        "size": 12,
        "mtime_ns": 20,
        "ctime_ns": 21,
        "mode": 0o600,
        "regular": True,
    }
    monkeypatch.setattr(fde_guest, "_boot_id", lambda: "boot-1")
    monkeypatch.setattr(fde_guest, "_boot_started_at", lambda: 1767225600)
    monkeypatch.setattr(time, "time", lambda: 1767225610.5)
    monkeypatch.setattr(fde_guest, "_stat_identity", lambda _path: identity)
    snapd = Mock(side_effect=AssertionError("repair progress must not query snapd"))
    monkeypatch.setattr(fde_guest, "_snapd", snapd)

    assert fde_guest.operation_repair_progress({}) == {
        "boot_id": "boot-1",
        "boot_started_at": 1767225600,
        "wall_time": 1767225610.5,
        "check_result": identity,
    }
    snapd.assert_not_called()


def _stage_identity(inode: int) -> dict[str, Any]:
    return {
        "inode": inode,
        "size": 12,
        "mtime_ns": inode * 10,
        "ctime_ns": inode * 10 + 1,
        "mode": 0o600,
        "regular": True,
    }


def _fake_clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Advance a fake monotonic clock only when the helper sleeps."""
    now = [100.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(time, "sleep", sleep)
    return sleeps


def test_repair_progress_returns_as_soon_as_the_check_result_is_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before, after = _stage_identity(9), _stage_identity(10)
    identities = iter([before, before, after])
    sleeps = _fake_clock(monkeypatch)
    monkeypatch.setattr(fde_guest, "_boot_id", lambda: "boot-1")
    monkeypatch.setattr(fde_guest, "_boot_started_at", lambda: 1767225600)
    monkeypatch.setattr(fde_guest, "_stat_identity", lambda _path: next(identities))
    snapd = Mock(side_effect=AssertionError("repair progress must not query snapd"))
    monkeypatch.setattr(fde_guest, "_snapd", snapd)

    progress = fde_guest.operation_repair_progress({"changed_from": before, "wait": 5})

    assert progress["check_result"] == after
    assert len(sleeps) == 2
    assert sum(sleeps) < 5
    snapd.assert_not_called()


def test_repair_progress_wait_reports_an_unchanged_file_at_its_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _stage_identity(9)
    sleeps = _fake_clock(monkeypatch)
    monkeypatch.setattr(fde_guest, "_boot_id", lambda: "boot-1")
    monkeypatch.setattr(fde_guest, "_boot_started_at", lambda: 1767225600)
    monkeypatch.setattr(fde_guest, "_stat_identity", lambda _path: dict(before))

    progress = fde_guest.operation_repair_progress({"changed_from": before, "wait": 2})

    assert progress["check_result"] == before
    assert 2 <= sum(sleeps) < 2.1


def test_repair_progress_wait_detects_a_file_appearing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    after = _stage_identity(10)
    identities = iter([None, after])
    _fake_clock(monkeypatch)
    monkeypatch.setattr(fde_guest, "_boot_id", lambda: "boot-1")
    monkeypatch.setattr(fde_guest, "_boot_started_at", lambda: 1767225600)
    monkeypatch.setattr(fde_guest, "_stat_identity", lambda _path: next(identities))

    progress = fde_guest.operation_repair_progress({"changed_from": None, "wait": 5})

    assert progress["check_result"] == after


@pytest.mark.parametrize(
    "parameters",
    [
        {"changed_from": None, "wait": -1},
        {"changed_from": None, "wait": 61},
        {"changed_from": None, "wait": True},
        {"changed_from": None, "wait": "5"},
        {"wait": 5},
        {"changed_from": [9], "wait": 5},
    ],
)
def test_repair_progress_rejects_an_unbounded_or_ambiguous_wait(
    monkeypatch: pytest.MonkeyPatch, parameters: dict[str, Any]
) -> None:
    stat_identity = Mock(side_effect=AssertionError("must validate first"))
    monkeypatch.setattr(fde_guest, "_stat_identity", stat_identity)

    with pytest.raises(fde_guest.HelperError) as raised:
        fde_guest.operation_repair_progress(parameters)

    assert raised.value.code == "invalid-argument"
    stat_identity.assert_not_called()


@contextlib.contextmanager
def _process(argv0: str | bytes) -> Iterator[subprocess.Popen[bytes]]:
    """Run a disposable child whose /proc cmdline starts with argv0."""
    process = subprocess.Popen(  # noqa: S603 - fixed interpreter and code
        [argv0, "-c", CHILD], executable=sys.executable, stdout=subprocess.PIPE
    )
    try:
        assert process.stdout is not None
        process.stdout.readline()
        yield process
    finally:
        _reap(process)


def _reap(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.kill()
    process.wait()
    if process.stdout is not None:
        process.stdout.close()


def _list_only(
    monkeypatch: pytest.MonkeyPatch, *processes: subprocess.Popen[bytes]
) -> None:
    real_listdir = os.listdir

    def listdir(path: Any = ".") -> list[Any]:
        if path == "/proc":
            return [str(process.pid) for process in processes]
        return real_listdir(path)

    monkeypatch.setattr(os, "listdir", listdir)


def _gui_entry(process: subprocess.Popen[bytes]) -> dict[str, Any]:
    return {"pid": process.pid, "uid": os.getuid(), "arguments": ["-c", CHILD]}


def test_gui_processes_skips_process_that_exits_before_stat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _process(fde_guest.GUI_EXECUTABLE) as gui, _process("sleep") as gone:
        _list_only(monkeypatch, gone, gui)
        real_stat = os.stat

        def stat_after_exit(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
            if path == f"/proc/{gone.pid}":
                _reap(gone)
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(os, "stat", stat_after_exit)

        assert fde_guest._gui_processes() == [_gui_entry(gui)]


def test_gui_processes_skips_process_that_exits_during_cmdline_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _process(fde_guest.GUI_EXECUTABLE) as gui, _process("sleep") as gone:
        _list_only(monkeypatch, gone, gui)

        def open_then_exit(path: Any, *args: Any, **kwargs: Any) -> Any:
            handle = open(path, *args, **kwargs)  # noqa: SIM115 - caller closes it
            if path == f"/proc/{gone.pid}/cmdline":
                _reap(gone)
            return handle

        monkeypatch.setattr(fde_guest, "open", open_then_exit, raising=False)

        assert fde_guest._gui_processes() == [_gui_entry(gui)]


def test_gui_processes_tolerates_non_utf8_command_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _process(fde_guest.GUI_EXECUTABLE) as gui, _process(b"\xffsleep") as other:
        _list_only(monkeypatch, other, gui)

        assert fde_guest._gui_processes() == [_gui_entry(gui)]


def test_gui_processes_reports_unexpected_proc_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _process(fde_guest.GUI_EXECUTABLE) as gui:
        _list_only(monkeypatch, gui)
        real_stat = os.stat

        def denied(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
            if path == f"/proc/{gui.pid}":
                raise PermissionError(errno.EACCES, "Permission denied", path)
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(os, "stat", denied)

        with pytest.raises(fde_guest.HelperError) as raised:
            fde_guest._gui_processes()

        assert raised.value.code == "unreadable"


DESKTOP_UID = 1000


def _gui_guard(monkeypatch: pytest.MonkeyPatch, *processes: dict[str, Any]) -> int:
    monkeypatch.setattr(fde_guest, "_run", lambda command, timeout=0: str(DESKTOP_UID))
    monkeypatch.setattr(fde_guest, "_gui_processes", lambda: list(processes))
    return fde_guest._assert_gui_is_a_real_desktop_user("desktop")


def _gui(uid: int, *arguments: str) -> dict[str, Any]:
    return {"pid": 1, "uid": uid, "arguments": list(arguments)}


def test_gui_guard_accepts_the_desktop_users_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _gui_guard(monkeypatch, _gui(DESKTOP_UID)) == DESKTOP_UID


def test_gui_guard_refuses_when_no_application_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(fde_guest.HelperError) as raised:
        _gui_guard(monkeypatch)

    assert raised.value.code == "gui-not-running"


@pytest.mark.parametrize(
    ("uid", "arguments", "code"),
    [
        (0, [], "gui-as-root"),
        (DESKTOP_UID, ["--dry-run"], "gui-not-production"),
        (DESKTOP_UID, ["--fake-service=1"], "gui-not-production"),
        (DESKTOP_UID + 1, [], "gui-wrong-user"),
    ],
)
def test_gui_guard_refuses_what_a_user_would_not_run(
    monkeypatch: pytest.MonkeyPatch, uid: int, arguments: list[str], code: str
) -> None:
    with pytest.raises(fde_guest.HelperError) as raised:
        _gui_guard(monkeypatch, _gui(uid, *arguments))

    assert raised.value.code == code


def test_test_mode_writes_the_switch_and_verifies_snapd_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    dropin = tmp_path / "snapd.service.d" / "zz-ugt-snappy-testing.conf"
    commands: list[list[str]] = []
    environment = "Environment=SNAPPY_TESTING=1"
    show = ["systemctl", "show", "-p", "Environment", "--value", fde_guest.SNAPD_UNIT]

    def fake_run(command: list[str], timeout: float = 0) -> str:
        commands.append(command)
        return environment if command == show else ""

    monkeypatch.setattr(fde_guest, "SNAPD_TESTING_DROPIN", str(dropin))
    monkeypatch.setattr(fde_guest, "_run", fake_run)
    monkeypatch.setattr(
        fde_guest,
        "operation_restart_snapd",
        lambda _: {"restarted": True, "snapd_version": "2.78", "boot_id": "boot"},
    )

    assert fde_guest.operation_enable_test_mode({}) == {
        "restarted": True,
        "snapd_version": "2.78",
        "boot_id": "boot",
        "testing": True,
    }
    assert dropin.read_text() == "[Service]\nEnvironment=SNAPPY_TESTING=1\n"
    assert dropin.stat().st_mode & 0o777 == 0o644
    assert commands == [["systemctl", "daemon-reload"], show]


def test_test_mode_fails_closed_when_snapd_ignores_the_switch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setattr(
        fde_guest, "SNAPD_TESTING_DROPIN", str(tmp_path / "snapd.service.d" / "zz.conf")
    )
    monkeypatch.setattr(fde_guest, "_run", lambda command, timeout=0: "")
    monkeypatch.setattr(fde_guest, "operation_restart_snapd", lambda _: {})

    with pytest.raises(fde_guest.HelperError) as raised:
        fde_guest.operation_enable_test_mode({})

    assert raised.value.code == "snapd-not-testing"
    assert "SNAPPY_TESTING" in raised.value.message


def _spec_event(*banks: tuple[int, int]) -> bytes:
    """A leading TPM 1.2 record carrying the Spec ID Event03 structure."""
    table = b"".join(struct.pack("<HH", algorithm, size) for algorithm, size in banks)
    spec = (
        b"Spec ID Event03\0"
        + struct.pack("<I", 0)
        + bytes((0, 2, 0, 2))
        + struct.pack("<I", len(banks))
        + table
    )
    return (
        struct.pack("<II", 0, 0x03) + b"\x00" * 20 + struct.pack("<I", len(spec)) + spec
    )


def _event2(
    pcr: int,
    event_type: int,
    data: bytes,
    algorithm: int = 0x0B,
    digest_size: int = 32,
) -> bytes:
    return (
        struct.pack("<II", pcr, event_type)
        + struct.pack("<I", 1)
        + struct.pack("<H", algorithm)
        + b"\x5a" * digest_size
        + struct.pack("<I", len(data))
        + data
    )


def _file_path_node(path: str) -> bytes:
    encoded = (path + "\0").encode("utf-16-le")
    return struct.pack("<BBH", 4, 4, 4 + len(encoded)) + encoded


def _hard_drive_node() -> bytes:
    return struct.pack("<BBHIQQ16sBB", 4, 1, 42, 1, 0, 0, b"\x00" * 16, 2, 2)


def _image_event(path: str) -> bytes:
    """A measured UEFI image: hard-drive node, file-path node, end node."""
    device_path = _hard_drive_node() + _file_path_node(path) + bytes((0x7F, 0xFF, 4, 0))
    return struct.pack("<QQQQ", 0, 0, 0, len(device_path)) + device_path


def test_tcg_events_read_pcr_type_and_data() -> None:
    raw = _spec_event((0x0B, 32)) + _event2(4, 0x80000003, b"image")
    raw += _event2(7, 0x0D, b"")

    assert fde_guest._tcg_events(raw) == [(4, 0x80000003, b"image"), (7, 0x0D, b"")]


def test_measured_image_path_reads_the_media_file_path_node() -> None:
    path = "\\EFI\\sysprep\\sysprep.efi"

    assert fde_guest._measured_image_path(_image_event(path)) == path


def test_measured_image_path_ignores_a_device_path_without_a_file_node() -> None:
    device_path = _hard_drive_node() + bytes((0x7F, 0xFF, 4, 0))
    data = struct.pack("<QQQQ", 0, 0, 0, len(device_path)) + device_path

    assert fde_guest._measured_image_path(data) == ""


def _variable_config_event(name: str) -> bytes:
    """A measured secure boot variable: GUID, two UINTNs, then UTF-16LE name."""
    guid = bytes.fromhex("cbb219d73a3d9645a3bcdad00e67656f")
    encoded = name.encode("utf-16-le")
    return guid + struct.pack("<QQ", len(encoded) // 2, 0) + encoded


def test_pre_os_measurements_lists_only_application_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _spec_event((0x0B, 32))
    raw += _event2(4, 0x80000003, _image_event("\\EFI\\sysprep\\sysprep.efi"))
    raw += _event2(4, 0x80000002, _image_event("\\EFI\\drivers\\driver.efi"))
    raw += _event2(7, 0x80000001, _variable_config_event("db"))
    support = struct.pack("<I", 6) + struct.pack("<I", 0x10)
    database = struct.pack("<I", 6) + _signature_list(
        "a159c0a5e494a74a87b5ab155c2bf072"
    )
    sources = {
        fde_guest.EVENT_LOG_PATH: raw,
        fde_guest.BOOT_OPTION_SUPPORT: support,
        fde_guest.SECURE_BOOT_DB_PATH: database,
    }
    monkeypatch.setattr(fde_guest, "_read_bytes", sources.__getitem__)

    assert fde_guest.operation_pre_os_measurements({}) == {
        "applications": ["\\EFI\\sysprep\\sysprep.efi"],
        "events": 3,
        "authorities": [],
        "secure_boot_config": [
            {"name": "db", "guid": "d719b2cb-3d3a-4596-a3bc-dad00e67656f"}
        ],
        "secure_boot_db": [],
        "boot_option_support": {"value": 0x10, "sysprep": True},
    }


def _authority_event(payload: bytes) -> bytes:
    """A measured db entry: the verified variable, then owner GUID and cert."""
    name = "db".encode("utf-16-le")
    owner = uuid.UUID("a159c0a5-e494-a74a-87b5-ab155c2bf072").bytes_le
    variable_data = owner + payload
    return (
        bytes.fromhex("cbb219d73a3d9645a3bcdad00e67656f")
        + struct.pack("<QQ", len(name) // 2, len(variable_data))
        + name
        + variable_data
    )


def test_measured_authorities_hash_the_signature_without_its_owner() -> None:
    events = [
        (7, 0x800000E0, _authority_event(b"certificate")),
        (4, 0x80000003, b"ignored"),
    ]

    assert fde_guest._measured_authorities(events) == [
        {
            "pcr": 7,
            "variable": "db",
            "owner": "a159c0a5-e494-a74a-87b5-ab155c2bf072",
            "sha256": hashlib.sha256(b"certificate").hexdigest(),
            "size": 11,
        }
    ]


def test_measured_authorities_include_the_payload_on_request() -> None:
    events = [(7, 0x800000E0, _authority_event(b"cert"))]

    assert fde_guest._measured_authorities(events, include_payload=True) == [
        {
            "pcr": 7,
            "variable": "db",
            "owner": "a159c0a5-e494-a74a-87b5-ab155c2bf072",
            "sha256": hashlib.sha256(b"cert").hexdigest(),
            "size": 4,
            "payload_hex": b"cert".hex(),
        }
    ]


def test_measured_authorities_reject_a_truncated_entry() -> None:
    with pytest.raises(fde_guest.HelperError) as raised:
        fde_guest._measured_authorities([(7, 0x800000E0, b"short")])

    assert raised.value.code == "malformed-measurements"


OWNER = "bd9afa775d036f49bc30c556cee02d0f"


def _signature_list(type_guid: str, *signatures: bytes) -> bytes:
    """One EFI_SIGNATURE_LIST holding the given signatures, each owned."""
    data = b"".join(bytes.fromhex(OWNER) + signature for signature in signatures)
    signature_size = 16 + len(signatures[0]) if signatures else 0
    size = 16 + fde_guest.SIGNATURE_LIST_HEADER.size + len(data)
    return (
        bytes.fromhex(type_guid)
        + fde_guest.SIGNATURE_LIST_HEADER.pack(size, 0, signature_size)
        + data
    )


def test_signature_database_names_each_entry() -> None:
    raw = _signature_list("a159c0a5e494a74a87b5ab155c2bf072", b"first", b"other")

    assert fde_guest._signature_database(raw) == [
        {
            "type": "a5c059a1-94e4-4aa7-87b5-ab155c2bf072",
            "owner": "77fa9abd-035d-496f-bc30-c556cee02d0f",
            "size": 5,
            "sha256": hashlib.sha256(b"first").hexdigest(),
        },
        {
            "type": "a5c059a1-94e4-4aa7-87b5-ab155c2bf072",
            "owner": "77fa9abd-035d-496f-bc30-c556cee02d0f",
            "size": 5,
            "sha256": hashlib.sha256(b"other").hexdigest(),
        },
    ]


def test_signature_database_rejects_a_truncated_list() -> None:
    raw = _signature_list("a159c0a5e494a74a87b5ab155c2bf072", b"certificate")[:-4]

    with pytest.raises(fde_guest.HelperError) as raised:
        fde_guest._signature_database(raw)

    assert raised.value.code == "malformed-measurements"


def test_secure_boot_config_ignores_other_pcrs_and_types() -> None:
    events = [
        (7, 0x80000001, _variable_config_event("db")),
        (4, 0x80000001, _variable_config_event("ignored")),
        (7, 0x80000003, b"ignored"),
    ]

    assert fde_guest._secure_boot_config_events(events) == [
        {"name": "db", "guid": "d719b2cb-3d3a-4596-a3bc-dad00e67656f"}
    ]


def test_secure_boot_config_rejects_a_truncated_name() -> None:
    data = _variable_config_event("db")[:-2]

    with pytest.raises(fde_guest.HelperError) as raised:
        fde_guest._secure_boot_config_events([(7, 0x80000001, data)])

    assert raised.value.code == "malformed-measurements"


def test_tcg_events_use_the_spec_digest_table_for_each_bank() -> None:
    raw = _spec_event((0x0B, 32), (0x0C, 48))
    raw += _event2(4, 0x80000003, b"sha384", algorithm=0x0C, digest_size=48)
    raw += _event2(4, 0x80000003, b"sha256", algorithm=0x0B, digest_size=32)

    assert fde_guest._tcg_events(raw) == [
        (4, 0x80000003, b"sha384"),
        (4, 0x80000003, b"sha256"),
    ]


@pytest.mark.parametrize("cut", [1, 8, 27, 31, 40, 63, 66, 70, 74])
def test_tcg_events_reject_truncated_input(cut: int) -> None:
    raw = _spec_event((0x0B, 32))
    raw += _event2(4, 0x80000003, _image_event("\\EFI\\sysprep\\sysprep.efi"))

    with pytest.raises(fde_guest.HelperError) as raised:
        fde_guest._tcg_events(raw[:cut])

    assert raised.value.code == "malformed-measurements"


def test_tcg_events_require_a_spec_id_event() -> None:
    raw = _event2(4, 0x80000003, b"image")

    with pytest.raises(fde_guest.HelperError) as raised:
        fde_guest._tcg_events(raw)

    assert raised.value.code == "malformed-measurements"


def test_tcg_events_reject_an_algorithm_missing_from_the_spec_table() -> None:
    raw = _spec_event((0x0B, 32))
    raw += _event2(4, 0x0D, b"", algorithm=0x0F, digest_size=32)

    with pytest.raises(fde_guest.HelperError) as raised:
        fde_guest._tcg_events(raw)

    assert raised.value.code == "malformed-measurements"
    assert "0x000f" in raised.value.message


@pytest.mark.parametrize(("value", "sysprep"), [(0x12, True), (0x02, False)])
def test_boot_option_support_reports_the_sysprep_bit(
    monkeypatch: pytest.MonkeyPatch, value: int, sysprep: bool
) -> None:
    raw = struct.pack("<I", 6) + struct.pack("<I", value)
    monkeypatch.setattr(fde_guest, "_read_bytes", lambda path: raw)

    assert fde_guest._boot_option_support() == {"value": value, "sysprep": sysprep}


def _stub_enrollment(
    monkeypatch: pytest.MonkeyPatch,
    *,
    change: dict[str, Any],
    auth_mode: str = "pin",
) -> tuple[list[tuple[str, str, dict[str, Any]]], list[str]]:
    posted: list[tuple[str, str, dict[str, Any]]] = []

    def fake_async(
        method: str, path: str, body: dict[str, Any], timeout: float = 0
    ) -> tuple[Any, str]:
        posted.append((method, path, body))
        return None, "7"

    monkeypatch.setattr(fde_guest, "_snapd_async", fake_async)
    requested = _stub_snapd(
        monkeypatch,
        {
            "/v2/changes/7": change,
            "/v2/system-volumes": _volumes(
                {"type": "platform", "roles": ["run+recover"], "auth-mode": auth_mode}
            ),
        },
    )
    return posted, requested


@pytest.mark.parametrize(
    ("mode", "field"), [("pin", "pin"), ("passphrase", "passphrase")]
)
def test_enroll_auth_replaces_the_platform_key_and_waits_for_the_change(
    monkeypatch: pytest.MonkeyPatch, mode: str, field: str
) -> None:
    secret = "1234" if mode == "pin" else "correct horse battery staple"
    posted, requested = _stub_enrollment(
        monkeypatch,
        auth_mode=mode,
        change={
            "id": "7",
            "kind": fde_guest.REPLACE_PLATFORM_KEY_CHANGE,
            "status": "Done",
            "ready": True,
        },
    )

    result = fde_guest.operation_enroll_auth({"auth_mode": mode, field: secret})

    assert posted == [
        (
            "POST",
            "/v2/system-volumes",
            {"action": "replace-platform-key", "auth-mode": mode, field: secret},
        )
    ]
    assert requested == ["GET /v2/changes/7", "GET /v2/system-volumes"]
    assert result == {"auth_mode": mode, "change": "7", "status": "Done"}
    assert secret not in repr(result)


def test_enroll_auth_rejects_an_unsupported_or_missing_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("snapd was called without a valid auth mode")

    monkeypatch.setattr(fde_guest, "_snapd_async", forbidden)

    with pytest.raises(fde_guest.HelperError) as raised:
        fde_guest.operation_enroll_auth({"auth_mode": "none"})

    assert raised.value.code == "invalid-argument"


def test_enroll_auth_rejects_a_missing_secret_without_echoing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("snapd was called without a secret")

    monkeypatch.setattr(fde_guest, "_snapd_async", forbidden)

    with pytest.raises(fde_guest.HelperError) as raised:
        fde_guest.operation_enroll_auth({"auth_mode": "pin"})

    assert raised.value.code == "invalid-argument"
    assert "pin" in raised.value.message


def test_enroll_auth_fails_closed_when_snapd_reports_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_enrollment(
        monkeypatch,
        change={
            "id": "7",
            "kind": fde_guest.REPLACE_PLATFORM_KEY_CHANGE,
            "status": "Error",
            "ready": True,
            "err": "cannot replace platform key",
        },
    )

    with pytest.raises(fde_guest.HelperError) as raised:
        fde_guest.operation_enroll_auth({"auth_mode": "pin", "pin": "1234"})

    assert raised.value.code == "change-failed"
    assert "1234" not in raised.value.message


def test_enroll_auth_rejects_a_change_of_another_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_enrollment(
        monkeypatch,
        change={
            "id": "7",
            "kind": "fde-add-recovery-key",
            "status": "Done",
            "ready": True,
        },
    )

    with pytest.raises(fde_guest.HelperError) as raised:
        fde_guest.operation_enroll_auth({"auth_mode": "pin", "pin": "1234"})

    assert raised.value.code == "snapd-malformed"


def test_enroll_auth_rejects_keyslots_that_keep_the_old_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_enrollment(
        monkeypatch,
        auth_mode="none",
        change={
            "id": "7",
            "kind": fde_guest.REPLACE_PLATFORM_KEY_CHANGE,
            "status": "Done",
            "ready": True,
        },
    )

    with pytest.raises(fde_guest.HelperError) as raised:
        fde_guest.operation_enroll_auth({"auth_mode": "pin", "pin": "1234"})

    assert raised.value.code == "enrollment-mismatch"
    assert "1234" not in raised.value.message


def test_wait_change_has_a_fixed_deadline() -> None:
    with pytest.raises(fde_guest.HelperError) as raised:
        fde_guest._wait_change("7", timeout=0)

    assert raised.value.code == "timeout"


def test_running_executable_resolves_what_the_process_runs() -> None:
    path, digest = fde_guest._running_executable(os.getpid())

    assert path == os.path.realpath(sys.executable)
    assert digest == fde_guest._file_sha256(path)


def test_running_executable_rejects_a_missing_process() -> None:
    with pytest.raises(fde_guest.HelperError) as raised:
        fde_guest._running_executable(2**22 + 1)

    assert raised.value.code == "unreadable"


def _stub_check(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, Any]]:
    seen: list[tuple[str, str, Any]] = []
    encryption: dict[str, Any] = {
        "storage-encryption": {"availability-check-errors": []}
    }
    responses: dict[tuple[str, str], Any] = {
        ("GET", "/v2/systems?running=true"): encryption,
        ("POST", "/v2/systems"): encryption,
        ("GET", "/v2/system-info/storage-encrypted"): {"status": "recovery"},
        ("GET", "/v2/changes?select=in-progress"): [],
        ("GET", "/v2/changes?select=all"): [],
    }

    def fake(method: str, path: str, body: Any = None, timeout: float = 0) -> Any:
        seen.append((method, path, body))
        return responses[(method, path)]

    monkeypatch.setattr(fde_guest, "_snapd", fake)
    monkeypatch.setattr(fde_guest, "_boot_id", lambda: "boot-1")
    return seen


def test_check_is_a_plain_get_unless_a_recheck_is_asked_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _stub_check(monkeypatch)

    fde_guest.operation_check({})

    assert ("GET", "/v2/systems?running=true", None) in seen
    assert not [call for call in seen if call[0] == "POST"]


def test_recheck_posts_an_empty_fix_action_so_the_dialog_keeps_its_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _stub_check(monkeypatch)

    fde_guest.operation_check({"recheck": True})

    assert (
        "POST",
        "/v2/systems",
        {"action": "fix-encryption-support", "fix-action": ""},
    ) in seen
    assert ("GET", "/v2/systems?running=true", None) not in seen


def test_recheck_must_be_a_boolean(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_check(monkeypatch)

    with pytest.raises(fde_guest.HelperError) as raised:
        fde_guest.operation_check({"recheck": "yes"})

    assert raised.value.code == "invalid-argument"
