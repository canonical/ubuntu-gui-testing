import logging
import sys
from pathlib import Path

from ubuntu_gui_testing_runner.cli import parse_args
from ubuntu_gui_testing_runner.image_runner import LibvirtImageRunner
from ubuntu_gui_testing_runner.iso_runner import LibvirtIsoRunner
from ubuntu_gui_testing_runner.runner import Runner


def main() -> None:
    logging.basicConfig(level=logging.DEBUG)

    args = parse_args()

    runner_ctx: Runner
    if args.iso:
        runner_ctx = LibvirtIsoRunner(
            iso=args.iso,
            suite_name=Path(args.suite).name,
            test_name=args.test,
            keep=args.keep,
            domain_template=args.domain_template,
            volume_template=args.volume_template,
            test_username=args.test_username,
            test_password=args.test_password,
            pool_template=args.pool_template,
            artifacts_dir=args.artifacts_dir,
            connection_uri=args.connection_uri,
            pool_name=args.pool_name,
            pool_dir=args.pool_dir,
        )
    else:
        runner_ctx = LibvirtImageRunner(
            source_domain=args.source_domain,
            suite_name=Path(args.suite).name,
            test_name=args.test,
            keep=args.keep,
            domain_template=args.domain_template,
            overlay_template=args.overlay_template,
            mount_source_domain=args.mount_source_domain,
            pool_template=args.pool_template,
            artifacts_dir=args.artifacts_dir,
            connection_uri=args.connection_uri,
            pool_name=args.pool_name,
            pool_dir=args.pool_dir,
        )

    with runner_ctx as runner:
        returncode = runner.run(
            suite=args.suite,
            test=args.test,
        )

    sys.exit(returncode)


if __name__ == "__main__":
    main()
