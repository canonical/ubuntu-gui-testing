from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ubuntu_gui_testing_runner.__main__ import main


def test_main_deletes_previous_before_iso_runner_construction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    class FakeRunner:
        def __init__(self, **_: object) -> None:
            calls.append("runner")

        def __enter__(self) -> FakeRunner:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def run(self, suite: str, test: str) -> int:
            return 0

    def fake_delete_previous_runs(**kwargs: object) -> None:
        calls.append("cleanup")
        assert kwargs["suite_name"] == "desktop-installer"
        assert kwargs["test_name"] == "resolute.entire-disk"
        assert kwargs["swtpm_state_dir"] == tmp_path / "swtpm"
        assert kwargs["pool_dir"] == tmp_path

    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--suite",
            "tests/desktop-installer",
            "--test",
            "resolute.entire-disk",
            "--iso",
            "ubuntu.iso",
            "--swtpm-state-dir",
            str(tmp_path / "swtpm"),
            "--pool-dir",
            str(tmp_path),
            "--delete-previous",
        ],
    )
    with (
        patch(
            "ubuntu_gui_testing_runner.__main__.delete_previous_runs",
            fake_delete_previous_runs,
        ),
        patch("ubuntu_gui_testing_runner.__main__.LibvirtIsoRunner", FakeRunner),
        patch("sys.exit") as exit_mock,
    ):
        main()

    assert calls == ["cleanup", "runner"]
    exit_mock.assert_called_once_with(0)


def test_main_skips_delete_previous_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = MagicMock()
    runner.__enter__.return_value = runner
    runner.run.return_value = 0
    monkeypatch.setattr(
        "sys.argv",
        ["runner", "--suite", "tests/s", "--test", "t", "--iso", "ubuntu.iso"],
    )
    with (
        patch("ubuntu_gui_testing_runner.__main__.delete_previous_runs") as cleanup,
        patch(
            "ubuntu_gui_testing_runner.__main__.LibvirtIsoRunner", return_value=runner
        ),
        patch("sys.exit"),
    ):
        main()

    cleanup.assert_not_called()
