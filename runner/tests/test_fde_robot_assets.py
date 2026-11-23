"""Static checks for the Robot suite's image assets.

Yarf resolves an image reference such as ``${Y}/generic/add-button.png`` from
the suite's image directory. A missing file does not fail at suite load time;
it fails only when the keyword reaches that click, after a real repair has
already run. This check makes the missing asset a fast test failure instead.
"""

from __future__ import annotations

import re
from pathlib import Path

SUITE = Path(__file__).resolve().parents[2] / "tests/desktop-security-center"
IMAGE_REFERENCE = re.compile(r"\$\{Y\}/(generic/[A-Za-z0-9_.-]+\.png)")


def _references() -> set[tuple[Path, str]]:
    references: set[tuple[Path, str]] = set()
    patterns = (
        "*.resource",
        "desktop-security-center-reprovision/*.resource",
        "desktop-security-center-reprovision/*.robot",
    )
    for pattern in patterns:
        for path in SUITE.glob(pattern):
            text = path.read_text(encoding="utf-8")
            for match in IMAGE_REFERENCE.finditer(text):
                references.add((path, match.group(1)))
    return references


def test_every_referenced_generic_image_exists() -> None:
    references = _references()
    assert references, "the suite no longer references any generic image"
    missing = sorted(
        f"{relative} referenced by {path.name}"
        for path, relative in references
        if not (SUITE / relative).is_file()
    )
    assert not missing, "missing Yarf image assets: " + ", ".join(missing)
