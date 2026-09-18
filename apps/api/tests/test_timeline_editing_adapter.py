"""Tests for TimelineV1 → EditingManifestV2 audio conversion (ADR 0007 Phase 1)."""

from __future__ import annotations

import pytest

from app.schemas.agent_canvas_editing import EditingDuckingConfigV2
from app.schemas.timeline import (
    TimelineClipV1,
    TimelineDuckingConfigV1,
    TimelineSubtitleStyleV1,
    TimelineTrackV1,
    TimelineV1,
    TimelineVolumeKeyframeV1,
)
from app.services.timeline_editing_adapter import TimelineEditingAdapter

_TS = "2026-09-20T00:00:00+00:00"


def _clip(
    clip_id: str,
    *,
    track_id: str,
    asset_id: str | None,
    start_time: float,
    duration: float,
    source_start: float = 0.0,
    source_duration: float | None = None,
    fade_in: float | None = None,
    fade_out: float | None = None,
    transition_in_type: str | None = None,
    transition_in_duration: float | None = None,
    transition_out_type: str | None = None,
    transition_out_duration: float | None = None,
    subtitle_text: str | None = None,
    subtitle_style: TimelineSubtitleStyleV1 | None = None,
    volume_keyframes: tuple[TimelineVolumeKeyframeV1, ...] = (),
) -> TimelineClipV1:
    return TimelineClipV1(
        clip_id=clip_id,
        track_id=track_id,
        asset_id=asset_id,
        start_time=start_time,
        duration=duration,
        source_start=source_start,
        source_duration=source_duration,
        fade_in=fade_in,
        fade_out=fade_out,
        transition_in_type=transition_in_type,
        transition_in_duration=transition_in_duration,
        transition_out_type=transition_out_type,
        transition_out_duration=transition_out_duration,
        subtitle_text=subtitle_text,
        subtitle_style=subtitle_style,
        volume_keyframes=volume_keyframes,
        created_at=_TS,
        updated_at=_TS,
    )


def _track(
    track_type: str,
    clips: tuple[TimelineClipV1, ...],
    *,
    muted: bool = False,
    volume: float = 1.0,
) -> TimelineTrackV1:
    return TimelineTrackV1(
        track_id=f"track-{track_type}",
        timeline_id="timeline-1",
        type=track_type,
        name=track_type,
        muted=muted,
        volume=volume,
        clips=clips,
        created_at=_TS,
        updated_at=_TS,
    )


def _timeline(
    *tracks: TimelineTrackV1,
    duration_seconds: float = 3.0,
    ducking: TimelineDuckingConfigV1 | None = None,
    subtitle_burn_in: bool = True,
) -> TimelineV1:
    return TimelineV1(
        timeline_id="timeline-1",
        workflow_id="workflow-1",
        duration_seconds=duration_seconds,
        ducking=ducking,
        subtitle_burn_in=subtitle_burn_in,
        tracks=tracks,
        created_at=_TS,
        updated_at=_TS,
    )


