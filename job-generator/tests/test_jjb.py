import yaml

from job_generator.jjb import render


def test_render_round_trips_to_yaml() -> None:
    jobs = [{"job": {"name": "ugt-s-t", "builders": [{"shell": "echo hi\n"}]}}]

    output = render(jobs)

    parsed = yaml.safe_load(output)
    assert parsed == jobs


def test_render_preserves_key_order() -> None:
    jobs = [
        {
            "job": {
                "name": "ugt-s-t",
                "scm": [{"git": {"url": "u", "branches": ["main"]}}],
                "builders": [{"shell": "echo hi\n"}],
            }
        }
    ]

    output = render(jobs)

    name_pos = output.index("name:")
    scm_pos = output.index("scm:")
    builders_pos = output.index("builders:")
    assert name_pos < scm_pos < builders_pos


def test_render_uses_block_scalars_for_shell() -> None:
    jobs = [{"job": {"name": "ugt-s-t", "builders": [{"shell": "a\nb\n"}]}}]

    output = render(jobs)

    assert "|" in output
    assert "\\n" not in output
