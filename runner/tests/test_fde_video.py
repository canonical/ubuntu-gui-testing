from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from ubuntu_gui_testing_runner.fde_capture import synthetic_frame
from ubuntu_gui_testing_runner.fde_video import (
    FPS,
    FrameSpan,
    Redaction,
    VideoError,
    attach_chapters,
    frame_spans,
    plan_edit,
    png_size,
    probe_timestamps,
    read_index,
    redaction_labels,
    render,
    render_labels,
    verify,
    write_chapters,
)

RED = (200, 30, 30)
BLUE = (30, 30, 200)
GREEN = (30, 200, 30)
GREY = (128, 128, 128)
BLACK = (0, 0, 0)

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are not installed",
)


def _frame(tmp_path: Path, index: int, colour: tuple[int, int, int]) -> Path:
    return synthetic_frame(tmp_path / f"frame-{index:03d}.png", 32, 20, colour)


def _timeline(
    tmp_path: Path, specs: list[tuple[tuple[int, int, int], float, float]]
) -> tuple[list[FrameSpan], dict[str, Any]]:
    frames: list[FrameSpan] = []
    entries: list[dict[str, Any]] = []
    for index, (colour, start, end) in enumerate(specs):
        path = _frame(tmp_path, index, colour)
        frames.append(FrameSpan(path=path, start=start, end=end))
        entries.append({"path": str(path), "started_at": start, "ended_at": end})
    return frames, {"frames": entries, "events": []}


def _wait(
    events: list[dict[str, Any]], start: float, end: float, reason: str, ident: str
) -> None:
    events.append(
        {"event": "wait-start", "at": start, "wait-id": ident, "reason": reason}
    )
    events.append({"event": "wait-end", "at": end, "wait-id": ident})


def test_frame_spans_validate_the_capture_index(tmp_path: Path) -> None:
    frames, index = _timeline(tmp_path, [(RED, 0.0, 1.0)])
    assert frame_spans(index) == tuple(frames)
    with pytest.raises(VideoError, match="no frames"):
        frame_spans({"frames": []})
    with pytest.raises(VideoError, match="no start time"):
        frame_spans({"frames": [{"path": "a.png", "ended_at": 1.0}]})
    with pytest.raises(VideoError, match="ends before it starts"):
        frame_spans({"frames": [{"path": "a.png", "started_at": 2.0, "ended_at": 1.0}]})
    with pytest.raises(VideoError, match="overlap"):
        frame_spans(
            {
                "frames": [
                    {"path": "a.png", "started_at": 0.0, "ended_at": 3.0},
                    {"path": "b.png", "started_at": 2.0, "ended_at": 4.0},
                ]
            }
        )


def test_declared_wait_is_accelerated_and_covers_the_timeline(
    tmp_path: Path,
) -> None:
    frames, index = _timeline(
        tmp_path, [(GREY, 0.0, 1.0), (BLUE, 1.0, 21.0), (GREEN, 21.0, 22.0)]
    )
    _wait(index["events"], 1.0, 21.0, "recovery prompt", "w1")
    plan = plan_edit(index, frames, [])
    idle = plan.idle_segments()
    assert len(idle) == 1
    assert idle[0].source_start == pytest.approx(1.0)
    assert idle[0].source_end == pytest.approx(21.0)
    assert 1.0 <= idle[0].output_duration <= 4.0
    assert idle[0].output_duration == pytest.approx(2.0)
    assert "20s source" in idle[0].label
    assert plan.output_duration == pytest.approx(
        plan.segments[0].output_duration
        + idle[0].output_duration
        + plan.segments[-1].output_duration
    )


def test_the_frame_that_begins_a_wait_may_carry_the_transition(
    tmp_path: Path,
) -> None:
    # The wait starts exactly when the prompt appears; that frame differs from
    # the one before the wait and must not be mistaken for activity during it.
    frames, index = _timeline(tmp_path, [(GREY, 0.0, 1.0), (BLUE, 1.0, 11.0)])
    _wait(index["events"], 1.0, 11.0, "repair", "w1")
    plan = plan_edit(index, frames, [])
    assert len(plan.idle_segments()) == 1