class TestAudioEntries:
    def test_all_audio_roles_enter_manifest_with_positions(self) -> None:
        result = TimelineEditingAdapter().convert(
            _timeline(
                _track("video", (_clip("c-v", track_id="track-video", asset_id="v1", start_time=0, duration=2),)),
                _track(
                    "voice",
                    (_clip("c-voice", track_id="track-voice", asset_id="a-voice", start_time=1.0, duration=1.0),),
                ),
                _track(
                    "bgm",
                    (_clip("c-bgm", track_id="track-bgm", asset_id="a-bgm", start_time=0.0, duration=3.0),),
                ),
                _track(
                    "sfx",
                    (_clip("c-sfx", track_id="track-sfx", asset_id="a-sfx", start_time=2.0, duration=0.5),),
                ),
            )
        )

        manifest = result.manifest
        assert manifest.bgm is None
        assert [entry.role for entry in manifest.audio_entries] == ["voice", "bgm", "sfx"]
        voice, bgm, sfx = manifest.audio_entries
        assert voice.asset_id == "a-voice"
        assert voice.timeline_start_seconds == 1.0
        assert voice.volume == 1.0
        assert bgm.asset_id == "a-bgm"
        assert bgm.timeline_start_seconds == 0.0
        assert bgm.volume == 0.3
        assert sfx.timeline_start_seconds == 2.0
        assert sfx.volume == 1.0
        assert result.voice_clip_count == 1
        assert result.bgm_clip_count == 1
        assert result.sfx_clip_count == 1

    def test_ducking_enabled_only_with_voice_and_bgm(self) -> None:
        with_both = TimelineEditingAdapter().convert(
            _timeline(
                _track("video", (_clip("c-v", track_id="track-video", asset_id="v1", start_time=0, duration=2),)),
                _track("voice", (_clip("c-voice", track_id="track-voice", asset_id="av", start_time=0, duration=1),)),
                _track("bgm", (_clip("c-bgm", track_id="track-bgm", asset_id="ab", start_time=0, duration=2),)),
            )
        )
        assert with_both.manifest.ducking == EditingDuckingConfigV2()
        assert with_both.manifest.ducking.enabled is True

        without_voice = TimelineEditingAdapter().convert(
            _timeline(
                _track("video", (_clip("c-v", track_id="track-video", asset_id="v1", start_time=0, duration=2),)),
                _track("bgm", (_clip("c-bgm", track_id="track-bgm", asset_id="ab", start_time=0, duration=2),)),
            )
        )
        assert without_voice.manifest.ducking is None

    def test_multiple_bgm_clips_all_emitted_in_start_order(self) -> None:
        result = TimelineEditingAdapter().convert(
            _timeline(
                _track("video", (_clip("c-v", track_id="track-video", asset_id="v1", start_time=0, duration=6),)),
                _track(
                    "bgm",
                    (
                        _clip("bgm-late", track_id="track-bgm", asset_id="bgm2", start_time=4.0, duration=2.0),
                        _clip("bgm-early", track_id="track-bgm", asset_id="bgm1", start_time=0.0, duration=3.0),
                    ),
                ),
                duration_seconds=6.0,
            )
        )

        bgm_entries = [entry for entry in result.manifest.audio_entries if entry.role == "bgm"]
        assert [entry.asset_id for entry in bgm_entries] == ["bgm1", "bgm2"]
        assert [entry.timeline_start_seconds for entry in bgm_entries] == [0.0, 4.0]
        assert result.bgm_clip_count == 2

    def test_source_trim_volume_and_fades_map_to_entry(self) -> None:
        result = TimelineEditingAdapter().convert(
            _timeline(
                _track("video", (_clip("c-v", track_id="track-video", asset_id="v1", start_time=0, duration=2),)),
                _track(
                    "sfx",
                    (
                        _clip(
                            "c-sfx",
                            track_id="track-sfx",
                            asset_id="sfx1",
                            start_time=1.5,
                            duration=1.0,
                            source_start=2.0,
                            source_duration=0.5,
                            fade_in=0.1,
                            fade_out=0.2,
                        ),
                    ),
                    volume=0.4,
                ),
            )
        )

        sfx = result.manifest.audio_entries[0]
        assert sfx.trim_start_seconds == 2.0
        assert sfx.trim_end_seconds == 2.5
        assert sfx.volume == 0.4
        assert sfx.fade_in_seconds == 0.1
        assert sfx.fade_out_seconds == 0.2

    def test_volume_envelope_maps_onto_audio_entry(self) -> None:
        result = TimelineEditingAdapter().convert(
            _timeline(
                _track("video", (_clip("c-v", track_id="track-video", asset_id="v1", start_time=0, duration=3),)),
                _track(
                    "voice",
                    (
                        _clip(
                            "c-voice",
                            track_id="track-voice",
                            asset_id="av",
                            start_time=0.0,
                            duration=3.0,
                            volume_keyframes=(
                                TimelineVolumeKeyframeV1(time_seconds=2.0, value=0.1),
                                TimelineVolumeKeyframeV1(time_seconds=0.0, value=1.0),
                                TimelineVolumeKeyframeV1(time_seconds=1.0, value=0.1),
                            ),
                        ),
                    ),
                ),
            )
        )

        voice = result.manifest.audio_entries[0]
        assert [(point.time_seconds, point.value) for point in voice.volume_keyframes] == [
            (0.0, 1.0),
            (1.0, 0.1),
            (2.0, 0.1),
        ]

    def test_single_envelope_point_is_treated_as_flat(self) -> None:
        result = TimelineEditingAdapter().convert(
            _timeline(
                _track("video", (_clip("c-v", track_id="track-video", asset_id="v1", start_time=0, duration=2),)),
                _track(
                    "sfx",
                    (
                        _clip(
                            "c-sfx",
                            track_id="track-sfx",
                            asset_id="sfx1",
                            start_time=0.0,
                            duration=2.0,
                            volume_keyframes=(
                                TimelineVolumeKeyframeV1(time_seconds=0.5, value=0.2),
                            ),
                        ),
                    ),
                ),
            )
        )

        assert result.manifest.audio_entries[0].volume_keyframes == ()

    def test_muted_track_clips_skipped_with_warning(self) -> None:
        result = TimelineEditingAdapter().convert(
            _timeline(
                _track("video", (_clip("c-v", track_id="track-video", asset_id="v1", start_time=0, duration=2),)),
                _track(
                    "voice",
                    (_clip("c-voice", track_id="track-voice", asset_id="av", start_time=0, duration=1),),
                    muted=True,
                ),
                _track("bgm", (_clip("c-bgm", track_id="track-bgm", asset_id="ab", start_time=0, duration=2),)),
            )
        )

        assert result.manifest.audio_entries  # bgm still present
        assert all(entry.role != "voice" for entry in result.manifest.audio_entries)
        assert result.voice_clip_count == 0
        assert result.manifest.ducking is None
        assert any("muted" in warning for warning in result.warnings)

    def test_assetless_audio_clip_skipped_with_warning(self) -> None:
        result = TimelineEditingAdapter().convert(
            _timeline(
                _track("video", (_clip("c-v", track_id="track-video", asset_id="v1", start_time=0, duration=2),)),
                _track(
                    "sfx",
                    (_clip("c-sfx", track_id="track-sfx", asset_id=None, start_time=0, duration=1),),
                ),
            )
        )

        assert result.manifest.audio_entries == ()
        assert result.sfx_clip_count == 0
        assert any("no asset" in warning for warning in result.warnings)

    def test_no_audio_tracks_yields_empty_entries(self) -> None:
        result = TimelineEditingAdapter().convert(
            _timeline(
                _track("video", (_clip("c-v", track_id="track-video", asset_id="v1", start_time=0, duration=2),)),
            )
        )

        assert result.manifest.audio_entries == ()
        assert result.manifest.ducking is None


