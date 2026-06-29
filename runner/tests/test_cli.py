from __future__ import annotations

import pytest

from ubuntu_gui_testing_runner.cli import parse_args
from ubuntu_gui_testing_runner.constants import (
    DEFAULT_ARTIFACTS_DIR,
    DEFAULT_CONNECTION_URI,
    DEFAULT_POOL_NAME,
)


def test_iso_and_source_domain_are_mutually_exclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--suite",
            "s",
            "--test",
            "t",
            "--iso",
            "a.iso",
            "--source-domain",
            "d",
        ],
    )
    with pytest.raises(SystemExit):
        parse_args()


def test_requires_iso_or_source_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["runner", "--suite", "s", "--test", "t"])
    with pytest.raises(SystemExit):
        parse_args()


def test_suite_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["runner", "--test", "t", "--iso", "a.iso"])
    with pytest.raises(SystemExit):
        parse_args()


def test_test_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["runner", "--suite", "s", "--iso", "a.iso"])
    with pytest.raises(SystemExit):
        parse_args()


def test_defaults_applied_for_iso_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv", ["runner", "--suite", "s", "--test", "t", "--iso", "a.iso"]
    )
    args = parse_args()
    assert args.connection_uri == DEFAULT_CONNECTION_URI
    assert args.pool_name == DEFAULT_POOL_NAME
    assert args.artifacts_dir == DEFAULT_ARTIFACTS_DIR


def test_defaults_applied_for_image_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv", ["runner", "--suite", "s", "--test", "t", "--source-domain", "d"]
    )
    args = parse_args()
    assert args.connection_uri == DEFAULT_CONNECTION_URI
    assert args.pool_name == DEFAULT_POOL_NAME
    assert args.artifacts_dir == DEFAULT_ARTIFACTS_DIR


def test_keep_flag_defaults_to_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv", ["runner", "--suite", "s", "--test", "t", "--iso", "a.iso"]
    )
    args = parse_args()
    assert args.keep is False


def test_keep_flag_set_to_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["runner", "--suite", "s", "--test", "t", "--iso", "a.iso", "--keep"],
    )
    args = parse_args()
    assert args.keep is True


def test_robot_variable_can_be_passed_multiple_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--suite",
            "s",
            "--test",
            "t",
            "--iso",
            "a.iso",
            "--robot-variable",
            "FOO:bar",
            "--robot-variable",
            "CID:123",
        ],
    )
    args = parse_args()
    assert args.robot_variables == {"FOO": "bar", "CID": "123"}


def test_robot_variable_requires_name_value_separator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--suite",
            "s",
            "--test",
            "t",
            "--iso",
            "a.iso",
            "--robot-variable",
            "INVALID",
        ],
    )
    with pytest.raises(SystemExit):
        parse_args()
