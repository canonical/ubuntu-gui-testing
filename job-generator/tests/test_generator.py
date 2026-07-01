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
) -> dict[tuple[str, str], tuple[str, dict[str, Any]]]:
    project = next(item["project"] for item in jobs if "project" in item)
    result = {}
    for entry in project["jobs"]:
        template_name = next(iter(entry))
        instance = entry[template_name]
        result[(instance["suite"], instance["test"])] = (template_name, instance)
    return result


def _templates(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item["job-template"] for item in jobs if "job-template" in item]


def _builders(jobs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    builders = [item["builder"] for item in jobs if "builder" in item]
    return {builder["name"]: builder for builder in builders}


def _publishers(jobs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    publishers = [item["publisher"] for item in jobs if "publisher" in item]
    return {publisher["name"]: publisher for publisher in publishers}


def test_emits_builders_templates_and_project(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
release: resolute
suites:
  s:
    tests:
      t: {}
""",
    )

    jobs = generate_jobs(config)

    assert [next(iter(item)) for item in jobs] == [
        "builder",
        "publisher",
        "job-template",
        "job-template",
        "project",
    ]


def test_emits_shared_builder_definitions(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
release: resolute
suites:
  s:
    tests:
      t: {}
""",
    )

    builders = _builders(generate_jobs(config))

    assert list(builders) == ["run-tests"]
    setup = builders["run-tests"]["builders"][0]["shell"]
    assert "git clone" in setup
    assert "https://github.com/canonical/yarf" in setup
    assert '--branch "$YARF_REF"' in setup
    assert "uv sync" in setup

    shell = builders["run-tests"]["builders"][1]["shell"]
    assert 'export PATH="$WORKSPACE/yarf/.venv/bin:$PATH"' in shell
    assert "cd runner && uv run ubuntu-gui-testing-runner" in shell
    assert "--suite ../tests/{suite}" in shell
    assert "--test {test}" in shell
    assert "{args}" in shell
    assert "\n+" not in shell


def test_job_templates_hold_shared_scm_shell_and_triggers(
    tmp_path: Path,
) -> None:
    config = _config(
        tmp_path,
        """
release: resolute
suites:
  s:
    tests:
      t: {}
""",
    )

    templates = _templates(generate_jobs(config))

    assert [template["id"] for template in templates] == [
        "ugt-iso",
        "ugt-source-domain",
    ]
    for template in templates:
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


def test_job_template_declares_yarf_ref_parameter(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
release: resolute
suites:
  s:
    tests:
      t: {}
""",
    )

    template = _templates(generate_jobs(config))[0]

    assert template["parameters"] == [
        {
            "string": {
                "name": "YARF_REF",
                "default": "main",
                "description": ("Git ref of canonical/yarf to build for this run."),
            }
        }
    ]


def test_source_domain_template_starts_with_yarf_setup(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
release: resolute
suites:
  s:
    tests:
      t: {}
""",
    )

    template = next(
        template
        for template in _templates(generate_jobs(config))
        if template["id"] == "ugt-source-domain"
    )
    assert template["builders"] == [
        {"run-tests": {"suite": "{suite}", "test": "{test}", "args": "{args}"}},
    ]


def test_iso_template_starts_with_iso_cache_builder(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
release: resolute
suites:
  s:
    tests:
      t: {}
""",
    )

    template = next(
        template
        for template in _templates(generate_jobs(config))
        if template["id"] == "ugt-iso"
    )

    assert template["builders"] == [
        {"dl-iso-to-cache": {"release": "resolute"}},
        {"run-tests": {"suite": "{suite}", "test": "{test}", "args": "{args}"}},
    ]


def test_source_domain_template_passes_parameters_to_run_tests(
    tmp_path: Path,
) -> None:
    config = _config(
        tmp_path,
        """
release: resolute
suites:
  s:
    tests:
      t: {}
""",
    )

    template = next(
        template
        for template in _templates(generate_jobs(config))
        if template["id"] == "ugt-source-domain"
    )

    assert template["builders"] == [
        {"run-tests": {"suite": "{suite}", "test": "{test}", "args": "{args}"}},
    ]


def test_job_template_archives_runner_artifacts(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
release: resolute
suites:
  s:
    tests:
      t: {}
""",
    )

    for template in _templates(generate_jobs(config)):
        assert template["publishers"] == ["publish-artifacts"]


def test_emits_artifacts_publisher_definition(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
release: resolute
suites:
  s:
    tests:
      t: {}
""",
    )

    publishers = _publishers(generate_jobs(config))

    assert publishers == {
        "publish-artifacts": {
            "name": "publish-artifacts",
            "publishers": [
                {"archive": {"artifacts": "runner/artifacts/**", "allow-empty": True}}
            ],
        }
    }


# runner builder verification removed; covered by shared builder tests


def test_iso_producer_instance(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
release: resolute
suites:
  desktop-installer:
    tests:
      resolute.entire-disk: {}
  firefox-example:
    tests:
      firefox-example-basic:
        depends-on: desktop-installer/resolute.entire-disk
""",
    )

    template_name, instance = _instances(generate_jobs(config))[
        ("desktop-installer", "resolute.entire-disk")
    ]

    assert template_name == "ugt-iso"
    expected = (
        "--iso /srv/data/.rf_image_cache/resolute/resolute-desktop-amd64.iso"
        + " \\\n--keep"
    )
    assert instance["args"] == expected
    assert instance["triggers"] == []
    assert "builders" not in instance


def test_dependency_consumer_instance(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
release: resolute
suites:
  desktop-installer:
    tests:
      resolute.entire-disk: {}
  firefox-example:
    tests:
      firefox-example-basic:
        depends-on: desktop-installer/resolute.entire-disk
""",
    )

    template_name, instance = _instances(generate_jobs(config))[
        ("firefox-example", "firefox-example-basic")
    ]

    assert template_name == "ugt-source-domain"
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
    assert "builders" not in instance


def test_standalone_iso_instance_has_no_keep_or_triggers(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
release: resolute
suites:
  s:
    tests:
      only: {}
""",
    )

    template_name, instance = _instances(generate_jobs(config))[("s", "only")]

    assert template_name == "ugt-iso"
    assert (
        instance["args"]
        == "--iso /srv/data/.rf_image_cache/resolute/resolute-desktop-amd64.iso"
    )
    assert "--keep" not in instance["args"]
    assert instance["triggers"] == []
    assert "builders" not in instance
