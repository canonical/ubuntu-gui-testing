"""Aggregate TPM-FDE run: read the manifest, execute each case, check coverage.

Cases run one after another, one disposable clone each. A --case run exits
successfully when its cases pass. A --full run exits successfully only when
every case passed, no inventory value is required or blocked, and the video
audit passed. A partial selection stays visibly partial.

The aggregate never invents execution evidence. It records the runner exit
status, the per-case artifact directory, the capture index and the marker file,
and it refuses to claim full coverage while the manifest still contains a
required or blocked value.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ubuntu_gui_testing_runner.fde_capture import synthetic_frame
from ubuntu_gui_testing_runner.fde_coverage import (
    Case,
    Manifest,
    ManifestError,
    inventory_size,
    load_manifest,
)
from ubuntu_gui_testing_runner.fde_video import (
    FPS,
    VideoError,
    attach_chapters,
    chapter_labels,
    frame_spans,
    plan_edit,
    png_size,
    read_index,
    redaction_labels,
    render,
    render_labels,
    verify,
    write_chapters,
)

RUNNER_PACKAGE: Final = "ubuntu_gui_testing_runner"
DEFAULT_TIMEOUT: Final = 4 * 60 * 60.0
GAP_SECONDS: Final = 1.0
EXECUTABLE_CLASSES: Final = frozenset({"vm"})


class SuiteError(RuntimeError):
    """The aggregate run cannot be executed or reported honestly."""


@dataclass
class CaseResult:
    case: Case
    started_at: float
    finished_at: float
    returncode: int
    artifacts: Path
    capture_index: Path | None
    marker_file: Path | None
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.returncode == 0 and self.error is None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.case.id,
            "execution_class": self.case.execution_class,
            "action": self.case.action,
            "fixture": self.case.fixture,
            "suite": self.case.suite,
            "test": self.case.test,
            "robot_test": self.case.robot_test,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": self.finished_at - self.started_at,
            "returncode": self.returncode,
            "passed": self.passed,
            "artifacts": str(self.artifacts),
            "capture_index": (
                str(self.capture_index) if self.capture_index is not None else None
            ),
            "marker_file": (
                str(self.marker_file) if self.marker_file is not None else None
            ),
            "error": self.error,
        }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SuiteError(f"cannot read {path}") from error
    if not isinstance(payload, dict):
        raise SuiteError(f"{path} is not an object")
    return payload


def load_fixtures(path: Path) -> dict[str, dict[str, Any]]:
    """Load the private fixture catalog, refusing anything incomplete."""
    raw = _read_json(Path(path))
    fixtures = raw.get("fixtures")
    if not isinstance(fixtures, dict) or not fixtures:
        raise SuiteError("the fixture catalog has no fixtures")
    required = {"config", "source-domain", "suite"}
    allowed = required | {
        "connection-uri",
        "pool-name",
        "pool-dir",
        "swtpm-state-dir",
    }
    validated: dict[str, dict[str, Any]] = {}
    for name, entry in fixtures.items():
        if not isinstance(name, str) or not name.strip():
            raise SuiteError("fixture names must be non-empty strings")
        if not isinstance(entry, dict):
            raise SuiteError(f"fixture {name!r} must be an object")
        unknown = sorted(set(entry) - allowed)
        if unknown:
            raise SuiteError(f"fixture {name!r} has unknown fields: {unknown}")
        missing = sorted(required - set(entry))
        if missing:
            raise SuiteError(f"fixture {name!r} is missing fields: {missing}")
        for key, value in entry.items():
            if not isinstance(value, str) or not value.strip():
                raise SuiteError(
                    f"fixture {name!r} field {key!r} must be a non-empty string"
                )
        config_path = Path(entry["config"])
        if not config_path.is_file():
            raise SuiteError(f"fixture {name!r} configuration is missing")
        if config_path.stat().st_mode & 0o077:
            raise SuiteError(
                f"fixture {name!r} configuration is accessible by other users"
            )
        validated[name] = dict(entry)
    return validated


def _repo_root() -> Path:
    # <repo>/runner/ubuntu_gui_testing_runner/fde_suite.py
    return Path(__file__).resolve().parents[2]


def _runner_command(
    case: Case,
    fixture: dict[str, Any],
    artifacts: Path,
    *,
    python: str,
) -> list[str]:
    command = [
        python,
        "-m",
        RUNNER_PACKAGE,
        "--suite",
        fixture["suite"],
        "--test",
        case.suite,
        "--robot-test",
        case.robot_test,
        "--source-domain",
        fixture["source-domain"],
        "--fde-config",
        fixture["config"],
        "--artifacts-dir",
        str(artifacts),
    ]
    for flag, key in (
        ("--connection-uri", "connection-uri"),
        ("--pool-name", "pool-name"),
        ("--pool-dir", "pool-dir"),
        ("--swtpm-state-dir", "swtpm-state-dir"),
    ):
        if key in fixture:
            command.extend([flag, fixture[key]])
    return command


def _environment() -> dict[str, str]:
    env = os.environ.copy()
    package_root = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = os.pathsep.join(
        [package_root, env["PYTHONPATH"]] if env.get("PYTHONPATH") else [package_root]
    )
    return env


def run_case(
    case: Case,
    fixture: dict[str, Any],
    run_dir: Path,
    *,
    python: str = sys.executable,
    timeout: float = DEFAULT_TIMEOUT,
) -> CaseResult:
    """Run one case in its own clone and retain its recording and markers."""
    artifacts = run_dir / "cases" / case.id
    artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    command = _runner_command(case, fixture, artifacts, python=python)
    started = time.monotonic()
    error: str | None = None
    returncode = 1
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, never a shell
            command,
            env=_environment(),
            cwd=str(_repo_root()),
            timeout=timeout,
            check=False,
            capture_output=True,
            text=True,
        )
        returncode = completed.returncode
        (artifacts / "runner.log").write_text(
            completed.stdout + completed.stderr, encoding="utf-8"
        )
        if returncode != 0:
            error = _diagnose(completed.stdout + completed.stderr)
    except subprocess.TimeoutExpired:
        error = f"the case exceeded its {timeout:g}s deadline"
    except OSError as failure:
        error = f"the runner could not start: {failure}"
    finished = time.monotonic()

    capture = artifacts / "capture-index.json"
    markers = artifacts / "markers.jsonl"
    if returncode == 0 and not capture.is_file():
        error = "the case produced no authoritative capture"
        returncode = 1
    return CaseResult(
        case=case,
        started_at=started,
        finished_at=finished,
        returncode=returncode,
        artifacts=artifacts,
        capture_index=capture if capture.is_file() else None,
        marker_file=markers if markers.is_file() else None,
        error=error,
    )


def _diagnose(output: str) -> str:
    """Extract the root failure without dumping OCR or credentials.

    Teardown errors are logged after the real cause, so a reverse scan can
    report a cleanup failure as the reason a case failed. Robot's own failure
    line wins; otherwise the first exception line, which is the root cause.
    """
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in lines:
        if "| FAIL |" in line or line.startswith("FAIL"):
            return line[:400]
    for line in lines:
        if re.match(r"^[A-Za-z_][\w.]*(Error|Exception): ", line):
            return line[:400]
    return lines[-1][:400] if lines else "the case failed without a diagnostic"


def _marker_events(path: Path | None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if path is None:
        return events
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return events
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("at"), (int, float)):
            events.append(payload)
    return events


def _wait_events(at: float, reason: str, identifier: str) -> list[dict[str, Any]]:
    return [
        {"event": "wait-start", "at": at, "wait-id": identifier, "reason": reason},
        {"event": "wait-end", "at": at, "wait-id": identifier},
    ]


def _namespace_markers(
    events: list[dict[str, Any]], case_id: str
) -> list[dict[str, Any]]:
    """Keep per-case marker identifiers unique on the combined timeline.

    Every case's marker writer starts at w1/s1, so merging case events without
    this prefix would pair one case's end with another case's start.
    """
    for event in events:
        for field in ("wait-id", "sensitive-id"):
            value = event.get(field)
            if isinstance(value, str) and value:
                event[field] = f"{case_id}:{value}"
    return events


def _case_chapters(
    result: CaseResult,
    events: list[dict[str, Any]],
    first: float,
    last: float,
) -> list[dict[str, Any]]:
    """Map a case's scenario markers onto its captured interval."""
    markers: list[dict[str, Any]] = []
    for event in events:
        if event.get("event") != "scenario":
            continue
        at = event.get("at")
        if isinstance(at, bool) or not isinstance(at, (int, float)):
            continue
        markers.append(
            {
                "scenario": str(event.get("scenario") or result.case.id),
                "title": str(event.get("title") or result.case.context),
                "outcome": str(event.get("outcome") or "unknown"),
                "at": min(max(float(at), first), last),
            }
        )
    markers.sort(key=lambda item: item["at"])
    if not markers:
        return [
            {
                "scenario": result.case.id,
                "title": (
                    f"{result.case.context} | snapd {result.case.action} | "
                    f"{result.case.robot_test}"
                ),
                "outcome": "passed" if result.passed else "failed",
                "start": first,
                "end": last,
            }
        ]
    chapters: list[dict[str, Any]] = []
    for position, marker in enumerate(markers):
        start = max(marker["at"], first)
        end = markers[position + 1]["at"] if position + 1 < len(markers) else last
        if end <= start:
            continue
        chapters.append(
            {
                "scenario": marker["scenario"],
                "title": marker["title"],
                "outcome": marker["outcome"],
                "start": start,
                "end": end,
            }
        )
    return chapters


