from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from ubuntu_gui_testing_runner import fde_suite
from ubuntu_gui_testing_runner.fde_capture import synthetic_frame
from ubuntu_gui_testing_runner.fde_coverage import (
    INVENTORY,
    Case,
    InventoryEntry,
    Manifest,
)
from ubuntu_gui_testing_runner.fde_suite import (
    CaseResult,
    SuiteError,
    _diagnose,
    _incomplete_reasons,
    _runner_command,
    build_combined_index,
    load_fixtures,
    run_case,
)
from ubuntu_gui_testing_runner.fde_video import frame_spans, read_index

CASE = Case(
    id="case-1",
    suite="desktop-security-center-reprovision",
    test="desktop-security-center",
    robot_test="TPM clear recovery reprovision",
    fixture="default",
    context="recovery",
    action="clear-tpm",
    continuation="recovery-key",
    execution_class="vm",
    oracles=("new-change",),
    recording=True,
)


def _manifest(*, required: bool = False) -> Manifest:
    inventory: list[InventoryEntry] = []
    for group, values in INVENTORY.items():
        for value in values:
            if required and group == "status" and value == "degraded":
                inventory.append(
                    InventoryEntry(
                        group, value, "required", None, (), "not yet qualified"
                    )
                )
            else:
                inventory.append(
                    InventoryEntry(
                        group,
                        value,
                        "source-inapplicable",
                        None,
                        (),
                        "not emitted by this source",
                    )
                )
    return Manifest(
        schema=1,
        pins={"snapd": "2.71"},
        cases=(CASE,),
        inventory=tuple(inventory),
    )


def _result(*, passed: bool = True, run_dir: Path | None = None) -> CaseResult:
    artifacts = (run_dir or Path("/tmp")) / "cases" / CASE.id
    return CaseResult(
        case=CASE,
        started_at=0.0,
        finished_at=1.0,
        returncode=0 if passed else 1,
        artifacts=artifacts,
        capture_index=artifacts / "capture-index.json" if passed else None,
        marker_file=None,
        error=None if passed else "FAIL | step failed",
    )


def _fixture_catalog(tmp_path: Path, **overrides: Any) -> Path:
    config = tmp_path / "fde.json"
    config.write_text("{}", encoding="utf-8")
    config.chmod(0o600)
    entry: dict[str, Any] = {
        "config": str(config),
        "source-domain": "tpm-fde-test2",
        "suite": "tests/desktop-security-center",
    }
    entry.update(overrides)
    path = tmp_path / "fixtures.json"
    path.write_text(json.dumps({"fixtures": {"default": entry}}), encoding="utf-8")
    return path


def test_load_fixtures_requires_private_complete_entries(tmp_path: Path) -> None:
    fixtures = load_fixtures(_fixture_catalog(tmp_path))
    assert fixtures["default"]["source-domain"] == "tpm-fde-test2"
    assert fixtures["default"]["suite"] == "tests/desktop-security-center"


def test_load_fixtures_rejects_unknown_and_missing_fields(tmp_path: Path) -> None:
    with pytest.raises(SuiteError, match="unknown fields"):
        load_fixtures(_fixture_catalog(tmp_path, extra="value"))
    path = tmp_path / "missing.json"
    path.write_text(
        json.dumps({"fixtures": {"default": {"config": "/nonexistent"}}}),
        encoding="utf-8",
    )
    with pytest.raises(SuiteError, match="missing fields"):
        load_fixtures(path)


def test_load_fixtures_rejects_a_missing_or_shared_configuration(
    tmp_path: Path,
) -> None:
    path = _fixture_catalog(tmp_path)
    config = tmp_path / "fde.json"
    config.chmod(0o644)
    with pytest.raises(SuiteError, match="accessible by other users"):
        load_fixtures(path)
    config.unlink()
    with pytest.raises(SuiteError, match="configuration is missing"):
        load_fixtures(path)


def test_load_fixtures_rejects_an_empty_catalog(tmp_path: Path) -> None:
    path = tmp_path / "fixtures.json"
    path.write_text('{"fixtures": {}}', encoding="utf-8")
    with pytest.raises(SuiteError, match="no fixtures"):
        load_fixtures(path)


