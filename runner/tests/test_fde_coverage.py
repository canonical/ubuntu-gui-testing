from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ubuntu_gui_testing_runner import fde_coverage
from ubuntu_gui_testing_runner.fde_coverage import (
    INVENTORY,
    ManifestError,
    inventory_size,
    load_manifest,
    required_cases,
)


def _case(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "case-1",
        "suite": "desktop-security-center-reprovision",
        "test": "desktop-security-center",
        "robot-test": "TPM clear recovery reprovision",
        "fixture": "default",
        "context": "recovery",
        "action": "clear-tpm",
        "continuation": "recovery-key",
        "execution-class": "vm",
        "oracles": ["new-change"],
        "recording": True,
    }
    payload.update(overrides)
    return payload


def _inventory() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for group, values in INVENTORY.items():
        for value in values:
            entries.append(
                {
                    "group": group,
                    "value": value,
                    "disposition": "required",
                    "case": None,
                    "evidence": [],
                    "reason": "",
                }
            )
    return entries


def _manifest(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": 1,
        "pins": {"snapd": "2.71", "security-center": "25.10"},
        "cases": [_case()],
        "inventory": _inventory(),
    }
    payload.update(overrides)
    return payload


def _write(tmp_path: Path, payload: Any, *, name: str = "manifest.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_accepts_a_complete_manifest(tmp_path: Path) -> None:
    manifest = load_manifest(_write(tmp_path, _manifest()))
    assert inventory_size() == len(_inventory())
    assert manifest.uninventoried() == ()
    assert manifest.pins["snapd"] == "2.71"
    assert [case.id for case in manifest.gui_cases] == ["case-1"]
    assert required_cases(manifest) == manifest.cases


def test_rejects_a_value_without_disposition(tmp_path: Path) -> None:
    inventory = _inventory()[1:]
    with pytest.raises(ManifestError, match="no disposition for"):
        load_manifest(_write(tmp_path, _manifest(inventory=inventory)))


def test_rejects_an_undeclared_group_or_value(tmp_path: Path) -> None:
    inventory = _inventory()
    inventory[0] = {**inventory[0], "value": "not-a-real-value"}
    with pytest.raises(ManifestError, match="is not declared"):
        load_manifest(_write(tmp_path, _manifest(inventory=inventory)))


def test_rejects_a_repeated_inventory_value(tmp_path: Path) -> None:
    inventory = _inventory()
    inventory.append(dict(inventory[0]))
    with pytest.raises(ManifestError, match="must not repeat"):
        load_manifest(_write(tmp_path, _manifest(inventory=inventory)))


def test_rejects_unknown_and_missing_case_fields(tmp_path: Path) -> None:
    unknown = _case(extra="value")
    with pytest.raises(ManifestError, match="unknown fields"):
        load_manifest(_write(tmp_path, _manifest(cases=[unknown])))
    missing = _case()
    del missing["continuation"]
    with pytest.raises(ManifestError, match="missing fields"):
        load_manifest(_write(tmp_path, _manifest(cases=[missing])))


def test_rejects_an_undeclared_action_and_class(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="action .* is not declared"):
        load_manifest(_write(tmp_path, _manifest(cases=[_case(action="explode")])))
    with pytest.raises(ManifestError, match="execution-class .* is not one of"):
        load_manifest(
            _write(tmp_path, _manifest(cases=[_case(**{"execution-class": "x"})]))
        )


def test_rejects_a_non_boolean_recording_flag(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="recording must be a boolean"):
        load_manifest(_write(tmp_path, _manifest(cases=[_case(recording="yes")])))


def test_rejects_an_empty_oracle_list(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="oracles"):
        load_manifest(_write(tmp_path, _manifest(cases=[_case(oracles=[])])))


def test_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="case ids must be unique"):
        load_manifest(_write(tmp_path, _manifest(cases=[_case(), _case()])))


def test_rejects_execution_without_evidence(tmp_path: Path) -> None:
    inventory = _inventory()
    inventory[0] = {
        **inventory[0],
        "disposition": "executed",
        "case": "case-1",
        "evidence": [],
    }
    # An executed value with no evidence fails before the run can claim it.
    with pytest.raises(ManifestError, match="evidence"):
        load_manifest(_write(tmp_path, _manifest(inventory=inventory)))


def test_rejects_execution_through_an_api_negative_case(tmp_path: Path) -> None:
    inventory = _inventory()
    inventory[0] = {
        **inventory[0],
        "disposition": "executed",
        "case": "case-1",
        "evidence": ["observed"],
    }
    manifest = _manifest(
        cases=[_case(**{"execution-class": "api-negative"})], inventory=inventory
    )
    with pytest.raises(ManifestError, match="claims GUI execution"):
        load_manifest(_write(tmp_path, manifest))


def test_rejects_an_api_negative_disposition_on_a_vm_case(tmp_path: Path) -> None:
    inventory = _inventory()
    inventory[0] = {
        **inventory[0],
        "disposition": "api-negative",
        "case": "case-1",
        "evidence": ["rejected"],
        "reason": "snapd must refuse the request",
    }
    with pytest.raises(ManifestError, match="claims api-negative"):
        load_manifest(_write(tmp_path, _manifest(inventory=inventory)))


