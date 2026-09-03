from __future__ import annotations

import re
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import libvirt  # type: ignore[import-untyped]

from ubuntu_gui_testing_runner.base import _BaseLibvirtRunner

_DOMAIN_NAME = re.compile(r"^ugt-desktop-installer-resolute\.entire-disk-\d{8}T\d{6}Z$")


class _FakeRunner(_BaseLibvirtRunner):
    """Minimal concrete subclass for testing base class behaviour."""

    def _setup(self) -> None:
        pass

    async def _run_yarf(
        self, suite: str, test: str, vsock_cid: int, vnc_port: int
    ) -> int:
        return 0


def _make_conn_with_existing_domains(names: list[str]) -> MagicMock:
    conn = MagicMock()

    def lookup(name: str) -> MagicMock:
        if name in names:
            return MagicMock()
        raise libvirt.libvirtError("not found")

    conn.lookupByName.side_effect = lookup
    return conn


def _fixed_now() -> datetime:
    return datetime(2026, 6, 18, 13, 4, 5, tzinfo=UTC)


def test_domain_name_includes_suite_test_and_utc_timestamp() -> None:
    conn = _make_conn_with_existing_domains([])

    with patch("libvirt.open", return_value=conn):
        runner = _FakeRunner(
            suite_name="desktop-installer",
            test_name="resolute.entire-disk",
        )
        try:
            assert _DOMAIN_NAME.match(runner.domain_name)
        finally:
            runner.close()


def test_domain_name_appends_suffix_on_collision() -> None:
    base = "ugt-desktop-installer-resolute.entire-disk-20260618T130405Z"
    conn = _make_conn_with_existing_domains([base])

    with (
        patch("libvirt.open", return_value=conn),
        patch("ubuntu_gui_testing_runner.base.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value = _fixed_now()
        runner = _FakeRunner(
            suite_name="desktop-installer",
            test_name="resolute.entire-disk",
        )
        try:
            assert runner.domain_name == f"{base}-2"
        finally:
            runner.close()


def test_domain_name_increments_suffix_until_unique() -> None:
    base = "ugt-desktop-installer-resolute.entire-disk-20260618T130405Z"
    existing = [base, f"{base}-2", f"{base}-3"]
    conn = _make_conn_with_existing_domains(existing)

    with (
        patch("libvirt.open", return_value=conn),
        patch("ubuntu_gui_testing_runner.base.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value = _fixed_now()
        runner = _FakeRunner(
            suite_name="desktop-installer",
            test_name="resolute.entire-disk",
        )
        try:
            assert runner.domain_name == f"{base}-4"
        finally:
            runner.close()
