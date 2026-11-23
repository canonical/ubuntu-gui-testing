from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def templates_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "templates"


def write_private_file(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.fixture
def fde_config(tmp_path: Path) -> Path:
    """A private TPM-FDE fixture configuration with owner-only secret files."""
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text(
        "[fde-baseline]:22 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample\n",
        encoding="utf-8",
    )
    known_hosts.chmod(0o644)

    config = {
        "ssh_user": "ubuntu",
        "desktop_user": "ubuntu",
        "ssh_identity": str(write_private_file(tmp_path / "id", "key\n")),
        "ssh_known_hosts": str(known_hosts),
        "ssh_host_alias": "fde-baseline",
        "login_password_file": str(
            write_private_file(tmp_path / "password", "password\n")
        ),
        "recovery_key_file": str(
            write_private_file(tmp_path / "recovery-key", "11111-22222\n")
        ),
        "passphrase_file": str(
            write_private_file(tmp_path / "passphrase", "passphrase\n")
        ),
        "security_center_revision": "42",
        "snapd_version": "2.68.3",
        "snapd_executable_sha256": "0" * 64,
        "auth_mode": "passphrase",
        "data_device": "/dev/disk/by-partlabel/data",
        "save_device": "/dev/disk/by-partlabel/save",
    }
    path = tmp_path / "fde.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.fixture
def mock_libvirt_connection() -> MagicMock:
    """A mock libvirt connection with sensible defaults."""
    conn = MagicMock()
    conn.lookupByName.side_effect = Exception("domain not found")
    return conn


@pytest.fixture
def mock_libvirt_open(
    mock_libvirt_connection: MagicMock,
) -> Generator[Any, None, None]:
    """Patch libvirt.open to return the mock connection."""
    with patch("libvirt.open", return_value=mock_libvirt_connection) as m:
        yield m
