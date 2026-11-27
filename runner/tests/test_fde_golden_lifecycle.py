from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import libvirt  # type: ignore[import-untyped]
import pytest

from ubuntu_gui_testing_runner import fde_golden


@pytest.mark.parametrize(
    ("failure", "expected_message"),
    [
        ("staging", "Staging the EFI binary failed"),
        ("active", "is still active"),
    ],
    ids=["staging-fails", "clone-still-active"],
)
def test_create_pre_os_domain_keeps_clone_and_logs_on_failure(
    failure: str,
    expected_message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_domain, clone_domain, conn, runner = (MagicMock() for _ in range(4))
    source_domain.isActive.return_value = 0
    clone_domain.isActive.return_value = int(failure == "active")
    missing_domain_error = libvirt.libvirtError("not found")
    monkeypatch.setattr(
        missing_domain_error, "get_error_code", lambda: libvirt.VIR_ERR_NO_DOMAIN
    )
    conn.lookupByName.side_effect = [missing_domain_error, source_domain, clone_domain]

    runner.domain_name = "intermediate-clone"
    runner.pool_dir = tmp_path
    runner.nvram_volume_name = "clone.fd"
    nvram_path = tmp_path / runner.nvram_volume_name
    nvram_path.write_bytes(b"unchanged")
    monkeypatch.setenv("UGT_EFI_FILE", "previous.efi")
    monkeypatch.delenv("UGT_SEED_PATH", raising=False)

    def fake_image_runner_class(*, artifacts_dir: Path, **_: object) -> MagicMock:
        def fake_run(**_: object) -> int:
            (artifacts_dir / "output.xml").write_text("Robot log", encoding="utf-8")
            return int(failure == "staging")

        runner.run.side_effect = fake_run
        return runner

    def fake_run_command(_: list[str]) -> str:
        nvram_path.write_bytes(b"modified")
        return ""

    monkeypatch.setattr(libvirt, "open", lambda _: conn)
    monkeypatch.setattr(fde_golden, "LibvirtImageRunner", fake_image_runner_class)
    monkeypatch.setattr(
        fde_golden, "build_trusted_efi", lambda _, work_dir: (work_dir / "a.efi", [])
    )
    monkeypatch.setattr(fde_golden, "_run_command", fake_run_command)

    with pytest.raises(RuntimeError, match=expected_message) as raised:
        fde_golden.create_pre_os_domain(
            "source", "preos-digest-sb", "new-domain", artifacts_dir=tmp_path
        )

    (staging_artifacts_dir,) = tmp_path.glob("fde-golden-*")
    assert "clone 'intermediate-clone' was kept" in str(raised.value)
    assert f"artifacts: {staging_artifacts_dir}" in str(raised.value)
    output_xml = staging_artifacts_dir / "output.xml"
    assert output_xml.read_text(encoding="utf-8") == "Robot log"
    assert nvram_path.read_bytes() == b"unchanged"
    clone_domain.rename.assert_not_called()
    assert os.environ["UGT_EFI_FILE"] == "previous.efi"
    assert "UGT_SEED_PATH" not in os.environ
