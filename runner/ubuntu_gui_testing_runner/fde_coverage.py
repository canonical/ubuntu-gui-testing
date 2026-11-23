"""Strict TPM-FDE coverage inventory and scenario-manifest validation.

A declaration is not a test result. This module keeps two things separate:

* every value the target source can declare, with an explicit disposition;
* the state/context/action edges (cases) the suite is required to execute.

What an individual run actually observed is recorded by the aggregate runner.

A manifest that names an unknown value, leaves a declared value without a
disposition, points one at a case that does not exist, marks a value blocked,
source-inapplicable or api-negative without a reason, or marks one executed
without an evidence entry is rejected. Nothing here executes a test or proves
coverage by itself; it refuses an incomplete or dishonest claim so the
aggregate runner cannot report one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

# The nine declared groups. These are the values the inspected target emits,
# not a wish list: reconcile them against the exact source pin at certification
# time and fail closed on any addition.
INVENTORY: Final[dict[str, tuple[str, ...]]] = {
    "status": (
        "indeterminate",
        "active",
        "inactive",
        "recovery",
        "degraded",
    ),
    "auto-repair-result": (
        "not-initialized",
        "not-attempted",
        "failed-platform-init",
        "failed-keyslots",
        "failed-encryption-support",
        "success",
    ),
    "recommendation": (
        "permit-manual",
        "require-reprovision",
        "require-platform-reset",
    ),
    "kind": (
        "internal-error",
        "shutdown-required",
        "reboot-required",
        "unexpected-action",
        "missing-argument",
        "invalid-argument",
        "action-failed",
        "running-in-vm",
        "system-not-efi",
        "efi-variable-access",
        "no-suitable-tpm2-device",
        "tpm-device-failure",
        "tpm-device-disabled",
        "tpm-hierarchies-owned",
        "tpm-device-lockout-locked-out",
        "insufficient-tpm-storage",
        "no-suitable-pcr-bank",
        "measured-boot",
        "tpm-command-failed",
        "invalid-tpm-response",
        "tpm-communication",
        "unsupported-platform",
        "insufficient-dma-protection",
        "no-kernel-iommu",
        "host-security",
        "tpm-pcr-unusable",
        "addon-drivers-present",
        "sys-prep-applications-present",
        "absolute-present",
        "invalid-secure-boot-mode",
        "weak-secure-boot-algorithms-detected",
        "pre-os-secure-boot-auth-by-enrolled-digests",
        "no-hardware-root-of-trust",
    ),
    "action": (
        "reboot",
        "shutdown",
        "reboot-to-fw-settings",
        "contact-oem",
        "contact-os-vendor",
        "enable-tpm-via-firmware",
        "enable-and-clear-tpm-via-firmware",
        "clear-tpm-via-firmware",
        "clear-tpm-simple",
        "clear-tpm",
        "proceed",
    ),
    "support": (
        "disabled",
        "available",
        "unavailable",
        "defective",
    ),
    "feature": (
        "passphrase-auth",
        "pin-auth",
    ),
    "requirement": ("volumes-auth",),
    "auth-mode": (
        "none",
        "passphrase",
        "pin",
    ),
}

EXECUTION_CLASSES: Final[frozenset[str]] = frozenset(
    {"vm", "physical", "api-negative", "source-inapplicable"}
)

# A case may record that snapd offered no executable action at all. This is a
# manifest sentinel, not a snapd action, so the inventory stays at eleven.
NO_ACTION: Final = "no-action"

DISPOSITIONS: Final[frozenset[str]] = frozenset(
    {
        "executed",
        "required",
        "api-negative",
        "source-inapplicable",
        "blocked",
    }
)

# Upper bound so a malformed or adversarial manifest cannot exhaust memory.
MAX_FILE_BYTES: Final = 8 * 1024 * 1024
MAX_CASES: Final = 4096


class ManifestError(ValueError):
    """A scenario manifest is unsafe, malformed or covers less than it claims."""


@dataclass(frozen=True)
class Case:
    """One independently executed state/context-to-action edge."""

    id: str
    suite: str
    test: str
    robot_test: str
    fixture: str
    context: str
    action: str
    continuation: str
    execution_class: str
    oracles: tuple[str, ...]
    recording: bool
    snapd_test_mode: bool = False

    @property
    def is_gui(self) -> bool:
        return self.execution_class in {"vm", "physical"}


@dataclass(frozen=True)
class InventoryEntry:
    group: str
    value: str
    disposition: str
    case: str | None
    evidence: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class Manifest:
    """A validated plan: inventory dispositions plus required case edges."""

    schema: int
    pins: dict[str, str]
    cases: tuple[Case, ...]
    inventory: tuple[InventoryEntry, ...]

    def cases_for(self, execution_class: str) -> tuple[Case, ...]:
        if execution_class not in EXECUTION_CLASSES:
            raise ManifestError(f"unknown execution class {execution_class!r}")
        return tuple(
            case for case in self.cases if case.execution_class == execution_class
        )

    @property
    def gui_cases(self) -> tuple[Case, ...]:
        return tuple(case for case in self.cases if case.is_gui)

    def uninventoried(self) -> tuple[str, ...]:
        """Declared values with no disposition; empty for a valid manifest."""
        declared = {
            (group, value) for group, values in INVENTORY.items() for value in values
        }
        covered = {(entry.group, entry.value) for entry in self.inventory}
        return tuple(f"{group}/{value}" for group, value in sorted(declared - covered))

    def incomplete_inventory(self) -> tuple[str, ...]:
        """Values whose disposition still requires execution."""
        return tuple(
            f"{entry.group}/{entry.value}"
            for entry in self.inventory
            if entry.disposition in {"required", "blocked"}
        )

    def incomplete_reasons(self) -> tuple[str, ...]:
        """Explain each incomplete value without calling a blocker unexecuted."""
        reasons: list[str] = []
        for entry in self.inventory:
            label = f"{entry.group}/{entry.value}"
            if entry.disposition == "required":
                reasons.append(f"inventory value still requires execution: {label}")
            elif entry.disposition == "blocked":
                detail = f" ({entry.reason})" if entry.reason else ""
                reasons.append(f"inventory value is blocked: {label}{detail}")
        return tuple(reasons)


def inventory_size() -> int:
    return sum(len(values) for values in INVENTORY.values())


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"duplicate key {key!r} in manifest")
        result[key] = value
    return result


def _read_json(path: Path) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError as error:
        raise ManifestError(f"cannot read manifest {path}") from error
    if size > MAX_FILE_BYTES:
        raise ManifestError(f"manifest {path} is larger than {MAX_FILE_BYTES} bytes")
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManifestError(f"manifest {path} is not valid UTF-8 JSON") from error
    if not isinstance(raw, dict):
        raise ManifestError("manifest must be a JSON object")
    return raw


def _string(mapping: dict[str, Any], key: str, *, required: bool = True) -> str:
    value = mapping.get(key)
    if not required and (value is None or value == ""):
        return ""
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{key!r} must be a non-empty string")
    return value.strip()


def _string_list(
    mapping: dict[str, Any], key: str, *, required: bool
) -> tuple[str, ...]:
    value = mapping.get(key)
    if not required and (value is None or value == []):
        return ()
    if not isinstance(value, list) or not value:
        raise ManifestError(f"{key!r} must be a non-empty list of strings")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ManifestError(f"{key!r} must contain non-empty strings only")
        items.append(item.strip())
    if len(items) != len(set(items)):
        raise ManifestError(f"{key!r} must not repeat an entry")
    return tuple(items)


def _check_keys(
    mapping: dict[str, Any],
    expected: frozenset[str],
    label: str,
    *,
    required: frozenset[str] | None = None,
) -> None:
    """Reject unknown fields, and any required field that is absent.

    `expected` is the complete vocabulary; `required` narrows it when some of
    those keys are optional. It defaults to `expected` so ordinary callers
    demand every field.
    """
    unknown = sorted(set(mapping) - expected)
    if unknown:
        raise ManifestError(f"{label} has unknown fields: {', '.join(unknown)}")
    mandatory = expected if required is None else required
    missing = sorted(mandatory - set(mapping))
    if missing:
        raise ManifestError(f"{label} is missing fields: {', '.join(missing)}")


_CASE_FIELDS: Final = frozenset(
    {
        "id",
        "suite",
        "test",
        "robot-test",
        "fixture",
        "context",
        "action",
        "continuation",
        "execution-class",
        "oracles",
        "recording",
    }
)
_CASE_OPTIONAL_FIELDS: Final = frozenset({"snapd-test-mode"})
_ENTRY_FIELDS: Final = frozenset(
    {"group", "value", "disposition", "case", "evidence", "reason"}
)


def _parse_case(raw: Any, index: int) -> Case:
    if not isinstance(raw, dict):
        raise ManifestError(f"cases[{index}] must be an object")
    _check_keys(
        raw,
        _CASE_FIELDS | _CASE_OPTIONAL_FIELDS,
        f"cases[{index}]",
        required=_CASE_FIELDS,
    )
    case_id = _string(raw, "id")
    execution_class = _string(raw, "execution-class")
    if execution_class not in EXECUTION_CLASSES:
        raise ManifestError(
            f"cases[{index}] execution-class {execution_class!r} is not one of "
            + ", ".join(sorted(EXECUTION_CLASSES))
        )
    action = _string(raw, "action")
    if action not in {*INVENTORY["action"], NO_ACTION}:
        raise ManifestError(f"cases[{index}] action {action!r} is not declared")
    recording = raw.get("recording")
    if not isinstance(recording, bool):
        raise ManifestError(f"cases[{index}] recording must be a boolean")
    test_mode = raw.get("snapd-test-mode", False)
    if not isinstance(test_mode, bool):
        raise ManifestError(f"cases[{index}] snapd-test-mode must be a boolean")
    oracles = _string_list(raw, "oracles", required=True)
    return Case(
        id=case_id,
        suite=_string(raw, "suite"),
        test=_string(raw, "test"),
        robot_test=_string(raw, "robot-test"),
        fixture=_string(raw, "fixture"),
        context=_string(raw, "context"),
        action=action,
        continuation=_string(raw, "continuation"),
        execution_class=execution_class,
        oracles=oracles,
        recording=recording,
        snapd_test_mode=test_mode,
    )


def _parse_inventory(raw: Any, index: int) -> InventoryEntry:
    if not isinstance(raw, dict):
        raise ManifestError(f"inventory[{index}] must be an object")
    _check_keys(raw, _ENTRY_FIELDS, f"inventory[{index}]")
    group = _string(raw, "group")
    value = _string(raw, "value")
    if group not in INVENTORY:
        raise ManifestError(f"inventory[{index}] group {group!r} is not declared")
    if value not in INVENTORY[group]:
        raise ManifestError(f"inventory[{index}] {group}/{value} is not declared")
    disposition = _string(raw, "disposition")
    if disposition not in DISPOSITIONS:
        raise ManifestError(
            f"inventory[{index}] disposition {disposition!r} is not one of "
            + ", ".join(sorted(DISPOSITIONS))
        )
    case = raw.get("case")
    if case is not None and (not isinstance(case, str) or not case.strip()):
        raise ManifestError(f"inventory[{index}] case must be a string or null")
    evidence = _string_list(raw, "evidence", required=disposition == "executed")
    reason = _string(
        raw,
        "reason",
        required=disposition in {"blocked", "source-inapplicable", "api-negative"},
    )
    if disposition == "executed" and not evidence:
        raise ManifestError(
            f"inventory[{index}] {group}/{value} claims execution without evidence"
        )
    return InventoryEntry(
        group=group,
        value=value,
        disposition=disposition,
        case=case.strip() if isinstance(case, str) else None,
        evidence=evidence,
        reason=reason,
    )


def load_manifest(path: Path) -> Manifest:
    """Load and validate a scenario manifest, failing closed on any gap."""
    raw = _read_json(Path(path))
    _check_keys(raw, frozenset({"schema", "pins", "cases", "inventory"}), "manifest")
    schema = raw["schema"]
    if schema != 1:
        raise ManifestError(f"unsupported manifest schema {schema!r}")

    pins_raw = raw["pins"]
    if not isinstance(pins_raw, dict) or not pins_raw:
        raise ManifestError("pins must be a non-empty object")
    pins: dict[str, str] = {}
    for key, value in pins_raw.items():
        if not isinstance(key, str) or not key.strip():
            raise ManifestError("pin names must be non-empty strings")
        if not isinstance(value, str) or not value.strip():
            raise ManifestError(f"pin {key!r} must be a non-empty string")
        pins[key.strip()] = value.strip()

    cases_raw = raw["cases"]
    if not isinstance(cases_raw, list) or not cases_raw:
        raise ManifestError("cases must be a non-empty list")
    if len(cases_raw) > MAX_CASES:
        raise ManifestError(f"cases exceeds the {MAX_CASES} case limit")
    cases = tuple(_parse_case(item, index) for index, item in enumerate(cases_raw))
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ManifestError("case ids must be unique")

    inventory_raw = raw["inventory"]
    if not isinstance(inventory_raw, list) or not inventory_raw:
        raise ManifestError("inventory must be a non-empty list")
    inventory = tuple(
        _parse_inventory(item, index) for index, item in enumerate(inventory_raw)
    )
    keys = [(entry.group, entry.value) for entry in inventory]
    if len(keys) != len(set(keys)):
        raise ManifestError("inventory must not repeat a declared value")

    manifest = Manifest(schema=schema, pins=pins, cases=cases, inventory=inventory)
    missing = manifest.uninventoried()
    if missing:
        raise ManifestError("inventory has no disposition for: " + ", ".join(missing))
    by_id = {case.id: case for case in cases}
    for entry in inventory:
        if entry.disposition in {"executed", "api-negative"}:
            if entry.case is None:
                raise ManifestError(
                    f"inventory {entry.group}/{entry.value} names no case"
                )
            case = by_id.get(entry.case)
            if case is None:
                raise ManifestError(
                    f"inventory {entry.group}/{entry.value} names unknown case "
                    f"{entry.case!r}"
                )
            if (
                entry.disposition == "api-negative"
                and case.execution_class != "api-negative"
            ):
                raise ManifestError(
                    f"inventory {entry.group}/{entry.value} claims api-negative "
                    f"but case {case.id!r} is {case.execution_class!r}"
                )
            if (
                entry.disposition == "executed"
                and case.execution_class == "api-negative"
            ):
                raise ManifestError(
                    f"inventory {entry.group}/{entry.value} claims GUI execution "
                    f"through the API-negative case {case.id!r}"
                )
    return manifest


def required_cases(manifest: Manifest) -> tuple[Case, ...]:
    """Every case the manifest requires, whatever its current support."""
    return manifest.cases


__all__ = [
    "Case",
    "DISPOSITIONS",
    "EXECUTION_CLASSES",
    "INVENTORY",
    "InventoryEntry",
    "Manifest",
    "ManifestError",
    "NO_ACTION",
    "inventory_size",
    "load_manifest",
    "required_cases",
]