def build_combined_index(
    results: list[CaseResult],
    output: Path,
    *,
    width: int,
    height: int,
) -> Path:
    """Merge per-case capture into one absolute timeline with explicit gaps.

    Each case recorded the same host monotonic clock. Inter-case gaps have no
    target display because each case owns a separate clone, so they are
    represented by a labelled synthetic frame rather than removed.
    """
    frames: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    chapters: list[dict[str, Any]] = []
    previous_end: float | None = None
    captured = [result for result in results if result.capture_index is not None]
    if not captured:
        raise SuiteError("no case produced a capture index")
    for result in captured:
        if result.capture_index is None:  # kept for the type checker
            continue
        index = read_index(result.capture_index)
        spans = frame_spans(index)
        first = spans[0].start
        last = spans[-1].end
        if previous_end is not None and first - previous_end > GAP_SECONDS:
            gap_path = output.parent / f"gap-{result.case.id}.png"
            synthetic_frame(gap_path, width, height, rgb=(24, 24, 24))
            frames.append(
                {
                    "path": str(gap_path),
                    "started_at": previous_end,
                    "ended_at": first,
                }
            )
            label = f"no target display between cases ({first - previous_end:.0f}s)"
            events.extend(_wait_events(previous_end, label, str(first)))
            chapters.append(
                {
                    "scenario": "between-cases",
                    "title": f"no target display before {result.case.id}",
                    "outcome": "not recorded",
                    "start": previous_end,
                    "end": first,
                }
            )
        capture_dir = result.artifacts / "capture"
        for span in spans:
            path = span.path if span.path.is_absolute() else capture_dir / span.path
            frames.append(
                {
                    "path": str(path),
                    "started_at": span.start,
                    "ended_at": span.end,
                }
            )
        case_events = [
            event for event in (index.get("events") or []) if isinstance(event, dict)
        ]
        case_events.extend(_marker_events(result.marker_file))
        case_events = _namespace_markers(case_events, result.case.id)
        events.extend(case_events)
        chapters.extend(_case_chapters(result, case_events, first, last))
        previous_end = last
    frames.sort(key=lambda frame: frame["started_at"])
    payload = {"frames": frames, "events": events}
    output.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    output.chmod(0o600)
    chapters_path = output.with_name("scenarios.json")
    chapters_path.write_text(
        json.dumps({"chapters": chapters}, indent=1), encoding="utf-8"
    )
    chapters_path.chmod(0o600)
    return output


