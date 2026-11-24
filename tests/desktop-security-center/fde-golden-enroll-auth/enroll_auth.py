"""Enroll a PIN or passphrase on the TPM-FDE platform keyslots through snapd.

Usage: python3 enroll_auth.py BODY_FILE

BODY_FILE holds the JSON body of the replace-platform-key request, secret
included. It is deleted before the request is sent, so the secret does not
stay on disk. Exits non-zero, with the reason on stderr, unless the change
ends Done and snapd then reports the requested authentication mode.
"""

import http.client
import json
import socket
import sys
import time
from pathlib import Path

SNAPD_SOCKET = "/run/snapd.socket"
CHANGE_TIMEOUT_SECONDS = 600


class SnapdConnection(http.client.HTTPConnection):
    def __init__(self) -> None:
        super().__init__("localhost", timeout=60)

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(SNAPD_SOCKET)


def snapd(method: str, path: str, body: dict | None = None) -> dict:
    conn = SnapdConnection()
    try:
        payload = None if body is None else json.dumps(body)
        conn.request(method, path, payload, {"Content-Type": "application/json"})
        reply = json.loads(conn.getresponse().read())
    finally:
        conn.close()
    if reply.get("type") == "error":
        sys.exit(f"{method} {path} failed: {reply.get('result', {}).get('message')}")
    return reply


def wait_for_change(change_id: str) -> None:
    deadline = time.monotonic() + CHANGE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        change = snapd("GET", f"/v2/changes/{change_id}")["result"]
        if change.get("ready"):
            if change.get("status") != "Done":
                sys.exit(f"change {change_id} ended {change.get('status')}: "
                         f"{change.get('err')}")
            return
        time.sleep(1)
    sys.exit(f"change {change_id} not ready after {CHANGE_TIMEOUT_SECONDS} s")


def platform_auth_modes() -> set[str]:
    volumes = snapd("GET", "/v2/system-volumes")["result"]
    modes = set()
    for volume in (volumes.get("by-container-role") or {}).values():
        for slot in (volume.get("keyslots") or {}).values():
            # A role is a "+"-joined token list such as "run+recover".
            roles = [r.split("+") for r in slot.get("roles") or []]
            if slot.get("type") == "platform" and any("run" in r for r in roles):
                modes.add(slot.get("auth-mode") or "none")
    return modes


def main() -> None:
    body_file = Path(sys.argv[1])
    body = json.loads(body_file.read_text())
    body_file.unlink()
    wait_for_change(snapd("POST", "/v2/system-volumes", body)["change"])
    modes = platform_auth_modes()
    if modes != {body["auth-mode"]}:
        sys.exit(f"platform keyslots report {sorted(modes)}, "
                 f"expected {body['auth-mode']!r}")
    print(body["auth-mode"])


if __name__ == "__main__":
    main()
