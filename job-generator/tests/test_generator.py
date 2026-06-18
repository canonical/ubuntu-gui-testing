from pathlib import Path
from typing import Any

from job_generator.generator import generate_jobs
from job_generator.schema import Config, load_config


def _config(tmp_path: Path, content: str) -> Config:
    path = tmp_path / "input.yaml"
    path.write_text(content)
    return load_config(path)


def _instances(
    jobs: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    project = next(item["project"] for item in jobs if "project" in item)
    result = {}
    for entry in project["jobs"]:
        instance = entry["ugt-{suite}-{test}"]
        result[(instance["suite"], instance["test"])] = instance
    return result


def test_emits_template_and_project(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
suites:
  s:
    tests:
      t:
        iso: x.iso
""",
    )

    jobs = generate_jobs(config)

    assert [next(iter(item)) for item in jobs] == [
        "job-template",
        "project",
    ]


def test_job_template_holds_shared_scm_shell_and_triggers(
    tmp_path: Path,
) -> None:
    config = _config(
        tmp_path,
        """
suites:
  s:
    tests:
      t:
        iso: x.iso
""",
    )

    jobs = generate_jobs(config)
    template = jobs[0]["job-template"]

    assert template["name"] == "ugt-{suite}-{test}"
    assert template["scm"] == [
        {
            "git": {
                "url": "https://github.com/canonical/ubuntu-gui-testing/",
                "branches": ["main"],
            }
        }
    ]
    assert template["triggers"] == "{obj:triggers}"
    shell = template["builders"][1]["shell"]
    assert "cd runner && uv run ubuntu-gui-testing-runner" in shell
    assert "--suite ../tests/{suite}" in shell
    assert "--test {test}" in shell
    assert "{args}" in shell


def test_job_template_declares_yarf_ref_parameter(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
suites:
  s:
    tests:
      t:
        iso: x.iso
""",
    )

    template = generate_jobs(config)[0]["job-template"]

    assert template["parameters"] == [
        {
            "string": {
                "name": "YARF_REF",
                "default": "main",
                "description": ("Git ref of canonical/yarf to build for this run."),
            }
        }
    ]


def test_job_template_first_builder_sets_up_yarf(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
suites:
  s:
    tests:
      t:
        iso: x.iso
""",
    )

    template = generate_jobs(config)[0]["job-template"]
    setup = template["builders"][0]["shell"]

    assert "git clone" in setup
    assert "https://github.com/canonical/yarf" in setup
    assert '--branch "$YARF_REF"' in setup
    assert "uv sync" in setup


def test_job_template_archives_runner_artifacts(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
suites:
  s:
    tests:
      t:
        iso: x.iso
""",
    )

    template = generate_jobs(config)[0]["job-template"]

    assert template["publishers"] == [
        {"archive": {"artifacts": "runner/artifacts/**", "allow-empty": True}},
    ]


def test_runner_builder_prepends_yarf_venv_to_path(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
suites:
  s:
    tests:
      t:
        iso: x.iso
""",
    )

    template = generate_jobs(config)[0]["job-template"]
    shell = template["builders"][1]["shell"]

    assert 'export PATH="$WORKSPACE/yarf/.venv/bin:$PATH"' in shell


def test_iso_producer_instance(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
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
""",
    )

    instance = _instances(generate_jobs(config))[
        ("desktop-installer", "resolute.entire-disk")
    ]

    assert instance["args"] == ("--iso /isos/ubuntu-26.04-desktop-amd64.iso \\\n--keep")
    assert instance["triggers"] == []


def test_dependency_consumer_instance(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
suites:
  desktop-installer:
    tests:
      resolute.entire-disk:
        iso: x.iso
  firefox-example:
    tests:
      firefox-example-basic:
        depends-on: desktop-installer/resolute.entire-disk
""",
    )

    instance = _instances(generate_jobs(config))[
        ("firefox-example", "firefox-example-basic")
    ]

    assert instance["args"] == (
        "--source-domain-prefix ugt-desktop-installer-resolute.entire-disk"
    )
    assert instance["triggers"] == [
        {
            "reverse": {
                "jobs": "ugt-desktop-installer-resolute.entire-disk",
                "result": "success",
            }
        }
    ]


def test_standalone_iso_instance_has_no_keep_or_triggers(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
suites:
  s:
    tests:
      only:
        iso: x.iso
""",
    )

    instance = _instances(generate_jobs(config))[("s", "only")]

    assert instance["args"] == "--iso /isos/x.iso"
    assert "--keep" not in instance["args"]
    assert instance["triggers"] == []