def _capture_canvas(results: list[CaseResult]) -> tuple[int, int]:
    """Pick the largest captured frame as the combined video canvas.

    Firmware and the desktop can use different display modes. Sizing the
    video from the first frame would downscale the desktop to the firmware's
    mode and make the application text unreadable, so the largest frame wins
    and smaller frames are padded or scaled into it.
    """
    best: tuple[int, int] | None = None
    best_area = 0
    for result in results:
        if result.capture_index is None:
            continue
        index = read_index(result.capture_index)
        entries = index.get("frames")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                continue
            name = Path(entry["path"])
            path = name if name.is_absolute() else result.artifacts / "capture" / name
            try:
                width, height = png_size(path)
            except (OSError, VideoError):
                continue
            if width * height > best_area:
                best_area = width * height
                best = (width, height)
    if best is None:
        raise SuiteError("no captured frame is available for the combined video")
    return best


def _is_rehearsal(manifest: Manifest) -> bool:
    # Only a store snap has a decimal revision; a local one was side-loaded.
    return not str(manifest.pins.get("security-center", "")).isdecimal()


def _run_intro(manifest: Manifest, run_dir: Path, results: list[CaseResult]) -> str:
    """Identify the run and build on the video itself."""
    parts = [
        f"run {run_dir.name}",
        f"snapd {manifest.pins.get('snapd', 'unknown')}",
        f"Security Center {manifest.pins.get('security-center', 'unknown')}",
    ]
    if _is_rehearsal(manifest):
        parts.append("REHEARSAL, not evidence")
    test_mode = sum(1 for result in results if result.case.snapd_test_mode)
    if test_mode:
        parts.append(f"snapd test mode: {test_mode} executed case(s)")
    return " | ".join(parts)