def test_a_transition_inside_a_declared_wait_is_refused(tmp_path: Path) -> None:
    frames, index = _timeline(
        tmp_path, [(GREY, 0.0, 1.0), (BLUE, 1.0, 2.0), (RED, 2.0, 12.0)]
    )
    _wait(index["events"], 1.0, 12.0, "repair", "w1")
    with pytest.raises(VideoError, match="contains a visible transition"):
        plan_edit(index, frames, [])


def _reconnect(events: list[dict[str, Any]], at: float, *, opens_at: float) -> None:
    events.append({"event": "capture-disconnected", "at": opens_at})
    events.append({"event": "capture-connected", "at": at})


def test_a_reconnect_blank_frame_does_not_break_a_declared_wait(
    tmp_path: Path,
) -> None:
    # The capture client times out every half minute and its first frame after
    # reconnect is black. That transport placeholder must not turn a 10-second
    # declared wait into a refused transition, and it must not be sampled.
    frames, index = _timeline(
        tmp_path,
        [(GREY, 0.0, 1.0), (BLUE, 1.0, 2.0), (BLACK, 2.0, 2.06), (BLUE, 2.06, 12.0)],
    )
    _wait(index["events"], 1.0, 12.0, "repair", "w1")
    _reconnect(index["events"], 2.0, opens_at=1.9)
    plan = plan_edit(index, frames, [])
    idle = plan.idle_segments()
    assert len(idle) == 1
    assert idle[0].source_start == pytest.approx(1.0)
    assert idle[0].source_end == pytest.approx(12.0)
    assert idle[0].output_duration <= 4.0
    assert all(frame.path.name != "frame-002.png" for frame in idle[0].frames)


def test_a_real_change_across_a_reconnect_is_still_refused(
    tmp_path: Path,
) -> None:
    # Substituting the last real frame for the placeholder must not hide a
    # genuine change that happened while the display was down.
    frames, index = _timeline(
        tmp_path,
        [
            (GREY, 0.0, 1.0),
            (BLUE, 1.0, 2.0),
            (BLACK, 2.0, 2.06),
            (RED, 2.06, 12.0),
        ],
    )
    _wait(index["events"], 1.0, 12.0, "repair", "w1")
    _reconnect(index["events"], 2.0, opens_at=1.9)
    with pytest.raises(VideoError, match="contains a visible transition"):
        plan_edit(index, frames, [])


def test_a_black_frame_away_from_a_reconnect_is_still_a_transition(
    tmp_path: Path,
) -> None:
    frames, index = _timeline(
        tmp_path, [(GREY, 0.0, 1.0), (BLUE, 1.0, 2.0), (BLACK, 2.0, 12.0)]
    )
    _wait(index["events"], 1.0, 12.0, "repair", "w1")
    with pytest.raises(VideoError, match="contains a visible transition"):
        plan_edit(index, frames, [])


def test_a_reconnect_blank_frame_does_not_split_an_unchanged_run(
    tmp_path: Path,
) -> None:
    frames, index = _timeline(
        tmp_path,
        [
            (GREY, 0.0, 1.0),
            (BLUE, 1.0, 10.0),
            (BLACK, 10.0, 10.06),
            (BLUE, 10.06, 21.0),
        ],
    )
    _reconnect(index["events"], 10.0, opens_at=9.9)
    plan = plan_edit(index, frames, [])
    idle = plan.idle_segments()
    assert len(idle) == 1
    assert idle[0].source_start == pytest.approx(1.0)
    assert idle[0].source_end == pytest.approx(21.0)
    assert all(frame.path.name != "frame-002.png" for frame in idle[0].frames)


def test_a_long_masked_interval_is_capped_even_when_the_screen_changes(
    tmp_path: Path,
) -> None:
    # Content under a privacy mask can keep changing, so visual idle detection
    # cannot see it. A mask longer than the limit would otherwise become a
    # long static black block in the finished video.
    specs: list[tuple[tuple[int, int, int], float, float]] = []
    for second in range(1, 10):
        colour = BLUE if second % 2 else RED
        specs.append((colour, float(second), float(second + 1)))
    frames, index = _timeline(tmp_path, [(GREY, 0.0, 1.0), *specs, (GREEN, 10.0, 11.0)])
    _sensitive(index["events"], 1.0, 10.0)
    plan = plan_edit(index, frames, [])
    idle = plan.idle_segments()
    assert len(idle) == 1
    assert idle[0].source_start == pytest.approx(1.0)
    assert idle[0].source_end == pytest.approx(10.0)
    assert 1.0 <= idle[0].output_duration <= 4.0
    assert len(plan.redactions) == 1
    assert plan.redactions[0].output_start == pytest.approx(idle[0].output_start)
    assert plan.redactions[0].output_end == pytest.approx(idle[0].output_end)


