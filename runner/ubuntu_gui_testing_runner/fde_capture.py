"""Authoritative capture of one disposable VM's display.

The capture client speaks RFB (VNC) directly to the libvirt display, so it
records the target framebuffer rather than the user's desktop. Because the
framebuffer exists before the OS starts, firmware and encrypted-boot prompts
are captured too, and the same stream survives a guest reboot.

Each received framebuffer update that changes the picture is written as a
PNG, and its host monotonic start time goes into an index file. A frame
remains on screen until the next such update arrives, so a long unchanged
screen is one long-duration frame, not a captured-at-a-fixed-rate
approximation. After 30 s without an update the client reconnects, which can
add a short black frame. A gap in the stream (the domain stopped, or capture
died) is recorded explicitly.

No secrets are interpreted here. Redaction happens later, over intervals the
test marks, and the raw frames are written owner-only.
"""

from __future__ import annotations

import contextlib
import json
import socket
import struct
import threading
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

_RFB_VERSION: Final = b"RFB 003.008\n"
_SECURITY_NONE: Final = 1
_SECURITY_VNC_AUTH: Final = 2
_UPDATE_FRAMEBUFFER: Final = 0
_SET_COLOUR_MAP: Final = 1
_BELL: Final = 2
_SERVER_CUT_TEXT: Final = 3
_ENCODING_RAW: Final = 0
_ENCODING_DESKTOP_SIZE: Final = -223
_CONNECT_TIMEOUT: Final = 10.0
_READ_TIMEOUT: Final = 30.0
_MAX_DIMENSION: Final = 4096
# One update can legitimately arrive several times a second. Keeping every
# change is cheap; coalescing is done by the editor, not by discarding frames.
_FRAME_INTERVAL: Final = 0.0
# Bounded reconnect window for a display that is running but unreachable.
RETRY_SECONDS: Final = 30.0


class CaptureError(RuntimeError):
    """The display could not be captured without losing required evidence."""


@dataclass(frozen=True)
class Frame:
    """One framebuffer image and how long it stayed on screen."""

    path: Path
    started_at: float
    ended_at: float | None = None

    @property
    def duration(self) -> float | None:
        if self.ended_at is None:
            return None
        return max(0.0, self.ended_at - self.started_at)


