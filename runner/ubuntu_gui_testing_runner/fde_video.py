"""Edit authoritative TPM-FDE capture into one chaptered video.

The rule this module enforces is per idle interval, not per video: every
contiguous unchanged or declared-wait interval occupies at most four seconds of
the encoded result. Waits are represented by time-lapse, never cut out, and the
complete source timeline is retained in the edit map.

Idle is decided from two independent signals:

* explicit wait markers emitted by the test, plus capture gaps caused by a
  stopped or unreachable display;
* a visual check of the captured frames themselves.

An interval marked as a wait that nevertheless shows a meaningful transition is
refused, not accelerated. An unchanged run longer than the limit is treated as
idle even without a marker, with a short normal-speed context at each end so the
prompt that appears before it and the result that follows stay readable.

A marked privacy interval longer than the limit is compressed the same way: the
mask, not the hidden content, is what a viewer would otherwise stare at for
several seconds. Transitions underneath the mask are therefore allowed, and the
speed label is omitted while the privacy label is shown.

A capture connection that times out during a long wait can deliver one short
all-black frame before the next paint. That frame is a transport placeholder,
not a screen state: its time stays in the edit, but it is not sampled and does
not count as a transition, so it cannot break the wait it interrupts. A real
change that happened while the display was down is still compared with the last
real frame and is still refused inside a declared wait.

Encoding uses the concat demuxer, which honours per-frame durations, followed by
a constant-frame-rate pass. The finished file is probed again and each planned
idle interval is measured from the encoded timestamps; planning alone is not
accepted as proof.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import struct
import subprocess
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

IDLE_LIMIT: Final = 4.0
# Leave room for frame rounding so the encoded interval stays below the limit,
# not merely equal to it.
IDLE_TARGET: Final = 3.9
FPS: Final = 30
# A short idle interval is still shown for a moment so the viewer registers it.
MIN_IDLE_OUTPUT: Final = 1.0
# A long idle interval is compressed no further than this.
IDLE_SPEED_FLOOR: Final = 10.0
# A change covering this fraction of the sampled screen is meaningful.
MEANINGFUL_CHANGE: Final = 0.05
SAMPLE_COLUMNS: Final = 32
SAMPLE_ROWS: Final = 20
# Frames in a declared wait that differ by less than this are still idle.
PIXEL_TOLERANCE: Final = 12
# A capture reconnect can deliver an all-black frame before the next paint.
# It is a transport placeholder, not a screen state; identify it only when it
# is short and arrives right after the connection resumes.
RESYNC_WINDOW: Final = 1.0
RESYNC_MAX_SECONDS: Final = 1.0
BLANK_LEVEL: Final = 8


class VideoError(RuntimeError):
    """The recording cannot be edited honestly or did not pass its audit."""


@dataclass(frozen=True)
class FrameSpan:
    path: Path
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class Segment:
    """One planned output segment mapped onto a source interval."""

    kind: str  # normal | idle
    source_start: float
    source_end: float
    output_start: float
    output_duration: float
    frames: tuple[FrameSpan, ...] = ()
    speed: float = 1.0
    label: str = ""

    @property
    def output_end(self) -> float:
        return self.output_start + self.output_duration


@dataclass(frozen=True)
class Chapter:
    scenario: str
    title: str
    outcome: str
    start: float
    end: float


@dataclass(frozen=True)
class Redaction:
    """One interval whose frames must be fully masked in the edit."""

    reason: str
    source_start: float
    source_end: float
    output_start: float
    output_end: float


@dataclass(frozen=True)
class EditPlan:
    segments: tuple[Segment, ...]
    chapters: tuple[Chapter, ...]
    source_duration: float
    output_duration: float
    idle_intervals: tuple[int, ...] = ()
    redactions: tuple[Redaction, ...] = ()

    def idle_segments(self) -> tuple[Segment, ...]:
        return tuple(segment for segment in self.segments if segment.kind == "idle")

    def to_json(self, path: Path) -> None:
        payload = {
            "fps": FPS,
            "idle_limit": IDLE_LIMIT,
            "source_duration": self.source_duration,
            "output_duration": self.output_duration,
            "segments": [
                {
                    "kind": segment.kind,
                    "source_start": segment.source_start,
                    "source_end": segment.source_end,
                    "output_start": segment.output_start,
                    "output_duration": segment.output_duration,
                    "speed": segment.speed,
                    "label": segment.label,
                    "frames": [str(frame.path) for frame in segment.frames],
                }
                for segment in self.segments
            ],
            "chapters": [
                {
                    "scenario": chapter.scenario,
                    "title": chapter.title,
                    "outcome": chapter.outcome,
                    "start": chapter.start,
                    "end": chapter.end,
                }
                for chapter in self.chapters
            ],
            "redactions": [
                {
                    "reason": redaction.reason,
                    "source_start": redaction.source_start,
                    "source_end": redaction.source_end,
                    "output_start": redaction.output_start,
                    "output_end": redaction.output_end,
                }
                for redaction in self.redactions
            ],
            "idle_segments": list(self.idle_intervals),
        }
        path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        path.chmod(0o600)


def _decode_frame(path: Path) -> tuple[int, int, bytes]:
    """Decode a PNG written by the capture client (filter type 0, RGB)."""
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise VideoError(f"{path.name} is not a PNG")
    offset = 8
    width = height = 0
    payload = bytearray()
    while offset < len(raw):
        (length,) = struct.unpack_from(">I", raw, offset)
        kind = raw[offset + 4 : offset + 8]
        data = raw[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            width, height = struct.unpack_from(">II", data)
        elif kind == b"IDAT":
            payload.extend(data)
        elif kind == b"IEND":
            break
    if width <= 0 or height <= 0:
        raise VideoError(f"{path.name} has no usable header")
    pixels = zlib.decompress(bytes(payload))
    stride = width * 3
    rows = bytearray()
    position = 0
    for _ in range(height):
        if position + 1 + stride > len(pixels) or pixels[position] != 0:
            raise VideoError(f"{path.name} is truncated or filtered")
        rows.extend(pixels[position + 1 : position + 1 + stride])
        position += 1 + stride
    return width, height, bytes(rows)


def png_size(path: Path) -> tuple[int, int]:
    """Read a PNG header without decoding its pixels."""
    header = Path(path).read_bytes()[:33]
    if len(header) < 33 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise VideoError(f"{Path(path).name} is not a PNG")
    width, height = struct.unpack_from(">II", header, 16)
    return width, height


def _signature(path: Path) -> tuple[tuple[int, int, int], ...]:
    """Downsample a frame to a coarse grid so animation is not a transition."""
    width, height, pixels = _decode_frame(path)
    stride = width * 3
    signature: list[tuple[int, int, int]] = []
    for row in range(SAMPLE_ROWS):
        y = min(height - 1, row * height // SAMPLE_ROWS + height // (2 * SAMPLE_ROWS))
        base = y * stride
        for column in range(SAMPLE_COLUMNS):
            x = min(
                width - 1,
                column * width // SAMPLE_COLUMNS + width // (2 * SAMPLE_COLUMNS),
            )
            pixel = base + x * 3
            signature.append((pixels[pixel], pixels[pixel + 1], pixels[pixel + 2]))
    return tuple(signature)


def _changed_fraction(
    first: Sequence[tuple[int, int, int]],
    second: Sequence[tuple[int, int, int]],
) -> float:
    if len(first) != len(second) or not first:
        return 1.0
    changed = 0
    for before, after in zip(first, second, strict=False):
        # Compare every channel: a red window replacing a blue one of the same
        # luminance is still a visible transition.
        if (
            max(
                abs(before[0] - after[0]),
                abs(before[1] - after[1]),
                abs(before[2] - after[2]),
            )
            > PIXEL_TOLERANCE
        ):
            changed += 1
    return changed / len(first)


def _blank_signature(signature: Sequence[tuple[int, int, int]]) -> bool:
    return all(max(pixel) <= BLANK_LEVEL for pixel in signature)


def _resync_placeholders(
    frames: Sequence[FrameSpan],
    signatures: Sequence[Sequence[tuple[int, int, int]]],
    index: Mapping[str, Any],
) -> frozenset[int]:
    """Find all-black frames emitted while a display connection resumes.

    The capture client reconnects after each RFB timeout. Its first frame is
    black, then the unchanged desktop returns. Such a frame is a transport
    placeholder, not a UI state: ignoring it cannot hide a real transition,
    because the next real frame is compared with the last real frame instead.
    """
    events = index.get("events")
    reconnects: list[float] = []
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            if event.get("event") not in {
                "capture-connected",
                "capture-retry-connected",
            }:
                continue
            at = event.get("at")
            if isinstance(at, bool) or not isinstance(at, (int, float)):
                continue
            reconnects.append(float(at))
    placeholders: set[int] = set()
    for position, (frame, signature) in enumerate(zip(frames, signatures, strict=True)):
        if frame.duration > RESYNC_MAX_SECONDS or not _blank_signature(signature):
            continue
        if any(0.0 <= frame.start - at <= RESYNC_WINDOW for at in reconnects):
            placeholders.add(position)
    return frozenset(placeholders)


def frame_spans(index: dict[str, Any]) -> tuple[FrameSpan, ...]:
    """Read a capture index into contiguous frame spans."""
    frames = index.get("frames")
    if not isinstance(frames, list) or not frames:
        raise VideoError("the capture index has no frames")
    spans: list[FrameSpan] = []
    for entry in frames:
        if not isinstance(entry, dict):
            raise VideoError("the capture index has a malformed frame")
        name = entry.get("path")
        start = entry.get("started_at")
        end = entry.get("ended_at")
        if not isinstance(name, str) or not name:
            raise VideoError("a captured frame has no path")
        if isinstance(start, bool) or not isinstance(start, (int, float)):
            raise VideoError(f"frame {name} has no start time")
        if isinstance(end, bool) or not isinstance(end, (int, float)):
            raise VideoError(f"frame {name} has no end time")
        if end < start:
            raise VideoError(f"frame {name} ends before it starts")
        spans.append(FrameSpan(path=Path(name), start=float(start), end=float(end)))
    spans.sort(key=lambda span: span.start)
    for previous, current in zip(spans, spans[1:], strict=False):
        if current.start < previous.end - 1e-9:
            raise VideoError("captured frames overlap")
    return tuple(spans)


def _markers(index: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    events = index.get("events")
    if not isinstance(events, list):
        return grouped
    for event in events:
        if not isinstance(event, dict):
            continue
        name = event.get("event")
        if isinstance(name, str):
            grouped.setdefault(name, []).append(event)
    return grouped


def _gap_intervals(
    grouped: Mapping[str, list[dict[str, Any]]],
) -> list[tuple[float, float, str]]:
    """Treat a display outage as a declared wait, never as hidden time."""
    events: list[tuple[float, str]] = []
    for name in ("capture-disconnected", "capture-connected"):
        for event in grouped.get(name, []):
            at = event.get("at")
            if isinstance(at, bool) or not isinstance(at, (int, float)):
                continue
            events.append((float(at), name))
    events.sort()
    intervals: list[tuple[float, float, str]] = []
    outage: float | None = None
    for at, name in events:
        if name == "capture-disconnected":
            if outage is None:
                outage = at
        elif outage is not None:
            if at > outage:
                intervals.append((outage, at, "display unavailable"))
            outage = None
    return intervals


def _paired_intervals(
    grouped: Mapping[str, list[dict[str, Any]]],
    *,
    start_event: str,
    end_event: str,
    id_field: str,
    reason_field: str,
    default_reason: str,
    source_start: float,
    source_end: float,
) -> list[tuple[float, float, str]]:
    """Pair start/end marker events and clip them to the recorded timeline."""
    starts = grouped.get(start_event, [])
    ends = grouped.get(end_event, [])
    by_id: dict[str, dict[str, Any]] = {}
    for event in starts:
        identifier = event.get(id_field)
        if isinstance(identifier, str) and identifier:
            by_id[identifier] = event
    intervals: list[tuple[float, float, str]] = []
    for event in ends:
        identifier = event.get(id_field)
        if not isinstance(identifier, str) or identifier not in by_id:
            continue
        opened = by_id[identifier]
        begin = opened.get("at")
        finish = event.get("at")
        if isinstance(begin, bool) or not isinstance(begin, (int, float)):
            continue
        if isinstance(finish, bool) or not isinstance(finish, (int, float)):
            continue
        clipped_start = max(float(begin), source_start)
        clipped_end = min(float(finish), source_end)
        if clipped_end - clipped_start > 0:
            reason = str(opened.get(reason_field) or default_reason)
            intervals.append((clipped_start, clipped_end, reason))
    intervals.sort()
    return intervals


def _wait_intervals(
    index: dict[str, Any], source_start: float, source_end: float
) -> list[tuple[float, float, str]]:
    """Collect declared waits and display outages inside the recorded timeline."""
    grouped = _markers(index)
    intervals = _paired_intervals(
        grouped,
        start_event="wait-start",
        end_event="wait-end",
        id_field="wait-id",
        reason_field="reason",
        default_reason="wait",
        source_start=source_start,
        source_end=source_end,
    )
    intervals.extend(_gap_intervals(grouped))
    intervals.sort()
    return intervals


def _sensitive_intervals(
    index: dict[str, Any], source_start: float, source_end: float
) -> list[tuple[float, float, str]]:
    """Collect intervals that must be masked, whatever the idle classification."""
    return _paired_intervals(
        _markers(index),
        start_event="sensitive-start",
        end_event="sensitive-end",
        id_field="sensitive-id",
        reason_field="reason",
        default_reason="secret",
        source_start=source_start,
        source_end=source_end,
    )


def _merge(
    intervals: Sequence[tuple[float, float, str]],
) -> list[tuple[float, float, str]]:
    merged: list[tuple[float, float, str]] = []
    for start, end, reason in sorted(intervals):
        if merged and start <= merged[-1][1] + 1e-6:
            previous = merged[-1]
            merged[-1] = (previous[0], max(previous[1], end), previous[2])
        else:
            merged.append((start, end, reason))
    return merged


def _force_idle(
    intervals: Sequence[tuple[float, float, str]],
    start: float,
    end: float,
    reason: str,
) -> list[tuple[float, float, str]]:
    """Make one source interval a single accelerated segment.

    A masked interval may contain the very transitions the mask exists to
    hide. Replacing any overlapping idle slice with one segment keeps the
    privacy overlay from becoming a long static black frame.
    """
    result: list[tuple[float, float, str]] = []
    for item_start, item_end, item_reason in intervals:
        if item_end <= start + 1e-6 or item_start >= end - 1e-6:
            result.append((item_start, item_end, item_reason))
            continue
        if item_start < start - 1e-6:
            result.append((item_start, start, item_reason))
        if item_end > end + 1e-6:
            result.append((end, item_end, item_reason))
    result.append((start, end, reason))
    result.sort()
    return result


def _detected_unchanged(
    frames: Sequence[FrameSpan],
    meaningful: Sequence[bool],
    *,
    limit: float,
) -> list[tuple[float, float, str]]:
    """Find unchanged runs longer than the limit, from the frames themselves."""
    detected: list[tuple[float, float, str]] = []
    run_start: float | None = None
    for previous, current, changed in zip(
        frames, frames[1:], meaningful[1:], strict=False
    ):
        if changed:
            if run_start is not None:
                detected.append((run_start, current.start, "unchanged screen"))
                run_start = None
        elif run_start is None:
            # The screen stopped changing when the first of the identical
            # frames was displayed, not when the second one arrived.
            run_start = previous.start
    if run_start is not None:
        detected.append((run_start, frames[-1].end, "unchanged screen"))
    # One update can cover a long unchanged stretch on its own. Its whole
    # display duration is idle even though there is no second frame to compare.
    detected.extend(
        (frame.start, frame.end, "unchanged screen")
        for frame in frames
        if frame.duration > limit
    )
    return [item for item in detected if item[1] - item[0] > limit]


def _map_time(segments: Sequence[Segment], source_time: float) -> float:
    for segment in segments:
        if segment.source_start <= source_time <= segment.source_end:
            if segment.kind == "idle":
                fraction = (source_time - segment.source_start) / max(
                    1e-9, segment.source_end - segment.source_start
                )
                return segment.output_start + fraction * segment.output_duration
            return segment.output_start + (source_time - segment.source_start)
    if segments and source_time > segments[-1].source_end:
        return segments[-1].output_end
    return 0.0


def _sample(
    frames: Sequence[FrameSpan], start: float, end: float, count: int
) -> tuple[FrameSpan, ...]:
    """Pick `count` frames in screen order for a source interval.

    A frame is chosen by the moment it was on screen, so a long unchanged
    stretch repeats one frame and a fast transition keeps its order.
    """
    selected = [frame for frame in frames if frame.start < end and frame.end > start]
    if not selected:
        return ()
    sampled: list[FrameSpan] = []
    position = 0
    span = end - start
    for index in range(count):
        moment = start + (index + 0.5) * span / count
        while position + 1 < len(selected) and selected[position + 1].start <= moment:
            position += 1
        sampled.append(selected[position])
    return tuple(sampled)


def _sample_preferring(
    frames: Sequence[FrameSpan],
    visible: Sequence[FrameSpan],
    start: float,
    end: float,
    count: int,
) -> tuple[FrameSpan, ...]:
    """Sample real frames, falling back only when a span has no other frame."""
    chosen = _sample(visible, start, end, count)
    if chosen:
        return chosen
    return _sample(frames, start, end, count)


def plan_edit(
    index: dict[str, Any],
    frames: Sequence[FrameSpan],
    chapters_meta: Sequence[Mapping[str, Any]],
    *,
    fps: int = FPS,
    limit: float = IDLE_LIMIT,
    target: float = IDLE_TARGET,
) -> EditPlan:
    """Plan a chaptered edit whose every idle interval fits within `limit`."""
    if not frames:
        raise VideoError("no captured frames to edit")
    source_start = frames[0].start
    source_end = frames[-1].end
    if source_end <= source_start:
        raise VideoError("the captured timeline has no duration")
    if target > limit:
        raise VideoError("the idle target cannot exceed the idle limit")

    signatures = [_signature(frame.path) for frame in frames]
    placeholders = _resync_placeholders(frames, signatures, index)
    effective: list[tuple[tuple[int, int, int], ...]] = []
    last_stable: tuple[tuple[int, int, int], ...] | None = None
    for position, signature in enumerate(signatures):
        if position in placeholders and last_stable is not None:
            # Compare the frame after the reconnect with the last real paint,
            # so a change that happened while the display was down is still a
            # visible transition and is still refused inside a declared wait.
            effective.append(last_stable)
            continue
        effective.append(signature)
        if position not in placeholders:
            last_stable = signature
    meaningful: list[bool] = [True]
    for first, second in zip(effective, effective[1:], strict=False):
        meaningful.append(_changed_fraction(first, second) >= MEANINGFUL_CHANGE)
    visible = tuple(
        frame for position, frame in enumerate(frames) if position not in placeholders
    ) or tuple(frames)

    # A masked interval hides real screen activity. When it is longer than the
    # limit the mask itself would become a static block, so the interval is
    # time-compressed like idle time. Transitions underneath the mask cannot be
    # read as activity inside a declared wait: the mask exists to hide them.
    sensitive = _sensitive_intervals(index, source_start, source_end)

    def masked(moment: float) -> bool:
        return any(start - 1e-6 <= moment < end for start, end, _ in sensitive)

    # A wait shorter than the limit already fits, and padding it out to the
    # minimum idle output would make the edited video longer than the source.
    declared = [
        interval
        for interval in _wait_intervals(index, source_start, source_end)
        if interval[1] - interval[0] > limit
    ]
    for start, end, reason in declared:
        for span, changed in zip(frames[1:], meaningful[1:], strict=True):
            # The frame that was already on screen when the wait began carries
            # the transition into the wait itself, not a change during it.
            if (
                span.start > start + 1e-6
                and span.start < end
                and changed
                and not masked(span.start)
            ):
                raise VideoError(
                    f"wait {reason!r} contains a visible transition at "
                    f"{span.path.name}; it cannot be accelerated"
                )

    detected = _detected_unchanged(frames, meaningful, limit=limit)
    idle = _merge([*declared, *detected])
    for start, end, reason in sensitive:
        if end - start > limit:
            idle = _force_idle(idle, start, end, f"masked {reason}")

    # Every declared wait must survive as accelerated intervals. Dropping one
    # would silently remove recorded time from the finished video. A mask can
    # split a wait into several adjacent intervals, so require continuous
    # coverage rather than one interval per wait.
    for start, end, reason in declared:
        covered = start
        for covered_start, covered_end, _ in idle:
            if covered_start <= covered + 1e-6:
                covered = max(covered, covered_end)
        if covered < end - 1e-6:
            raise VideoError(f"declared wait {reason!r} was not scheduled as idle")

    segments: list[Segment] = []
    output = 0.0
    cursor = source_start
    frame_budget = max(1, int(target * fps))

    def append_normal(start: float, end: float) -> None:
        nonlocal output, cursor
        duration = end - start
        if duration <= 1e-9:
            return
        count = max(1, int(round(duration * fps)))
        chosen = _sample_preferring(frames, visible, start, end, count)
        if not chosen:
            raise VideoError(
                f"no frame covers {duration:.1f}s at source time {start:.1f}"
            )
        # Rounded to whole frames so the rendered video is exactly this long.
        edited = count / fps
        segments.append(
            Segment(
                kind="normal",
                source_start=start,
                source_end=end,
                output_start=output,
                output_duration=edited,
                frames=chosen,
            )
        )
        output += edited
        cursor = end

    def append_idle(start: float, end: float, reason: str) -> None:
        nonlocal output, cursor
        duration = end - start
        if duration <= 1e-9:
            return
        inside = [
            frame for frame in visible if frame.start < end and frame.end > start
        ] or [frame for frame in frames if frame.start < end and frame.end > start]
        if not inside:
            raise VideoError(f"idle interval {reason!r} has no captured frame")
        wanted = min(target, max(MIN_IDLE_OUTPUT, duration / IDLE_SPEED_FLOOR))
        sample_count = max(1, min(frame_budget, int(round(wanted * fps))))
        # Repeating the unchanged frame is the time-lapse; a real transition
        # inside a wait was already refused, and a reconnect placeholder is not
        # a screen state.
        sampled = _sample_preferring(frames, visible, start, end, sample_count)
        edited = sample_count / fps
        if edited > limit:
            sample_count = max(1, int(math.floor(limit * fps)))
            edited = sample_count / fps
        speed = duration / edited if edited > 0 else 1.0
        segments.append(
            Segment(
                kind="idle",
                source_start=start,
                source_end=end,
                output_start=output,
                output_duration=edited,
                frames=sampled,
                speed=speed,
                label=(f"{reason}: {_timing_text(start, end, edited, speed)}"),
            )
        )
        output += edited
        cursor = end

    for start, end, reason in idle:
        append_normal(cursor, start)
        append_idle(start, end, reason)
        cursor = end
    append_normal(cursor, source_end)

    covered = sum(segment.source_end - segment.source_start for segment in segments)
    if abs(covered - (source_end - source_start)) > 1e-6:
        raise VideoError(
            f"the edit covers {covered:.3f}s of {source_end - source_start:.3f}s"
        )

    chapters: list[Chapter] = []
    for meta in chapters_meta:
        scenario = str(meta.get("scenario") or "scenario")
        begin = meta.get("start")
        finish = meta.get("end")
        if isinstance(begin, bool) or not isinstance(begin, (int, float)):
            raise VideoError(f"chapter {scenario!r} has no source interval")
        if isinstance(finish, bool) or not isinstance(finish, (int, float)):
            raise VideoError(f"chapter {scenario!r} has no source interval")
        mapped_start = _map_time(segments, float(begin))
        mapped_end = _map_time(segments, float(finish))
        chapters.append(
            Chapter(
                scenario=scenario,
                title=str(meta.get("title") or ""),
                outcome=str(meta.get("outcome") or ""),
                start=mapped_start,
                end=max(mapped_start, mapped_end),
            )
        )

    idle_indexes = tuple(
        position for position, segment in enumerate(segments) if segment.kind == "idle"
    )
    redactions: list[Redaction] = []
    for start, end, reason in _sensitive_intervals(index, source_start, source_end):
        mapped_start = _map_time(segments, start)
        mapped_end = _map_time(segments, end)
        redactions.append(
            Redaction(
                reason=reason,
                source_start=start,
                source_end=end,
                output_start=mapped_start,
                output_end=max(mapped_start, mapped_end),
            )
        )
    return EditPlan(
        segments=tuple(segments),
        chapters=tuple(chapters),
        source_duration=source_end - source_start,
        output_duration=output,
        idle_intervals=idle_indexes,
        redactions=tuple(redactions),
    )


def _timing_text(
    source_start: float,
    source_end: float,
    output_duration: float,
    speed: float,
) -> str:
    """Describe one source-to-edited time-lapse without naming its reason."""
    return (
        f"{source_end - source_start:.0f}s source -> "
        f"{output_duration:.1f}s ({speed:.1f}x)"
    )


def _escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def _normalized_frame(
    ffmpeg: str,
    source: Path,
    target: Path,
    size: tuple[int, int],
) -> Path:
    """Return a canvas-sized PNG for a frame captured in another display mode.

    The image sequence mixes the firmware's 640x480 mode with the desktop's
    1280x800 mode. Feeding that directly to one ffmpeg filter graph makes it
    reconfigure on the first size change and drop the opening frame, so each
    off-size frame is converted once before the graph sees the sequence.
    """
    try:
        if png_size(source) == size:
            return source
    except (OSError, VideoError) as error:
        raise VideoError(f"captured frame {source} is unreadable") from error
    width, height = size
    key = hashlib.sha256(f"{source.resolve()}:{width}x{height}".encode()).hexdigest()[
        :16
    ]
    output = target / f"normalized-{key}.png"
    if output.is_file():
        return output
    completed = subprocess.run(  # noqa: S603 - fixed argv, never a shell
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vf",
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
            "-frames:v",
            "1",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0 or not output.is_file():
        raise VideoError(
            f"could not normalize captured frame {source}: "
            + (completed.stderr.strip() or "no diagnostic")[:300]
        )
    output.chmod(0o600)
    return output


def render(
    frames_dir: Path,
    plan: EditPlan,
    output: Path,
    *,
    labels: Sequence[tuple[float, float, str]] = (),
    footer_labels: Sequence[tuple[float, float, str]] = (),
    redactions: Sequence[Mapping[str, Any]] = (),
    size: tuple[int, int] | None = None,
    fps: int = FPS,
) -> Path:
    """Render the edit with ffmpeg, burning speed labels and redactions."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise VideoError("ffmpeg is not installed")
    frames_dir = Path(frames_dir)
    sequence = [frame for segment in plan.segments for frame in segment.frames]
    if not sequence:
        raise VideoError("the edit plan has no frames")
    # One link per output frame, at exactly the target frame rate: no duration
    # rounding, and the concat demuxer cannot add a frame at a boundary.
    links = frames_dir / ".render"
    if links.exists():
        shutil.rmtree(links)
    links.mkdir(mode=0o700)
    for index, frame in enumerate(sequence):
        path = frame.path if frame.path.is_absolute() else frames_dir / frame.path.name
        if not path.is_file():
            raise VideoError(f"captured frame {path} is missing")
        if size is not None:
            path = _normalized_frame(ffmpeg, path, links, size)
        (links / f"frame-{index:06d}.png").symlink_to(path.resolve())

    filters: list[str] = []
    if size is not None:
        width, height = size
        filters.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease")
        filters.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")
    filters.extend([f"fps={fps}", "format=yuv420p"])
    # Masks are composited first so the burned labels that explain the interval
    # stay readable over the covered area.
    for region in redactions:
        begin = region.get("start")
        finish = region.get("end")
        box = region.get("box")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            raise VideoError("a redaction region needs x, y, width and height")
        if isinstance(begin, bool) or not isinstance(begin, (int, float)):
            raise VideoError("a redaction region needs an output interval")
        if isinstance(finish, bool) or not isinstance(finish, (int, float)):
            raise VideoError("a redaction region needs an output interval")
        x, y, width, height = (int(value) for value in box)
        filters.append(
            f"drawbox=x={x}:y={y}:w={width}:h={height}:color=black@1.0:t=fill:"
            f"enable='between(t,{begin:.3f},{finish:.3f})'"
        )
    for y, group in ((12, labels), (44, footer_labels)):
        for start, end, text in group:
            filters.append(
                "drawtext=font=Sans:fontsize=18:fontcolor=white:box=1:"
                f"boxcolor=black@0.75:x=12:y={y}:text='{_escape_drawtext(text)}':"
                f"enable='between(t,{start:.3f},{end:.3f})'"
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(links / "frame-%06d.png"),
        "-vf",
        ",".join(filters),
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-movflags",
        "+faststart",
        "-an",
        str(output),
    ]
    completed = subprocess.run(  # noqa: S603 - fixed argv, never a shell
        command, capture_output=True, text=True, timeout=3600, check=False
    )
    if completed.returncode != 0:
        raise VideoError(
            "ffmpeg failed: " + (completed.stderr.strip() or "no diagnostic")[:600]
        )
    output.chmod(0o600)
    return output