def edit_run(
    results: list[CaseResult],
    run_dir: Path,
    *,
    intro: str = "",
) -> dict[str, Any]:
    """Build, render, chapter and verify the single combined run video."""
    edited = run_dir / "edited"
    edited.mkdir(parents=True, exist_ok=True, mode=0o700)
    width, height = _capture_canvas(results)
    index_path = build_combined_index(
        results, edited / "combined-index.json", width=width, height=height
    )
    index = read_index(index_path)
    spans = frame_spans(index)
    chapters = _read_json(edited / "scenarios.json").get("chapters") or []
    if not isinstance(chapters, list):
        raise SuiteError("the combined chapter list is malformed")
    plan = plan_edit(index, spans, chapters, fps=FPS)
    plan.to_json(edited / "edit-map.json")
    redactions = [
        {
            "start": redaction.output_start,
            "end": redaction.output_end,
            "box": [0, 0, width, height],
        }
        for redaction in plan.redactions
    ]
    raw = render(
        edited,
        plan,
        edited / "full-run.raw.mp4",
        labels=[
            *render_labels(plan),
            *chapter_labels(plan),
            *redaction_labels(plan),
        ],
        footer_labels=([(0.0, min(8.0, plan.output_duration), intro)] if intro else []),
        redactions=redactions,
        size=(width, height),
    )
    metadata = edited / "chapters.ffmeta"
    write_chapters(plan, metadata)
    final = attach_chapters(raw, metadata, edited / "full-run.mp4")
    audit = verify(plan, final)
    audit["source_duration"] = plan.source_duration
    audit["output_duration"] = plan.output_duration
    audit["chapters"] = len(plan.chapters)
    audit["canvas"] = f"{width}x{height}"
    (edited / "timing-audit.json").write_text(
        json.dumps(audit, indent=1), encoding="utf-8"
    )
    (edited / "timing-audit.json").chmod(0o600)
    return audit