def test_a_transition_inside_a_masked_declared_wait_is_allowed(
    tmp_path: Path,
) -> None:
    # The mask exists to hide this transition; it is not evidence of activity
    # that must keep the wait at normal speed.
    frames, index = _timeline(
        tmp_path, [(GREY, 0.0, 1.0), (BLUE, 1.0, 2.0), (RED, 2.0, 12.0)]
    )
    _wait(index["events"], 1.0, 12.0, "repair", "w1")
    _sensitive(index["events"], 1.0, 12.0)
    plan = plan_edit(index, frames, [])
    idle = plan.idle_segments()
    assert len(idle) == 1
    assert idle[0].source_start == pytest.approx(1.0)
    assert idle[0].source_end == pytest.approx(12.0)
    assert idle[0].output_duration <= 4.0


def test_a_long_mask_inside_a_declared_wait_keeps_the_wait_covered(
    tmp_path: Path,
) -> None:
    # Capping the masked slice must split the wait, never shorten it: every
    # source second up to the wait end must still map onto the edit.
    frames, index = _timeline(
        tmp_path,
        [
            (GREY, 0.0, 1.0),
            (BLUE, 1.0, 6.0),
            (RED, 6.0, 12.0),
            (GREEN, 12.0, 13.0),
        ],
    )
    _wait(index["events"], 1.0, 12.0, "repair", "w1")
    _sensitive(index["events"], 4.0, 9.0)
    plan = plan_edit(index, frames, [])
    idle = plan.idle_segments()
    assert len(idle) == 3
    assert idle[0].source_start == pytest.approx(1.0)
    assert idle[-1].source_end == pytest.approx(12.0)
    assert all(segment.output_duration <= 4.0 for segment in idle)


def test_a_fully_masked_idle_segment_keeps_its_timing_in_the_privacy_label(
    tmp_path: Path,
) -> None:
    frames, index = _timeline(
        tmp_path, [(GREY, 0.0, 1.0), (BLUE, 1.0, 11.0), (GREEN, 11.0, 12.0)]
    )
    _sensitive(index["events"], 1.0, 11.0)
    plan = plan_edit(index, frames, [])
    idle = plan.idle_segments()
    assert len(idle) == 1
    assert idle[0].label
    # No second label is drawn over the mask, but the required timing is folded
    # into the privacy label instead of being dropped.
    assert render_labels(plan) == []
    labels = redaction_labels(plan)
    assert len(labels) == 1
    assert labels[0][:2] == (idle[0].output_start, idle[0].output_end)
    assert labels[0][2].startswith("recovery key hidden for privacy | ")
    assert idle[0].label.split(": ", 1)[1] in labels[0][2]


def test_a_partly_masked_idle_segment_keeps_its_speed_label(tmp_path: Path) -> None:
    frames, index = _timeline(
        tmp_path, [(GREY, 0.0, 1.0), (BLUE, 1.0, 11.0), (GREEN, 11.0, 12.0)]
    )
    _sensitive(index["events"], 1.0, 5.0)
    plan = plan_edit(index, frames, [])
    idle = plan.idle_segments()
    assert len(idle) == 1
    assert render_labels(plan) == [
        (idle[0].output_start, idle[0].output_end, idle[0].label)
    ]


def test_a_long_single_frame_is_idle_without_a_marker(tmp_path: Path) -> None:
    frames, index = _timeline(tmp_path, [(GREY, 0.0, 10.0), (RED, 10.0, 10.5)])
    plan = plan_edit(index, frames, [])
    idle = plan.idle_segments()
    assert len(idle) == 1
    assert idle[0].source_end - idle[0].source_start == pytest.approx(10.0)
    # One sampled frame is repeated enough times to stay on screen for a moment.
    assert idle[0].output_duration == pytest.approx(1.0)
    assert len(idle[0].frames) == 30


