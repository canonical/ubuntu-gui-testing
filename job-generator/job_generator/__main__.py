import logging
import sys

from job_generator.cli import run


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    sys.exit(run())


if __name__ == "__main__":
    main()
