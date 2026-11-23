"""Robot library for real TPM-FDE end-to-end cases.

Every case runs against one disposable clone of a stopped TPM-FDE baseline. This
library performs fixture setup and independent postcondition checks through an
authenticated guest channel, and controls power only for the clone it owns. The
repair itself is always driven through the installed Security Center by the
Robot suite, as the ordinary desktop user.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from robot.api import logger
from robot.libraries.BuiltIn import BuiltIn

from ubuntu_gui_testing_runner import fde_power
from ubuntu_gui_testing_runner.fde import (
    REAL_TPM_RECIPES,
    FdeFixture,
    FdeGuest,
    FdeGuestError,
    FdeGuestTimeout,
)

BOOT_TIMEOUT = 600.0
SHUTDOWN_TIMEOUT = 120.0
POLL_INTERVAL = 5.0
REPAIR_START_TIMEOUT = 300.0
SNAPSHOT_TIMEOUT = 20.0
# One in-guest stage wait; the guest helper refuses waits over 60 s.
STAGE_WAIT = 10.0
OBSERVER_STOP_TIMEOUT = 180.0
COLLECTION_GRACE = 120.0
INTERRUPTION_SETTLE_TIMEOUT = 120.0
CHECK_RESULT_MODE = 0o600
# snapd fails a reprovision task rerun after a restart with this error.
LOST_CONTEXT_ERROR = "missing reprovision context"
MARKER_FILE_VARIABLE = "FDE_MARKER_FILE"


class _MarkerWriter:
    """Append host-monotonic test markers for the video editor.

    The capture client records the display with the same monotonic clock, so a
    marker written here identifies the source interval that the editor may
    classify as idle. Markers never contain screen text or credentials.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._wait: str | None = None
        self._sensitive: str | None = None
        self._counter = 0

    def emit(self, event: str, **fields: Any) -> None:
        payload = {
            "event": event,
            "at": time.monotonic(),
            "wall": time.time(),
            **fields,
        }
        try:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload) + "\n")
        except OSError as error:
            raise AssertionError(f"cannot write the capture marker file: {error}")

    def wait_start(self, reason: str) -> None:
        if self._wait is not None:
            raise AssertionError("a wait is already open; close it before opening one")
        self._counter += 1
        self._wait = f"w{self._counter}"
        self.emit("wait-start", **{"wait-id": self._wait, "reason": reason})

    def wait_end(self) -> None:
        if self._wait is None:
            raise AssertionError("no wait is open")
        self.emit("wait-end", **{"wait-id": self._wait})
        self._wait = None

    def close_open_wait(self) -> None:
        if self._wait is not None:
            self.wait_end()

    def sensitive_start(self, reason: str) -> None:
        if self._sensitive is not None:
            raise AssertionError(
                "a sensitive interval is already open; close it before opening one"
            )
        self._counter += 1
        self._sensitive = f"s{self._counter}"
        self.emit(
            "sensitive-start",
            **{"sensitive-id": self._sensitive, "reason": reason},
        )

    def sensitive_end(self) -> None:
        if self._sensitive is None:
            raise AssertionError("no sensitive interval is open")
        self.emit("sensitive-end", **{"sensitive-id": self._sensitive})
        self._sensitive = None

    def close_open_sensitive(self) -> None:
        if self._sensitive is not None:
            self.sensitive_end()


def _finished_before_cut_message(change: dict[str, Any]) -> str:
    return (
        "the fde-reprovision change finished before the power cut could be "
        f"observed (id {change.get('id')}, status {change.get('status')!r}); "
        "it cannot be counted as an interrupted repair"
    )


