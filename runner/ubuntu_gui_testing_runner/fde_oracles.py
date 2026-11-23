"""Independent pass/fail oracles for TPM-FDE scenarios.

These checks consume evidence that was gathered by the runner or guest helper
and reject known false positives. They never click a control, mutate a machine
or infer success from a screenshot. A green Robot step without these checks is
not a passing E2E case.

The contract split matters:

* a completed repair must prove a new change, credentials on both containers
  and a real recovery boot;
* a cancellation must prove nothing changed;
* an interruption must prove the durable boundary it crossed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

TERMINAL_STATUSES = frozenset({"Done", "Error", "Undo", "Undone", "Hold"})


class OracleError(AssertionError):
    """Recorded evidence does not satisfy the required contract."""


@dataclass(frozen=True)
class ActionSet:
    """The complete actions snapd offered for one issue, with its arguments."""

    kind: str
    actions: tuple[str, ...]
    arguments: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_response(cls, issue: Mapping[str, Any]) -> ActionSet:
        kind = issue.get("kind")
        if not isinstance(kind, str) or not kind:
            raise OracleError("an availability issue has no kind")
        raw_actions = issue.get("actions")
        if raw_actions is None:
            raw_actions = []
        if not isinstance(raw_actions, list):
            raise OracleError(f"issue {kind!r} has a malformed action list")
        actions: list[str] = []
        for item in raw_actions:
            if isinstance(item, str):
                actions.append(item)
            elif isinstance(item, Mapping):
                name = item.get("action") or item.get("name")
                if not isinstance(name, str) or not name:
                    raise OracleError(f"issue {kind!r} has a malformed action")
                actions.append(name)
            else:
                raise OracleError(f"issue {kind!r} has a malformed action")
        arguments = {
            str(key): str(value)
            for key, value in (issue.get("arguments") or {}).items()
        }
        return cls(kind=kind, actions=tuple(actions), arguments=arguments)

    def require_exact(self, expected: Sequence[str], *, label: str = "") -> None:
        """Require the offered set to equal the reviewed set, order-insensitively."""
        want = sorted(expected)
        got = sorted(self.actions)
        if got != want:
            where = f" for {label}" if label else ""
            raise OracleError(
                f"issue {self.kind!r}{where} offered {got}, expected {want}"
            )

    def require_absent(self, action: str) -> None:
        if action in self.actions:
            raise OracleError(f"issue {self.kind!r} unexpectedly offers {action!r}")

    def require_present(self, action: str) -> None:
        if action not in self.actions:
            raise OracleError(
                f"issue {self.kind!r} does not offer {action!r}: {list(self.actions)}"
            )


def require_expected_issues(
    observed: Iterable[Mapping[str, Any]],
    expected: Mapping[str, Sequence[str]],
) -> dict[str, ActionSet]:
    """Require every expected issue and its exact action set, and no extra issue."""
    found: dict[str, ActionSet] = {}
    for issue in observed:
        action_set = ActionSet.from_response(issue)
        if action_set.kind in found:
            raise OracleError(f"issue {action_set.kind!r} was reported twice")
        found[action_set.kind] = action_set
    missing = sorted(set(expected) - set(found))
    if missing:
        raise OracleError("snapd did not report expected issues: " + ", ".join(missing))
    unexpected = sorted(set(found) - set(expected))
    if unexpected:
        raise OracleError("snapd reported unreviewed issues: " + ", ".join(unexpected))
    for kind, actions in expected.items():
        found[kind].require_exact(actions, label=kind)
    return found


def require_no_repair_action(action_set: ActionSet) -> None:
    """Require an issue that offers no executable repair at all."""
    if action_set.actions:
        raise OracleError(
            f"issue {action_set.kind!r} offers {list(action_set.actions)}; "
            "the contract requires no suggested repair action"
        )


def require_new_change(
    baseline: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    *,
    kind: str = "fde-reprovision",
    status: str = "Done",
) -> Mapping[str, Any]:
    """Require a change this run created, in the expected terminal state."""
    previous = baseline.get("last_reprovision")
    previous_id = previous.get("id") if isinstance(previous, Mapping) else None
    change = snapshot.get("last_reprovision")
    if not isinstance(change, Mapping):
        raise OracleError(f"snapd recorded no {kind} change")
    if change.get("kind") != kind:
        raise OracleError(
            f"new change kind is {change.get('kind')!r}, expected {kind!r}"
        )
    change_id = change.get("id")
    if not isinstance(change_id, str) or not change_id:
        raise OracleError("the new change has no id")
    if change_id == previous_id:
        raise OracleError(
            f"change {change_id} is the baseline change; no new operation ran"
        )
    if change.get("status") != status or not change.get("ready"):
        raise OracleError(
            f"change {change_id} is {change.get('status')!r} "
            f"(ready={change.get('ready')!r}), expected {status!r}"
        )
    if status == "Done" and change.get("err"):
        raise OracleError(f"change {change_id} completed with an error")
    pending = snapshot.get("changes") or []
    if any(
        isinstance(entry, Mapping) and entry.get("kind") == kind for entry in pending
    ):
        raise OracleError(f"a {kind} change is still in progress")
    return change


def require_key_outcomes(
    observed: Mapping[str, Any],
    *,
    new_key_unlocks: bool,
    old_key_unlocks: bool,
) -> None:
    """Require both containers to agree on the new and old recovery keys."""
    new = observed.get("new")
    old = observed.get("old")
    if not isinstance(new, Mapping) or not isinstance(old, Mapping):
        raise OracleError("key evidence must report both the new and old key")
    for label, key_result, expected in (
        ("new", new, new_key_unlocks),
        ("old", old, old_key_unlocks),
    ):
        for container in ("data", "save"):
            value = key_result.get(container)
            if not isinstance(value, bool):
                raise OracleError(f"the {label} key has no {container} result")
            if value is not expected:
                outcome = "unlock" if expected else "be rejected by"
                raise OracleError(
                    f"the {label} recovery key must {outcome} the {container} "
                    f"container, observed {value}"
                )


def require_boot_changed(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    """Require a real reboot, identified by the kernel boot id."""
    old = before.get("boot_id")
    new = after.get("boot_id")
    if not isinstance(old, str) or not old:
        raise OracleError("the baseline has no boot id")
    if not isinstance(new, str) or not new:
        raise OracleError("the observed boot has no boot id")
    if new == old:
        raise OracleError(f"boot id {new} did not change; no reboot was proved")
    return new


def require_no_mutation(baseline: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    """Require a cancellation or refusal to leave product state untouched."""
    for field_name in ("boot_id", "auth_mode", "keyslots", "last_reprovision"):
        if field_name not in baseline:
            raise OracleError(f"the baseline has no {field_name}")
        if field_name not in after:
            raise OracleError(f"the observation has no {field_name}")
        if after[field_name] != baseline[field_name]:
            raise OracleError(f"a cancelled operation changed {field_name}")
    pending = after.get("changes") or []
    if any(
        isinstance(entry, Mapping) and entry.get("kind") == "fde-reprovision"
        for entry in pending
    ):
        raise OracleError("a cancelled operation left a reprovision change running")


@dataclass(frozen=True)
class Interruption:
    """Evidence that an operation was interrupted at a specific durable stage."""

    stage: str
    commit_crossed: bool
    change_id: str

    @classmethod
    def from_evidence(cls, evidence: Mapping[str, Any]) -> Interruption:
        stage = evidence.get("stage")
        if not isinstance(stage, str) or not stage:
            raise OracleError("interruption evidence has no durable stage")
        crossed = evidence.get("commit_crossed")
        if not isinstance(crossed, bool):
            raise OracleError("interruption evidence has no commit-boundary result")
        change_id = evidence.get("change_id")
        if not isinstance(change_id, str) or not change_id:
            raise OracleError("interruption evidence has no change id")
        if evidence.get("finished_before_interrupt") is True:
            raise OracleError(
                f"change {change_id} finished before the interruption; "
                "the experiment did not interrupt it"
            )
        if evidence.get("settled_on_boot") is not True:
            raise OracleError(f"change {change_id} had not settled on the next boot")
        return cls(stage=stage, commit_crossed=crossed, change_id=change_id)

    def require_rolled_back(self) -> None:
        if self.commit_crossed:
            raise OracleError(
                f"stage {self.stage} crossed the protector-key commit boundary; "
                "the rollback contract does not apply"
            )

    def require_committed(self) -> None:
        if not self.commit_crossed:
            raise OracleError(
                f"stage {self.stage} did not cross the commit boundary; "
                "the committed-repair contract does not apply"
            )


def require_cleanup(
    before: Mapping[str, Any], after: Mapping[str, Any], *, replaced: bool
) -> None:
    """Require keyslot and counter cleanup in line with the operation contract."""
    before_slots = before.get("keyslots")
    after_slots = after.get("keyslots")
    if not isinstance(before_slots, Mapping) or not isinstance(after_slots, Mapping):
        raise OracleError("cleanup evidence must report keyslots per container")
    if replaced:
        if set(after_slots) != set(before_slots):
            raise OracleError("a completed repair changed the container set")
        for role, names in after_slots.items():
            if not isinstance(names, list) or not names:
                raise OracleError(f"container {role!r} has no keyslots after repair")
            leftovers = [name for name in names if "old" in str(name)]
            if leftovers:
                raise OracleError(f"old keyslots remain on {role!r}: {leftovers}")
    elif after_slots != before_slots:
        raise OracleError("an unmutated operation changed the keyslot set")


def require_data_integrity(before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    """Require the pre-established non-secret canaries to survive unchanged."""
    old = before.get("canaries")
    new = after.get("canaries")
    if not isinstance(old, Mapping) or not old:
        raise OracleError("baseline has no data-integrity canaries")
    if not isinstance(new, Mapping):
        raise OracleError("the observation has no data-integrity canaries")
    for name, value in old.items():
        if name not in new:
            raise OracleError(f"canary {name!r} is missing after the operation")
        if new[name] != value:
            raise OracleError(f"canary {name!r} changed")


def require_recommendation(snapshot: Mapping[str, Any], expected: str | None) -> None:
    """Require the reported storage recommendation, or its absence."""
    storage = snapshot.get("storage")
    if not isinstance(storage, Mapping):
        raise OracleError("the snapshot has no storage state")
    recommendations = storage.get("recommendations") or []
    if not isinstance(recommendations, list):
        raise OracleError("the snapshot has a malformed recommendation list")
    if expected is None:
        if recommendations:
            raise OracleError(f"a healthy system still recommends {recommendations}")
    elif expected not in recommendations:
        raise OracleError(
            f"recommendations {recommendations} do not contain {expected!r}"
        )


__all__ = [
    "ActionSet",
    "Interruption",
    "OracleError",
    "TERMINAL_STATUSES",
    "require_boot_changed",
    "require_cleanup",
    "require_data_integrity",
    "require_expected_issues",
    "require_key_outcomes",
    "require_new_change",
    "require_no_mutation",
    "require_no_repair_action",
    "require_recommendation",
]
