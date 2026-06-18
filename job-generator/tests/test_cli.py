from pathlib import Path

import pytest

from job_generator.cli import parse_args, run


def test_parse_args_input_and_output() -> None:
    args = parse_args(["input.yaml", "-o", "out.yaml"])
    assert args.input_file == "input.yaml"
    assert args.output == "out.yaml"


def test_parse_args_defaults_output_to_none() -> None:
    args = parse_args(["input.yaml"])
    assert args.output is None


def test_run_writes_output_file(tmp_path: Path) -> None:
    input_file = tmp_path / "input.yaml"
    input_file.write_text(
        """
suites:
  desktop-installer:
    tests:
      resolute.entire-disk:
        iso: ubuntu-26.04-desktop-amd64.iso
  firefox-example:
    tests:
      firefox-example-basic:
        depends-on: desktop-installer/resolute.entire-disk
"""
    )
    output_file = tmp_path / "out.yaml"

    exit_code = run([str(input_file), "-o", str(output_file)])

    assert exit_code == 0
    content = output_file.read_text()
    assert "job-template:" in content
    assert "name: ugt-{suite}-{test}" in content
    assert "test: resolute.entire-disk" in content
    assert "test: firefox-example-basic" in content
    assert "reverse" in content


def test_run_writes_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    input_file = tmp_path / "input.yaml"
    input_file.write_text(
        """
suites:
  s:
    tests:
      t:
        iso: x.iso
"""
    )

    exit_code = run([str(input_file)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "name: ugt-{suite}-{test}" in out
    assert "suite: s" in out
    assert "test: t" in out


def test_run_returns_error_on_invalid_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    input_file = tmp_path / "input.yaml"
    input_file.write_text(
        """
suites:
  s:
    tests:
      t:
        iso: x.iso
        depends-on: s/other
"""
    )

    exit_code = run([str(input_file)])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "exactly one" in err
