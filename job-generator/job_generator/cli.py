from __future__ import annotations

import argparse
import sys
from pathlib import Path

from job_generator.generator import generate_jobs
from job_generator.jjb import render
from job_generator.schema import GeneratorError, load_config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="job-generator",
        description="Job generator for Ubuntu GUI testing",
    )
    parser.add_argument(
        "input_file",
        help="Path to the input YAML describing suites and tests",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Path to write the JJB YAML (default: stdout)",
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config(Path(args.input_file))
        output = render(generate_jobs(config))
    except GeneratorError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.output is None:
        sys.stdout.write(output)
    else:
        Path(args.output).write_text(output, encoding="utf-8")
    return 0
