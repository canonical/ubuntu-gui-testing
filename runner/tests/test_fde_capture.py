from __future__ import annotations

import json
import socket
import struct
import threading
import time
from pathlib import Path

import pytest

from ubuntu_gui_testing_runner import fde_capture
from ubuntu_gui_testing_runner.fde_capture import (
    CaptureError,
    CaptureSupervisor,
    DisplayRecorder,
    RfbClient,
    synthetic_frame,
)

_PIXEL_FORMAT = struct.pack(
    ">BBBBHHHBBB3x",
    32,
    24,
    0,
    1,
    255,
    255,
    255,
    16,
    8,
    0,
)


def _recv_exactly(connection: socket.socket, count: int) -> bytes:
    buffer = b""
    while len(buffer) < count:
        chunk = connection.recv(count - len(buffer))
        if not chunk:
            raise ConnectionError("the test client closed the connection")
        buffer += chunk
    return buffer


class _FakeDisplay(threading.Thread):
    """A minimal RFB 3.8 server that serves one fixed raw framebuffer."""

    def __init__(
        self,
        width: int = 2,
        height: int = 2,
        pixels: bytes = b"\x00\x00\xff\x00" * 4,
        *,
        updates: int = 1,
        close_after: bool = True,
        version: bytes = b"RFB 003.008\n",
    ) -> None:
        super().__init__(daemon=True)
        self.width = width
        self.height = height
        self.pixels = pixels
        self.updates = updates
        self.close_after = close_after
        self.version = version
        self.port = 0
        self.requests: list[int] = []
        self._ready = threading.Event()
        self.error: BaseException | None = None

    @property
    def ready(self) -> bool:
        return self._ready.wait(5.0)

    def run(self) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                self.port = listener.getsockname()[1]
                self._ready.set()
                connection, _ = listener.accept()
                with connection:
                    self._serve(connection)
        except BaseException as error:  # noqa: BLE001 - reported to the test
            self.error = error
            self._ready.set()

    def _serve(self, connection: socket.socket) -> None:
        connection.sendall(self.version)
        _recv_exactly(connection, 12)
        connection.sendall(bytes((1, 1)))  # one security type: None
        _recv_exactly(connection, 1)
        connection.sendall(struct.pack(">I", 0))
        _recv_exactly(connection, 1)  # ClientInit
        connection.sendall(
            struct.pack(">HH", self.width, self.height)
            + _PIXEL_FORMAT
            + struct.pack(">I", 0)
        )
        _recv_exactly(connection, 20)  # SetPixelFormat
        header = _recv_exactly(connection, 4)
        (count,) = struct.unpack(">H", header[2:4])
        _recv_exactly(connection, count * 4)
        for _ in range(self.updates):
            request = _recv_exactly(connection, 10)  # FramebufferUpdateRequest
            self.requests.append(request[1])
            connection.sendall(
                struct.pack(">BBH", 0, 0, 1)
                + struct.pack(">HHHH", 0, 0, self.width, self.height)
                + struct.pack(">i", 0)
                + self.pixels
            )
        if not self.close_after:
            while connection.recv(10):
                pass


def _client_for(display: _FakeDisplay) -> RfbClient:
    assert display.ready
    assert display.error is None
    return RfbClient("127.0.0.1", display.port)


def test_rfb_client_reads_the_framebuffer_in_rgb_order() -> None:
    # Little-endian RGBX: blue, green, red, unused.
    pixels = b"\x00\x00\xff\x00" * 4
    display = _FakeDisplay(pixels=pixels, updates=2)
    display.start()
    with _client_for(display) as client:
        assert client.width == 2
        assert client.height == 2
        assert client.read_frame() is True
        assert client.read_frame() is True
        assert client.snapshot() == bytes((255, 0, 0)) * 4
    assert display.requests == [0, 1]


def test_rfb_client_rejects_an_old_or_unreadable_version() -> None:
    display = _FakeDisplay(version=b"RFB 003.003\n")
    display.start()
    assert display.ready
    with pytest.raises(CaptureError, match="too old"):
        RfbClient("127.0.0.1", display.port)
    garbage = _FakeDisplay(version=b"HTTP/1.1 200")
    garbage.start()
    assert garbage.ready
    with pytest.raises(CaptureError, match="did not send an RFB version"):
        RfbClient("127.0.0.1", garbage.port)


def test_display_recorder_keeps_changes_and_their_durations(
    tmp_path: Path,
) -> None:
    recorder = DisplayRecorder(tmp_path / "capture")
    first = bytes((255, 0, 0)) * 4
    second = bytes((0, 255, 0)) * 4
    assert recorder.add(first, started_at=10.0, width=2, height=2) is True
    assert recorder.add(first, started_at=11.0, width=2, height=2) is False
    assert recorder.add(second, started_at=12.0, width=2, height=2) is True
    recorder.close(ended_at=15.0)
    assert [frame.duration for frame in recorder.frames] == [2.0, 3.0]
    index = tmp_path / "index.json"
    recorder.write_index(index, events=[{"event": "wait-start", "at": 10.0}])
    payload = json.loads(index.read_text(encoding="utf-8"))
    assert len(payload["frames"]) == 2
    assert payload["frames"][0]["duration"] == 2.0
    assert payload["events"][0]["event"] == "wait-start"
    assert index.stat().st_mode & 0o077 == 0
    assert all(
        (tmp_path / "capture" / frame.path.name).stat().st_mode & 0o077 == 0
        for frame in recorder.frames
    )


def test_synthetic_frame_is_a_private_png(tmp_path: Path) -> None:
    path = synthetic_frame(tmp_path / "gap.png", 4, 3, (10, 20, 30))
    assert path.is_file()
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert path.stat().st_mode & 0o077 == 0


def test_supervisor_captures_and_writes_an_index(tmp_path: Path) -> None:
    display = _FakeDisplay(updates=2)
    display.start()
    assert display.ready
    supervisor = CaptureSupervisor(
        "127.0.0.1",
        display.port,
        tmp_path / "capture",
        domain_running=lambda: False,
    )
    deadline = time.monotonic() + 5.0
    while not supervisor.recorder.frames and time.monotonic() < deadline:
        time.sleep(0.05)
    supervisor.stop()
    assert supervisor.recorder.frames
    index = tmp_path / "capture-index.json"
    supervisor.write_index(index)
    payload = json.loads(index.read_text(encoding="utf-8"))
    assert payload["frames"]
    assert payload["frames"][-1]["ended_at"] is not None
    events = {event["event"] for event in payload["events"]}
    assert {"capture-start", "capture-connected", "capture-stop"} <= events


def test_supervisor_reports_an_unrecoverable_capture_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fde_capture, "RETRY_SECONDS", 0.5)
    # The display never accepts a connection and the domain claims to be
    # running, so the supervisor must fail instead of pretending to record.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()
    supervisor = CaptureSupervisor(
        "127.0.0.1",
        port,
        tmp_path / "capture",
        domain_running=lambda: True,
    )
    deadline = time.monotonic() + 10.0
    while supervisor.is_alive() and time.monotonic() < deadline:
        time.sleep(0.2)
    with pytest.raises(CaptureError, match="capture failed"):
        supervisor.stop()