def test_a_short_unchanged_run_is_not_accelerated(tmp_path: Path) -> None:
    frames, index = _timeline(
        tmp_path,
        [(GREY, 0.0, 1.0), (GREY, 1.0, 2.0), (GREY, 2.0, 3.0), (RED, 3.0, 4.0)],
    )
    plan = plan_edit(index, frames, [])
    assert plan.idle_segments() == ()
    assert plan.output_duration == pytest.approx(4.0)


def test_a_short_declared_wait_is_not_scheduled_as_idle(
    tmp_path: Path,
) -> None:
    # Every keyword the suite marks must not turn a sub-limit pause into a
    # padded idle segment that lengthens the finished video.
    frames, index = _timeline(
        tmp_path, [(GREY, 0.0, 1.0), (BLUE, 1.0, 2.0), (GREEN, 2.0, 3.0)]
    )
    _wait(index["events"], 1.0, 2.0, "short repair step", "w1")
    plan = plan_edit(index, frames, [])
    assert plan.idle_segments() == ()
    assert plan.output_duration == pytest.approx(3.0)


def _sensitive(
    events: list[dict[str, Any]],
    start: float,
    end: float,
    reason: str = "recovery key",
    ident: str = "s1",
) -> None:
    events.append(
        {
            "event": "sensitive-start",
            "at": start,
            "sensitive-id": ident,
            "reason": reason,
        }
    )
    events.append({"event": "sensitive-end", "at": end, "sensitive-id": ident})


def test_a_sensitive_interval_is_mapped_onto_the_edit(tmp_path: Path) -> None:
    frames, index = _timeline(
        tmp_path, [(GREY, 0.0, 1.0), (BLUE, 1.0, 21.0), (GREEN, 21.0, 22.0)]
    )
    _sensitive(index["events"], 1.0, 21.0, "recovery key", "s1")
    plan = plan_edit(index, frames, [])
    assert len(plan.redactions) == 1
    redaction = plan.redactions[0]
    assert redaction.reason == "recovery key"
    assert redaction.source_start == pytest.approx(1.0)
    assert redaction.source_end == pytest.approx(21.0)
    assert redaction.output_start == pytest.approx(1.0)
    # The interval was also idle, so its output end must follow the speed-up.
    assert redaction.output_end == pytest.approx(plan.segments[1].output_end)
    assert redaction.output_end - redaction.output_start < 4.0
    labels = redaction_labels(plan)
    assert len(labels) == 1
    assert labels[0][0] == redaction.output_start
    assert labels[0][1] == redaction.output_end
    assert labels[0][2].startswith("recovery key hidden for privacy | ")
    assert plan.segments[1].label.split(": ", 1)[1] in labels[0][2]


def test_a_display_outage_is_treated_as_an_accelerated_wait(
    tmp_path: Path,
) -> None:
    frames, index = _timeline(tmp_path, [(GREY, 0.0, 1.0), (BLUE, 1.0, 21.0)])
    index["events"] = [
        {"event": "capture-disconnected", "at": 1.0},
        {"event": "capture-connected", "at": 21.0},
    ]
    plan = plan_edit(index, frames, [])
    idle = plan.idle_segments()
    assert len(idle) == 1
    assert idle[0].source_start == pytest.approx(1.0)
    assert "display unavailable" in idle[0].label


def test_chapters_are_mapped_onto_the_edited_timeline(tmp_path: Path) -> None:
    frames, index = _timeline(
        tmp_path, [(GREY, 0.0, 1.0), (BLUE, 1.0, 11.0), (GREEN, 11.0, 12.0)]
    )
    _wait(index["events"], 1.0, 11.0, "repair", "w1")
    plan = plan_edit(
        index,
        frames,
        [
            {
                "scenario": "clear-tpm",
                "title": "TPM clear",
                "outcome": "passed",
                "start": 0.0,
                "end": 12.0,
            }
        ],
    )
    assert len(plan.chapters) == 1
    chapter = plan.chapters[0]
    assert chapter.start == 0.0
    assert chapter.end == pytest.approx(plan.output_duration)
    assert chapter.end < 12.0


