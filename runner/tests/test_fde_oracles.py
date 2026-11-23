from __future__ import annotations

from typing import Any

import pytest

from ubuntu_gui_testing_runner.fde_oracles import (
    ActionSet,
    Interruption,
    OracleError,
    require_boot_changed,
    require_cleanup,
    require_data_integrity,
    require_expected_issues,
    require_key_outcomes,
    require_new_change,
    require_no_mutation,
    require_no_repair_action,
    require_recommendation,
)


def _issue(kind: str, actions: list[Any], **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "actions": actions, **extra}


def test_action_set_accepts_strings_and_objects() -> None:
    action_set = ActionSet.from_response(
        _issue(
            "action-failed", ["reboot", {"action": "contact-oem"}], arguments={"a": 1}
        )
    )
    action_set.require_exact(["contact-oem", "reboot"])
    action_set.require_present("reboot")
    action_set.require_absent("shutdown")
    assert action_set.arguments == {"a": "1"}


def test_action_set_rejects_a_malformed_issue() -> None:
    with pytest.raises(OracleError, match="no kind"):
        ActionSet.from_response({"actions": []})
    with pytest.raises(OracleError, match="malformed action list"):
        ActionSet.from_response({"kind": "x", "actions": "reboot"})
    with pytest.raises(OracleError, match="malformed action"):
        ActionSet.from_response({"kind": "x", "actions": [{}]})


def test_expected_issues_require_exact_sets_and_no_extras() -> None:
    found = require_expected_issues(
        [_issue("running-in-vm", ["shutdown"]), _issue("measured-boot", [])],
        {"running-in-vm": ["shutdown"], "measured-boot": []},
    )
    assert set(found) == {"running-in-vm", "measured-boot"}
    with pytest.raises(OracleError, match="did not report expected issues"):
        require_expected_issues([], {"running-in-vm": ["shutdown"]})
    with pytest.raises(OracleError, match="unreviewed issues"):
        require_expected_issues(
            [_issue("running-in-vm", ["shutdown"]), _issue("extra", [])],
            {"running-in-vm": ["shutdown"]},
        )
    with pytest.raises(OracleError, match="reported twice"):
        require_expected_issues([_issue("a", []), _issue("a", [])], {"a": []})
    with pytest.raises(OracleError, match="offered"):
        require_expected_issues([_issue("a", ["reboot"])], {"a": ["shutdown"]})


def test_no_repair_action_rejects_any_offer() -> None:
    require_no_repair_action(ActionSet(kind="host-security", actions=()))
    with pytest.raises(OracleError, match="offers"):
        require_no_repair_action(ActionSet(kind="host-security", actions=("reboot",)))


def _baseline_with_change(change_id: str, status: str = "Done") -> dict[str, Any]:
    return {
        "last_reprovision": {"kind": "fde-reprovision", "id": change_id},
    }


def test_new_change_requires_a_distinct_terminal_change() -> None:
    baseline = _baseline_with_change("1")
    snapshot = {
        "last_reprovision": {
            "kind": "fde-reprovision",
            "id": "2",
            "status": "Done",
            "ready": True,
            "err": "",
        },
        "changes": [],
    }
    assert require_new_change(baseline, snapshot)["id"] == "2"
    with pytest.raises(OracleError, match="baseline change"):
        require_new_change(
            _baseline_with_change("2"),
            {
                "last_reprovision": {
                    "kind": "fde-reprovision",
                    "id": "2",
                    "status": "Done",
                    "ready": True,
                }
            },
        )
    with pytest.raises(OracleError, match="expected 'Error'"):
        require_new_change(
            baseline,
            {
                "last_reprovision": {
                    "kind": "fde-reprovision",
                    "id": "3",
                    "status": "Done",
                    "ready": True,
                }
            },
            status="Error",
        )
    with pytest.raises(OracleError, match="completed with an error"):
        require_new_change(
            baseline,
            {
                "last_reprovision": {
                    "kind": "fde-reprovision",
                    "id": "3",
                    "status": "Done",
                    "ready": True,
                    "err": "boom",
                }
            },
        )
    with pytest.raises(OracleError, match="still in progress"):
        require_new_change(
            baseline,
            {
                "last_reprovision": {
                    "kind": "fde-reprovision",
                    "id": "3",
                    "status": "Done",
                    "ready": True,
                },
                "changes": [{"kind": "fde-reprovision", "id": "3"}],
            },
        )
    with pytest.raises(OracleError, match="no fde-reprovision change"):
        require_new_change(baseline, {})


def test_key_outcomes_require_both_containers_to_agree() -> None:
    observed = {
        "new": {"data": True, "save": True},
        "old": {"data": False, "save": False},
    }
    require_key_outcomes(observed, new_key_unlocks=True, old_key_unlocks=False)
    with pytest.raises(OracleError, match="save container"):
        require_key_outcomes(
            {
                "new": {"data": True, "save": False},
                "old": {"data": False, "save": False},
            },
            new_key_unlocks=True,
            old_key_unlocks=False,
        )
    with pytest.raises(OracleError, match="no data result"):
        require_key_outcomes(
            {"new": {"save": True}, "old": {"data": False, "save": False}},
            new_key_unlocks=True,
            old_key_unlocks=False,
        )
    with pytest.raises(OracleError, match="both the new and old key"):
        require_key_outcomes(
            {"new": {"data": True, "save": True}},
            new_key_unlocks=True,
            old_key_unlocks=False,
        )


