from pathlib import Path

import pytest

from job_generator.schema import Config, GeneratorError, load_config


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "input.yaml"
    path.write_text(content)
    return path


def test_loads_iso_and_dependency_tests(tmp_path: Path) -> None:
    path = _write(
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

    config = load_config(path)

    assert isinstance(config, Config)
    by_key = {t.key: t for t in config.tests}
    producer = by_key["desktop-installer/resolute.entire-disk"]
    consumer = by_key["firefox-example/firefox-example-basic"]
    assert producer.iso == "ubuntu-26.04-desktop-amd64.iso"
    assert producer.depends_on is None
    assert producer.job_name == "ugt-desktop-installer-resolute.entire-disk"
    assert consumer.depends_on == "desktop-installer/resolute.entire-disk"
    assert consumer.iso is None


def test_producer_and_consumer_relationships(tmp_path: Path) -> None:
    path = _write(
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

    config = load_config(path)
    by_key = {t.key: t for t in config.tests}
    producer = by_key["desktop-installer/resolute.entire-disk"]
    consumer = by_key["firefox-example/firefox-example-basic"]

    assert config.is_producer(producer) is True
    assert config.is_producer(consumer) is False
    assert config.consumers_of(producer) == [consumer]
    assert config.consumers_of(consumer) == []


def test_error_when_both_sources(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
suites:
  s:
    tests:
      t:
        iso: x.iso
        depends-on: s/other
""",
    )
    with pytest.raises(GeneratorError, match="exactly one"):
        load_config(path)


def test_error_when_no_source(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
suites:
  s:
    tests:
      t: {}
""",
    )
    with pytest.raises(GeneratorError, match="exactly one"):
        load_config(path)


def test_error_when_dangling_reference(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
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