def test_plan_rejects_an_empty_or_negative_timeline(tmp_path: Path) -> None:
    path = _frame(tmp_path, 0, RED)
    with pytest.raises(VideoError, match="no captured frames"):
        plan_edit({"frames": [], "events": []}, [], [])
    with pytest.raises(VideoError, match="no duration"):
        plan_edit(
            {"frames": [], "events": []},
            [FrameSpan(path=path, start=1.0, end=1.0)],
            [],
        )
    with pytest.raises(VideoError, match="cannot exceed"):
        plan_edit(
            {"frames": [], "events": []},
            [FrameSpan(path=path, start=0.0, end=1.0)],
            [],
            target=5.0,
        )


@needs_ffmpeg
def test_render_and_verify_keep_every_idle_interval_below_the_limit(
    tmp_path: Path,
) -> None:
    frames, index = _timeline(
        tmp_path, [(GREY, 0.0, 1.0), (BLUE, 1.0, 13.0), (GREEN, 13.0, 14.0)]
    )
    _wait(index["events"], 1.0, 13.0, "recovery prompt", "w1")
    plan = plan_edit(index, frames, [])
    output = render(
        tmp_path,
        plan,
        tmp_path / "run.mp4",
        labels=render_labels(plan),
        size=(32, 20),
    )
    audit = verify(plan, output)
    assert audit["frames"] >= 2
    assert len(audit["idle_intervals"]) == 1
    assert audit["idle_intervals"][0]["edited_seconds"] <= 4.0
    assert output.stat().st_mode & 0o077 == 0


@needs_ffmpeg
def test_verify_rejects_an_encoded_idle_interval_above_the_limit(
    tmp_path: Path,
) -> None:
    frames, index = _timeline(
        tmp_path, [(GREY, 0.0, 1.0), (BLUE, 1.0, 13.0), (GREEN, 13.0, 14.0)]
    )
    _wait(index["events"], 1.0, 13.0, "recovery prompt", "w1")
    plan = plan_edit(index, frames, [])
    output = render(tmp_path, plan, tmp_path / "run.mp4", size=(32, 20))
    with pytest.raises(VideoError, match="above the 1s limit"):
        verify(plan, output, limit=1.0)


@needs_ffmpeg
def test_chapters_are_attached_without_re_encoding(tmp_path: Path) -> None:
    frames, index = _timeline(tmp_path, [(RED, 0.0, 2.0), (GREEN, 2.0, 4.0)])
    plan = plan_edit(
        index,
        frames,
        [
            {
                "scenario": "case: one",
                "title": "first = chapter",
                "outcome": "passed",
                "start": 0.0,
                "end": 4.0,
            }
        ],
    )
    raw = render(tmp_path, plan, tmp_path / "raw.mp4", size=(32, 20))
    metadata = tmp_path / "chapters.ffmeta"
    write_chapters(plan, metadata)
    assert "case: one" in metadata.read_text(encoding="utf-8")
    assert r"first \= chapter" in metadata.read_text(encoding="utf-8")
    final = attach_chapters(raw, metadata, tmp_path / "final.mp4")
    assert final.is_file()
    assert final.stat().st_mode & 0o077 == 0
    assert probe_timestamps(final)


def test_png_size_and_index_reader(tmp_path: Path) -> None:
    path = _frame(tmp_path, 0, RED)
    assert png_size(path) == (32, 20)
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a png")
    with pytest.raises(VideoError, match="not a PNG"):
        png_size(bad)
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps({"frames": [], "events": []}), encoding="utf-8")
    assert read_index(index_path) == {"frames": [], "events": []}
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(VideoError, match="cannot read"):
        read_index(broken)
    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    with pytest.raises(VideoError, match="not an object"):
        read_index(array)


def test_fps_constant_matches_the_renderer() -> None:
    assert FPS == 30
    assert 1.0 / FPS < 0.04