class TestStoredDuckingSettings:
    def _voice_bgm_timeline(self, **ducking) -> TimelineV1:
        config = TimelineDuckingConfigV1(**ducking) if ducking else None
        return _timeline(
            _track("video", (_clip("c-v", track_id="track-video", asset_id="v1", start_time=0, duration=2),)),
            _track("voice", (_clip("c-voice", track_id="track-voice", asset_id="av", start_time=0, duration=1),)),
            _track("bgm", (_clip("c-bgm", track_id="track-bgm", asset_id="ab", start_time=0, duration=2),)),
            ducking=config,
        )

    def test_custom_parameters_pass_through_to_manifest(self) -> None:
        result = TimelineEditingAdapter().convert(
            self._voice_bgm_timeline(
                threshold_db=-24.0,
                ratio=8.0,
                attack_ms=20,
                release_ms=400,
                makeup_gain_db=1.5,
            )
        )

        assert result.manifest.ducking == EditingDuckingConfigV2(
            threshold_db=-24.0,
            ratio=8.0,
            attack_ms=20,
            release_ms=400,
            makeup_gain_db=1.5,
        )

    def test_disabled_config_turns_ducking_off(self) -> None:
        result = TimelineEditingAdapter().convert(
            self._voice_bgm_timeline(enabled=False)
        )

        assert result.manifest.ducking is None
        # Audio entries are still emitted — only the sidechain is disabled.
        assert {entry.role for entry in result.manifest.audio_entries} == {"voice", "bgm"}

    def test_stored_config_ignored_without_both_roles(self) -> None:
        timeline = _timeline(
            _track("video", (_clip("c-v", track_id="track-video", asset_id="v1", start_time=0, duration=2),)),
            _track("voice", (_clip("c-voice", track_id="track-voice", asset_id="av", start_time=0, duration=1),)),
            ducking=TimelineDuckingConfigV1(threshold_db=-18.0),
        )

        result = TimelineEditingAdapter().convert(timeline)

        assert result.manifest.ducking is None


