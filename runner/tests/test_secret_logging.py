from __future__ import annotations

import base64
import re
import zlib
from io import StringIO
from pathlib import Path

import pytest
from robot import run  # type: ignore[import-untyped]  # Robot has no type marker.

KEY = "12345-12345-12345-12345-12345-12345-12345-12345"
# A real timeout quotes the whole screen, which is long enough for Robot's log
# and report models to store it base64-encoded and compressed.
SCREEN = "Text read on screen: " + " ".join(["recovery key"] * 12) + " " + KEY
SECURITY_CENTER_DIR = (
    Path(__file__).resolve().parents[2] / "tests/desktop-security-center"
)
TPM_FDE_RESOURCE = (
    SECURITY_CENTER_DIR / "desktop-security-center-reprovision/tpm-fde.resource"
)


_JS_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}


def _js_unescape(text: str) -> str:
    """Decode a JavaScript string literal body, including Robot's \\xNN escapes."""
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue
        escape = text[index + 1]
        if escape == "x":
            out.append(chr(int(text[index + 2 : index + 4], 16)))
            index += 4
        elif escape == "u":
            out.append(chr(int(text[index + 2 : index + 6], 16)))
            index += 6
        else:
            out.append(_JS_ESCAPES.get(escape, escape))
            index += 2
    return "".join(out)


def artifact_strings(path: Path) -> str:
    """Every string a log or report can show, compressed entries decoded."""
    html = path.read_text(encoding="utf-8")
    payloads = re.findall(
        r'window\.output\["strings"\] = '
        r'window\.output\["strings"\]\.concat\((\[.*?\])\);',
        html,
        re.S,
    )
    assert payloads, f"{path.name} has no string cache"
    strings: list[str] = []
    for payload in payloads:
        for literal in re.findall(r'"((?:[^"\\]|\\.)*)"', payload):
            entry = _js_unescape(literal)
            if entry.startswith("*"):
                strings.append(entry[1:])
            else:
                strings.append(zlib.decompress(base64.b64decode(entry)).decode())
    return "\n".join(strings)


@pytest.fixture
def screen_boundary(tmp_path: Path) -> Path:
    screen = tmp_path / "SecretScreen.py"
    screen.write_text(
        "from robot.api.deco import keyword\n"
        "\n"
        "@keyword\n"
        "def find_text(text):\n"
        "    return []\n"
        "\n"
        "@keyword\n"
        "def match_text(text, timeout=0):\n"
        f"    raise ValueError({SCREEN!r})\n",
        encoding="utf-8",
    )
    (tmp_path / "kvm.resource").write_text(
        "*** Settings ***\nLibrary    SecretScreen.py\n", encoding="utf-8"
    )
    return screen


@pytest.mark.parametrize(
    ("matcher", "contains_key"),
    [("Match Text", True), ("Match Text Without Echo", False)],
)
def test_timeout_does_not_expose_the_screen_in_robot_output(
    tmp_path: Path, screen_boundary: Path, matcher: str, contains_key: bool
) -> None:
    suite = tmp_path / "secret.robot"
    suite.write_text(
        "*** Settings ***\n"
        f"Library    {SECURITY_CENTER_DIR / 'TpmFde.py'}\n"
        f"Library    {screen_boundary}\n"
        "\n"
        "*** Test Cases ***\n"
        "Timeout On Recovery Key Screen\n"
        "    Set Log Level    NONE\n"
        f"    {matcher}    New recovery key    0\n",
        encoding="utf-8",
    )
    console = StringIO()

    assert run(str(suite), outputdir=str(tmp_path), stdout=console, stderr=console) == 1

    output = (tmp_path / "output.xml").read_text(encoding="utf-8")
    assert (KEY in output) is contains_key
    for name in ("log.html", "report.html"):
        strings = artifact_strings(tmp_path / name)
        # Control: the cache decodes, so an absent key means it is absent.
        assert "Timeout On Recovery Key Screen" in strings
        assert (KEY in strings) is contains_key
    if not contains_key:
        assert KEY not in console.getvalue()


def test_artifact_strings_decode_a_compressed_secret(tmp_path: Path) -> None:
    """Control: a logged secret is compressed, so only decoding finds it."""
    suite = tmp_path / "leak.robot"
    suite.write_text(
        f"*** Test Cases ***\nLog The Screen\n    Log    {SCREEN}\n",
        encoding="utf-8",
    )
    console = StringIO()

    assert run(str(suite), outputdir=str(tmp_path), stdout=console, stderr=console) == 0

    logged = artifact_strings(tmp_path / "log.html")
    assert "Log The Screen" in logged
    assert KEY in logged
    # The plain text hides it: the check above is the one that can fail.
    assert KEY not in (tmp_path / "log.html").read_text(encoding="utf-8")
    # A report only carries test-level data, so it needs its own control.
    assert "Log The Screen" in artifact_strings(tmp_path / "report.html")


def test_repair_button_timeout_does_not_expose_the_screen(
    tmp_path: Path, screen_boundary: Path
) -> None:
    suite = tmp_path / "repair.robot"
    suite.write_text(
        "*** Settings ***\n"
        f"Resource    {TPM_FDE_RESOURCE}\n"
        "Suite Teardown    Show Logs Again\n"
        "\n"
        "*** Test Cases ***\n"
        "Repair Button Missing On Key Screen\n"
        "    Keyword Should Exist    Find Repair Button\n"
        "    Keyword Should Exist    Match Text Without Echo\n"
        "    Hide Recovery Key From Logs\n"
        "    Run Keyword And Expect Error    *    Find Repair Button\n",
        encoding="utf-8",
    )
    console = StringIO()

    assert (
        run(
            str(suite),
            outputdir=str(tmp_path),
            pythonpath=[str(tmp_path)],
            stdout=console,
            stderr=console,
        )
        == 0
    )

    assert KEY not in (tmp_path / "output.xml").read_text(encoding="utf-8")
    for name in ("log.html", "report.html"):
        strings = artifact_strings(tmp_path / name)
        assert "Repair Button Missing On Key Screen" in strings
        assert KEY not in strings
    assert KEY not in console.getvalue()


def test_quiet_blocks_preserve_the_callers_log_level(
    tmp_path: Path, screen_boundary: Path
) -> None:
    suite = tmp_path / "logging.robot"
    suite.write_text(
        "*** Settings ***\n"
        f"Resource    {TPM_FDE_RESOURCE}\n"
        "\n"
        "*** Test Cases ***\n"
        "Restoring Without A Quiet Block Preserves Debug\n"
        "    Show Logs Again\n"
        "    ${previous}=    Set Log Level    DEBUG\n"
        "    Should Be Equal    ${previous}    DEBUG\n"
        "Nested Quiet Blocks Restore The Original Level\n"
        "    Hide Recovery Key From Logs\n"
        "    Hide Recovery Key From Logs\n"
        "    Show Logs Again\n"
        "    ${previous}=    Set Log Level    DEBUG\n"
        "    Should Be Equal    ${previous}    DEBUG\n",
        encoding="utf-8",
    )
    console = StringIO()

    assert (
        run(
            str(suite),
            outputdir=str(tmp_path),
            pythonpath=[str(tmp_path)],
            loglevel="DEBUG",
            stdout=console,
            stderr=console,
        )
        == 0
    ), console.getvalue()