@needs_ffmpeg
def test_render_burns_a_footer_label(tmp_path: Path) -> None:
    frames, index = _timeline(tmp_path, [(GREY, 0.0, 1.0), (BLUE, 1.0, 2.0)])
    plan = plan_edit(index, frames, [])
    output = render(
        tmp_path,
        plan,
        tmp_path / "footer.mp4",
        footer_labels=[(0.0, 1.0, "run test | snapd 2.78")],
        size=(320, 200),
    )
    assert output.is_file()


@needs_ffmpeg
def test_render_and_verify_record_a_masked_interval(tmp_path: Path) -> None:
    frames, index = _timeline(
        tmp_path, [(GREY, 0.0, 1.0), (BLUE, 1.0, 13.0), (GREEN, 13.0, 14.0)]
    )
    _sensitive(index["events"], 1.0, 13.0, "recovery key", "s1")
    plan = plan_edit(index, frames, [])
    assert len(plan.redactions) == 1
    redactions = [
        {
            "start": redaction.output_start,
            "end": redaction.output_end,
            "box": [0, 0, 32, 20],
        }
        for redaction in plan.redactions
    ]
    output = render(
        tmp_path,
        plan,
        tmp_path / "masked.mp4",
        labels=redaction_labels(plan),
        redactions=redactions,
        size=(32, 20),
    )
    audit = verify(plan, output)
    assert len(audit["redaction_intervals"]) == 1
    masked = audit["redaction_intervals"][0]
    assert masked["reason"] == "recovery key"
    assert masked["edited_seconds"] <= 4.0
    # Metadata alone is not proof: decode a masked frame and a clean frame.
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None

    def frame_at(seconds: float) -> bytes:
        return subprocess.run(  # noqa: S603 - fixed argv, never a shell
            [
                ffmpeg,
                "-loglevel",
                "error",
                "-ss",
                f"{seconds:.2f}",
                "-i",
                str(output),
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            check=True,
            capture_output=True,
        ).stdout

    def saturated_pixels(raw: bytes) -> int:
        count = 0
        for offset in range(0, len(raw), 3):
            red, green, blue = raw[offset : offset + 3]
            if max(red, green, blue) - min(red, green, blue) > 60:
                count += 1
        return count

    # The masked interval contains only black and the white label; the green
    # segment after it proves the decoder is reading real colour frames.
    assert saturated_pixels(frame_at(2.0)) == 0
    assert saturated_pixels(frame_at(plan.output_duration - 0.2)) > 0


@needs_ffmpeg
def test_render_keeps_a_single_off_size_frame_before_the_desktop(
    tmp_path: Path,
) -> None:
    # The first case opens in the firmware's 640x480 mode and the desktop then
    # switches to 1280x800. A lone off-size frame made ffmpeg reconfigure its
    # graph and drop that opening frame, so the encoded count was one short.
    first = synthetic_frame(tmp_path / "frame-000.png", 32, 20, GREY)
    second = synthetic_frame(tmp_path / "frame-001.png", 16, 10, BLUE)
    frames = [
        FrameSpan(first, 0.0, 1 / 30),
        FrameSpan(second, 1 / 30, 10 + 1 / 30),
    ]
    index = {
        "frames": [
            {"path": str(first), "started_at": 0.0, "ended_at": 1 / 30},
            {"path": str(second), "started_at": 1 / 30, "ended_at": 10 + 1 / 30},
        ],
        "events": [],
    }
    plan = plan_edit(index, frames, [])
    output = render(tmp_path, plan, tmp_path / "mixed.mp4", size=(32, 20))
    audit = verify(plan, output)
    assert audit["frames"] == sum(len(segment.frames) for segment in plan.segments)


@needs_ffmpeg
def test_verify_rejects_a_redaction_outside_the_video(tmp_path: Path) -> None:
    frames, index = _timeline(
        tmp_path, [(GREY, 0.0, 1.0), (BLUE, 1.0, 13.0), (GREEN, 13.0, 14.0)]
    )
    plan = plan_edit(index, frames, [])
    output = render(tmp_path, plan, tmp_path / "plain.mp4", size=(32, 20))
    stray = replace(
        plan,
        redactions=(Redaction("recovery key", 1.0, 13.0, 0.0, 999.0),),
    )
    with pytest.raises(VideoError, match="outside the encoded video"):
        verify(stray, output)