def test_runner_command_passes_the_private_configuration(
    tmp_path: Path,
) -> None:
    fixture = {
        "config": str(tmp_path / "fde.json"),
        "source-domain": "tpm-fde-test2",
        "suite": "tests/desktop-security-center",
        "connection-uri": "qemu:///session",
        "pool-name": "pool",
        "pool-dir": str(tmp_path / "pool"),
        "swtpm-state-dir": str(tmp_path / "swtpm"),
    }
    command = _runner_command(CASE, fixture, tmp_path / "out", python="python3")
    assert command[:3] == ["python3", "-m", "ubuntu_gui_testing_runner"]
    assert command[command.index("--robot-test") + 1] == CASE.robot_test
    assert command[command.index("--test") + 1] == CASE.suite
    assert "--connection-uri" in command
    assert "--swtpm-state-dir" in command


def test_diagnose_prefers_a_robot_failure_line() -> None:
    output = "\n".join(
        [
            "noise",
            "| FAIL | the change did not complete",
            "more noise",
        ]
    )
    assert _diagnose(output) == "| FAIL | the change did not complete"
    assert _diagnose("first\nsecond\n") == "second"
    assert _diagnose("") == "the case failed without a diagnostic"


def test_diagnose_prefers_the_root_cause_over_a_teardown_error() -> None:
    output = "\n".join(
        [
            "libvirt: Storage Driver error : inaccessible backing store",
            "ERROR:ubuntu_gui_testing_runner.base:Failed to delete NVRAM volume",
            "Traceback (most recent call last):",
            '  File "image_runner.py", line 234, in _create_overlay',
            "libvirt.libvirtError: inaccessible backing store volume",
            "During handling of the above exception, another exception occurred:",
            "Traceback (most recent call last):",
            "libvirt.libvirtError: Storage volume not found",
        ]
    )
    assert _diagnose(output) == (
        "libvirt.libvirtError: inaccessible backing store volume"
    )


def test_run_case_requires_authoritative_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        fde_suite,
        "_runner_command",
        lambda *args, **kwargs: [sys.executable, "-c", "pass"],
    )
    result = run_case(
        CASE,
        {"config": "x", "source-domain": "y", "suite": "z"},
        tmp_path,
    )
    assert result.returncode == 1
    assert result.error == "the case produced no authoritative capture"
    assert (tmp_path / "cases" / CASE.id / "runner.log").is_file()


def test_run_case_reports_a_failure_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = "import sys; print('| FAIL | the clone did not boot'); sys.exit(1)"
    monkeypatch.setattr(
        fde_suite,
        "_runner_command",
        lambda *args, **kwargs: [sys.executable, "-c", script],
    )
    result = run_case(
        CASE,
        {"config": "x", "source-domain": "y", "suite": "z"},
        tmp_path,
    )
    assert result.returncode == 1
    assert not result.passed
    assert result.error == "| FAIL | the clone did not boot"


def _case_with_capture(
    run_dir: Path,
    case: Case,
    specs: list[tuple[tuple[int, int, int], float, float]],
    *,
    markers: list[dict[str, Any]] | None = None,
) -> CaseResult:
    capture = run_dir / "cases" / case.id / "capture"
    frames: list[dict[str, Any]] = []
    for index, (colour, start, end) in enumerate(specs):
        path = synthetic_frame(capture / f"frame-{index:07d}.png", 32, 20, colour)
        frames.append({"path": path.name, "started_at": start, "ended_at": end})
    index_path = run_dir / "cases" / case.id / "capture-index.json"
    index_path.write_text(
        json.dumps({"frames": frames, "events": []}), encoding="utf-8"
    )
    marker_file = run_dir / "cases" / case.id / "markers.jsonl"
    if markers:
        marker_file.write_text(
            "\n".join(json.dumps(marker) for marker in markers) + "\n",
            encoding="utf-8",
        )
    return CaseResult(
        case=case,
        started_at=specs[0][1],
        finished_at=specs[-1][2],
        returncode=0,
        artifacts=run_dir / "cases" / case.id,
        capture_index=index_path,
        marker_file=marker_file if markers else None,
    )


