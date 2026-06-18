from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ubuntu_gui_testing_runner.base import (
    domain_name_prefix,
    resolve_latest_domain,
)


def _make_conn(names: list[str]) -> MagicMock:
    conn = MagicMock()
    domains = []
    for name in names:
        domain = MagicMock()
        domain.name.return_value = name
        domains.append(domain)
    conn.listAllDomains.return_value = domains
    return conn


def test_domain_name_prefix_format() -> None:
    assert (
        domain_name_prefix("desktop-installer", "resolute.entire-disk")
        == "ugt-desktop-installer-resolute.entire-disk"
    )


def test_resolve_latest_domain_returns_newest_timestamp() -> None:
    prefix = "ugt-desktop-installer-resolute.entire-disk"
    conn = _make_conn(
        [
            f"{prefix}-20260618T130405Z",
            f"{prefix}-20260618T140000Z",
            f"{prefix}-20260101T000000Z",
        ]
    )

    assert resolve_latest_domain(conn, prefix) == f"{prefix}-20260618T140000Z"


def test_resolve_latest_domain_ignores_non_matching_prefixes() -> None:
    prefix = "ugt-firefox-example-firefox-example-basic"
    conn = _make_conn(
        [
            "ugt-firefox-example-firefox-example-basic-extended-20260618T130405Z",
            f"{prefix}-20260618T120000Z",
            "ugt-other-suite-test-20260618T140000Z",
        ]
    )

    assert resolve_latest_domain(conn, prefix) == f"{prefix}-20260618T120000Z"


def test_resolve_latest_domain_handles_collision_suffix() -> None:
    prefix = "ugt-desktop-installer-resolute.entire-disk"
    conn = _make_conn(
        [
            f"{prefix}-20260618T130405Z",
            f"{prefix}-20260618T130405Z-2",
        ]
    )

    assert resolve_latest_domain(conn, prefix) == f"{prefix}-20260618T130405Z-2"


def test_resolve_latest_domain_raises_when_no_match() -> None:
    prefix = "ugt-desktop-installer-resolute.entire-disk"
    conn = _make_conn(["ugt-other-suite-test-20260618T130405Z"])

    with pytest.raises(RuntimeError, match="No domain found matching prefix"):
        resolve_latest_domain(conn, prefix)
