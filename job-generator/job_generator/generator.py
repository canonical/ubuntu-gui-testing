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

_SHELL = (
    'export PATH="$WORKSPACE/yarf/.venv/bin:$PATH"\n'
    "cd runner && uv run ubuntu-gui-testing-runner \\\n"
    "  --suite ../tests/{suite} \\\n"
    "  --test {test} \\\n"
    "  {args}\n"
)


def generate_jobs(config: Config) -> list[dict[str, Any]]:
    return [
        {"job-template": _job_template()},
        {"project": _project(config)},
    ]


def _job_template() -> dict[str, Any]:
    return {
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
        "builders": [
            {"shell": _YARF_SETUP},
            {"shell": _SHELL},
        ],
        "publishers": [
            {"archive": {"artifacts": ARTIFACTS_GLOB, "allow-empty": True}},
        ],
    }


def _project(config: Config) -> dict[str, Any]:
    return {
        "name": "ugt",
        "jobs": [
            {"ugt-{suite}-{test}": _instance(config, test)} for test in config.tests
        ],
    }


def _instance(config: Config, test: Test) -> dict[str, Any]:
    producer = config.producer_of(test)
    if producer is not None:
        source = f"--source-domain-prefix {producer.job_name}"
    else:
        iso = f"{ISO_CACHE_DIR}/{config.release}/{config.release}-desktop-amd64.iso"
        source = f"--iso {iso}"

    args = source
    if config.is_producer(test):
        args = f"{source} \\\n--keep"

    triggers: list[dict[str, Any]] = []
    if producer is not None:
        triggers = [{"reverse": {"jobs": producer.job_name, "result": "success"}}]

    return {
        "suite": test.suite,
        "test": test.name,
        "args": args,
        "triggers": triggers,
    }