def test_combined_index_adds_a_labelled_gap_between_cases(
    tmp_path: Path,
) -> None:
    second = Case(
        id="case-2",
        suite=CASE.suite,
        test=CASE.test,
        robot_test=CASE.robot_test,
        fixture=CASE.fixture,
        context="degraded",
        action="repair",
        continuation="reboot",
        execution_class="vm",
        oracles=("no-mutation",),
        recording=True,
    )
    results = [
        _case_with_capture(
            tmp_path,
            CASE,
            [((10, 10, 10), 0.0, 1.0), ((20, 20, 20), 1.0, 2.0)],
            markers=[
                {
                    "event": "scenario",
                    "at": 0.5,
                    "scenario": "clear-tpm",
                    "title": "TPM clear",
                    "outcome": "passed",
                }
            ],
        ),
        _case_with_capture(
            tmp_path,
            second,
            [((10, 10, 10), 6.0, 7.0), ((20, 20, 20), 7.0, 8.0)],
        ),
    ]
    index_path = build_combined_index(
        results, tmp_path / "edited" / "combined.json", width=32, height=20
    )
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(payload["frames"]) == 5
    gap = payload["frames"][2]
    assert Path(gap["path"]).is_file()
    assert gap["started_at"] == 2.0
    assert gap["ended_at"] == 6.0
    gaps = [
        event
        for event in payload["events"]
        if event["event"] == "wait-start" and "no target display" in event["reason"]
    ]
    assert len(gaps) == 1
    chapters = json.loads(
        (tmp_path / "edited" / "scenarios.json").read_text(encoding="utf-8")
    )["chapters"]
    assert [chapter["scenario"] for chapter in chapters] == [
        "clear-tpm",
        "between-cases",
        "case-2",
    ]
    spans = frame_spans(read_index(index_path))
    assert spans[0].start == 0.0
    assert spans[-1].end == 8.0


def test_combined_index_rejects_a_run_without_capture(tmp_path: Path) -> None:
    with pytest.raises(SuiteError, match="no case produced a capture index"):
        build_combined_index(
            [_result(passed=False)], tmp_path / "combined.json", width=32, height=20
        )


