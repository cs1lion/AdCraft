"""Tests for timeline subtitle SRT/ASS serialization (ADR 0007 Phase 3.3)."""

from __future__ import annotations

from app.schemas.timeline import (
    TimelineClipV1,
    TimelineSubtitleStyleV1,
)
from app.services.timeline_subtitle_writer import clips_to_ass, clips_to_srt

_TS = "2026-09-18T00:00:00+00:00"


def _subtitle_clip(
    clip_id: str,
    *,
    text: str | None,
    start_time: float = 0.0,
    duration: float = 1.0,
    style: TimelineSubtitleStyleV1 | None = None,
) -> TimelineClipV1:
    return TimelineClipV1(
        clip_id=clip_id,
        track_id="track-subtitle",
        start_time=start_time,
        duration=duration,
        subtitle_text=text,
        subtitle_style=style,
        created_at=_TS,
        updated_at=_TS,
    )


def test_srt_serializes_indexed_cues_with_timestamps() -> None:
    document = clips_to_srt(
        [
            _subtitle_clip("c1", text="Hello", start_time=0.0, duration=1.5),
            _subtitle_clip("c2", text="Goodbye", start_time=2.0, duration=1.0),
        ]
    )

    lines = document.splitlines()
    assert lines[0] == "1"
    assert lines[1] == "00:00:00,000 --> 00:00:01,500"
    assert lines[2] == "Hello"
    assert "2" in lines
    assert "00:00:02,000 --> 00:00:03,000" in document
    assert "Goodbye" in document
    # Blocks are separated by a blank line.
    assert "\n\n2\n" in document


def test_srt_keeps_multiline_text_and_rounds_milliseconds() -> None:
    document = clips_to_srt(
        [_subtitle_clip("c1", text="line one\nline two", start_time=0.0, duration=1.0009)]
    )

    assert "00:00:00,000 --> 00:00:01,001" in document
    assert "line one\nline two" in document


def test_srt_sorts_by_start_time_and_skips_empty_cues() -> None:
    document = clips_to_srt(
        [
            _subtitle_clip("later", text="Later", start_time=4.0, duration=1.0),
            _subtitle_clip("blank", text="   ", start_time=1.0, duration=1.0),
            _subtitle_clip("none", text=None, start_time=2.0, duration=1.0),
            _subtitle_clip("first", text="First", start_time=0.5, duration=1.0),
        ]
    )

    # Only the two non-empty cues survive, ordered chronologically.
    assert document.index("First") < document.index("Later")
    assert "Later" not in document.split("First")[0]
    assert document.startswith("1\n")


def test_ass_document_has_sections_and_default_style() -> None:
    document = clips_to_ass([_subtitle_clip("c1", text="Hello")])

    assert "[Script Info]" in document
    assert "ScriptType: v4.00+" in document
    assert "PlayResX: 1920" in document
    assert "PlayResY: 1080" in document
    assert "[V4+ Styles]" in document
    assert document.startswith("[Script Info]")
    assert "Style: Default,Arial,52,&H00FFFFFF,&H00FFFFFF,&H00101010," in document
    assert "[Events]" in document
    assert (
        "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Hello" in document
    )


def test_ass_emits_per_cue_style_with_bgr_colors_and_alignment() -> None:
    style = TimelineSubtitleStyleV1(
        font_family="Noto Sans",
        font_size=64,
        primary_color="#ff8800",
        outline_color="#000000",
        position="top",
        bold=True,
        italic=True,
    )
    document = clips_to_ass(
        [_subtitle_clip("c1", text="Styled", start_time=1.0, duration=2.0, style=style)]
    )

    style_line = next(
        line for line in document.splitlines() if line.startswith("Style: Subtitle1,")
    )
    # ASS colours are &HAABBGGRR: #ff8800 -> BB=00 GG=88 RR=ff.
    assert "&H000088FF" in style_line
    assert "&H00000000" in style_line
    assert "Noto Sans,64," in style_line
    # Top-centre alignment is numpad 8; bold/italic are -1.
    assert style_line.rstrip().endswith(",-1,-1,0,0,100,100,0,0,1,3,0,8,40,40,60,1")
    dialogue = next(
        line for line in document.splitlines() if line.startswith("Dialogue:")
    )
    assert dialogue == (
        "Dialogue: 0,0:00:01.00,0:00:03.00,Subtitle1,,0,0,0,,Styled"
    )


def test_ass_middle_position_uses_alignment_five_with_no_vertical_margin() -> None:
    style = TimelineSubtitleStyleV1(position="middle")
    document = clips_to_ass([_subtitle_clip("c1", text="Center", style=style)])

    style_line = next(
        line for line in document.splitlines() if line.startswith("Style: Subtitle1,")
    )
    assert ",5,40,40,0,1" in style_line


def test_ass_escapes_newlines_and_braces() -> None:
    document = clips_to_ass(
        [_subtitle_clip("c1", text="first line\n{override} second")]
    )

    dialogue = next(
        line for line in document.splitlines() if line.startswith("Dialogue:")
    )
    assert r"\N" in dialogue
    assert "{override}" not in dialogue
    assert "(override) second" in dialogue


def test_ass_empty_style_object_falls_back_to_default_style() -> None:
    document = clips_to_ass(
        [
            _subtitle_clip(
                "c1",
                text="Plain",
                style=TimelineSubtitleStyleV1(),
            )
        ]
    )

    assert "Style: Subtitle1," not in document
    dialogue = next(
        line for line in document.splitlines() if line.startswith("Dialogue:")
    )
    assert ",Default,,0,0,0,,Plain" in dialogue


def test_srt_and_ass_return_empty_documents_without_cues() -> None:
    assert clips_to_srt([]) == ""
    ass = clips_to_ass([])
    assert "[Events]" in ass
    assert "Dialogue:" not in ass
