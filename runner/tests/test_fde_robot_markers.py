"""Static checks for the Robot suite's privacy markers.

The mask must cover every frame in which the generated recovery key can be on
screen. When the start marker followed the click that painted the dialog, the
frame just before the mask showed the key in clear text; when the end marker
came directly after the Repair click, frames taken while the dialog was still
on screen were left unmasked. These checks make both orderings a fast test
failure instead of a privacy defect that only a frame-by-frame audit would
catch.
"""

from __future__ import annotations

from pathlib import Path

FLOWS = (
    Path(__file__).resolve().parents[2]
    / "tests/desktop-security-center/desktop-security-center-reprovision"
)


def _significant_lines(path: Path) -> list[tuple[int, str]]:
    """Return numbered Robot lines that carry a keyword or argument."""
    lines: list[tuple[int, str]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append((number, line))
    return lines


def _can_paint_the_key(line: str) -> bool:
    """Return whether a Robot step may put the generated key on screen."""
    return (
        line.startswith("Ignore Virtual Machine Warning")
        or line.startswith("Clear Issue")
        or line.startswith("Continue Past Existing Authentication Warning")
        or line.startswith("Answer Repair Prompts")
        or (line.startswith("Wait For Repair Text") and "New recovery key" in line)
    )


def test_every_generated_key_is_masked_before_the_dialog_can_paint() -> None:
    flows = [
        path
        for path in sorted(FLOWS.glob("*.robot"))
        if "Acknowledge Saved Recovery Key" in path.read_text(encoding="utf-8")
    ]
    assert flows, "the suite no longer saves and acknowledges recovery keys"
    for path in flows:
        lines = _significant_lines(path)
        starts = [
            (number, line) for number, line in lines if line.startswith("Start Repair")
        ]
        hides = [
            number
            for number, line in lines
            if line.startswith("Hide Recovery Key In Recording")
        ]
        assert starts, f"{path.name}: a repair flow never starts a repair"
        assert len(hides) == len(starts), (
            f"{path.name}: {len(starts)} repair start(s) but {len(hides)} "
            "sensitive-start marker(s)"
        )
        for start_number, _ in starts:
            following = [
                (number, line) for number, line in lines if number > start_number
            ]
            paint = next(
                (
                    (number, line)
                    for number, line in following
                    if _can_paint_the_key(line)
                ),
                None,
            )
            assert paint is not None, (
                f"{path.name}:{start_number}: the flow never reaches a step "
                "that can paint the recovery key"
            )
            paint_number, paint_line = paint
            assert any(
                start_number < hide_number < paint_number for hide_number in hides
            ), (
                f"{path.name}:{paint_number}: the sensitive-start marker must "
                "come after Start Repair and before the first step that can "
                f"paint the key ({paint_line!r})"
            )


def test_every_repair_flow_unmasks_after_the_key_dialog_closes() -> None:
    flows = [
        path
        for path in sorted(FLOWS.glob("*.robot"))
        if "Acknowledge Saved Recovery Key" in path.read_text(encoding="utf-8")
    ]
    assert flows, "the suite no longer saves and acknowledges recovery keys"
    for path in flows:
        stage = None
        for number, raw in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = raw.strip()
            if line.startswith("Confirm Repair"):
                stage = "confirm"
            elif line.startswith("Wait For Recovery Key Dialog To Close"):
                assert stage == "confirm", (
                    f"{path.name}:{number}: the dialog wait does not follow "
                    "the repair confirmation"
                )
                stage = "wait"
            elif line.startswith("Show Recording Again"):
                assert stage == "wait", (
                    f"{path.name}:{number}: the mask ends before the key dialog "
                    "is confirmed closed"
                )
                stage = None
        assert stage is None, f"{path.name}: a repair flow leaves the mask open"