def _png(width: int, height: int, rgb: bytes) -> bytes:
    """Encode one RGB frame as a filterless PNG (standard library only)."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    stride = width * 3
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filter type 0: none
        rows.extend(rgb[y * stride : (y + 1) * stride])
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
        + chunk(b"IEND", b"")
    )


class RfbClient:
    """Minimal RFB 3.8 client requesting raw true-colour framebuffer updates."""

    def __init__(self, host: str, port: int, timeout: float = _CONNECT_TIMEOUT) -> None:
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(_READ_TIMEOUT)
        self._buffer = bytearray()
        self.width = 0
        self.height = 0
        self._framebuffer = bytearray()
        self._requests = 0
        try:
            self._handshake()
        except BaseException:
            self.close()
            raise

    # --------------------------------------------------------------- transport

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._sock.close()

    def __enter__(self) -> RfbClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _recv_into_buffer(self, count: int) -> None:
        """Read exactly `count` bytes into the buffer, raising on a short link."""
        while len(self._buffer) < count:
            chunk = self._sock.recv(0x10000)
            if not chunk:
                raise CaptureError("the display closed the connection")
            self._buffer.extend(chunk)

    def _take(self, count: int) -> bytes:
        self._recv_into_buffer(count)
        value = bytes(self._buffer[:count])
        del self._buffer[:count]
        return value

    def _u8(self) -> int:
        return self._take(1)[0]

    def _u16(self) -> int:
        (value,) = struct.unpack(">H", self._take(2))
        return int(value)

    def _u32(self) -> int:
        (value,) = struct.unpack(">I", self._take(4))
        return int(value)

    # ---------------------------------------------------------------- protocol

    def _handshake(self) -> None:
        version = self._take(12)
        if not version.startswith(b"RFB "):
            raise CaptureError("the display did not send an RFB version")
        try:
            major, minor = (
                int(part) for part in version[4:11].decode("ascii").split(".")
            )
        except (ValueError, UnicodeDecodeError) as error:
            raise CaptureError("the display sent an unreadable RFB version") from error
        if (major, minor) < (3, 8):
            raise CaptureError(f"RFB {major}.{minor} is too old for this client")
        self._sock.sendall(_RFB_VERSION)

        count = self._u8()
        if count == 0:
            reason = self._take(self._u32())
            raise CaptureError(f"the display refused the connection: {reason!r}")
        types = {self._u8() for _ in range(count)}
        if _SECURITY_NONE in types:
            self._sock.sendall(bytes((_SECURITY_NONE,)))
        elif _SECURITY_VNC_AUTH in types:
            # A disposable clone's display is deliberately unauthenticated. A
            # password-protected display would need a secret this client must
            # not hold, so refuse rather than guess.
            raise CaptureError("the display requires VNC authentication")
        else:
            raise CaptureError(f"no supported security type in {sorted(types)}")
        result = self._u32()
        # On success RFB 3.8 sends no reason string; on failure the branch
        # above already raised.
        if result != 0:
            raise CaptureError("the display rejected the security handshake")

        self._sock.sendall(b"\x01")  # ClientInit: shared desktop
        self.width = self._u16()
        self.height = self._u16()
        if not (0 < self.width <= _MAX_DIMENSION and 0 < self.height <= _MAX_DIMENSION):
            raise CaptureError(
                f"the display reported an implausible size {self.width}x{self.height}"
            )
        self._take(16)  # server pixel format
        name_length = self._u32()
        self._take(name_length)
        self._framebuffer = bytearray(self.width * self.height * 3)

        # Ask for a known pixel format: 32 bpp true colour with red at shift
        # 16, so the server sends RGBX and no palette handling is needed.
        pixel_format = struct.pack(
            ">BBBBHHHBBB3x",
            32,  # bits per pixel
            24,  # depth
            0,  # big-endian flag
            1,  # true-colour flag
            255,  # red maximum
            255,  # green maximum
            255,  # blue maximum
            16,  # red shift
            8,  # green shift
            0,  # blue shift
        )
        self._sock.sendall(struct.pack(">B3x", 0) + pixel_format)
        self._sock.sendall(
            struct.pack(">BBH", 2, 0, 2)
            + struct.pack(">i", _ENCODING_RAW)
            + struct.pack(">i", _ENCODING_DESKTOP_SIZE)
        )

    def request_update(self, incremental: bool = True) -> None:
        self._sock.sendall(
            struct.pack(
                ">BBHHHH", 3, 1 if incremental else 0, 0, 0, self.width, self.height
            )
        )

    def read_frame(self) -> bool:
        """Block until one framebuffer update; return whether pixels changed."""
        # The first request must ask for the whole screen: an incremental
        # request is not guaranteed to answer before the guest changes anything.
        self.request_update(incremental=self._requests > 0)
        self._requests += 1
        while True:
            message = self._u8()
            if message == _UPDATE_FRAMEBUFFER:
                return self._read_update()
            if message == _BELL:
                continue
            if message == _SET_COLOUR_MAP:
                self._u8()
                self._u16()
                self._u16()
                count = self._u16()
                self._take(6 * count)
                continue
            if message == _SERVER_CUT_TEXT:
                self._take(3)
                length = self._u32()
                if length > 1 << 20:
                    raise CaptureError("the display sent an oversized cut text")
                self._take(length)
                continue
            raise CaptureError(f"unsupported RFB server message {message}")

    def _read_update(self) -> bool:
        self._u8()  # padding
        rects = self._u16()
        changed = False
        for _ in range(rects):
            x = self._u16()
            y = self._u16()
            width = self._u16()
            height = self._u16()
            (encoding,) = struct.unpack(">i", self._take(4))
            if encoding == _ENCODING_DESKTOP_SIZE:
                if 0 < width <= _MAX_DIMENSION and 0 < height <= _MAX_DIMENSION:
                    self.width = width
                    self.height = height
                    self._framebuffer = bytearray(width * height * 3)
                continue
            if encoding != _ENCODING_RAW:
                raise CaptureError(f"the display used unsupported encoding {encoding}")
            if x + width > self.width or y + height > self.height:
                raise CaptureError("a framebuffer update exceeds the display")
            raw = self._take(width * height * 4)
            self._apply(x, y, width, height, raw)
            changed = True
        return changed

    def _apply(self, x: int, y: int, width: int, height: int, raw: bytes) -> None:
        framebuffer = self._framebuffer
        stride = self.width * 3
        for row in range(height):
            source = row * width * 4
            target = (y + row) * stride + x * 3
            line = raw[source : source + width * 4]
            # Slice assignment in C keeps a full-screen update responsive.
            framebuffer[target : target + width * 3 : 3] = line[2::4]
            framebuffer[target + 1 : target + width * 3 : 3] = line[1::4]
            framebuffer[target + 2 : target + width * 3 : 3] = line[0::4]

    def snapshot(self) -> bytes:
        return bytes(self._framebuffer)


def synthetic_frame(
    path: Path, width: int, height: int, rgb: tuple[int, int, int]
) -> Path:
    """Write a solid frame used for a declared no-display interval.

    A powered-off guest produces no framebuffer. Representing that time with a
    labelled solid frame keeps the interval on the timeline instead of hiding
    it; it never impersonates guest output.
    """
    pixels = bytes(rgb) * (width * height)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_png(width, height, pixels))
    path.chmod(0o600)
    return path


class DisplayRecorder:
    """Persist timestamped frames from one display connection."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.frames: list[Frame] = []
        self._last: Frame | None = None
        self._last_pixels: bytes | None = None
        self._counter = 0

    def add(self, pixels: bytes, *, started_at: float, width: int, height: int) -> bool:
        """Record `pixels` if they differ from the previous frame."""
        if pixels == self._last_pixels:
            return False
        now = time.monotonic()
        if self._last is not None and now - self._last.started_at < _FRAME_INTERVAL:
            return False
        path = self.directory / f"frame-{self._counter:07d}.png"
        self._counter += 1
        path.write_bytes(_png(width, height, pixels))
        path.chmod(0o600)
        if self._last is not None:
            previous = Frame(
                path=self._last.path,
                started_at=self._last.started_at,
                ended_at=started_at,
            )
            self.frames[-1] = previous
        frame = Frame(path=path, started_at=started_at)
        self.frames.append(frame)
        self._last = frame
        self._last_pixels = pixels
        return True

    def close(self, *, ended_at: float | None = None) -> None:
        if self._last is not None:
            self.frames[-1] = Frame(
                path=self._last.path,
                started_at=self._last.started_at,
                ended_at=ended_at if ended_at is not None else time.monotonic(),
            )

    def write_index(self, path: Path, *, events: list[dict[str, Any]]) -> None:
        payload = {
            "frames": [
                {
                    "path": frame.path.name,
                    "started_at": frame.started_at,
                    "ended_at": frame.ended_at,
                    "duration": frame.duration,
                }
                for frame in self.frames
            ],
            "events": events,
        }
        path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        path.chmod(0o600)


