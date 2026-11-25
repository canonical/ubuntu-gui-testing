from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ubuntu_gui_testing_runner.cli import parse_args
from ubuntu_gui_testing_runner.constants import (
    DEFAULT_ARTIFACTS_DIR,
    DEFAULT_CONNECTION_URI,
    DEFAULT_POOL_NAME,
    DEFAULT_SHUTDOWN_TIMEOUT,
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
    assert args.shutdown_timeout == DEFAULT_SHUTDOWN_TIMEOUT


def test_shutdown_timeout_accepts_zero(monkeypatch: pytest.MonkeyPatch) -> None:
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
            "--shutdown-timeout",
            "0",
        ],
    )
    assert parse_args().shutdown_timeout == 0


def test_shutdown_timeout_rejects_negative_values(
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
            "--shutdown-timeout",
            "-1",
        ],
    )
    with pytest.raises(SystemExit):
        parse_args()


def test_shutdown_timeout_is_passed_to_iso_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ubuntu_gui_testing_runner import __main__

    args = SimpleNamespace(
        iso="a.iso",
        suite="suite.robot",
        test="test",
        keep=False,
        domain_template=None,
        volume_template=None,
        test_username="user",
        test_password="password",
        shutdown_timeout=7,
        pool_template=None,
        artifacts_dir=None,
        connection_uri=None,
        pool_name=None,
        pool_dir=None,
    )
    runner = MagicMock()
    iso_runner = MagicMock(return_value=runner)
    monkeypatch.setattr(__main__, "parse_args", lambda: args)
    monkeypatch.setattr(__main__, "LibvirtIsoRunner", iso_runner)

    with pytest.raises(SystemExit):
        __main__.main()

    assert iso_runner.call_args.kwargs["shutdown_timeout"] == 7


def test_default_shutdown_timeout_is_passed_to_iso_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ubuntu_gui_testing_runner import __main__

    args = SimpleNamespace(
        iso="a.iso",
        suite="suite.robot",
        test="test",
        keep=False,
        domain_template=None,
        volume_template=None,
        test_username="user",
        test_password="password",
        shutdown_timeout=DEFAULT_SHUTDOWN_TIMEOUT,
        pool_template=None,
        artifacts_dir=None,
        connection_uri=None,
        pool_name=None,
        pool_dir=None,
    )
    iso_runner = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(__main__, "parse_args", lambda: args)
    monkeypatch.setattr(__main__, "LibvirtIsoRunner", iso_runner)

    with pytest.raises(SystemExit):
        __main__.main()

    assert iso_runner.call_args.kwargs["shutdown_timeout"] == DEFAULT_SHUTDOWN_TIMEOUT


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


def test_mount_source_domain_defaults_to_sda(
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
            "--source-domain",
            "d",
            "--mount-source-domain",
        ],
    )
    args = parse_args()
    assert args.mount_source_domain == "/dev/sda"


def test_mount_source_domain_accepts_device(
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
            "--source-domain",
            "d",
            "--mount-source-domain",
            "/dev/sdb",
        ],
    )
    args = parse_args()
    assert args.mount_source_domain == "/dev/sdb"