def test_report_is_complete_only_for_a_full_run_without_gaps(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    result = _result(run_dir=tmp_path)
    audit: dict[str, Any] = {"frames": 10}
    report = fde_suite._write_report(
        tmp_path, manifest, [result], full=True, video_audit=audit
    )
    assert report["complete"] is True
    assert report["incomplete"] == []
    assert (tmp_path / "coverage.json").stat().st_mode & 0o077 == 0
    assert "Outcome: complete" in (tmp_path / "report.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("revision", "rehearsal"), [("x2", True), (None, True), ("233", False)]
)
def test_report_stamps_a_side_loaded_build_as_a_rehearsal(
    tmp_path: Path, revision: str | None, rehearsal: bool
) -> None:
    pins = (
        {"snapd": "2.78"}
        if revision is None
        else {"snapd": "2.78", "security-center": revision}
    )
    manifest = replace(_manifest(), pins=pins)

    report = fde_suite._write_report(
        tmp_path, manifest, [_result(run_dir=tmp_path)], full=True, video_audit={}
    )

    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert report["rehearsal"] is rehearsal
    assert ("REHEARSAL" in text) is rehearsal
    assert ("REHEARSAL" in fde_suite._run_intro(manifest, tmp_path, [])) is rehearsal


def test_report_stays_incomplete_for_a_partial_run(tmp_path: Path) -> None:
    report = fde_suite._write_report(
        tmp_path, _manifest(), [_result(run_dir=tmp_path)], full=False, video_audit={}
    )
    assert report["complete"] is False
    assert "Mode: PARTIAL" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_report_lists_required_values_and_unexecuted_cases(
    tmp_path: Path,
) -> None:
    manifest = _manifest(required=True)
    reasons = _incomplete_reasons(manifest, [])
    assert any("inventory value still requires execution" in item for item in reasons)
    assert any("required case was not executed" in item for item in reasons)
    report = fde_suite._write_report(tmp_path, manifest, [], full=True, video_audit={})
    assert report["complete"] is False
    assert "Still required" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_report_records_a_failed_case(tmp_path: Path) -> None:
    reasons = _incomplete_reasons(
        _manifest(), [_result(passed=False, run_dir=tmp_path)]
    )
    assert any("required case failed" in item for item in reasons)


def test_report_states_coverage_video_and_source_inapplicable(
    tmp_path: Path,
) -> None:
    audit: dict[str, Any] = {
        "frames": 90,
        "duration": 3.0,
        "source_duration": 30.0,
        "canvas": "1280x800",
        "chapters": 2,
        "idle_intervals": [
            {"edited_seconds": 2.5},
            {"edited_seconds": 1.0},
        ],
        "redaction_intervals": [{"reason": "recovery key"}],
    }
    report = fde_suite._write_report(
        tmp_path,
        _manifest(),
        [_result(run_dir=tmp_path)],
        full=True,
        video_audit=audit,
    )
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert report["complete"] is True
    assert "## Coverage" in text
    assert "| source-inapplicable |" in text
    assert "## Video" in text
    assert "1280x800" in text
    assert "longest edited interval 2.5s" in text
    assert "## Source-inapplicable" in text
    assert "not emitted by this source" in text


def test_combined_index_namespaces_marker_ids(tmp_path: Path) -> None:
    second = Case(
        id="case-2",
        suite=CASE.suite,
        test=CASE.test,
        robot_test=CASE.robot_test,
        fixture=CASE.fixture,
        context="degraded",
        action="repair",
        continuation="reboot",
        execution_class="vm",
        oracles=("no-mutation",),
        recording=True,
    )
    results = [
        _case_with_capture(
            tmp_path,
            CASE,
            [((10, 10, 10), 0.0, 2.0)],
            markers=[
                {"event": "wait-start", "at": 0.1, "wait-id": "w1", "reason": "a"},
                {"event": "wait-end", "at": 0.9, "wait-id": "w1"},
                {
                    "event": "sensitive-start",
                    "at": 0.2,
                    "sensitive-id": "s1",
                    "reason": "recovery key",
                },
                {"event": "sensitive-end", "at": 0.8, "sensitive-id": "s1"},
            ],
        ),
        _case_with_capture(
            tmp_path,
            second,
            [((20, 20, 20), 6.0, 8.0)],
            markers=[
                {"event": "wait-start", "at": 6.1, "wait-id": "w1", "reason": "b"},
                {"event": "wait-end", "at": 6.9, "wait-id": "w1"},
            ],
        ),
    ]
    index_path = build_combined_index(
        results, tmp_path / "edited" / "combined.json", width=32, height=20
    )
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    waits = [
        event["wait-id"]
        for event in payload["events"]
        if event["event"] == "wait-start" and str(event["wait-id"]).startswith("case-")
    ]
    assert waits == ["case-1:w1", "case-2:w1"]
    sensitive = [
        event["sensitive-id"]
        for event in payload["events"]
        if event["event"] == "sensitive-start"
    ]
    assert sensitive == ["case-1:s1"]


def test_report_discloses_executed_snapd_test_mode(tmp_path: Path) -> None:
    mode_case = replace(CASE, snapd_test_mode=True)
    result = CaseResult(
        case=mode_case,
        started_at=0.0,
        finished_at=1.0,
        returncode=0,
        artifacts=tmp_path / "cases" / mode_case.id,
        capture_index=tmp_path / "cases" / mode_case.id / "capture-index.json",
        marker_file=None,
        error=None,
    )
    manifest = Manifest(
        schema=1,
        pins={"snapd": "2.71"},
        cases=(mode_case,),
        inventory=_manifest().inventory,
    )
    report = fde_suite._write_report(
        tmp_path, manifest, [result], full=False, video_audit={}
    )
    assert report["snapd_test_mode"] == {
        "declared": [CASE.id],
        "executed": [CASE.id],
    }
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "## snapd test mode" in text
    assert f"- {CASE.id}" in text


def test_combined_canvas_uses_the_largest_capture(tmp_path: Path) -> None:
    result = _case_with_capture(tmp_path, CASE, [((10, 10, 10), 0.0, 1.0)])
    assert result.capture_index is not None
    large = synthetic_frame(
        result.artifacts / "capture" / "large.png", 64, 40, (20, 20, 20)
    )
    index = json.loads(result.capture_index.read_text(encoding="utf-8"))
    index["frames"].append({"path": large.name, "started_at": 1.0, "ended_at": 2.0})
    result.capture_index.write_text(json.dumps(index), encoding="utf-8")
    assert fde_suite._capture_canvas([result]) == (64, 40)


def test_intro_identifies_the_run_build_and_test_mode(tmp_path: Path) -> None:
    mode_case = replace(CASE, snapd_test_mode=True)
    manifest = Manifest(
        schema=1,
        pins={"snapd": "2.78", "security-center": "x2"},
        cases=(mode_case,),
        inventory=(),
    )
    result = CaseResult(
        case=mode_case,
        started_at=0.0,
        finished_at=1.0,
        returncode=0,
        artifacts=tmp_path / "cases" / mode_case.id,
        capture_index=None,
        marker_file=None,
        error=None,
    )
    assert fde_suite._run_intro(manifest, tmp_path / "run-1", [result]) == (
        "run run-1 | snapd 2.78 | Security Center x2 | REHEARSAL, not evidence | "
        "snapd test mode: 1 executed case(s)"
    )
