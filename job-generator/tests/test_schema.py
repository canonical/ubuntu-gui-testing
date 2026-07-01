from pathlib import Path

import pytest

from job_generator.schema import Config, GeneratorError, load_config


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "input.yaml"
    path.write_text(content)
    return path


def test_loads_release_and_dependency_tests(tmp_path: Path) -> None:
    path = _write(
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

    config = load_config(path)

    assert isinstance(config, Config)
    assert config.release == "resolute"
    by_key = {t.key: t for t in config.tests}
    producer = by_key["desktop-installer/resolute.entire-disk"]
    consumer = by_key["firefox-example/firefox-example-basic"]
    assert producer.depends_on is None
    assert producer.job_name == "ugt-desktop-installer-resolute.entire-disk"
    assert consumer.depends_on == "desktop-installer/resolute.entire-disk"


def test_producer_and_consumer_relationships(tmp_path: Path) -> None:
    path = _write(
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

    config = load_config(path)
    by_key = {t.key: t for t in config.tests}
    producer = by_key["desktop-installer/resolute.entire-disk"]
    consumer = by_key["firefox-example/firefox-example-basic"]

    assert config.is_producer(producer) is True
    assert config.is_producer(consumer) is False
    assert config.consumers_of(producer) == [consumer]
    assert config.consumers_of(consumer) == []


def test_error_when_release_missing(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
suites:
  s:
    tests:
      t: {}
""",
    )
    with pytest.raises(GeneratorError, match="release"):
        load_config(path)


def test_error_when_release_not_string(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
release: 2604
suites:
  s:
    tests:
      t: {}
""",
    )
    with pytest.raises(GeneratorError, match="release"):
        load_config(path)


def test_error_when_test_defines_iso(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
release: resolute
suites:
  s:
    tests:
      t:
        iso: x.iso
""",
    )
    with pytest.raises(GeneratorError, match="iso"):
        load_config(path)


def test_error_when_dangling_reference(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
release: resolute
suites:
  s:
    tests:
      t:
        depends-on: s/missing
""",
    )
    with pytest.raises(GeneratorError, match="unknown test"):
        load_config(path)


def test_error_on_cycle(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
release: resolute
suites:
  s:
    tests:
      a:
        depends-on: s/b
      b:
        depends-on: s/a
""",
    )
    with pytest.raises(GeneratorError, match="cycle"):
        load_config(path)


def test_error_when_top_level_not_suites(tmp_path: Path) -> None:
    path = _write(tmp_path, "[1, 2, 3]\n")
    with pytest.raises(GeneratorError, match="suites"):
        load_config(path)