def test_boot_changed_requires_a_different_boot_id() -> None:
    assert require_boot_changed({"boot_id": "a"}, {"boot_id": "b"}) == "b"
    with pytest.raises(OracleError, match="did not change"):
        require_boot_changed({"boot_id": "a"}, {"boot_id": "a"})
    with pytest.raises(OracleError, match="no boot id"):
        require_boot_changed({}, {"boot_id": "b"})


def test_no_mutation_compares_identity_fields_and_pending_changes() -> None:
    baseline = {
        "boot_id": "a",
        "auth_mode": "passphrase",
        "keyslots": {"data": ["0"], "save": ["0"]},
        "last_reprovision": {"id": "1"},
    }
    after = {**baseline, "changes": []}
    require_no_mutation(baseline, after)
    with pytest.raises(OracleError, match="changed auth_mode"):
        require_no_mutation(baseline, {**after, "auth_mode": "pin"})
    with pytest.raises(OracleError, match="left a reprovision change running"):
        require_no_mutation(
            baseline, {**after, "changes": [{"kind": "fde-reprovision"}]}
        )
    with pytest.raises(OracleError, match="no keyslots"):
        require_no_mutation(
            {k: v for k, v in baseline.items() if k != "keyslots"}, after
        )


def test_interruption_requires_settlement_and_a_real_boundary() -> None:
    evidence = {
        "stage": "save-unlock",
        "commit_crossed": False,
        "change_id": "7",
        "settled_on_boot": True,
    }
    interruption = Interruption.from_evidence(evidence)
    interruption.require_rolled_back()
    with pytest.raises(OracleError, match="commit boundary"):
        interruption.require_committed()

    committed = Interruption.from_evidence({**evidence, "commit_crossed": True})
    committed.require_committed()
    with pytest.raises(OracleError, match="rollback contract does not apply"):
        committed.require_rolled_back()

    for missing, message in (
        ({"stage": ""}, "no durable stage"),
        ({"commit_crossed": "yes"}, "no commit-boundary result"),
        ({"change_id": ""}, "no change id"),
    ):
        with pytest.raises(OracleError, match=message):
            Interruption.from_evidence({**evidence, **missing})
    with pytest.raises(OracleError, match="finished before the interruption"):
        Interruption.from_evidence({**evidence, "finished_before_interrupt": True})
    with pytest.raises(OracleError, match="had not settled"):
        Interruption.from_evidence({**evidence, "settled_on_boot": False})


def test_cleanup_requires_a_consistent_keyslot_set() -> None:
    before = {"keyslots": {"data": ["0", "old"], "save": ["0"]}}
    after = {"keyslots": {"data": ["0"], "save": ["0"]}}
    require_cleanup(before, after, replaced=True)
    with pytest.raises(OracleError, match="old keyslots remain"):
        require_cleanup(before, before, replaced=True)
    with pytest.raises(OracleError, match="changed the container set"):
        require_cleanup(
            before,
            {"keyslots": {"data": ["0"]}},
            replaced=True,
        )
    with pytest.raises(OracleError, match="no keyslots after repair"):
        require_cleanup(
            before, {"keyslots": {"data": [], "save": ["0"]}}, replaced=True
        )
    with pytest.raises(OracleError, match="changed the keyslot set"):
        require_cleanup(
            before,
            {"keyslots": {"data": ["0", "new"], "save": ["0"]}},
            replaced=False,
        )
    require_cleanup(before, before, replaced=False)


def test_data_integrity_preserves_every_canary() -> None:
    before = {"canaries": {"home": "abc", "etc": "def"}}
    require_data_integrity(before, {"canaries": {"home": "abc", "etc": "def"}})
    with pytest.raises(OracleError, match="canary 'etc' changed"):
        require_data_integrity(before, {"canaries": {"home": "abc", "etc": "x"}})
    with pytest.raises(OracleError, match="missing after the operation"):
        require_data_integrity(before, {"canaries": {"home": "abc"}})
    with pytest.raises(OracleError, match="no data-integrity canaries"):
        require_data_integrity({}, {"canaries": {}})


def test_recommendation_presence_and_absence() -> None:
    healthy: dict[str, Any] = {"storage": {"recommendations": []}}
    degraded: dict[str, Any] = {"storage": {"recommendations": ["require-reprovision"]}}
    require_recommendation(healthy, None)
    require_recommendation(degraded, "require-reprovision")
    with pytest.raises(OracleError, match="still recommends"):
        require_recommendation(degraded, None)
    with pytest.raises(OracleError, match="do not contain"):
        require_recommendation(healthy, "require-platform-reset")
    with pytest.raises(OracleError, match="no storage state"):
        require_recommendation({}, None)
    with pytest.raises(OracleError, match="malformed recommendation list"):
        require_recommendation({"storage": {"recommendations": "none"}}, None)
