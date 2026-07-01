from __future__ import annotations

from typing import Any

from job_generator.schema import Config, Test

REPO_URL = "https://github.com/canonical/ubuntu-gui-testing/"
BRANCH = "main"
ISO_CACHE_DIR = "/srv/data/.rf_image_cache"
YARF_REPO_URL = "https://github.com/canonical/yarf"
YARF_DEFAULT_REF = "main"
ARTIFACTS_GLOB = "runner/artifacts/**"

_YARF_SETUP = (
    'rm -rf "$WORKSPACE/yarf"\n'
    'git clone --depth 1 --branch "$YARF_REF" '
    f'{YARF_REPO_URL} "$WORKSPACE/yarf"\n'
    'cd "$WORKSPACE/yarf" && uv sync\n'
)

_RUN_TESTS = (
    'export PATH="$WORKSPACE/yarf/.venv/bin:$PATH"\n'
    "cd runner && uv run ubuntu-gui-testing-runner \\\n"
    "  --suite ../tests/{suite} \\\n"
    "  --test {test} \\\n"
    "  {args}\n"
)


def generate_jobs(config: Config) -> list[dict[str, Any]]:
    return [
        {"builder": _run_tests_builder()},
        {"publisher": _artifacts_publisher()},
        {"job-template": _job_template("ugt-iso", _iso_builders(config.release))},
        {"job-template": _job_template("ugt-source-domain", _source_domain_builders())},
        {"project": _project(config)},
    ]


def _job_template(template_id: str, builders: list[Any]) -> dict[str, Any]:
    return {
        "id": template_id,
        "name": "ugt-{suite}-{test}",
        "scm": [{"git": {"url": REPO_URL, "branches": [BRANCH]}}],
        "parameters": [
            {
                "string": {
                    "name": "YARF_REF",
                    "default": YARF_DEFAULT_REF,
                    "description": "Git ref of canonical/yarf to build for this run.",
                }
            }
        ],
        "triggers": "{obj:triggers}",
        "builders": builders,
        "publishers": ["publish-artifacts"],
    }


def _iso_builders(release: str) -> list[Any]:
    return [
        {"dl-iso-to-cache": {"release": release}},
        _run_tests_reference(),
    ]


def _source_domain_builders() -> list[Any]:
    return [
        _run_tests_reference(),
    ]


def _run_tests_reference() -> dict[str, dict[str, str]]:
    return {"run-tests": {"suite": "{suite}", "test": "{test}", "args": "{args}"}}


def _run_tests_builder() -> dict[str, Any]:
    return {
        "name": "run-tests",
        "builders": [
            {"shell": _YARF_SETUP},
            {"shell": _RUN_TESTS},
        ],
    }


def _artifacts_publisher() -> dict[str, Any]:
    return {
        "name": "publish-artifacts",
        "publishers": [
            {"archive": {"artifacts": ARTIFACTS_GLOB, "allow-empty": True}},
        ],
    }


def _project(config: Config) -> dict[str, Any]:
    jobs: list[dict[str, Any]] = []
    for test in config.tests:
        template_name, instance = _instance(config, test)
        jobs.append({template_name: instance})
    return {
        "name": "ugt",
        "jobs": jobs,
    }


def _instance(config: Config, test: Test) -> tuple[str, dict[str, Any]]:
    producer = config.producer_of(test)
    if producer is not None:
        template_name = "ugt-source-domain"
        source = f"--source-domain-prefix {producer.job_name}"
    else:
        template_name = "ugt-iso"
        iso = f"{ISO_CACHE_DIR}/{config.release}/{config.release}-desktop-amd64.iso"
        source = f"--iso {iso}"

    args = source
    if config.is_producer(test):
        args = f"{source} \\\n--keep"

    triggers: list[dict[str, Any]] = []
    if producer is not None:
        triggers = [{"reverse": {"jobs": producer.job_name, "result": "success"}}]

    instance = {
        "suite": test.suite,
        "test": test.name,
        "args": args,
        "triggers": triggers,
    }
    return template_name, instance
