from __future__ import annotations

import runpy
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from ubuntu_gui_testing_runner import fde_power
from ubuntu_gui_testing_runner.fde import FdeGuest, FdeGuestError, FdeGuestTimeout

CLONE_UUID = "11111111-2222-3333-4444-555555555555"
SOURCE_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CONNECTION_URI = "qemu:///session"


@pytest.fixture
def keyword_library() -> Any:
    library_path = (
        Path(__file__).resolve().parents[2] / "tests/desktop-security-center/TpmFde.py"
    )
    library = runpy.run_path(str(library_path))["TpmFde"]()
    library._guest = Mock(spec=FdeGuest)
    return library


@pytest.mark.parametrize("change_id,ready", [("41", True), ("42", False)])
def test_repair_requires_a_new_ready_change(
    keyword_library: Any, change_id: str, ready: bool
) -> None:
    keyword_library.guest.request.return_value = {
        "last_reprovision": {
            "id": change_id,
            "kind": "fde-reprovision",
            "status": "Done",
            "ready": ready,
            "err": None,
        },
        "changes": [],
    }
    baseline = {"last_reprovision": {"id": "41"}}

    with pytest.raises(AssertionError):
        keyword_library.assert_reprovision_change(baseline)


def test_repair_accepts_a_new_ready_change(keyword_library: Any) -> None:
    snapshot = {
        "last_reprovision": {
            "id": "42",
            "kind": "fde-reprovision",
            "status": "Done",
            "ready": True,
            "err": None,
        },
        "changes": [],
    }
    keyword_library.guest.request.return_value = snapshot

    assert (
        keyword_library.assert_reprovision_change({"last_reprovision": {"id": "41"}})
        == snapshot
    )


@pytest.fixture
def cancel_baseline() -> dict[str, Any]:
    return {
        "boot_id": "previous-boot",
        "auth_mode": "pin",
        "last_reprovision": {"id": "41", "status": "Done"},
        "changes": [],
    }


@pytest.mark.parametrize(
    "changed",
    [
        {"boot_id": "new-boot"},
        {"auth_mode": "none"},
        {"last_reprovision": {"id": "42", "status": "Done"}},
        {"changes": [{"id": "42", "kind": "fde-reprovision"}]},
    ],
)
def test_cancel_rejects_changed_encryption_state(
    keyword_library: Any, cancel_baseline: dict[str, Any], changed: dict[str, Any]
) -> None:
    keyword_library.guest.request.return_value = cancel_baseline | changed

    with pytest.raises(AssertionError):
        keyword_library.assert_repair_was_cancelled(cancel_baseline)


@pytest.mark.parametrize(
    "missing", ["boot_id", "auth_mode", "last_reprovision", "changes"]
)
def test_cancel_requires_complete_snapshot_evidence(
    keyword_library: Any, cancel_baseline: dict[str, Any], missing: str
) -> None:
    incomplete = cancel_baseline.copy()
    incomplete.pop(missing)
    keyword_library.guest.request.return_value = incomplete

    with pytest.raises(AssertionError):
        keyword_library.assert_repair_was_cancelled(cancel_baseline)


def test_cancel_accepts_unchanged_encryption_state(
    keyword_library: Any, cancel_baseline: dict[str, Any]
) -> None:
    keyword_library.guest.request.return_value = cancel_baseline.copy()

    assert (
        keyword_library.assert_repair_was_cancelled(cancel_baseline) == cancel_baseline
    )


@pytest.mark.parametrize(
    "error",
    [
        FdeGuestError("snapshot", "malformed response", code="snapd-malformed"),
        FdeGuestError("connect", "guest host key does not match the fixture"),
    ],
)
def test_boot_wait_rejects_permanent_guest_errors(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch, error: FdeGuestError
) -> None:
    keyword_library.guest.request.side_effect = error

    def retry_is_a_bug(_: float) -> None:
        pytest.fail("a permanent guest error was retried")

    monkeypatch.setattr(time, "sleep", retry_is_a_bug)
    with pytest.raises(FdeGuestError):
        keyword_library.wait_for_new_boot("previous-boot")


@pytest.mark.parametrize(
    "error",
    [
        FdeGuestTimeout("snapshot", "timed out"),
        FdeGuestError(
            "snapshot",
            "cannot convert volume structure",
            code="snapd-error",
        ),
    ],
)
def test_boot_wait_after_cut_retries_the_retry_window(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch, error: FdeGuestError
) -> None:
    keyword_library.guest.request.side_effect = [error, {"boot_id": "new-boot"}]
    monkeypatch.setattr(time, "sleep", lambda _: None)

    assert keyword_library.wait_for_guest_after_power_cut()["boot_id"] == "new-boot"