def _case_by_id(manifest: Manifest, identifier: str) -> Case:
    for case in manifest.cases:
        if case.id == identifier:
            return case
    raise SuiteError(f"manifest has no case {identifier!r}")


def _incomplete_reasons(manifest: Manifest, results: list[CaseResult]) -> list[str]:
    reasons = list(manifest.incomplete_reasons())
    by_id = {result.case.id: result for result in results}
    for case in manifest.cases:
        result = by_id.get(case.id)
        if result is None:
            reasons.append(f"required case was not executed: {case.id}")
        elif not result.passed:
            reasons.append(f"required case failed: {case.id}: {result.error or ''}")
    return reasons


def _write_report(
    run_dir: Path,
    manifest: Manifest,
    results: list[CaseResult],
    *,
    full: bool,
    video_audit: dict[str, Any] | None,
) -> dict[str, Any]:
    incomplete = _incomplete_reasons(manifest, results)
    test_mode_executed = [
        result.case.id for result in results if result.case.snapd_test_mode
    ]
    payload = {
        "run": run_dir.name,
        "full": full,
        "complete": full and not incomplete and video_audit is not None,
        "inventory_values": inventory_size(),
        "pins": manifest.pins,
        "rehearsal": _is_rehearsal(manifest),
        "cases": [result.to_json() for result in results],
        "incomplete": incomplete,
        "video": video_audit,
        "snapd_test_mode": {
            "declared": [case.id for case in manifest.cases if case.snapd_test_mode],
            "executed": test_mode_executed,
        },
    }
    (run_dir / "coverage.json").write_text(
        json.dumps(payload, indent=1), encoding="utf-8"
    )
    (run_dir / "coverage.json").chmod(0o600)
    lines = [
        f"# TPM-FDE run {run_dir.name}",
        "",
        f"Mode: {'FULL' if full else 'PARTIAL'}",
        f"Outcome: {'complete' if payload['complete'] else 'INCOMPLETE'}",
        (
            "Provenance: REHEARSAL, side-loaded Security Center build; "
            "this run is not store evidence"
            if payload["rehearsal"]
            else "Provenance: store revision; this suite does not verify the channel"
        ),
        f"Inventory declarations: {payload['inventory_values']}",
        "",
        "Each executed case ran in its own disposable clone of the certified",
        "baseline; no case reused another case's disk or TPM state.",
        "",
        "## Coverage",
        "",
        "| disposition | inventory values |",
        "| --- | --- |",
    ]
    dispositions = Counter(entry.disposition for entry in manifest.inventory)
    for disposition in (
        "executed",
        "blocked",
        "source-inapplicable",
        "api-negative",
        "required",
    ):
        if disposition == "executed" or dispositions[disposition]:
            lines.append(f"| {disposition} | {dispositions[disposition]} |")
    lines.extend(
        [
            "",
            "| case | class | action | result |",
            "| --- | --- | --- | --- |",
        ]
    )
    for result in results:
        lines.append(
            f"| {result.case.id} | {result.case.execution_class} | "
            f"{result.case.action} | {'PASS' if result.passed else 'FAIL'} |"
        )
    if test_mode_executed:
        lines.extend(
            [
                "",
                "## snapd test mode",
                "",
                "These executed cases declare snapd's build-tagged test mode to",
                "reach a phase the production build cannot select:",
                "",
            ]
        )
        lines.extend(f"- {case_id}" for case_id in test_mode_executed)
    if video_audit:
        idle = video_audit.get("idle_intervals") or []
        redactions = video_audit.get("redaction_intervals") or []
        longest = max(
            (float(item["edited_seconds"]) for item in idle),
            default=0.0,
        )
        lines.extend(
            [
                "",
                "## Video",
                "",
                f"- `edited/full-run.mp4`: {video_audit.get('frames', 0)} frames at "
                f"{video_audit.get('canvas', 'the captured canvas')}, "
                f"{float(video_audit.get('duration', 0.0)):.1f}s from "
                f"{float(video_audit.get('source_duration', 0.0)):.1f}s captured",
                f"- {len(idle)} accelerated idle intervals; longest edited "
                f"interval {longest:.1f}s",
                f"- {len(redactions)} privacy-masked intervals",
                f"- {video_audit.get('chapters', 0)} scenario chapters; the edit "
                "map and timing audit are in `edited/`",
            ]
        )
    inapplicable = [
        entry
        for entry in manifest.inventory
        if entry.disposition == "source-inapplicable"
    ]
    if inapplicable:
        lines.extend(
            [
                "",
                "## Source-inapplicable",
                "",
                "These values do not occur in the target snapd source; they are",
                "listed separately and are not counted as passes.",
                "",
            ]
        )
        for entry in inapplicable:
            detail = f" ({entry.reason})" if entry.reason else ""
            lines.append(f"- {entry.group}/{entry.value}{detail}")
    if incomplete:
        lines.extend(["", "## Still required", ""])
        lines.extend(f"- {reason}" for reason in incomplete)
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (run_dir / "report.md").chmod(0o600)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the reviewed TPM-FDE state/action matrix"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--validate", action="store_true")
    group.add_argument("--case", action="append", default=[])
    group.add_argument("--full", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Run the remaining cases after a case fails",
    )
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
        fixtures = load_fixtures(args.fixtures)
    except (ManifestError, SuiteError) as error:
        print(f"invalid run definition: {error}", file=sys.stderr)
        return 2

    if args.validate:
        problems = [
            f"case {case.id} names unknown fixture {case.fixture!r}"
            for case in manifest.cases
            if case.fixture not in fixtures
        ]
        if problems:
            for problem in problems:
                print(problem, file=sys.stderr)
            return 2
        print(
            f"manifest ok: {len(manifest.cases)} cases, "
            f"{inventory_size()} declared inventory values, "
            f"{len(manifest.incomplete_inventory())} still requiring execution"
        )
        return 0

    if args.full:
        selected = list(manifest.cases)
    else:
        selected = []
        for identifier in args.case:
            case = _case_by_id(manifest, identifier)
            if case not in selected:
                selected.append(case)
    for case in selected:
        if case.fixture not in fixtures:
            print(
                f"case {case.id} names unknown fixture {case.fixture!r}",
                file=sys.stderr,
            )
            return 2
        if case.execution_class not in EXECUTABLE_CLASSES:
            print(
                f"case {case.id} is {case.execution_class}; this entrypoint "
                "executes VM cases only",
                file=sys.stderr,
            )
            return 2
        if not case.recording:
            print(
                f"case {case.id} is not marked for authoritative recording",
                file=sys.stderr,
            )
            return 2

    run_dir = args.artifacts_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    results: list[CaseResult] = []
    for case in selected:
        print(f"running {case.id} ...", flush=True)
        result = run_case(
            case,
            fixtures[case.fixture],
            run_dir,
            python=args.python,
            timeout=args.timeout,
        )
        results.append(result)
        print(
            f"{case.id}: {'PASS' if result.passed else 'FAIL'}"
            + (f" ({result.error})" if result.error else ""),
            flush=True,
        )
        if not result.passed and not args.keep_going:
            break

    video_audit: dict[str, Any] | None = None
    if results:
        try:
            video_audit = edit_run(
                results, run_dir, intro=_run_intro(manifest, run_dir, results)
            )
        except (VideoError, SuiteError) as error:
            print(f"video audit failed: {error}", file=sys.stderr)

    report = _write_report(
        run_dir, manifest, results, full=args.full, video_audit=video_audit
    )
    print(
        f"run {'complete' if report['complete'] else 'INCOMPLETE'}: "
        f"{len(results)} case(s) executed; see {run_dir / 'report.md'}",
        flush=True,
    )
    if args.full:
        return 0 if report["complete"] else 1
    return 0 if results and all(result.passed for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
