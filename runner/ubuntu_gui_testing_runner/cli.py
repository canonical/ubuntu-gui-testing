import argparse
from pathlib import Path

from ubuntu_gui_testing_runner.constants import (
    DEFAULT_ARTIFACTS_DIR,
    DEFAULT_CONNECTION_URI,
    DEFAULT_OVERLAY_TEMPLATE,
    DEFAULT_POOL_DIR,
    DEFAULT_POOL_NAME,
    DEFAULT_POOL_TEMPLATE,
    DEFAULT_SWTPM_STATE_DIR,
    DEFAULT_TEST_PASSWORD,
    DEFAULT_TEST_USERNAME,
    DEFAULT_VOLUME_TEMPLATE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--suite",
        required=True,
        help="Name of the test suite to run",
    )
    parser.add_argument(
        "--test",
        required=True,
        help="Name of the test to run",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the domain and resources after the run completes",
    )
    parser.add_argument(
        "--mount-source-domain",
        nargs="?",
        const="/dev/sda",
        default=None,
        metavar="DEVICE",
        help="Attach a second overlay of the source domain as a USB disk",
    )

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--iso",
        help="Path to an ISO for installation",
    )
    source.add_argument(
        "--source-domain",
        help="Name of an existing libvirt domain to clone from",
    )

    libvirt = parser.add_argument_group("libvirt connection")
    libvirt.add_argument(
        "--connection-uri",
        default=DEFAULT_CONNECTION_URI,
        help="Libvirt connection URI (default: %(default)s)",
    )
    libvirt.add_argument(
        "--pool-name",
        default=DEFAULT_POOL_NAME,
        help="Name of the storage pool (default: %(default)s)",
    )
    libvirt.add_argument(
        "--pool-dir",
        type=Path,
        default=DEFAULT_POOL_DIR,
        help="Directory for the storage pool (default: %(default)s)",
    )

    templates = parser.add_argument_group("templates")
    templates.add_argument(
        "--pool-template",
        type=Path,
        default=DEFAULT_POOL_TEMPLATE,
        help="Override the storage pool XML template",
    )
    templates.add_argument(
        "--domain-template",
        type=Path,
        default=None,
        help="Override the domain XML template",
    )
    templates.add_argument(
        "--volume-template",
        type=Path,
        default=DEFAULT_VOLUME_TEMPLATE,
        help="Override the volume XML template (ISO runner)",
    )
    templates.add_argument(
        "--overlay-template",
        type=Path,
        default=DEFAULT_OVERLAY_TEMPLATE,
        help="Override the overlay volume XML template (image runner)",
    )

    paths = parser.add_argument_group("paths")
    paths.add_argument(
        "--artifacts-dir",
        type=Path,
        default=DEFAULT_ARTIFACTS_DIR,
        help="Directory to store test artifacts (default: %(default)s)",
    )
    paths.add_argument(
        "--swtpm-state-dir",
        type=Path,
        default=DEFAULT_SWTPM_STATE_DIR,
        help="Path to the swtpm state directory (default: %(default)s)",
    )

    guest = parser.add_argument_group("guest credentials")
    guest.add_argument(
        "--test-username",
        default=DEFAULT_TEST_USERNAME,
        help="Username for SSH access to the guest (default: %(default)s)",
    )
    guest.add_argument(
        "--test-password",
        default=DEFAULT_TEST_PASSWORD,
        help="Password for SSH access to the guest (default: %(default)s)",
    )

    return parser.parse_args()