def test_rejects_execution_naming_an_unknown_case(tmp_path: Path) -> None:
    inventory = _inventory()
    inventory[0] = {
        **inventory[0],
        "disposition": "executed",
        "case": "missing",
        "evidence": ["observed"],
    }
    with pytest.raises(ManifestError, match="names unknown case"):
        load_manifest(_write(tmp_path, _manifest(inventory=inventory)))


def test_rejects_blocked_and_inapplicable_without_a_reason(tmp_path: Path) -> None:
    for disposition in ("blocked", "source-inapplicable"):
        inventory = _inventory()
        inventory[0] = {**inventory[0], "disposition": disposition}
        with pytest.raises(ManifestError, match="reason"):
            load_manifest(_write(tmp_path, _manifest(inventory=inventory)))


def test_rejects_unknown_disposition(tmp_path: Path) -> None:
    inventory = _inventory()
    inventory[0] = {**inventory[0], "disposition": "maybe"}
    with pytest.raises(ManifestError, match="disposition"):
        load_manifest(_write(tmp_path, _manifest(inventory=inventory)))


def test_rejects_empty_pins_and_wrong_schema(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="pins"):
        load_manifest(_write(tmp_path, _manifest(pins={})))
    with pytest.raises(ManifestError, match="schema"):
        load_manifest(_write(tmp_path, _manifest(schema=2)))


def test_rejects_a_duplicate_json_key(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        '{"schema": 1, "schema": 1, "pins": {"a": "b"}, "cases": [], "inventory": []}',
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="duplicate key"):
        load_manifest(path)


def test_rejects_a_non_object_and_invalid_utf8(tmp_path: Path) -> None:
    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    with pytest.raises(ManifestError, match="JSON object"):
        load_manifest(array)
    binary = tmp_path / "binary.json"
    binary.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ManifestError, match="valid UTF-8 JSON"):
        load_manifest(binary)


def test_rejects_an_oversized_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fde_coverage, "MAX_FILE_BYTES", 8)
    path = tmp_path / "manifest.json"
    path.write_text('{"schema": 1}', encoding="utf-8")
    with pytest.raises(ManifestError, match="larger than"):
        load_manifest(path)


def test_incomplete_inventory_reports_required_and_blocked(tmp_path: Path) -> None:
    inventory = _inventory()
    inventory[0] = {
        **inventory[0],
        "disposition": "blocked",
        "reason": "needs physical hardware",
    }
    inventory[1] = {
        **inventory[1],
        "disposition": "source-inapplicable",
        "reason": "not emitted by this source",
    }
    manifest = load_manifest(_write(tmp_path, _manifest(inventory=inventory)))
    incomplete = manifest.incomplete_inventory()
    assert f"{inventory[0]['group']}/{inventory[0]['value']}" in incomplete
    assert f"{inventory[1]['group']}/{inventory[1]['value']}" not in incomplete
    assert len(incomplete) == len(inventory) - 1


def test_cases_for_rejects_an_unknown_class(tmp_path: Path) -> None:
    manifest = load_manifest(_write(tmp_path, _manifest()))
    assert manifest.cases_for("vm") == manifest.cases
    with pytest.raises(ManifestError, match="unknown execution class"):
        manifest.cases_for("elsewhere")


def test_snapd_test_mode_is_optional_and_typed(tmp_path: Path) -> None:
    manifest = load_manifest(_write(tmp_path, _manifest()))
    assert manifest.cases[0].snapd_test_mode is False
    enabled = load_manifest(
        _write(
            tmp_path,
            _manifest(cases=[_case(**{"snapd-test-mode": True})]),
            name="enabled.json",
        )
    )
    assert enabled.cases[0].snapd_test_mode is True
    with pytest.raises(ManifestError, match="snapd-test-mode must be a boolean"):
        load_manifest(
            _write(
                tmp_path,
                _manifest(cases=[_case(**{"snapd-test-mode": "yes"})]),
                name="typed.json",
            )
        )


def test_incomplete_reasons_distinguishes_blocked_from_required(
    tmp_path: Path,
) -> None:
    inventory = _inventory()
    for entry in inventory[2:]:
        entry["disposition"] = "source-inapplicable"
        entry["reason"] = "not emitted by this source"
    inventory[0] = {
        **inventory[0],
        "disposition": "blocked",
        "reason": "needs physical hardware",
    }
    manifest = load_manifest(_write(tmp_path, _manifest(inventory=inventory)))
    reasons = manifest.incomplete_reasons()
    first = f"{inventory[0]['group']}/{inventory[0]['value']}"
    second = f"{inventory[1]['group']}/{inventory[1]['value']}"
    assert f"inventory value is blocked: {first} (needs physical hardware)" in reasons
    assert f"inventory value still requires execution: {second}" in reasons
    assert len(reasons) == 2