def _video_timeline(*clips: TimelineClipV1, duration: float = 6.0) -> TimelineV1:
    return _timeline(_track("video", clips), duration_seconds=duration)


class TestVideoTransitions:
    def test_incoming_dissolve_on_adjacent_clips_marks_incoming_entry(self) -> None:
        result = TimelineEditingAdapter().convert(
            _video_timeline(
                _clip("c1", track_id="track-video", asset_id="v1", start_time=0, duration=3),
                _clip(
                    "c2",
                    track_id="track-video",
                    asset_id="v2",
                    start_time=3,
                    duration=3,
                    transition_in_type="dissolve",
                    transition_in_duration=0.5,
                ),
            )
        )

        first, second = result.manifest.video_entries
        assert first.transition == "cut"
        assert first.transition_duration_seconds == 0.0
        assert second.transition == "dissolve"
        assert second.transition_duration_seconds == pytest.approx(0.5)
        assert result.warnings == ()

    def test_outgoing_dissolve_drives_the_same_boundary(self) -> None:
        result = TimelineEditingAdapter().convert(
            _video_timeline(
                _clip(
                    "c1",
                    track_id="track-video",
                    asset_id="v1",
                    start_time=0,
                    duration=3,
                    transition_out_type="dissolve",
                    transition_out_duration=0.75,
                ),
                _clip("c2", track_id="track-video", asset_id="v2", start_time=3, duration=3),
            )
        )

        first, second = result.manifest.video_entries
        assert first.transition == "cut"
        assert second.transition == "dissolve"
        assert second.transition_duration_seconds == pytest.approx(0.75)

    def test_shorter_edge_duration_wins(self) -> None:
        result = TimelineEditingAdapter().convert(
            _video_timeline(
                _clip(
                    "c1",
                    track_id="track-video",
                    asset_id="v1",
                    start_time=0,
                    duration=3,
                    transition_out_type="dissolve",
                    transition_out_duration=1.0,
                ),
                _clip(
                    "c2",
                    track_id="track-video",
                    asset_id="v2",
                    start_time=3,
                    duration=3,
                    transition_in_type="dissolve",
                    transition_in_duration=0.4,
                ),
            )
        )

        assert result.manifest.video_entries[1].transition_duration_seconds == pytest.approx(0.4)

    def test_dissolve_across_a_gap_falls_back_to_cut_with_warning(self) -> None:
        result = TimelineEditingAdapter().convert(
            _video_timeline(
                _clip("c1", track_id="track-video", asset_id="v1", start_time=0, duration=2),
                _clip(
                    "c2",
                    track_id="track-video",
                    asset_id="v2",
                    start_time=3,
                    duration=3,
                    transition_in_type="dissolve",
                    transition_in_duration=0.5,
                ),
            )
        )

        assert result.manifest.video_entries[1].transition == "cut"
        assert any("gap" in warning for warning in result.warnings)

    def test_dissolve_duration_is_capped_to_half_the_shorter_clip(self) -> None:
        result = TimelineEditingAdapter().convert(
            _video_timeline(
                _clip(
                    "c1",
                    track_id="track-video",
                    asset_id="v1",
                    start_time=0,
                    duration=2,
                    transition_out_type="dissolve",
                    transition_out_duration=2.0,
                ),
                _clip("c2", track_id="track-video", asset_id="v2", start_time=2, duration=4),
            )
        )

        # min(2.0, 0.5*2, 0.5*4) == 1.0
        assert result.manifest.video_entries[1].transition_duration_seconds == pytest.approx(1.0)
        assert any("shortened" in warning for warning in result.warnings)

    def test_dissolve_without_duration_is_a_cut_with_warning(self) -> None:
        result = TimelineEditingAdapter().convert(
            _video_timeline(
                _clip(
                    "c1",
                    track_id="track-video",
                    asset_id="v1",
                    start_time=0,
                    duration=2,
                    transition_out_type="dissolve",
                ),
                _clip("c2", track_id="track-video", asset_id="v2", start_time=2, duration=2),
            )
        )

        assert result.manifest.video_entries[1].transition == "cut"
        assert any("without a duration" in warning for warning in result.warnings)

    def test_outgoing_fade_to_black_maps_to_fade(self) -> None:
        result = TimelineEditingAdapter().convert(
            _video_timeline(
                _clip(
                    "c1",
                    track_id="track-video",
                    asset_id="v1",
                    start_time=0,
                    duration=2,
                    transition_out_type="fade",
                    transition_out_duration=0.4,
                ),
                _clip("c2", track_id="track-video", asset_id="v2", start_time=3, duration=2),
            )
        )

        first, second = result.manifest.video_entries
        assert first.transition == "fade"
        assert first.transition_duration_seconds == pytest.approx(0.4)
        assert second.transition == "cut"

    def test_outgoing_fade_is_superseded_by_incoming_dissolve(self) -> None:
        result = TimelineEditingAdapter().convert(
            _video_timeline(
                _clip(
                    "c1",
                    track_id="track-video",
                    asset_id="v1",
                    start_time=0,
                    duration=3,
                    transition_out_type="fade",
                    transition_out_duration=0.4,
                ),
                _clip(
                    "c2",
                    track_id="track-video",
                    asset_id="v2",
                    start_time=3,
                    duration=3,
                    transition_in_type="dissolve",
                    transition_in_duration=0.6,
                ),
            )
        )

        first, second = result.manifest.video_entries
        assert first.transition == "cut"
        assert second.transition == "dissolve"
        assert second.transition_duration_seconds == pytest.approx(0.6)

    def test_dangling_outgoing_dissolve_warns_and_cuts(self) -> None:
        result = TimelineEditingAdapter().convert(
            _video_timeline(
                _clip(
                    "c1",
                    track_id="track-video",
                    asset_id="v1",
                    start_time=0,
                    duration=2,
                    transition_out_type="dissolve",
                    transition_out_duration=0.5,
                ),
            )
        )

        assert result.manifest.video_entries[0].transition == "cut"
        assert any("no adjacent following clip" in warning for warning in result.warnings)

    def test_wipe_transition_renders_on_incoming_edge(self) -> None:
        result = TimelineEditingAdapter().convert(
            _video_timeline(
                _clip("c1", track_id="track-video", asset_id="v1", start_time=0, duration=2),
                _clip(
                    "c2",
                    track_id="track-video",
                    asset_id="v2",
                    start_time=2,
                    duration=2,
                    transition_in_type="wipe",
                    transition_in_duration=0.5,
                ),
            )
        )

        first, second = result.manifest.video_entries
        assert first.transition == "cut"
        assert second.transition == "wipe"
        assert second.transition_duration_seconds == pytest.approx(0.5)
        assert result.warnings == ()

    def test_slide_transition_on_both_edges_uses_shortest_duration(self) -> None:
        result = TimelineEditingAdapter().convert(
            _video_timeline(
                _clip(
                    "c1",
                    track_id="track-video",
                    asset_id="v1",
                    start_time=0,
                    duration=2,
                    transition_out_type="slide",
                    transition_out_duration=0.4,
                ),
                _clip(
                    "c2",
                    track_id="track-video",
                    asset_id="v2",
                    start_time=2,
                    duration=2,
                    transition_in_type="slide",
                    transition_in_duration=0.8,
                ),
            )
        )

        first, second = result.manifest.video_entries
        assert first.transition == "cut"
        assert second.transition == "slide"
        assert second.transition_duration_seconds == pytest.approx(0.4)
        assert result.warnings == ()

    def test_outgoing_wipe_alone_is_consumed_by_successor(self) -> None:
        result = TimelineEditingAdapter().convert(
            _video_timeline(
                _clip(
                    "c1",
                    track_id="track-video",
                    asset_id="v1",
                    start_time=0,
                    duration=2,
                    transition_out_type="wipe",
                    transition_out_duration=0.6,
                ),
                _clip("c2", track_id="track-video", asset_id="v2", start_time=2, duration=2),
            )
        )

        first, second = result.manifest.video_entries
        assert first.transition == "cut"
        assert second.transition == "wipe"
        assert second.transition_duration_seconds == pytest.approx(0.6)

    def test_mismatched_edges_prefer_incoming_type_and_warn(self) -> None:
        result = TimelineEditingAdapter().convert(
            _video_timeline(
                _clip(
                    "c1",
                    track_id="track-video",
                    asset_id="v1",
                    start_time=0,
                    duration=2,
                    transition_out_type="wipe",
                    transition_out_duration=0.5,
                ),
                _clip(
                    "c2",
                    track_id="track-video",
                    asset_id="v2",
                    start_time=2,
                    duration=2,
                    transition_in_type="slide",
                    transition_in_duration=0.5,
                ),
            )
        )

        assert result.manifest.video_entries[1].transition == "slide"
        assert any("using the incoming slide" in warning for warning in result.warnings)

    def test_wipe_across_a_gap_cuts_with_warning(self) -> None:
        result = TimelineEditingAdapter().convert(
            _video_timeline(
                _clip("c1", track_id="track-video", asset_id="v1", start_time=0, duration=2),
                _clip(
                    "c2",
                    track_id="track-video",
                    asset_id="v2",
                    start_time=3,
                    duration=3,
                    transition_in_type="wipe",
                    transition_in_duration=0.5,
                ),
            )
        )

        assert result.manifest.video_entries[1].transition == "cut"
        assert any("gap" in warning for warning in result.warnings)

    def test_wipe_duration_is_capped_to_half_the_shorter_clip(self) -> None:
        result = TimelineEditingAdapter().convert(
            _video_timeline(
                _clip("c1", track_id="track-video", asset_id="v1", start_time=0, duration=2),
                _clip(
                    "c2",
                    track_id="track-video",
                    asset_id="v2",
                    start_time=2,
                    duration=4,
                    transition_in_type="slide",
                    transition_in_duration=2.0,
                ),
            )
        )

        # min(2.0, 0.5*2, 0.5*4) == 1.0
        entry = result.manifest.video_entries[1]
        assert entry.transition == "slide"
        assert entry.transition_duration_seconds == pytest.approx(1.0)
        assert any("shortened" in warning for warning in result.warnings)

    def test_dangling_outgoing_slide_warns_and_cuts(self) -> None:
        result = TimelineEditingAdapter().convert(
            _video_timeline(
                _clip(
                    "c1",
                    track_id="track-video",
                    asset_id="v1",
                    start_time=0,
                    duration=2,
                    transition_out_type="slide",
                    transition_out_duration=0.5,
                ),
            )
        )

        assert result.manifest.video_entries[0].transition == "cut"
        assert any("no adjacent following clip" in warning for warning in result.warnings)

    def test_wipe_without_duration_is_a_cut_with_warning(self) -> None:
        result = TimelineEditingAdapter().convert(
            _video_timeline(
                _clip("c1", track_id="track-video", asset_id="v1", start_time=0, duration=2),
                _clip(
                    "c2",
                    track_id="track-video",
                    asset_id="v2",
                    start_time=2,
                    duration=2,
                    transition_in_type="wipe",
                ),
            )
        )

        assert result.manifest.video_entries[1].transition == "cut"
        assert any("without a duration" in warning for warning in result.warnings)