class _PowerCutObserver:
    """Cut host power as soon as the reprovision handler's stage signal lands.

    The handler holds snapd's global state lock from its first keyslot work
    until it marks the change Done, so no /v2 query can answer inside the
    window a cut must hit. On an installed system only that handler replaces
    the private check-result file, after it has renamed the old keyslots and
    added the new recovery key and immediately before TPM sealing, so a
    replacement proves the handler is mid-repair. The observer waits for it
    inside the guest and powers the clone off as soon as it is reported,
    without first asking snapd anything; the post-reboot oracles prove what
    the cut interrupted.

    The observer owns a separate FdeGuest transport so the main Robot thread
    can drive the installed Security Center and answer polkit while the
    observation is already running. It never logs: Robot's logger is not
    thread-safe. The collected result is reported on the main thread.
    """

    def __init__(
        self,
        clone: fde_power.ClonePower,
        guest: FdeGuest,
        boot_id: str,
        baseline_signal: dict[str, Any],
        finished: Callable[[dict[str, Any]], dict[str, Any] | None],
        window: float,
    ) -> None:
        self._clone = clone
        self._guest = guest
        self._boot_id = boot_id
        self._baseline_signal = baseline_signal
        self._finished = finished
        self._window = window
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._outcome: str | None = None
        self._evidence: dict[str, Any] | None = None
        self._finished_change: dict[str, Any] | None = None
        self._failure: BaseException | None = None
        self._last_timeout: FdeGuestTimeout | None = None
        self._thread = threading.Thread(
            target=self._run, name="fde-power-cut", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            outcome = self._watch()
        except BaseException as error:
            with self._lock:
                self._failure = error
        else:
            with self._lock:
                self._outcome = outcome
        finally:
            try:
                self._guest.close()
            except BaseException as error:
                with self._lock:
                    if self._failure is None:
                        self._failure = error

    def _watch(self) -> str:
        deadline = time.monotonic() + self._window
        seen = self._baseline_signal.get("check_result")
        while not self._stop.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            progress = self._progress(min(STAGE_WAIT, remaining), seen)
            if progress is None:
                if self._stop.wait(fde_power.POLL_INTERVAL):
                    return "cancelled"
                continue
            if self._stage_reached(progress):
                if self._stop.is_set():
                    return "cancelled"
                self._cut(progress)
                return "cut"
            seen = progress.get("check_result")
        if self._stop.is_set():
            return "cancelled"
        final = self._final_snapshot()
        if final is not None:
            finished = self._finished(final)
            if finished is not None:
                self._finished_change = finished
                return "finished"
        return "missed"

    def _progress(
        self, wait: float, seen: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Wait in the guest until the check-result identity differs from `seen`."""
        try:
            progress = self._guest.request(
                "repair-progress",
                {"wait": wait, "changed_from": seen},
                timeout=wait + SNAPSHOT_TIMEOUT,
            )
        except FdeGuestTimeout as error:
            self._last_timeout = error
            return None
        except FdeGuestError as error:
            raise AssertionError(f"cannot observe the repair stage: {error}") from error
        if not isinstance(progress, dict):
            raise AssertionError("the passive repair observation is not an object")
        boot_id = progress.get("boot_id")
        if not isinstance(boot_id, str) or not boot_id:
            raise AssertionError(
                "the passive repair observation has no boot identifier"
            )
        if boot_id != self._boot_id:
            raise AssertionError(
                "the observed clone boot changed during the repair observation; "
                "the power cut was not attempted"
            )
        check_result = progress.get("check_result")
        if check_result is not None and not isinstance(check_result, dict):
            raise AssertionError(
                "the passive repair observation has a malformed check result"
            )
        return progress

    def _stage_reached(self, progress: dict[str, Any]) -> bool:
        before = self._baseline_signal.get("check_result")
        after = progress.get("check_result")
        if not isinstance(after, dict) or not self._is_private_regular_file(after):
            return False
        if not isinstance(before, dict):
            return True
        return any(
            after.get(field) != before.get(field)
            for field in ("inode", "mtime_ns", "ctime_ns")
        )

    @staticmethod
    def _is_private_regular_file(identity: Any) -> bool:
        if not isinstance(identity, dict):
            return False
        if identity.get("regular") is not True:
            return False
        if identity.get("mode") != CHECK_RESULT_MODE:
            return False
        return all(
            isinstance(identity.get(field), int)
            for field in ("inode", "mtime_ns", "ctime_ns")
        )

    def _final_snapshot(self) -> dict[str, Any] | None:
        try:
            return self._guest.request("snapshot", timeout=SNAPSHOT_TIMEOUT)
        except FdeGuestError:
            return None

    def _cut(self, progress: dict[str, Any]) -> None:
        try:
            state = fde_power.power_off_clone(self._clone)
        except fde_power.FdePowerError as error:
            raise AssertionError(f"refusing the power cut: {error}") from error
        self._evidence = {
            "domain_uuid": self._clone.domain_uuid,
            "source_uuid": self._clone.source_uuid,
            "boot_id": progress.get("boot_id"),
            "signal": {
                "path": "/var/lib/snapd/save/preinstall",
                "baseline": self._baseline_signal.get("check_result"),
                "after": progress.get("check_result"),
                "wall_time": progress.get("wall_time"),
                "boot_started_at": progress.get("boot_started_at"),
            },
            "state": state,
        }

    def result(self, timeout: float | None = None) -> dict[str, Any]:
        """Join the observer and return evidence or fail honestly."""
        wait = self._window + COLLECTION_GRACE if timeout is None else float(timeout)
        if wait <= 0:
            raise AssertionError("the power cut collection timeout must be positive")
        self._thread.join(wait)
        if self._thread.is_alive():
            self._stop.set()
            self._thread.join(OBSERVER_STOP_TIMEOUT)
            raise AssertionError(
                f"the power cut observer did not finish within {wait:g}s; "
                "no cut was confirmed"
            )
        self._guest.close()
        with self._lock:
            failure = self._failure
            outcome = self._outcome
            evidence = self._evidence
            finished = self._finished_change
            last_timeout = self._last_timeout
        if failure is not None:
            if isinstance(failure, AssertionError):
                raise failure
            raise AssertionError(f"power cut observer failed: {failure}") from failure
        if outcome == "cut":
            if evidence is None:
                raise AssertionError(
                    "the power cut observer reported a cut without evidence"
                )
            return evidence
        if outcome == "finished":
            if finished is None:
                raise AssertionError(
                    "the observer reported completion without the finished change"
                )
            raise AssertionError(_finished_before_cut_message(finished))
        if outcome == "missed":
            raise AssertionError(
                "missed the fde-reprovision observation window within "
                f"{self._window:g}s; the clone was not powered off"
            ) from last_timeout
        if outcome == "cancelled":
            raise AssertionError(
                "the power cut observer was cancelled before the repair stage was seen"
            )
        raise AssertionError("the power cut observer ended without a result")

    def cancel_and_stop(self) -> None:
        """Cancel a pending observation and release its dedicated channel."""
        self._stop.set()
        self._thread.join(OBSERVER_STOP_TIMEOUT)
        if self._thread.is_alive():
            raise AssertionError(
                f"the power cut observer did not stop within {OBSERVER_STOP_TIMEOUT:g}s"
            )
        self._guest.close()


class TpmFde:
    """Real TPM-FDE fixture operations for Robot Framework suites."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self) -> None:
        self._builtin = BuiltIn()
        self._fixture: FdeFixture | None = None
        self._guest: FdeGuest | None = None
        self._power_observer: _PowerCutObserver | None = None
        self._power_target: fde_power.ClonePower | None = None
        self._saved_recovery_key: str | None = None
        self._markers: _MarkerWriter | None = None

    # --------------------------------------------------------------- markers

    @property
    def markers(self) -> _MarkerWriter:
        """The marker file the runner supplied for this case, if any."""
        if self._markers is None:
            raw = self._builtin.get_variable_value(
                f"${{{MARKER_FILE_VARIABLE}}}", ""
            )
            if not isinstance(raw, str) or not raw:
                raise AssertionError(
                    "FDE_MARKER_FILE is required to classify recorded waits"
                )
            self._markers = _MarkerWriter(Path(raw))
        return self._markers

    def mark_wait_start(self, reason: str = "wait") -> None:
        """Open one recorded idle interval before a known wait begins."""
        self.markers.wait_start(reason)

    def mark_wait_end(self) -> None:
        """Close the recorded idle interval."""
        self.markers.wait_end()

    def mark_sensitive_start(self, reason: str = "secret") -> None:
        """Open a recorded interval the editor must mask."""
        self.markers.sensitive_start(reason)

    def mark_sensitive_end(self) -> None:
        """Close the masked interval."""
        self.markers.sensitive_end()

    def mark_scenario(self, scenario: str, title: str, outcome: str) -> None:
        """Record a scenario chapter boundary and its outcome."""
        self.markers.emit(
            "scenario", scenario=scenario, title=title, outcome=outcome
        )

    # ------------------------------------------------------------------ fixture

    @property
    def fixture(self) -> FdeFixture:
        if self._fixture is None:
            self._fixture = FdeFixture.load(Path(self._variable("FDE_CONFIG")))
        return self._fixture

    @property
    def guest(self) -> FdeGuest:
        if self._guest is None:
            self._guest = FdeGuest(self.fixture, int(self._variable("CID")))
        return self._guest

    def close_all(self) -> None:
        """Cancel the observer and release every guest command channel."""
        if self._markers is not None:
            self._markers.close_open_wait()
            self._markers.close_open_sensitive()
        observer = self._power_observer
        self._power_observer = None
        try:
            if observer is not None:
                observer.cancel_and_stop()
        finally:
            if self._guest is not None:
                self._guest.close()
                self._guest = None
            self._saved_recovery_key = None

    def _new_observer_guest(self, cid: int) -> FdeGuest:
        """Open a transport that only the background observer uses."""
        return FdeGuest(self.fixture, cid)

    def _observed_cid(self) -> int:
        try:
            cid = int(self._variable("CID").strip())
        except ValueError as error:
            raise AssertionError("CID must be a positive integer") from error
        if cid <= 0:
            raise AssertionError("CID must be a positive integer")
        return cid

    def _observed_vnc_port(self) -> int:
        try:
            port = int(self._variable("FDE_VNC_PORT").strip())
        except ValueError as error:
            raise AssertionError("FDE_VNC_PORT must be a positive integer") from error
        if port <= 0:
            raise AssertionError("FDE_VNC_PORT must be a positive integer")
        return port

    def _variable(self, name: str) -> str:
        value = self._builtin.get_variable_value(f"${{{name}}}")
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"Robot variable {name} is required for an FDE case")
        return value

    def _request(
        self, operation: str, parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            return self.guest.request(operation, parameters)
        except FdeGuestError as error:
            # The helper's code names the real cause, so a platform that cannot
            # host a scenario reads differently from a genuine failure.
            if error.code:
                raise AssertionError(f"{error} [{error.code}]") from error
            raise AssertionError(str(error)) from error

    # ----------------------------------------------------------------- keywords

    def preflight_fde_fixture(self) -> dict[str, Any]:
        """Prove the clone matches the declared fixture before touching state."""
        summary = self._request(
            "preflight",
            {
                "desktop_user": self.fixture.desktop_user,
                "data_device": self.fixture.data_device,
                "save_device": self.fixture.save_device,
            },
        )
        expected = {
            "snapd_version": self.fixture.snapd_version,
            "snapd_executable_sha256": self.fixture.snapd_executable_sha256,
            "security_center_revision": self.fixture.security_center_revision,
        }
        for key, value in expected.items():
            if str(summary.get(key)) != value:
                raise AssertionError(
                    f"{key} is {summary.get(key)!r}, fixture expects {value!r}"
                )
        logger.info(
            f"FDE fixture ready: snapd {summary['snapd_version']} "
            f"running {summary.get('snapd_executable_path')}, "
            f"app {summary['security_center_revision']}, "
            f"boot {summary['boot_id']}, "
            f"storage {(summary['storage'] or {}).get('status')}, "
            f"auth {summary['auth_mode']}"
        )
        return summary

    def desktop_home(self) -> str:
        """Return the home directory of the fixture's desktop user."""
        return f"/home/{self.fixture.desktop_user}"

    def desktop_user(self) -> str:
        """Return the fixture's desktop login name."""
        return self.fixture.desktop_user

    def record_baseline(self) -> dict[str, Any]:
        """Record the real boot and encryption state without running a check."""
        return self._request("snapshot")

    def assert_repair_was_cancelled(self, baseline: dict[str, Any]) -> dict[str, Any]:
        """Prove cancellation preserved the boot, authentication and repair history."""
        snapshot = self._request("snapshot")
        for field in ("boot_id", "auth_mode", "last_reprovision"):
            if field not in baseline or field not in snapshot:
                raise AssertionError(f"cannot verify cancellation without {field}")
            if snapshot[field] != baseline[field]:
                raise AssertionError(f"repair cancellation changed {field}")
        if "changes" not in snapshot:
            raise AssertionError("cannot verify cancellation without pending changes")
        if any(entry.get("kind") == "fde-reprovision" for entry in snapshot["changes"]):
            raise AssertionError("an fde-reprovision change is still in progress")
        return snapshot

    def assert_actual_repair_preconditions(
        self,
        expected_status: str,
        expected_issue: str = "",
        expected_support: str = "",
        expected_result: str = "",
        expected_features: str = "",
        expected_requirements: str = "",
        recheck: bool = False,
    ) -> dict[str, Any]:
        """Assert what the real snapd check reports for this mutated clone.

        `expected_result` accepts several values separated by a comma. A mutated
        boot chain either leaves snapd declining the repair outright or lets
        its post-install check reject the chain, which snapd records as
        `failed-encryption-support`; both still require the manual repair the
        case exercises, and the caller asserts that recommendation.

        `expected_issue` matches the availability errors snapd reports. A plain
        check on a production snapd reports `running-in-vm` and nothing else,
        because secboot rejects a virtual machine before it reaches any other
        check. The later issues appear once the user has proceeded past that
        warning in the dialog; read them with `recheck`, because a plain check
        starts a new context and the user's proceed is lost.
        """
        check = self._request("check", {"recheck": True} if recheck else None)
        storage = check.get("storage") or {}
        encryption = (check.get("systems") or {}).get("storage-encryption") or {}

        actual_status = str(storage.get("status"))
        if actual_status != expected_status:
            raise AssertionError(
                f"snapd reports status {actual_status!r}, expected {expected_status!r}"
            )

        if expected_result:
            actual_result = str(storage.get("auto-repair-result"))
            accepted = [value.strip() for value in expected_result.split(",")]
            if actual_result not in accepted:
                raise AssertionError(
                    "snapd reports auto-repair result "
                    f"{actual_result!r}, expected one of {accepted}"
                )

        if expected_support:
            actual_support = str(encryption.get("support"))
            if actual_support != expected_support:
                raise AssertionError(
                    "snapd reports encryption support "
                    f"{actual_support!r}, expected {expected_support!r}"
                )

        if expected_features:
            actual_features = [str(item) for item in encryption.get("features") or []]
            for feature in (
                item.strip() for item in expected_features.split(",") if item.strip()
            ):
                if feature not in actual_features:
                    raise AssertionError(
                        f"snapd reports features {actual_features}, "
                        f"expected {feature!r}"
                    )

        if expected_requirements:
            actual_requirements = [
                str(item) for item in encryption.get("requirements") or []
            ]
            if expected_requirements.strip() == "none":
                if actual_requirements:
                    raise AssertionError(
                        f"snapd requires {actual_requirements}, expected none"
                    )
            else:
                for requirement in (
                    item.strip()
                    for item in expected_requirements.split(",")
                    if item.strip()
                ):
                    if requirement not in actual_requirements:
                        raise AssertionError(
                            f"snapd reports requirements {actual_requirements}, "
                            f"expected {requirement!r}"
                        )

        if expected_issue:
            kinds = [
                str(issue.get("kind"))
                for issue in encryption.get("availability-check-errors") or []
            ]
            if expected_issue not in kinds:
                raise AssertionError(
                    f"snapd reports issues {kinds}, expected {expected_issue!r}"
                )

        reported_kinds = [
            issue.get("kind")
            for issue in encryption.get("availability-check-errors") or []
        ]
        logger.info(
            f"Real snapd check: status={actual_status} "
            f"result={storage.get('auto-repair-result')} "
            f"support={encryption.get('support')} issues={reported_kinds}"
        )
        return check

    def assert_repair_is_required(self) -> dict[str, Any]:
        """Assert the real snapd check requires reprovisioning for this clone."""
        check = self._request("check")
        storage = check.get("storage") or {}
        recommendations = storage.get("recommendations") or []
        if "require-reprovision" not in recommendations:
            raise AssertionError(
                "snapd does not require reprovisioning: "
                f"status={storage.get('status')!r} recommendations={recommendations}"
            )
        logger.info(
            f"real snapd requires reprovisioning: status={storage.get('status')}"
            f" result={storage.get('auto-repair-result')}"
        )
        return check

    def enable_snapd_test_mode(self) -> dict[str, Any]:
        """Let real snapd check this virtual machine instead of rejecting it.

        secboot refuses a virtual machine before it reaches any other check, so
        without snapd's own testing switch a mutated boot chain can never
        surface as a check error. The switch permits the virtual machine only;
        every check still runs against the guest's real firmware, TPM and TCG
        log, and every repair still goes through the product.
        """
        result = self._request("enable-test-mode")
        logger.info(
            f"snapd test mode enabled: version={result.get('snapd_version')} "
            f"boot={result.get('boot_id')}"
        )
        return result

    def confirm_snapd_reports_issue(
        self, kind: str, expected_actions: str = "proceed", recheck: bool = False
    ) -> dict[str, Any]:
        """Assert real snapd reports this issue and offers exactly these actions.

        `expected_actions` is comma separated. Use `recheck` once the dialog is
        open: a plain check would drop what the user already proceeded past.
        """
        check = self._request("check", {"recheck": True} if recheck else None)
        encryption = (check.get("systems") or {}).get("storage-encryption") or {}
        errors = encryption.get("availability-check-errors") or []
        matching = [issue for issue in errors if issue.get("kind") == kind]
        if not matching:
            measurements = self._request(
                "pre-os-measurements", {"authority_payloads": True}
            )
            for authority in measurements.get("authorities") or []:
                logger.info(
                    f"authority event owner={authority.get('owner')} "
                    f"size={authority.get('size')} "
                    f"payload={authority.get('payload_hex')}"
                )
            details = [
                f"{issue.get('kind')}: {issue.get('message')}" for issue in errors
            ]
            raise AssertionError(
                f"snapd reports issues {details}, expected {kind!r}; "
                f"firmware measured {measurements.get('applications')} "
                f"after these db signatures {measurements.get('authorities')}; "
                f"the guest db holds {measurements.get('secure_boot_db')}"
            )
        actions = [str(action) for action in matching[0].get("actions") or []]
        expected = [item.strip() for item in expected_actions.split(",") if item.strip()]
        if sorted(actions) != sorted(expected):
            raise AssertionError(
                f"snapd offers {actions} for {kind!r}, expected {expected}"
            )
        logger.info(f"real snapd reports {kind}: actions={actions}")
        return check

    def log_pre_os_measurements(self) -> dict[str, Any]:
        """Record the firmware images this boot measured before the OS."""
        measurements = self._request("pre-os-measurements")
        measured = measurements.get("applications") or []
        authorities = measurements.get("authorities") or []
        support = measurements.get("boot_option_support") or {}
        config = measurements.get("secure_boot_config") or []
        database = measurements.get("secure_boot_db") or []
        logger.info(
            "pre-OS measured images: "
            + (", ".join(measured) or "none")
            + "; db signatures used: "
            + (
                ", ".join(
                    f"{authority.get('owner')} {authority.get('sha256')} "
                    f"({authority.get('size')} bytes)"
                    for authority in authorities
                )
                or "none"
            )
            + "; guest db: "
            + (
                ", ".join(
                    f"{entry.get('owner')} {entry.get('size')} bytes "
                    f"{entry.get('sha256')}"
                    for entry in database
                )
                or "none"
            )
            + f"; PCR7 config: {config}"
            + f"; firmware SysPrep support: {support.get('sysprep')}"
        )
        return measurements

    def apply_real_fde_fault(self, recipe: str) -> dict[str, Any]:
        """Change the clone's TPM state with one of the TPM's own commands."""
        if recipe not in REAL_TPM_RECIPES:
            raise AssertionError(
                f"fault {recipe!r} plants a mount or a canned reply, not a real TPM "
                f"change; allowed: {sorted(REAL_TPM_RECIPES)}"
            )
        try:
            return self._request("fault", {"recipe": recipe})
        except AssertionError as error:
            raise AssertionError(f"fault {recipe!r}: {error}") from error

    def assert_repair_is_not_needed(self) -> dict[str, Any]:
        """Prove a healthy clone shows no reprovisioning requirement."""
        check = self._request("check")
        storage = check.get("storage") or {}
        recommendations = storage.get("recommendations") or []
        if recommendations:
            raise AssertionError(
                f"a healthy clone still recommends action: {recommendations}"
            )
        if str(storage.get("status")) not in {"active"}:
            raise AssertionError(
                f"a healthy clone reports status {storage.get('status')!r}"
            )
        return check

    def assert_reprovision_change(self, baseline: dict[str, Any]) -> dict[str, Any]:
        """Assert snapd finished a real fde-reprovision change without error."""
        snapshot = self._request("snapshot")
        change = snapshot.get("last_reprovision")
        if not change:
            raise AssertionError("snapd recorded no fde-reprovision change")
        previous = baseline.get("last_reprovision") or {}
        if not change.get("id") or change.get("id") == previous.get("id"):
            raise AssertionError("snapd recorded no new fde-reprovision change")
        if str(change.get("kind")) != "fde-reprovision":
            raise AssertionError(f"unexpected change kind {change.get('kind')!r}")
        if (
            str(change.get("status")) != "Done"
            or not change.get("ready")
            or change.get("err")
        ):
            raise AssertionError(
                "fde-reprovision change did not succeed: "
                f"status={change.get('status')!r} ready={change.get('ready')!r} "
                f"err={change.get('err')!r}"
            )
        pending = [
            entry
            for entry in snapshot.get("changes") or []
            if entry.get("kind") == "fde-reprovision"
        ]
        if pending:
            raise AssertionError("an fde-reprovision change is still in progress")
        logger.info(f"snapd completed fde-reprovision change {change['id']}")
        return snapshot

    def assert_reprovision_failed(
        self, baseline: dict[str, Any], reason: str
    ) -> dict[str, Any]:
        """Assert a new fde-reprovision change really failed for `reason`.

        The reason is a non-secret fragment of snapd's error, never a
        credential. A still-running repair change also fails the check.
        """
        if not reason.strip():
            raise AssertionError("a non-empty failure reason is required")
        if "last_reprovision" not in baseline:
            raise AssertionError(
                "cannot verify a new failed change without the baseline history"
            )
        baseline_change = baseline.get("last_reprovision")
        if baseline_change is None:
            previous = None
        elif isinstance(baseline_change, dict) and isinstance(
            baseline_change.get("id"), str
        ):
            previous = baseline_change["id"]
        else:
            raise AssertionError(
                "cannot verify a new failed change from a malformed baseline"
            )

        snapshot = self._request("snapshot")
        change = snapshot.get("last_reprovision")
        if not isinstance(change, dict):
            raise AssertionError("snapd recorded no fde-reprovision change")
        if str(change.get("kind")) != "fde-reprovision":
            raise AssertionError(f"unexpected change kind {change.get('kind')!r}")
        change_id = change.get("id")
        if not isinstance(change_id, str) or not change_id:
            raise AssertionError("snapd recorded no new fde-reprovision change")
        if change_id == previous:
            raise AssertionError("snapd recorded no new fde-reprovision change")
        if not change.get("ready") or str(change.get("status")) != "Error":
            raise AssertionError(
                "the new fde-reprovision change did not fail: "
                f"status={change.get('status')!r} ready={change.get('ready')!r}"
            )
        error = str(change.get("err") or "")
        if reason.lower() not in error.lower():
            raise AssertionError(
                f"snapd reported {error!r}, expected it to contain {reason!r}"
            )
        pending = [
            entry
            for entry in snapshot.get("changes") or []
            if isinstance(entry, dict) and entry.get("kind") == "fde-reprovision"
        ]
        if pending:
            raise AssertionError("an fde-reprovision change is still in progress")
        logger.info(f"snapd failed fde-reprovision change {change_id}: {reason}")
        return snapshot

    def assert_expired_recovery_key_was_rejected(
        self, saved_key_path: str, home: str
    ) -> None:
        """Prove the expired generated key fails and the fixture key still works.

        The keys travel only inside guest requests and are never returned,
        logged, or passed as Robot arguments.
        """
        saved = self._request("read-saved-key", {"path": saved_key_path, "home": home})
        expired_key = saved.get("key")
        if not isinstance(expired_key, str) or not expired_key:
            raise AssertionError("the saved recovery key is unreadable")
        expired = self._request(
            "check-key",
            {
                "key": expired_key,
                "data_device": self.fixture.data_device,
                "save_device": self.fixture.save_device,
            },
        )
        if expired.get("data") or expired.get("save"):
            raise AssertionError(
                "the expired recovery key still unlocks a device: "
                f"data={expired.get('data')} save={expired.get('save')}"
            )

        current = self._request(
            "check-key",
            {
                "key": self.fixture.secret("recovery_key"),
                "data_device": self.fixture.data_device,
                "save_device": self.fixture.save_device,
            },
        )
        if not (current.get("data") and current.get("save")):
            raise AssertionError(
                "the fixture recovery key no longer unlocks both devices: "
                f"data={current.get('data')} save={current.get('save')}"
            )
        logger.info(
            "expired recovery key rejected; fixture recovery key still unlocks "
            "both devices"
        )

    def assert_recovery_credentials(
        self,
        saved_key_path: str,
        home: str,
        expected_auth: str,
    ) -> None:
        """Prove the new key unlocks data and save, and the old key does not."""
        new_key = str(
            self._request("read-saved-key", {"path": saved_key_path, "home": home})[
                "key"
            ]
        )
        new_result = self._request(
            "check-key",
            {
                "key": new_key,
                "data_device": self.fixture.data_device,
                "save_device": self.fixture.save_device,
            },
        )
        if not (new_result.get("data") and new_result.get("save")):
            raise AssertionError(
                "the new recovery key did not unlock both devices: "
                f"data={new_result.get('data')} save={new_result.get('save')}"
            )

        old_result = self._request(
            "check-key",
            {
                "key": self.fixture.secret("recovery_key"),
                "data_device": self.fixture.data_device,
                "save_device": self.fixture.save_device,
            },
        )
        if old_result.get("data") or old_result.get("save"):
            raise AssertionError(
                "the previous recovery key still unlocks a device: "
                f"data={old_result.get('data')} save={old_result.get('save')}"
            )

        auth = self._request("assert-auth", {"expected": expected_auth})
        if not auth.get("matches"):
            raise AssertionError(
                "the enrolled authentication mode is "
                f"{auth.get('auth_mode')!r}, expected {expected_auth!r}"
            )
        logger.info("recovery credentials verified: new key works, old key rejected")

    def assert_fixture_recovery_key_works(self) -> None:
        """Prove the fixture recovery key still unlocks both encrypted devices.

        This is the acceptance check for an unavailable TPM or a cancelled
        repair, where the original key must remain usable. The key stays inside
        the guest request and is never returned or logged.
        """
        result = self._request(
            "check-key",
            {
                "key": self.fixture.secret("recovery_key"),
                "data_device": self.fixture.data_device,
                "save_device": self.fixture.save_device,
            },
        )
        if not (result.get("data") and result.get("save")):
            raise AssertionError(
                "the fixture recovery key no longer unlocks both devices: "
                f"data={result.get('data')} save={result.get('save')}"
            )
        logger.info("fixture recovery key unlocks both encrypted devices")

    def capture_saved_recovery_key(
        self, saved_key_path: str, home: str
    ) -> dict[str, bool]:
        """Hold the UI-saved new recovery key in memory, never in Robot data.

        Capture it before the final confirmation of a repair that will be
        interrupted, so Assert Captured Recovery Key Rejected can prove snapd
        removed the interrupted attempt's key. The key is never returned or
        logged.
        """
        saved = self._request("read-saved-key", {"path": saved_key_path, "home": home})
        key = saved.get("key")
        if not isinstance(key, str) or not key:
            raise AssertionError("the saved recovery key is unreadable")
        self._saved_recovery_key = key
        return {"captured": True}

    def assert_captured_recovery_key_rejected(self) -> None:
        """Prove the captured key of an interrupted repair unlocks no device.

        The interrupted attempt had already added this key before the power
        cut, so its rejection shows snapd removed the attempt's keyslots. This
        uses only the internally captured key and never returns or logs it.
        """
        if self._saved_recovery_key is None:
            raise AssertionError(
                "Capture Saved Recovery Key must run before checking the saved key"
            )
        result = self._request(
            "check-key",
            {
                "key": self._saved_recovery_key,
                "data_device": self.fixture.data_device,
                "save_device": self.fixture.save_device,
            },
        )
        if result.get("data") or result.get("save"):
            raise AssertionError(
                "the interrupted repair's recovery key still unlocks a device: "
                f"data={result.get('data')} save={result.get('save')}"
            )
        logger.info(
            "the interrupted repair's recovery key is rejected by both devices"
        )

    def type_fixture_secret(self, name: str) -> None:
        """Type a fixture secret into the focused field without logging it."""
        value = self.fixture.secret(name)
        hid: Any = self._builtin.get_library_instance("Hid")
        asyncio.run(hid.type_string(value))

    def match_text_without_echo(self, text: str, timeout: float = 1) -> Any:
        """Match text without a timeout echoing the screen, which may show a secret."""
        # Match Text quotes the whole screen in its timeout, so poll Find Text,
        # which returns an empty list and never raises.
        deadline = time.monotonic() + float(timeout)
        while True:
            matches = self._builtin.run_keyword("Find Text", text)
            if matches:
                return matches
            if time.monotonic() >= deadline:
                raise AssertionError(f"text not found on screen: {text}")
            time.sleep(0.2)

    # ------------------------------------------------------------ power control

    def _snapshot_changes(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        changes = snapshot.get("changes")
        if not isinstance(changes, list):
            raise AssertionError("the guest snapshot has no in-progress change list")
        validated: list[dict[str, Any]] = []
        for change in changes:
            if not isinstance(change, dict):
                raise AssertionError("the guest snapshot has a malformed change entry")
            validated.append(change)
        return validated

    @staticmethod
    def _change_id(change: dict[str, Any]) -> str:
        change_id = change.get("id")
        if not isinstance(change_id, str) or not change_id:
            raise AssertionError("an fde-reprovision change has no id")
        return change_id

    def _known_reprovision_ids(self, snapshot: dict[str, Any]) -> frozenset[str]:
        known: set[str] = set()
        for change in self._snapshot_changes(snapshot):
            if change.get("kind") == "fde-reprovision":
                known.add(self._change_id(change))
        last = snapshot.get("last_reprovision")
        if last is not None:
            if not isinstance(last, dict):
                raise AssertionError("the guest snapshot has a malformed last change")
            known.add(self._change_id(last))
        return frozenset(known)

    def _new_finished_reprovision(
        self, snapshot: dict[str, Any], known: frozenset[str]
    ) -> dict[str, Any] | None:
        finished: list[dict[str, Any]] = []
        for change in self._snapshot_changes(snapshot):
            if change.get("kind") != "fde-reprovision":
                continue
            if self._change_id(change) in known:
                continue
            if bool(change.get("ready")) or str(change.get("status")) in {
                "Done",
                "Error",
                "Undone",
            }:
                finished.append(change)
        last = snapshot.get("last_reprovision")
        if isinstance(last, dict):
            if self._change_id(last) not in known:
                finished.append(last)
        elif last is not None:
            raise AssertionError("the guest snapshot has a malformed last change")
        return finished[0] if finished else None

    def _snapshot_reprovision_changes(
        self, snapshot: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        entries = list(self._snapshot_changes(snapshot))
        last = snapshot.get("last_reprovision")
        if last is not None:
            if not isinstance(last, dict):
                raise AssertionError("the guest snapshot has a malformed last change")
            entries.append(last)
        changes: dict[str, dict[str, Any]] = {}
        for change in entries:
            if change.get("kind") != "fde-reprovision":
                continue
            changes[self._change_id(change)] = change
        return changes

    @staticmethod
    def _snapd_epoch(value: Any, field: str) -> float:
        if not isinstance(value, str) or not value:
            raise AssertionError(f"the fde-reprovision change has no {field}")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise AssertionError(
                f"the fde-reprovision change has malformed {field}: {value!r}"
            ) from error
        if parsed.tzinfo is None:
            raise AssertionError(
                f"the fde-reprovision change has no timezone in {field}: {value!r}"
            )
        return parsed.timestamp()

    def arm_power_cut_observer(
        self, timeout: float = REPAIR_START_TIMEOUT
    ) -> dict[str, Any]:
        """Verify the owned clone and baseline the passive repair stage.

        Call after the repair dialog is open and before its final confirmation.
        This refuses a boot that already has an fde-reprovision change, because
        a queued or running repair would make the private-file signal
        ambiguous. The baseline boot and check-result identity are read over a
        dedicated transport, and that transport starts watching immediately.
        Robot confirms the repair in the Security Center while the observer
        runs. The observation window is bounded from this call, so a missed
        window fails without touching the clone. The returned snapshot, with
        its boot and keyslot names, is the baseline for Assert Power Cut
        Interrupted Repair.
        """
        if self._power_observer is not None:
            raise AssertionError("a power cut observer is already armed")
        window = float(timeout)
        if window <= 0:
            raise AssertionError("the power cut observation window must be positive")
        cid = self._observed_cid()
        clone = fde_power.verified_clone(
            self._variable("FDE_DOMAIN_UUID"),
            self._variable("FDE_SOURCE_UUID"),
            self._variable("FDE_CONNECTION_URI"),
            cid,
        )
        snapshot = self._request("snapshot")
        boot_id = snapshot.get("boot_id")
        if not isinstance(boot_id, str) or not boot_id:
            raise AssertionError("the guest snapshot has no boot identifier")
        active = [
            change
            for change in self._snapshot_changes(snapshot)
            if change.get("kind") == "fde-reprovision"
        ]
        if active:
            raise AssertionError(
                "an fde-reprovision change is already in progress; the passive "
                "repair stage would be ambiguous"
            )
        known = self._known_reprovision_ids(snapshot)
        observer_guest = self._new_observer_guest(cid)
        try:
            baseline = observer_guest.request(
                "repair-progress", timeout=SNAPSHOT_TIMEOUT
            )
            if not isinstance(baseline, dict):
                raise AssertionError("the passive repair baseline is not an object")
            observed_boot = baseline.get("boot_id")
            if not isinstance(observed_boot, str) or not observed_boot:
                raise AssertionError(
                    "the passive repair baseline has no boot identifier"
                )
            if observed_boot != boot_id:
                raise AssertionError(
                    "the clone boot changed while arming the power cut observer"
                )
            check_result = baseline.get("check_result")
            if check_result is not None and not isinstance(check_result, dict):
                raise AssertionError(
                    "the passive repair baseline has a malformed check result"
                )
            observer = _PowerCutObserver(
                clone,
                observer_guest,
                boot_id,
                baseline,
                lambda current: self._new_finished_reprovision(current, known),
                window,
            )
        except FdeGuestError as error:
            observer_guest.close()
            raise AssertionError(
                f"cannot baseline the passive repair observation: {error}"
            ) from error
        except BaseException:
            observer_guest.close()
            raise
        self._power_observer = observer
        self._power_target = clone
        logger.info(
            f"power cut observer running for clone {clone.domain_uuid} "
            f"(vsock CID {clone.vsock_cid}); "
            f"known fde-reprovision changes: {sorted(known) or 'none'}"
        )
        return snapshot

    def cut_power_when_repair_starts(
        self, timeout: float | None = None
    ) -> dict[str, Any]:
        """Wait for the armed observer to cut host power and return its evidence.

        The observer has watched the handler's private stage signal since Arm
        Power Cut Observer and powers the clone off as soon as it lands, so a
        fast repair cannot start and finish between the GUI confirmation and
        this keyword. A change that finished first, or a missed window, fails
        without touching the clone. snapd answers no query while the handler
        holds its state lock, so the evidence is the signal alone; Assert Power
        Cut Interrupted Repair proves what the cut interrupted after the reboot.
        """
        observer = self._power_observer
        if observer is None:
            raise AssertionError(
                "Arm Power Cut Observer must run before Cut Power When Repair Starts"
            )
        evidence = observer.result(timeout)
        self._power_observer = None
        self.guest.close()
        logger.info(
            f"power cut clone {evidence['domain_uuid']} after the repair stage "
            f"signal at guest time {evidence['signal']['wall_time']}"
        )
        return evidence

    def assert_power_cut_interrupted_repair(
        self, baseline: dict[str, Any], evidence: dict[str, Any]
    ) -> dict[str, Any]:
        """Prove the cut interrupted the repair and snapd rolled it back.

        Call on the new boot, before retrying the repair. The stage signal
        shows the handler had already renamed the old keyslots and added the
        new recovery key when the power went. snapd runs the interrupted task
        again on its next start, restores the old keyslots, and fails the
        change because its in-memory repair context did not survive. So
        exactly one new fde-reprovision change must exist, spawned before the
        signal and finished in Error on this boot with that lost-context error,
        and the keyslot names must equal the armed baseline. Anything else,
        including a change that completed before the cut, is a failed
        experiment, never proof of interruption.
        """
        if not isinstance(baseline, dict):
            raise AssertionError("the power cut baseline is not an object")
        if not isinstance(evidence, dict):
            raise AssertionError("the power cut evidence is not an object")
        baseline_boot = baseline.get("boot_id")
        if not isinstance(baseline_boot, str) or not baseline_boot:
            raise AssertionError("the power cut baseline has no boot identifier")
        if evidence.get("boot_id") != baseline_boot:
            raise AssertionError(
                "the power cut evidence does not belong to the armed boot"
            )
        baseline_keyslots = baseline.get("keyslots")
        if not isinstance(baseline_keyslots, dict) or not baseline_keyslots:
            raise AssertionError("the power cut baseline has no keyslot names")
        signal = evidence.get("signal")
        if not isinstance(signal, dict):
            raise AssertionError("the power cut evidence has no stage signal")
        signal_wall = signal.get("wall_time")
        if isinstance(signal_wall, bool) or not isinstance(signal_wall, (int, float)):
            raise AssertionError("the stage signal has no wall-clock time")

        snapshot, change = self._settled_interrupted_change(
            baseline_boot, self._known_reprovision_ids(baseline)
        )
        boot_id = snapshot["boot_id"]
        boot_started_at = snapshot.get("boot_started_at")
        if (
            isinstance(boot_started_at, bool)
            or not isinstance(boot_started_at, int)
            or boot_started_at <= 0
        ):
            raise AssertionError("the guest snapshot has no kernel boot timestamp")
        change_id = self._change_id(change)
        spawn_epoch = self._snapd_epoch(change.get("spawn_time"), "spawn-time")
        if spawn_epoch > float(signal_wall) + 1.0:
            raise AssertionError(
                f"fde-reprovision change {change_id} spawned after the observed "
                "stage signal; the cut did not interrupt this repair"
            )
        ready_epoch = self._snapd_epoch(change.get("ready_time"), "ready-time")
        if ready_epoch < boot_started_at:
            raise AssertionError(
                f"fde-reprovision change {change_id} completed before the "
                "power loss; the cut did not interrupt it"
            )
        status = change.get("status")
        if status != "Error":
            raise AssertionError(
                f"fde-reprovision change {change_id} ended {status!r} after the "
                "power cut; an interrupted repair must fail when snapd retries it"
            )
        error = change.get("err")
        if not isinstance(error, str) or LOST_CONTEXT_ERROR not in error:
            raise AssertionError(
                f"fde-reprovision change {change_id} failed for a reason other "
                f"than its lost repair context: {error!r}"
            )
        keyslots = snapshot.get("keyslots")
        if keyslots != baseline_keyslots:
            raise AssertionError(
                "the keyslots after the interrupted repair differ from the armed "
                f"baseline ({keyslots!r} != {baseline_keyslots!r}); snapd did not "
                "restore the old keys"
            )

        result = {
            "change_id": change_id,
            "status": status,
            "spawn_time": change.get("spawn_time"),
            "ready_time": change.get("ready_time"),
            "previous_boot_id": baseline_boot,
            "boot_id": boot_id,
            "boot_started_at": boot_started_at,
            "keyslots": keyslots,
            "interrupted": True,
            "rolled_back": True,
        }
        logger.info(
            f"power cut interrupted fde-reprovision {change_id}; on boot "
            f"{boot_id} snapd failed it ({LOST_CONTEXT_ERROR}) and restored "
            f"keyslots {keyslots}"
        )
        return result

    def _settled_interrupted_change(
        self, previous_boot: str, known: frozenset[str]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Wait until snapd's retry of the interrupted change has finished.

        snapd retries the task shortly after it starts, so the change may still
        be running when the clone first answers.
        """
        deadline = time.monotonic() + INTERRUPTION_SETTLE_TIMEOUT
        while True:
            snapshot = self._request("snapshot")
            boot_id = snapshot.get("boot_id")
            if not isinstance(boot_id, str) or not boot_id:
                raise AssertionError("the guest snapshot has no boot identifier")
            if boot_id == previous_boot:
                raise AssertionError(
                    "the clone is still on the boot that was observed before the "
                    "power cut; the interruption was not exercised"
                )
            new = [
                change
                for change_id, change in self._snapshot_reprovision_changes(
                    snapshot
                ).items()
                if change_id not in known
            ]
            if len(new) != 1:
                raise AssertionError(
                    "expected exactly one new fde-reprovision change after the "
                    f"power cut, found {len(new)}; run this oracle before retrying"
                )
            change = new[0]
            if change.get("ready") is True:
                return snapshot, change
            if time.monotonic() >= deadline:
                raise AssertionError(
                    f"fde-reprovision change {self._change_id(change)} did not "
                    f"finish within {INTERRUPTION_SETTLE_TIMEOUT:g}s on the new "
                    f"boot (status {change.get('status')!r})"
                )
            time.sleep(POLL_INTERVAL)

    def start_clone_after_power_cut(self) -> str:
        """Start the same verified clone again after the host-side cut.

        The clone must come back on the vsock CID and VNC port this case uses,
        so neither the guest channel nor Yarf's input reaches another domain.
        """
        if self._power_target is None:
            raise AssertionError(
                "Arm Power Cut Observer must run before starting the clone again"
            )
        vnc_port = self._observed_vnc_port()
        try:
            state = fde_power.start_clone(self._power_target, vnc_port)
        except fde_power.FdePowerError as error:
            raise AssertionError(f"refusing to start the clone: {error}") from error
        logger.info(
            f"power cut clone {self._power_target.domain_uuid} started: {state}"
        )
        return state

    def wait_for_power_cut_to_stop_the_guest(self) -> None:
        """Prove the cut ended the guest that was answering before it.

        A destroyed clone keeps no vsock listener, so the channel reports a
        transport timeout instead of an answer. Any other guest error is a real
        failure and must not count as proof of the cut. The probe bypasses
        ``_request``, which turns every guest error into an AssertionError.
        """
        deadline = time.monotonic() + SHUTDOWN_TIMEOUT
        while True:
            try:
                self.guest.request("snapshot")
            except FdeGuestTimeout:
                logger.info("the cut guest stopped answering")
                return
            if time.monotonic() >= deadline:
                raise AssertionError(
                    "the guest kept answering after the power cut; the clone "
                    "was not interrupted"
                )
            time.sleep(POLL_INTERVAL)

    def wait_for_guest_after_power_cut(self) -> dict[str, Any]:
        """Wait until the restarted clone answers over its guest channel.

        snapd answers a snapshot probe with a `snapd-error` while its on-boot
        retry is still converting the interrupted keyslots, and the guest is
        unreachable until userspace starts, so both are retried. Trust,
        authentication and malformed-response failures stay permanent and fail
        at once.
        """
        deadline = time.monotonic() + BOOT_TIMEOUT
        last_error: FdeGuestError | None = None
        while time.monotonic() < deadline:
            try:
                return self.guest.request("snapshot")
            except FdeGuestError as error:
                if not self._boot_wait_may_retry(error):
                    raise
                last_error = error
                self.guest.close()
                time.sleep(POLL_INTERVAL)
        raise AssertionError(
            "the restarted clone did not answer over its guest channel: "
            f"{last_error}"
        ) from last_error

    @staticmethod
    def _boot_wait_may_retry(error: FdeGuestError) -> bool:
        """Return whether a boot wait may retry this guest failure."""
        return isinstance(error, FdeGuestTimeout) or error.code == "snapd-error"

    def reboot_clone_for_verification(self) -> None:
        """Reboot after a completed repair to verify TPM unlock without a key."""
        self._request("reboot")
        self.guest.close()
        self._wait_for_shutdown()

    def _wait_for_shutdown(self) -> None:
        """Wait until the clone stops answering, so its shutdown window is over.

        sshd can accept a connection and then refuse the login while the guest
        is going down. Waiting here keeps that window out of the boot wait,
        which must not retry permanent guest errors.
        """
        deadline = time.monotonic() + SHUTDOWN_TIMEOUT
        last_error: FdeGuestError | None = None
        while time.monotonic() < deadline:
            try:
                self.guest.request("snapshot")
            except FdeGuestTimeout:
                return
            except FdeGuestError as error:
                last_error = error
            else:
                self.guest.close()
            time.sleep(POLL_INTERVAL)
        if last_error is not None:
            raise AssertionError(
                "the clone kept answering but refused guest access during shutdown"
            ) from last_error
        raise AssertionError("the clone did not shut down within the deadline")

    def wait_for_new_boot(self, previous_boot_id: str) -> str:
        """Wait until the clone reports a different real boot identifier."""
        deadline = time.monotonic() + BOOT_TIMEOUT
        last_error: FdeGuestTimeout | None = None
        while time.monotonic() < deadline:
            try:
                snapshot = self.guest.request("snapshot")
            except FdeGuestTimeout as error:
                last_error = error
                self.guest.close()
                time.sleep(POLL_INTERVAL)
                continue
            boot_id = snapshot.get("boot_id")
            if not isinstance(boot_id, str) or not boot_id:
                raise AssertionError("the guest snapshot has no boot identifier")
            if boot_id != previous_boot_id:
                logger.info(f"clone booted: {boot_id}")
                return boot_id
            self.guest.close()
            time.sleep(POLL_INTERVAL)
        raise AssertionError(
            "the clone did not boot within the deadline"
        ) from last_error


__all__ = ["TpmFde"]