class CaptureSupervisor:
    """Keep one display captured across guest restarts, without hiding gaps.

    The supervisor runs in a background thread. It records why the stream
    stopped (domain powered off, display refused, capture failure) and
    reconnects when the runner asks it to, so a reboot cannot silently drop
    the firmware or recovery prompt that follows.
    """

    def __init__(
        self,
        host: str,
        port: int,
        directory: Path,
        *,
        domain_running: Callable[[], bool] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.recorder = DisplayRecorder(directory)
        self.events: list[dict[str, Any]] = []
        self._domain_running = domain_running
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._failure: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run, name="fde-capture", daemon=True
        )
        self._thread.start()

    def _event(self, kind: str, **fields: Any) -> None:
        with self._lock:
            self.events.append(
                {"event": kind, "at": time.monotonic(), "wall": time.time(), **fields}
            )

    def _run(self) -> None:
        self._event("capture-start")
        while not self._stop.is_set():
            try:
                with RfbClient(self.host, self.port) as client:
                    self._event(
                        "capture-connected",
                        width=client.width,
                        height=client.height,
                    )
                    self.recorder.add(
                        client.snapshot(),
                        started_at=time.monotonic(),
                        width=client.width,
                        height=client.height,
                    )
                    while not self._stop.is_set():
                        if client.read_frame():
                            self.recorder.add(
                                client.snapshot(),
                                started_at=time.monotonic(),
                                width=client.width,
                                height=client.height,
                            )
            except (OSError, CaptureError) as error:
                if self._stop.is_set():
                    break
                running = self._safe_running()
                self._event(
                    "capture-disconnected",
                    reason=str(error),
                    domain_running=running,
                )
                # A stopped domain is the only acceptable reason to have no
                # display. Anything else is an evidence gap, not a retry.
                if running is False:
                    if self._stop.wait(0.5):
                        break
                    continue
                if not self._retry():
                    with self._lock:
                        self._failure = error
                    break
        self._event("capture-stop")
        self.recorder.close()

    def _retry(self) -> bool:
        """Reconnect a running display for a bounded time before failing."""
        deadline = time.monotonic() + RETRY_SECONDS
        while time.monotonic() < deadline and not self._stop.is_set():
            if self._stop.wait(0.5):
                return False
            try:
                probe = RfbClient(self.host, self.port, timeout=5.0)
            except (OSError, CaptureError):
                continue
            probe.close()
            self._event("capture-retry-connected")
            return True
        return False

    def _safe_running(self) -> bool | None:
        if self._domain_running is None:
            return None
        try:
            return self._domain_running()
        except Exception:  # noqa: BLE001 - the display state is advisory
            return None

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def mark(self, kind: str, **fields: Any) -> None:
        """Record a lifecycle/navigation marker used for idle classification."""
        self._event(kind, **fields)

    def stop(self, timeout: float = 30.0) -> None:
        self._stop.set()
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise CaptureError(f"the capture worker did not stop within {timeout:g}s")
        if self._failure is not None:
            raise CaptureError(f"capture failed: {self._failure}") from self._failure

    def write_index(self, path: Path) -> None:
        self.recorder.write_index(path, events=list(self.events))


__all__ = [
    "CaptureError",
    "CaptureSupervisor",
    "DisplayRecorder",
    "Frame",
    "RfbClient",
]