class TestSubtitleEntries:
    @staticmethod
    def _video_track() -> TimelineTrackV1:
        return _track(
            "video",
            (_clip("c-v", track_id="track-video", asset_id="v1", start_time=0, duration=4),),
        )

    def test_subtitle_clips_become_ordered_cues_with_style(self) -> None:
        style = TimelineSubtitleStyleV1(font_size=40, position="top", primary_color="#ff0000")
        later = _clip(
            "c-s2",
            track_id="track-subtitle",
            asset_id=None,
            start_time=2.0,
            duration=1.5,
            subtitle_text=" Second line ",
        )
        earlier = _clip(
            "c-s1",
            track_id="track-subtitle",
            asset_id=None,
            start_time=0.5,
            duration=1.0,
            subtitle_text="First line",
            subtitle_style=style,
        )
        result = TimelineEditingAdapter().convert(
            _timeline(
                self._video_track(),
                _track("subtitle", (later, earlier)),
                duration_seconds=4.0,
            )
        )

        cues = result.manifest.subtitle_entries
        assert [cue.text for cue in cues] == ["First line", "Second line"]
        first, second = cues
        assert first.start_seconds == 0.5
        assert first.end_seconds == pytest.approx(1.5)
        assert first.style == style
        assert second.start_seconds == 2.0
        assert second.end_seconds == pytest.approx(3.5)
        assert second.style is None
        assert result.subtitle_clip_count == 2
        assert result.manifest.subtitle_burn_in is True

    def test_muted_subtitle_track_skips_all_clips_with_warning(self) -> None:
        clip = _clip(
            "c-s1",
            track_id="track-subtitle",
            asset_id=None,
            start_time=0.0,
            duration=1.0,
            subtitle_text="Hidden",
        )
        result = TimelineEditingAdapter().convert(
            _timeline(
                self._video_track(),
                _track("subtitle", (clip,), muted=True),
            )
        )

        assert result.manifest.subtitle_entries == ()
        assert result.subtitle_clip_count == 0
        assert any("muted" in warning for warning in result.warnings)

    def test_blank_text_clips_are_skipped_with_warning(self) -> None:
        blank = _clip(
            "c-blank",
            track_id="track-subtitle",
            asset_id=None,
            start_time=0.0,
            duration=1.0,
            subtitle_text="   ",
        )
        voiced = _clip(
            "c-ok",
            track_id="track-subtitle",
            asset_id=None,
            start_time=1.0,
            duration=1.0,
            subtitle_text="Kept",
        )
        result = TimelineEditingAdapter().convert(
            _timeline(
                self._video_track(),
                _track("subtitle", (blank, voiced)),
            )
        )

        assert [cue.text for cue in result.manifest.subtitle_entries] == ["Kept"]
        assert any("c-blank" in warning and "no text" in warning for warning in result.warnings)

    def test_burn_in_flag_false_is_passed_through(self) -> None:
        clip = _clip(
            "c-s1",
            track_id="track-subtitle",
            asset_id=None,
            start_time=0.0,
            duration=1.0,
            subtitle_text="Not burned",
        )
        result = TimelineEditingAdapter().convert(
            _timeline(
                self._video_track(),
                _track("subtitle", (clip,)),
                subtitle_burn_in=False,
            )
        )

        assert result.manifest.subtitle_burn_in is False
        assert len(result.manifest.subtitle_entries) == 1

    def test_no_subtitle_track_keeps_empty_defaults(self) -> None:
        result = TimelineEditingAdapter().convert(_timeline(self._video_track()))

        assert result.manifest.subtitle_entries == ()
        assert result.manifest.subtitle_burn_in is True
        assert result.subtitle_clip_count == 0