@pytest.mark.parametrize(
    "error",
    [
        FdeGuestError("snapshot", "malformed response", code="snapd-malformed"),
        FdeGuestError("connect", "guest host key does not match the fixture"),
    ],
)
def test_boot_wait_after_cut_rejects_permanent_errors(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch, error: FdeGuestError
) -> None:
    keyword_library.guest.request.side_effect = error

    def retry_is_a_bug(_: float) -> None:
        pytest.fail("a permanent guest error was retried")

    monkeypatch.setattr(time, "sleep", retry_is_a_bug)
    with pytest.raises(FdeGuestError):
        keyword_library.wait_for_guest_after_power_cut()


def test_shutdown_wait_returns_once_the_guest_stops_answering(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    keyword_library.guest.request.side_effect = [
        {"boot_id": "old-boot"},
        FdeGuestTimeout("snapshot", "guest is not accepting logins yet"),
    ]
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    keyword_library._wait_for_shutdown()


def test_shutdown_wait_rejects_a_guest_that_keeps_answering(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    keyword_library.guest.request.return_value = {"boot_id": "old-boot"}
    ticks = iter([0.0, 0.0, 1000.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    with pytest.raises(AssertionError):
        keyword_library._wait_for_shutdown()


def test_boot_wait_does_not_accept_missing_identity(keyword_library: Any) -> None:
    keyword_library.guest.request.return_value = {"boot_id": None}

    with pytest.raises(AssertionError):
        keyword_library.wait_for_new_boot("previous-boot")


def test_boot_wait_requires_a_new_identity_after_transient_failure(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    keyword_library.guest.request.side_effect = [
        FdeGuestTimeout("connect", "guest vsock is unreachable"),
        {"boot_id": "previous-boot"},
        {"boot_id": "new-boot"},
    ]
    monkeypatch.setattr(time, "sleep", lambda _: None)

    assert keyword_library.wait_for_new_boot("previous-boot") == "new-boot"


# --------------------------------------------------------- healthy-state oracle


@pytest.mark.parametrize(
    "recommendations",
    [
        ["require-reprovision"],
        ["permit-manual"],
        ["require-platform-reset"],
        ["permit-manual", "require-reprovision"],
    ],
)
def test_healthy_oracle_rejects_any_remaining_recommendation(
    keyword_library: Any, recommendations: list[str]
) -> None:
    keyword_library.guest.request.return_value = {
        "storage": {"status": "active", "recommendations": recommendations}
    }

    with pytest.raises(AssertionError, match="still recommends action"):
        keyword_library.assert_repair_is_not_needed()


def test_healthy_oracle_accepts_an_active_system_without_recommendations(
    keyword_library: Any,
) -> None:
    check = {"storage": {"status": "active", "recommendations": []}}
    keyword_library.guest.request.return_value = check

    assert keyword_library.assert_repair_is_not_needed() == check


def test_healthy_oracle_still_rejects_a_non_active_status(
    keyword_library: Any,
) -> None:
    keyword_library.guest.request.return_value = {
        "storage": {"status": "recovery", "recommendations": []}
    }

    with pytest.raises(AssertionError, match="status"):
        keyword_library.assert_repair_is_not_needed()


# ------------------------------------------------------------- power cut safety


@pytest.fixture(autouse=True)
def _fast_power_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the real observer loop bounded to milliseconds in unit tests."""
    monkeypatch.setattr(fde_power, "POLL_INTERVAL", 0.01)


def _snapshot(
    last_id: str | None = "41",
    changes: list[dict[str, Any]] | None = None,
    boot_id: str = "boot-1",
    boot_started_at: int = 1767225600,
    keyslots: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "boot_id": boot_id,
        "boot_started_at": boot_started_at,
        "wall_time": 1767225700.0,
        "keyslots": {"default": "recovery"} if keyslots is None else keyslots,
        "changes": changes or [],
        "last_reprovision": None
        if last_id is None
        else {
            "id": last_id,
            "kind": "fde-reprovision",
            "status": "Done",
            "ready": True,
            "err": None,
            "spawn_time": "2026-01-01T00:00:00Z",
            "ready_time": "2026-01-01T00:00:30Z",
        },
    }


CHECK_RESULT = {
    "inode": 1,
    "size": 10,
    "mtime_ns": 100,
    "ctime_ns": 100,
    "mode": 0o600,
    "regular": True,
}


def _progress(
    check_result: dict[str, Any] | None = None,
    boot_id: str = "boot-1",
) -> dict[str, Any]:
    return {
        "boot_id": boot_id,
        "boot_started_at": 1767225600,
        "wall_time": 1767225610.0,
        "check_result": CHECK_RESULT if check_result is None else check_result,
    }


def _replaced(inode: int = 2) -> dict[str, Any]:
    return {**CHECK_RESULT, "inode": inode, "mtime_ns": 200, "ctime_ns": 200}


def _reprovision(
    change_id: str, status: str = "Doing", ready: bool = False
) -> dict[str, Any]:
    return {
        "id": change_id,
        "kind": "fde-reprovision",
        "status": status,
        "ready": ready,
        "err": None,
        "spawn_time": "2026-01-01T00:00:05Z",
        "ready_time": None,
    }


def _observer_guest(*responses: Any, default: Any) -> Mock:
    guest = Mock(spec=FdeGuest)
    guest.request.side_effect = _responder(*responses, default=default)
    return guest


def _arm(
    keyword_library: Any,
    monkeypatch: pytest.MonkeyPatch,
    baseline: dict[str, Any],
    observer: Mock | None = None,
    window: float = 5.0,
    cid: str = "3",
    power_off: Mock | None = None,
) -> Mock:
    variables = {
        "FDE_DOMAIN_UUID": CLONE_UUID,
        "FDE_SOURCE_UUID": SOURCE_UUID,
        "FDE_CONNECTION_URI": CONNECTION_URI,
        "CID": cid,
    }
    monkeypatch.setattr(keyword_library, "_variable", lambda name: variables[name])
    monkeypatch.setattr(
        fde_power,
        "verified_clone",
        lambda *_: fde_power.ClonePower(
            CONNECTION_URI, CLONE_UUID, SOURCE_UUID, int(cid)
        ),
    )
    observer_guest = (
        observer
        if observer is not None
        else _observer_guest(_progress(), default=_progress())
    )
    monkeypatch.setattr(
        keyword_library, "_new_observer_guest", lambda _cid: observer_guest
    )
    monkeypatch.setattr(
        fde_power,
        "power_off_clone",
        power_off if power_off is not None else Mock(return_value="shut off"),
    )
    keyword_library.guest.request.return_value = baseline
    keyword_library.arm_power_cut_observer(window)
    return observer_guest


def _responder(*responses: Any, default: Any) -> Any:
    pending = iter(responses)

    def respond(*_args: Any, **_kwargs: Any) -> Any:
        result = next(pending, default)
        if isinstance(result, BaseException):
            raise result
        return result

    return respond


def test_power_cut_requires_an_armed_observer(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    power_off = Mock(return_value="shut off")
    monkeypatch.setattr(fde_power, "power_off_clone", power_off)

    with pytest.raises(AssertionError, match="Arm Power Cut Observer"):
        keyword_library.cut_power_when_repair_starts(5)
    power_off.assert_not_called()


def test_arm_rejects_the_source_domain_before_any_guest_request(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    variables = {
        "FDE_DOMAIN_UUID": SOURCE_UUID,
        "FDE_SOURCE_UUID": SOURCE_UUID,
        "FDE_CONNECTION_URI": CONNECTION_URI,
        "CID": "3",
    }
    monkeypatch.setattr(keyword_library, "_variable", lambda name: variables[name])
    virsh = Mock(side_effect=AssertionError("must not contact libvirt"))
    monkeypatch.setattr(fde_power, "_virsh", virsh)

    with pytest.raises(fde_power.FdePowerError, match="source domain"):
        keyword_library.arm_power_cut_observer()
    virsh.assert_not_called()
    keyword_library.guest.request.assert_not_called()


def test_arm_cannot_overwrite_an_armed_observer(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _arm(keyword_library, monkeypatch, _snapshot())

    with pytest.raises(AssertionError, match="already armed"):
        keyword_library.arm_power_cut_observer()
    keyword_library.close_all()


def test_arm_pins_the_robot_cid_to_the_clone_guard(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    variables = {
        "FDE_DOMAIN_UUID": CLONE_UUID,
        "FDE_SOURCE_UUID": SOURCE_UUID,
        "FDE_CONNECTION_URI": CONNECTION_URI,
        "CID": "7",
    }
    monkeypatch.setattr(keyword_library, "_variable", lambda name: variables[name])
    guarded: list[tuple[str, str, str, int]] = []

    def verified(domain: str, source: str, uri: str, cid: int) -> fde_power.ClonePower:
        guarded.append((domain, source, uri, cid))
        return fde_power.ClonePower(uri, domain, source, cid)

    monkeypatch.setattr(fde_power, "verified_clone", verified)
    observer_cids: list[int] = []
    observer_guest = _observer_guest(default=_snapshot())

    def new_observer(cid: int) -> Mock:
        observer_cids.append(cid)
        return observer_guest

    monkeypatch.setattr(
        keyword_library,
        "_new_observer_guest",
        new_observer,
    )
    keyword_library.guest.request.return_value = _snapshot()

    keyword_library.arm_power_cut_observer(0.05)

    assert guarded == [(CLONE_UUID, SOURCE_UUID, CONNECTION_URI, 7)]
    assert observer_cids == [7]
    assert keyword_library._power_target.vsock_cid == 7
    keyword_library.close_all()


def test_power_cut_lands_on_the_stage_signal_without_asking_snapd(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    observer = _observer_guest(
        _progress(),
        _progress(_replaced()),
        default=_snapshot(),
    )
    power_off = Mock(return_value="shut off")
    _arm(keyword_library, monkeypatch, _snapshot(), observer, power_off=power_off)

    evidence = keyword_library.cut_power_when_repair_starts(5)

    assert evidence["signal"]["baseline"] == CHECK_RESULT
    assert evidence["signal"]["after"] == _replaced()
    assert evidence["signal"]["wall_time"] == 1767225610.0
    assert evidence["domain_uuid"] == CLONE_UUID
    assert evidence["source_uuid"] == SOURCE_UUID
    assert evidence["state"] == "shut off"
    power_off.assert_called_once_with(
        fde_power.ClonePower(CONNECTION_URI, CLONE_UUID, SOURCE_UUID, 3)
    )
    # snapd holds its state lock inside the handler, so the cut is the stage
    # signal alone and no status query is attempted before power goes.
    assert [call.args[0] for call in observer.request.call_args_list] == [
        "repair-progress",
        "repair-progress",
    ]
    observer.close.assert_called()
    # The main transport only read the snapshot baseline; the observer owns
    # the stage polling.
    assert keyword_library.guest.request.call_count == 1
    keyword_library.guest.close.assert_called_once()


def test_arm_observes_before_the_cut_keyword_runs(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = threading.Event()
    observer = Mock(spec=FdeGuest)
    calls = 0

    def respond(operation: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        if operation == "repair-progress":
            calls += 1
            seen.set()
            return _progress() if calls == 1 else _progress(_replaced())
        return _snapshot()

    observer.request.side_effect = respond
    power_off = Mock(return_value="shut off")
    _arm(keyword_library, monkeypatch, _snapshot(), observer, power_off=power_off)

    assert seen.wait(2.0)
    assert keyword_library.guest.request.call_count == 1

    assert keyword_library.cut_power_when_repair_starts(5)["state"] == "shut off"
    power_off.assert_called_once()


def test_observer_never_logs_from_its_worker_thread(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    observer = _observer_guest(
        _progress(),
        _progress(_replaced()),
        default=_snapshot(),
    )
    threads: list[str] = []
    module_logger = Mock()
    module_logger.info.side_effect = lambda *_args, **_kwargs: threads.append(
        threading.current_thread().name
    )
    monkeypatch.setitem(
        keyword_library.arm_power_cut_observer.__func__.__globals__,
        "logger",
        module_logger,
    )

    _arm(keyword_library, monkeypatch, _snapshot(), observer)
    keyword_library.cut_power_when_repair_starts(5)

    assert threads
    assert threads == [threading.main_thread().name] * len(threads)


def test_power_cut_never_claims_a_completed_change_was_interrupted(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    completed = _snapshot(last_id="42")
    observer = _observer_guest(
        _progress(), _progress(), _progress(), completed, default=completed
    )
    power_off = Mock(return_value="shut off")
    _arm(
        keyword_library,
        monkeypatch,
        _snapshot(),
        observer,
        window=0.001,
        power_off=power_off,
    )

    with pytest.raises(AssertionError, match="finished before"):
        keyword_library.cut_power_when_repair_starts(2)
    power_off.assert_not_called()


def test_power_cut_reports_a_missed_window_without_cutting(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = _snapshot(last_id=None)
    observer = _observer_guest(
        _progress(), _progress(), _progress(), empty, default=empty
    )
    power_off = Mock(return_value="shut off")
    _arm(
        keyword_library,
        monkeypatch,
        _snapshot(),
        observer,
        window=0.001,
        power_off=power_off,
    )

    with pytest.raises(AssertionError, match="missed the fde-reprovision"):
        keyword_library.cut_power_when_repair_starts(2)
    power_off.assert_not_called()


def test_power_cut_retries_a_transient_guest_timeout(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    observer = _observer_guest(
        _progress(),
        FdeGuestTimeout("snapshot", "guest is not accepting logins yet"),
        _progress(_replaced()),
        default=_snapshot(),
    )
    power_off = Mock(return_value="shut off")
    _arm(keyword_library, monkeypatch, _snapshot(), observer, power_off=power_off)

    assert keyword_library.cut_power_when_repair_starts(5)["state"] == "shut off"
    power_off.assert_called_once()


def test_power_cut_fails_on_a_permanent_guest_error_without_cutting(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    observer = _observer_guest(
        _progress(),
        default=FdeGuestError("snapshot", "malformed response", code="snapd-malformed"),
    )
    power_off = Mock(return_value="shut off")
    _arm(keyword_library, monkeypatch, _snapshot(), observer, power_off=power_off)

    with pytest.raises(AssertionError, match="cannot observe"):
        keyword_library.cut_power_when_repair_starts(5)
    power_off.assert_not_called()


def test_power_cut_observer_is_consumed_once(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    observer = _observer_guest(
        _progress(),
        _progress(_replaced()),
        default=_snapshot(),
    )
    _arm(keyword_library, monkeypatch, _snapshot(), observer)

    keyword_library.cut_power_when_repair_starts(5)

    with pytest.raises(AssertionError, match="Arm Power Cut Observer"):
        keyword_library.cut_power_when_repair_starts(5)


@pytest.mark.parametrize(
    "after",
    [
        None,
        {**CHECK_RESULT, "regular": False, "inode": 2},
        {**CHECK_RESULT, "mode": 0o644, "inode": 2},
        CHECK_RESULT,
    ],
)
def test_power_cut_refuses_an_unrelated_or_unchanged_stage_signal(
    keyword_library: Any,
    monkeypatch: pytest.MonkeyPatch,
    after: dict[str, Any] | None,
) -> None:
    empty = _snapshot(last_id=None)
    observer = _observer_guest(
        _progress(),
        _progress(after)
        if after is not None
        else {
            **_progress(),
            "check_result": None,
        },
        _progress()
        if after is not None
        else {
            **_progress(),
            "check_result": None,
        },
        empty,
        default=empty,
    )
    power_off = Mock(return_value="shut off")
    _arm(
        keyword_library,
        monkeypatch,
        _snapshot(),
        observer,
        window=0.001,
        power_off=power_off,
    )

    with pytest.raises(AssertionError, match="missed|unrelated"):
        keyword_library.cut_power_when_repair_starts(2)
    power_off.assert_not_called()


def test_power_cut_fails_when_the_observed_boot_changes(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    observer = _observer_guest(
        _progress(),
        _progress(boot_id="boot-2"),
        default=_progress(boot_id="boot-2"),
    )
    power_off = Mock(return_value="shut off")
    _arm(keyword_library, monkeypatch, _snapshot(), observer, power_off=power_off)

    with pytest.raises(AssertionError, match="boot changed"):
        keyword_library.cut_power_when_repair_starts(5)
    power_off.assert_not_called()


def test_arm_rejects_a_boot_with_an_existing_repair_change(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    variables = {
        "FDE_DOMAIN_UUID": CLONE_UUID,
        "FDE_SOURCE_UUID": SOURCE_UUID,
        "FDE_CONNECTION_URI": CONNECTION_URI,
        "CID": "3",
    }
    monkeypatch.setattr(keyword_library, "_variable", lambda name: variables[name])
    monkeypatch.setattr(
        fde_power,
        "verified_clone",
        lambda *_: fde_power.ClonePower(CONNECTION_URI, CLONE_UUID, SOURCE_UUID, 3),
    )
    keyword_library.guest.request.return_value = _snapshot(changes=[_reprovision("42")])

    with pytest.raises(AssertionError, match="already in progress"):
        keyword_library.arm_power_cut_observer()


def test_close_all_cancels_an_observer_before_any_cut(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    observer = _observer_guest(default=_snapshot())
    power_off = Mock(return_value="shut off")
    _arm(
        keyword_library,
        monkeypatch,
        _snapshot(),
        observer,
        window=30,
        power_off=power_off,
    )
    main_guest = keyword_library.guest

    started = time.monotonic()
    keyword_library.close_all()

    assert time.monotonic() - started < 5
    power_off.assert_not_called()
    observer.close.assert_called()
    main_guest.close.assert_called_once()
    assert keyword_library._power_observer is None


# ------------------------------------------------------- failed-repair oracles


def _failed_change(
    change_id: str = "42",
    *,
    kind: str = "fde-reprovision",
    status: str = "Error",
    ready: bool = True,
    err: str = "cannot get recovery key: recovery key has expired",
) -> dict[str, Any]:
    return {
        "id": change_id,
        "kind": kind,
        "status": status,
        "ready": ready,
        "err": err,
    }


def test_failed_reprovision_accepts_a_new_errored_change(
    keyword_library: Any,
) -> None:
    snapshot = {"last_reprovision": _failed_change(), "changes": []}
    keyword_library.guest.request.return_value = snapshot

    assert (
        keyword_library.assert_reprovision_failed(
            {"last_reprovision": {"id": "41"}}, "recovery key has expired"
        )
        == snapshot
    )


@pytest.mark.parametrize(
    ("change", "changes", "message"),
    [
        (_failed_change("41"), [], "no new"),
        ({**_failed_change(), "id": None}, [], "no new"),
        (_failed_change(kind="other-change"), [], "unexpected change kind"),
        (_failed_change(ready=False), [], "did not fail"),
        (_failed_change(status="Done"), [], "did not fail"),
        (_failed_change(err="some other failure"), [], "expected it to contain"),
        (
            _failed_change(),
            [
                {
                    "id": "43",
                    "kind": "fde-reprovision",
                    "status": "Doing",
                    "ready": False,
                    "err": None,
                }
            ],
            "still in progress",
        ),
    ],
)
def test_failed_reprovision_rejects_wrong_evidence(
    keyword_library: Any,
    change: dict[str, Any],
    changes: list[dict[str, Any]],
    message: str,
) -> None:
    keyword_library.guest.request.return_value = {
        "last_reprovision": change,
        "changes": changes,
    }

    with pytest.raises(AssertionError, match=message):
        keyword_library.assert_reprovision_failed(
            {"last_reprovision": {"id": "41"}}, "recovery key has expired"
        )


def test_failed_reprovision_requires_the_baseline_history(
    keyword_library: Any,
) -> None:
    with pytest.raises(AssertionError, match="baseline history"):
        keyword_library.assert_reprovision_failed({}, "recovery key has expired")


def test_failed_reprovision_accepts_the_first_change_of_a_clone(
    keyword_library: Any,
) -> None:
    snapshot = {"last_reprovision": _failed_change(), "changes": []}
    keyword_library.guest.request.return_value = snapshot

    assert (
        keyword_library.assert_reprovision_failed(
            {"last_reprovision": None}, "recovery key has expired"
        )
        == snapshot
    )


@pytest.fixture
def fixture_key(keyword_library: Any) -> Any:
    fixture = Mock()
    fixture.data_device = "/dev/disk/by-partlabel/data"
    fixture.save_device = "/dev/disk/by-partlabel/save"
    fixture.secret.return_value = "fixture-key"
    keyword_library._fixture = fixture
    return fixture


def test_expired_key_is_rejected_while_the_fixture_key_still_works(
    keyword_library: Any, fixture_key: Any
) -> None:
    keyword_library.guest.request.side_effect = [
        {"key": "expired-key"},
        {"data": False, "save": False},
        {"data": True, "save": True},
    ]

    assert (
        keyword_library.assert_expired_recovery_key_was_rejected(
            "/home/ubuntu/recovery-key.txt", "/home/ubuntu"
        )
        is None
    )

    calls = keyword_library.guest.request.call_args_list
    assert calls[0].args == (
        "read-saved-key",
        {"path": "/home/ubuntu/recovery-key.txt", "home": "/home/ubuntu"},
    )
    assert calls[1].args[1]["key"] == "expired-key"
    assert calls[2].args[1]["key"] == "fixture-key"
    assert fixture_key.secret.call_args.args == ("recovery_key",)


@pytest.mark.parametrize(
    ("expired", "current", "message"),
    [
        (
            {"data": True, "save": False},
            {"data": True, "save": True},
            "expired recovery key still unlocks",
        ),
        (
            {"data": False, "save": False},
            {"data": True, "save": False},
            "fixture recovery key no longer unlocks",
        ),
    ],
)
def test_expired_key_oracle_rejects_wrong_key_state(
    keyword_library: Any,
    fixture_key: Any,
    expired: dict[str, bool],
    current: dict[str, bool],
    message: str,
) -> None:
    keyword_library.guest.request.side_effect = [
        {"key": "expired-key"},
        expired,
        current,
    ]

    with pytest.raises(AssertionError, match=message):
        keyword_library.assert_expired_recovery_key_was_rejected(
            "/home/ubuntu/recovery-key.txt", "/home/ubuntu"
        )


def test_expired_key_oracle_rejects_an_unreadable_saved_key(
    keyword_library: Any, fixture_key: Any
) -> None:
    keyword_library.guest.request.return_value = {}

    with pytest.raises(AssertionError, match="unreadable"):
        keyword_library.assert_expired_recovery_key_was_rejected(
            "/home/ubuntu/recovery-key.txt", "/home/ubuntu"
        )


# ------------------------------------------------------- power cut interruption


POWER_BASELINE = {
    "boot_id": "boot-1",
    "changes": [],
    "last_reprovision": {"id": "41", "kind": "fde-reprovision"},
    "keyslots": {"default": "recovery"},
}


def _interruption_evidence() -> dict[str, Any]:
    return {
        "boot_id": "boot-1",
        "signal": {"wall_time": 1767225610.0},
    }


def _after_boot(change: dict[str, Any] | None = None) -> dict[str, Any]:
    return _snapshot(
        boot_id="boot-2",
        boot_started_at=1767225630,
        last_id=None,
        changes=[change or _interrupted_change()],
    )


def _interrupted_change(**overrides: Any) -> dict[str, Any]:
    """The retried change snapd fails when its repair context is gone."""
    return {
        **_reprovision("42", status="Error", ready=True),
        "err": "cannot finish fde-reprovision: missing reprovision context",
        "ready_time": "2026-01-01T00:00:40Z",
        **overrides,
    }


def test_power_cut_oracle_proves_the_repair_was_rolled_back(
    keyword_library: Any,
) -> None:
    keyword_library.guest.request.return_value = _after_boot()

    result = keyword_library.assert_power_cut_interrupted_repair(
        POWER_BASELINE, _interruption_evidence()
    )

    assert result == {
        "change_id": "42",
        "status": "Error",
        "spawn_time": "2026-01-01T00:00:05Z",
        "ready_time": "2026-01-01T00:00:40Z",
        "previous_boot_id": "boot-1",
        "boot_id": "boot-2",
        "boot_started_at": 1767225630,
        "keyslots": {"default": "recovery"},
        "interrupted": True,
        "rolled_back": True,
    }


@pytest.mark.parametrize(
    ("snapshot", "message"),
    [
        (
            _after_boot(_interrupted_change(spawn_time="2026-01-01T00:00:20Z")),
            "spawned after",
        ),
        (
            _after_boot(_interrupted_change(ready_time="2026-01-01T00:00:05Z")),
            "completed before",
        ),
        (
            _after_boot(_interrupted_change(status="Done")),
            "must fail",
        ),
        (
            _after_boot(_interrupted_change(err="cannot get recovery key")),
            "lost repair context",
        ),
        (
            _after_boot(),
            "restore the old keys",
        ),
    ],
)
def test_power_cut_oracle_rejects_wrong_evidence(
    keyword_library: Any,
    snapshot: dict[str, Any],
    message: str,
) -> None:
    if message == "restore the old keys":
        snapshot["keyslots"] = {"default": "recovery", "new": "recovery-new"}
    keyword_library.guest.request.return_value = snapshot

    with pytest.raises(AssertionError, match=message):
        keyword_library.assert_power_cut_interrupted_repair(
            POWER_BASELINE, _interruption_evidence()
        )


@pytest.mark.parametrize(
    "snapshot",
    [
        _snapshot(boot_id="boot-2", last_id="41"),
        _snapshot(
            boot_id="boot-2",
            last_id=None,
            changes=[_interrupted_change(), _interrupted_change(id="43")],
        ),
    ],
)
def test_power_cut_oracle_requires_exactly_one_new_change(
    keyword_library: Any, snapshot: dict[str, Any]
) -> None:
    keyword_library.guest.request.return_value = snapshot

    with pytest.raises(AssertionError, match="exactly one"):
        keyword_library.assert_power_cut_interrupted_repair(
            POWER_BASELINE, _interruption_evidence()
        )


def test_power_cut_oracle_rejects_the_same_boot(keyword_library: Any) -> None:
    keyword_library.guest.request.return_value = _snapshot(last_id=None)

    with pytest.raises(AssertionError, match="still on the boot"):
        keyword_library.assert_power_cut_interrupted_repair(
            POWER_BASELINE, _interruption_evidence()
        )


def test_power_cut_oracle_rejects_mismatched_evidence_boot(
    keyword_library: Any,
) -> None:
    evidence = _interruption_evidence()
    evidence["boot_id"] = "boot-0"

    with pytest.raises(AssertionError, match="does not belong"):
        keyword_library.assert_power_cut_interrupted_repair(POWER_BASELINE, evidence)


def test_power_cut_oracle_requires_authoritative_spawn_time(
    keyword_library: Any,
) -> None:
    keyword_library.guest.request.return_value = _after_boot(
        _interrupted_change(spawn_time=None)
    )

    with pytest.raises(AssertionError, match="spawn-time"):
        keyword_library.assert_power_cut_interrupted_repair(
            POWER_BASELINE, _interruption_evidence()
        )


def test_power_cut_oracle_requires_baseline_keyslots(keyword_library: Any) -> None:
    baseline = {
        key: value for key, value in POWER_BASELINE.items() if key != "keyslots"
    }

    with pytest.raises(AssertionError, match="no keyslot names"):
        keyword_library.assert_power_cut_interrupted_repair(
            baseline, _interruption_evidence()
        )


def test_capture_saved_recovery_key_never_returns_the_secret(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    keyword_library.guest.request.return_value = {"key": "new-secret-key"}

    assert keyword_library.capture_saved_recovery_key("/tmp/key", "/home/ubuntu") == {
        "captured": True
    }
    assert keyword_library._saved_recovery_key == "new-secret-key"
    assert "new-secret-key" not in repr(keyword_library.guest.request.call_args)


def test_capture_saved_recovery_key_rejects_an_empty_read(
    keyword_library: Any,
) -> None:
    keyword_library.guest.request.return_value = {}

    with pytest.raises(AssertionError, match="unreadable"):
        keyword_library.capture_saved_recovery_key("/tmp/key", "/home/ubuntu")


def test_captured_key_rejection_proves_both_devices_reject_it(
    keyword_library: Any, fixture_key: Any
) -> None:
    keyword_library._saved_recovery_key = "pre-cut-key"
    keyword_library.guest.request.return_value = {"data": False, "save": False}

    assert keyword_library.assert_captured_recovery_key_rejected() is None
    parameters = keyword_library.guest.request.call_args.args[1]
    assert parameters["key"] == "pre-cut-key"
    assert parameters["data_device"] == fixture_key.data_device


@pytest.mark.parametrize(
    "answer",
    [{"data": True, "save": False}, {"data": False, "save": True}],
)
def test_captured_key_rejection_fails_when_either_device_opens(
    keyword_library: Any, fixture_key: Any, answer: dict[str, bool]
) -> None:
    keyword_library._saved_recovery_key = "pre-cut-key"
    keyword_library.guest.request.return_value = answer

    with pytest.raises(AssertionError, match="still unlocks"):
        keyword_library.assert_captured_recovery_key_rejected()


def test_captured_key_rejection_requires_capture(keyword_library: Any) -> None:
    with pytest.raises(AssertionError, match="Capture Saved"):
        keyword_library.assert_captured_recovery_key_rejected()


def test_fixture_recovery_key_oracle_accepts_both_devices(
    keyword_library: Any, fixture_key: Any
) -> None:
    keyword_library.guest.request.return_value = {"data": True, "save": True}

    assert keyword_library.assert_fixture_recovery_key_works() is None
    parameters = keyword_library.guest.request.call_args.args[1]
    assert parameters["key"] == "fixture-key"
    assert fixture_key.secret.call_args.args == ("recovery_key",)


@pytest.mark.parametrize(
    "answer",
    [{"data": True, "save": False}, {"data": False, "save": True}],
)
def test_fixture_recovery_key_oracle_requires_both_devices(
    keyword_library: Any, fixture_key: Any, answer: dict[str, bool]
) -> None:
    keyword_library.guest.request.return_value = answer

    with pytest.raises(AssertionError, match="no longer unlocks both"):
        keyword_library.assert_fixture_recovery_key_works()


def test_close_all_clears_the_captured_key(keyword_library: Any) -> None:
    keyword_library._saved_recovery_key = "new-secret-key"

    keyword_library.close_all()

    assert keyword_library._saved_recovery_key is None


# ------------------------------------------------------- guarded clone restart


def test_start_clone_requires_an_armed_target(keyword_library: Any) -> None:
    with pytest.raises(AssertionError, match="Arm Power Cut Observer"):
        keyword_library.start_clone_after_power_cut()


def test_start_clone_refuses_a_malformed_vnc_port_before_libvirt(
    keyword_library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    keyword_library._power_target = fde_power.ClonePower(
        CONNECTION_URI, CLONE_UUID, SOURCE_UUID, 3
    )
    monkeypatch.setattr(keyword_library, "_variable", lambda _name: "5901x")
    start = Mock()
    monkeypatch.setattr(fde_power, "start_clone", start)

    with pytest.raises(AssertionError, match="FDE_VNC_PORT"):
        keyword_library.start_clone_after_power_cut()
    start.assert_not_called()
