from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class GeneratorError(Exception):
    """Raised when the input configuration is invalid."""


@dataclass(frozen=True)
class Test:
    suite: str
    name: str
    depends_on: str | None

    @property
    def key(self) -> str:
        return f"{self.suite}/{self.name}"

    @property
    def job_name(self) -> str:
        return f"ugt-{self.suite}-{self.name}"


@dataclass(frozen=True)
class Config:
    release: str
    tests: tuple[Test, ...]

    def is_producer(self, test: Test) -> bool:
        return any(other.depends_on == test.key for other in self.tests)

    def consumers_of(self, test: Test) -> list[Test]:
        return [other for other in self.tests if other.depends_on == test.key]

    def producer_of(self, test: Test) -> Test | None:
        if test.depends_on is None:
            return None
        return next(
            (other for other in self.tests if other.key == test.depends_on),
            None,
        )


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text())
    release, tests = _parse(raw)
    _validate_references(tests)
    _validate_acyclic(tests)
    return Config(release=release, tests=tuple(tests))


def _parse(raw: Any) -> tuple[str, list[Test]]:
    if not isinstance(raw, dict) or "suites" not in raw:
        raise GeneratorError("Top-level document must be a mapping with 'suites'")
    release = raw.get("release")
    if not isinstance(release, str):
        raise GeneratorError("Top-level 'release' must be a string")
    suites = raw["suites"]
    if not isinstance(suites, dict):
        raise GeneratorError("'suites' must be a mapping of suite names")

    tests: list[Test] = []
    for suite_name, suite_body in suites.items():
        if not isinstance(suite_body, dict) or "tests" not in suite_body:
            raise GeneratorError(f"Suite '{suite_name}' must contain a 'tests' mapping")
        suite_tests = suite_body["tests"]
        if not isinstance(suite_tests, dict):
            raise GeneratorError(f"'tests' in suite '{suite_name}' must be a mapping")
        for test_name, test_body in suite_tests.items():
            tests.append(_parse_test(suite_name, test_name, test_body))
    return release, tests


def _parse_test(suite_name: str, test_name: str, body: Any) -> Test:
    body = body or {}
    if not isinstance(body, dict):
        raise GeneratorError(f"Test '{suite_name}/{test_name}' must be a mapping")
    if "iso" in body:
        raise GeneratorError(f"Test '{suite_name}/{test_name}' must not define 'iso'")
    depends_on = body.get("depends-on")
    return Test(
        suite=suite_name,
        name=test_name,
        depends_on=depends_on,
    )


def _validate_references(tests: list[Test]) -> None:
    keys = {test.key for test in tests}
    for test in tests:
        if test.depends_on is not None and test.depends_on not in keys:
            raise GeneratorError(
                f"Test '{test.key}' depends-on unknown test '{test.depends_on}'"
            )


def _validate_acyclic(tests: list[Test]) -> None:
    edges = {test.key: test.depends_on for test in tests}
    for start in edges:
        seen: set[str] = set()
        node: str | None = start
        while node is not None:
            if node in seen:
                raise GeneratorError(f"Dependency cycle detected involving '{start}'")
            seen.add(node)
            node = edges.get(node)
