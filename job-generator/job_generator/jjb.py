from __future__ import annotations

from typing import Any

import yaml


class _Dumper(yaml.SafeDumper):
    pass


def _str_representer(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_Dumper.add_representer(str, _str_representer)


def render(jobs: list[dict[str, Any]]) -> str:
    """Serialize JJB job documents to a YAML string with preserved key order."""
    return yaml.dump(
        jobs,
        Dumper=_Dumper,
        default_flow_style=False,
        sort_keys=False,
    )