def probe_timestamps(video: Path) -> list[float]:
    """Return decoded frame presentation timestamps, in output order."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise VideoError("ffprobe is not installed")
    completed = subprocess.run(  # noqa: S603 - fixed argv, never a shell
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "frame=best_effort_timestamp_time",
            "-of",
            "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
        timeout=1200,
        check=False,
    )
    if completed.returncode != 0:
        raise VideoError("ffprobe could not read the encoded video")
    stamps: list[float] = []
    for line in completed.stdout.splitlines():
        line = line.strip().rstrip(",")
        if not line or line == "N/A":
            continue
        try:
            stamps.append(float(line))
        except ValueError as error:
            raise VideoError(f"ffprobe returned a bad timestamp {line!r}") from error
    if not stamps:
        raise VideoError("the encoded video has no frames")
    return stamps


def verify(
    plan: EditPlan,
    video: Path,
    *,
    limit: float = IDLE_LIMIT,
    fps: int = FPS,
) -> dict[str, Any]:
    """Prove every planned idle interval fits the limit after encoding."""
    stamps = probe_timestamps(video)
    planned_frames = sum(len(segment.frames) for segment in plan.segments)
    if len(stamps) != planned_frames:
        raise VideoError(
            f"the encoded video has {len(stamps)} frames, the plan has {planned_frames}"
        )
    if len(stamps) < 2:
        raise VideoError("the encoded video has fewer than two frames")
    frame_duration = 1.0 / fps
    observed_end = stamps[-1] + frame_duration
    if abs(observed_end - plan.output_duration) > 2.0 * frame_duration:
        raise VideoError(
            f"encoded duration {observed_end:.2f}s does not match the plan "
            f"{plan.output_duration:.2f}s"
        )
    results: list[dict[str, Any]] = []
    for index in plan.idle_intervals:
        segment = plan.segments[index]
        inside = [
            stamp
            for stamp in stamps
            if segment.output_start - 1e-6 <= stamp < segment.output_end - 1e-6
        ]
        if not inside:
            raise VideoError(f"idle interval {index} occupies no encoded frame")
        measured = inside[-1] - inside[0] + frame_duration
        results.append(
            {
                "segment": index,
                "source_seconds": segment.source_end - segment.source_start,
                "edited_seconds": measured,
                "speed": segment.speed,
                "label": segment.label,
            }
        )
        if measured > limit + 1e-6:
            raise VideoError(
                f"idle interval {index} occupies {measured:.3f}s after encoding, "
                f"above the {limit:g}s limit"
            )
    for redaction in plan.redactions:
        if redaction.output_end <= redaction.output_start:
            continue
        if not (
            redaction.output_start >= 0.0
            and redaction.output_end <= observed_end + 1e-6
        ):
            raise VideoError(
                f"redaction {redaction.reason!r} maps outside the encoded video"
            )
    return {
        "video": str(video),
        "frames": len(stamps),
        "duration": observed_end,
        "idle_intervals": results,
        "redaction_intervals": [
            {
                "reason": redaction.reason,
                "source_seconds": redaction.source_end - redaction.source_start,
                "edited_start": redaction.output_start,
                "edited_seconds": redaction.output_end - redaction.output_start,
            }
            for redaction in plan.redactions
            if redaction.output_end > redaction.output_start
        ],
    }


def write_chapters(plan: EditPlan, path: Path) -> None:
    """Write an FFmetadata chapter file at edited timestamps."""
    lines = [";FFMETADATA1"]
    for chapter in plan.chapters:
        if chapter.end <= chapter.start:
            continue
        title = chapter.title or chapter.scenario
        outcome = f" [{chapter.outcome}]" if chapter.outcome else ""
        escaped = (title + outcome).replace("=", r"\=")
        lines.extend(
            [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={int(round(chapter.start * 1000))}",
                f"END={int(round(chapter.end * 1000))}",
                f"title={chapter.scenario} - {escaped}",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


def attach_chapters(video: Path, metadata: Path, output: Path) -> Path:
    """Remux the encoded video with its chapters; the stream is not re-encoded."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise VideoError("ffmpeg is not installed")
    completed = subprocess.run(  # noqa: S603 - fixed argv, never a shell
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-i",
            str(metadata),
            "-map_metadata",
            "1",
            "-map_chapters",
            "1",
            "-c",
            "copy",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if completed.returncode != 0:
        raise VideoError(
            "ffmpeg could not attach chapters: "
            + (completed.stderr.strip() or "no diagnostic")[:400]
        )
    output.chmod(0o600)
    return output


def render_labels(plan: EditPlan) -> list[tuple[float, float, str]]:
    """Burn one speed label per accelerated interval.

    A fully masked interval carries its speed and real elapsed wait inside the
    privacy label (`redaction_labels`), so no second label is drawn over the
    mask. A partly visible interval keeps its own speed label.
    """
    labels: list[tuple[float, float, str]] = []
    for position in plan.idle_intervals:
        segment = plan.segments[position]
        if not segment.label:
            continue
        if any(
            redaction.output_start <= segment.output_start + 1e-6
            and redaction.output_end >= segment.output_end - 1e-6
            for redaction in plan.redactions
        ):
            continue
        labels.append((segment.output_start, segment.output_end, segment.label))
    return labels


def chapter_labels(plan: EditPlan) -> list[tuple[float, float, str]]:
    return [
        (
            chapter.start,
            min(chapter.end, chapter.start + 6.0),
            f"{chapter.scenario} | {chapter.title} | {chapter.outcome}",
        )
        for chapter in plan.chapters
        if chapter.end > chapter.start
    ]


def redaction_labels(plan: EditPlan) -> list[tuple[float, float, str]]:
    """Label each masked interval without echoing what it contains.

    An accelerated interval that is fully masked keeps its speed and real
    elapsed wait in this label. The mask therefore preserves the timing
    evidence the idle limit requires without drawing a second label over it.
    """
    labels: list[tuple[float, float, str]] = []
    for redaction in plan.redactions:
        if redaction.output_end <= redaction.output_start:
            continue
        text = f"{redaction.reason} hidden for privacy"
        timing: list[str] = []
        for position in plan.idle_intervals:
            segment = plan.segments[position]
            if (
                segment.label
                and redaction.output_start <= segment.output_start + 1e-6
                and redaction.output_end >= segment.output_end - 1e-6
            ):
                timing.append(
                    _timing_text(
                        segment.source_start,
                        segment.source_end,
                        segment.output_duration,
                        segment.speed,
                    )
                )
        if timing:
            text += " | " + "; ".join(timing)
        labels.append((redaction.output_start, redaction.output_end, text))
    return labels


def read_index(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VideoError(f"cannot read capture index {path}") from error
    if not isinstance(payload, dict):
        raise VideoError("the capture index is not an object")
    return payload


__all__ = [
    "Chapter",
    "EditPlan",
    "FPS",
    "FrameSpan",
    "IDLE_LIMIT",
    "Segment",
    "VideoError",
    "attach_chapters",
    "chapter_labels",
    "frame_spans",
    "plan_edit",
    "png_size",
    "probe_timestamps",
    "read_index",
    "render",
    "render_labels",
    "verify",
    "write_chapters",
]
