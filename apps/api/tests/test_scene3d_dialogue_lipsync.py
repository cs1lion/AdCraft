"""Unit tests for the dialogue-driven lip-sync wiring service.

Covers the chain dialogue -> speech timeline -> lip-sync keyframes ->
re-validated SceneScript: measured vs estimated duration provenance, merge
semantics (position/rotation inheritance, action-only updates), advisory
issues (overlap/out-of-scene), unknown speakers, and fail-closed validation.
"""

from __future__ import annotations

import math

import pytest

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.dialogue_lipsync_service import (
    DialogueLipSyncError,
    apply_dialogue_lip_sync,
)


def scene_script(duration: float = 8.0) -> SceneScriptRoot:
    return SceneScriptRoot.model_validate(
        {
            "scene": {
                "name": "地下研究所 B2",
                "environment": "indoor",
                "lighting": "cool",
                "duration": duration,
                "frame_rate": 30,
            },
            "characters": [
                {
                    "id": "char_a",
                    "type": "lowpoly_human",
                    "appearance": {"color": "#E74C3C", "height": 1.7, "scale": 1.0},
                    "keyframes": [
                        {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"},
                        {"frame": 240, "position": [2, 2, 0], "rotation_y": 90, "action": "stand"},
                    ],
                },
                {
                    "id": "char_b",
                    "type": "lowpoly_human",
                    "appearance": {"color": "#3498DB", "height": 1.7, "scale": 1.0},
                    "keyframes": [
                        {"frame": 0, "position": [-1, 1, 0], "rotation_y": 180, "action": "stand"},
                    ],
                },
            ],
            "props": [],
            "environment": [],
            "cameras": [
                {
                    "id": "cam1",
                    "shot_type": "wide",
                    "keyframes": [{"frame": 0, "position": [8, -10, 5], "look_at": [0, 0, 1]}],
                }
            ],
            "shots": [
                {"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 239, "description": "wide"}
            ],
            "speech_bindings": [],
        }
    )


DIALOGUE = [
    {"character_id": "char_a", "text": "就是这里，信号源在墙后面。"},
    {"character_id": "char_a", "text": "（轻声）你确定要进去吗？", "start_time": 3.5},
    {"character_id": "char_b", "text": "跟紧我。", "start_time": 5.0},
]


def test_merges_lip_sync_keyframes_for_speaking_characters() -> None:
    result = apply_dialogue_lip_sync(scene_script(), DIALOGUE)
    script = result.scene_script

    talk_frames_a = [
        keyframe for keyframe in script.characters[0].keyframes if keyframe.action == "talk"
    ]
    talk_frames_b = [
        keyframe for keyframe in script.characters[1].keyframes if keyframe.action == "talk"
    ]
    assert talk_frames_a, "the speaking character gained talk keyframes"
    assert talk_frames_b, "the second speaker gained talk keyframes"
    # Keyframes stay sorted and within the scene's total frames.
    frames = [keyframe.frame for keyframe in script.characters[0].keyframes]
    assert frames == sorted(frames)
    assert all(frame <= script.total_frames for frame in frames)


def test_lip_sync_keyframes_inherit_position_and_rotation() -> None:
    result = apply_dialogue_lip_sync(scene_script(), DIALOGUE)
    character = result.scene_script.characters[0]

    # The original two keyframes survive as-is (positions preserved).
    by_frame = {keyframe.frame: keyframe for keyframe in character.keyframes}
    assert by_frame[0].position == [0, 0, 0]
    assert by_frame[240].position == [2, 2, 0]

    # Every inserted talk keyframe inherits the pose the character ALREADY HAS
    # at that frame — the INTERPOLATED pose on the authored 0→240 path, not a
    # raw endpoint copy (V0.2 §14.13: an audio redo must not quantize the
    # visual layer). A frame at t therefore sits at 2*t/240 metres in x, never
    # the origin default and never a teleport.
    talk_keyframes = [
        keyframe for keyframe in character.keyframes if keyframe.action == "talk"
    ]
    assert talk_keyframes, "the merge inserted no talk frames"
    for keyframe in talk_keyframes:
        expected_x = 2.0 * keyframe.frame / 240.0
        assert keyframe.position[0] == pytest.approx(expected_x, abs=1e-6), (
            f"frame {keyframe.frame} sits off the authored path: "
            f"x={keyframe.position[0]} expected {expected_x}"
        )
        expected_y = 2.0 * keyframe.frame / 240.0
        assert keyframe.position[1] == pytest.approx(expected_y, abs=1e-6)


def test_summary_reports_provenance_and_bindings() -> None:
    result = apply_dialogue_lip_sync(scene_script(), DIALOGUE)
    summary = result.summary

    assert summary["dialogue_line_count"] == 3
    assert summary["segment_count"] == 3
    assert summary["characters_with_speech"] == ["char_a", "char_b"]
    # No real TTS configured in this test: estimated durations, and the
    # summary SAYS so (never silent).
    assert summary["duration_source"] == "estimated"
    assert summary["total_speech_seconds"] > 0
    assert summary["speech_exceeds_scene"] is False

    bindings = result.scene_script.speech_bindings
    assert [binding.character for binding in bindings] == ["char_a", "char_a", "char_b"]
    assert all(binding.mode == "bound" for binding in bindings)


def test_measured_duration_source_with_real_engine() -> None:
    class _FakeEngine:
        def synthesize(self, text, character_id, output_path, emotion=None, voice_id=None):
            return output_path

        def estimate_duration(self, text: str) -> float:
            return 1.25

    result = apply_dialogue_lip_sync(scene_script(), DIALOGUE, tts_engine=_FakeEngine())
    assert result.summary["duration_source"] == "measured"


def test_unknown_speakers_fail_closed_with_actionable_message() -> None:
    dialogue = [{"character_id": "ghost", "text": "有人吗？"}]
    with pytest.raises(DialogueLipSyncError) as exc:
        apply_dialogue_lip_sync(scene_script(), dialogue)
    assert exc.value.code == "dialogue_unknown_speaker"
    # The error names both the unknown id and the valid ones: actionable, not silent.
    assert "ghost" in str(exc.value)
    assert "char_a" in str(exc.value)


def test_overlapping_dialogue_is_reported_as_an_issue() -> None:
    dialogue = [
        {"character_id": "char_a", "text": "第一句台词"},
        {"character_id": "char_b", "text": "第二句台词", "start_time": 0.1},
    ]
    result = apply_dialogue_lip_sync(scene_script(), dialogue)
    issue_types = {issue["issue_type"] for issue in result.summary["issues"]}
    assert "overlap_cross_talk" in issue_types


def test_speech_beyond_scene_is_flagged() -> None:
    dialogue = [{"character_id": "char_a", "text": "长台词" * 40, "start_time": 7.9}]
    result = apply_dialogue_lip_sync(scene_script(duration=8.0), dialogue)
    assert result.summary["speech_exceeds_scene"] is True
    assert any(issue["issue_type"] == "out_of_bounds" for issue in result.summary["issues"])


def test_empty_dialogue_fails_closed() -> None:
    with pytest.raises(DialogueLipSyncError) as exc:
        apply_dialogue_lip_sync(scene_script(), [])
    assert exc.value.code == "dialogue_required"


def test_missing_text_fails_closed() -> None:
    with pytest.raises(DialogueLipSyncError) as exc:
        apply_dialogue_lip_sync(scene_script(), [{"character_id": "char_a", "text": "  "}])
    assert exc.value.code == "dialogue_text_required"


def test_negative_start_time_fails_closed() -> None:
    with pytest.raises(DialogueLipSyncError) as exc:
        apply_dialogue_lip_sync(
            scene_script(), [{"character_id": "char_a", "text": "hi", "start_time": -1}]
        )
    assert exc.value.code == "dialogue_start_time_invalid"


def test_invalid_scene_script_fails_closed() -> None:
    with pytest.raises(DialogueLipSyncError) as exc:
        apply_dialogue_lip_sync({"scene": {"name": "broken"}}, DIALOGUE)
    assert exc.value.code == "scene_script_invalid"


def test_scene_script_dict_input_is_accepted() -> None:
    result = apply_dialogue_lip_sync(scene_script().model_dump(mode="json"), DIALOGUE)
    assert result.summary["segment_count"] == 3


def test_merge_is_deterministic_and_non_mutating() -> None:
    base = scene_script()
    snapshot = base.model_dump(mode="json")
    first = apply_dialogue_lip_sync(base, DIALOGUE)
    second = apply_dialogue_lip_sync(base, DIALOGUE)
    assert first.scene_script.model_dump(mode="json") == second.scene_script.model_dump(mode="json")
    assert base.model_dump(mode="json") == snapshot


def test_custom_syllable_density_changes_keyframe_count() -> None:
    sparse = apply_dialogue_lip_sync(scene_script(), DIALOGUE, syllables_per_second=1.0)
    dense = apply_dialogue_lip_sync(scene_script(), DIALOGUE, syllables_per_second=10.0)
    sparse_frames = [
        keyframe.frame for keyframe in sparse.scene_script.characters[0].keyframes
    ]
    dense_frames = [
        keyframe.frame for keyframe in dense.scene_script.characters[0].keyframes
    ]
    assert len(dense_frames) > len(sparse_frames)


def test_summary_carries_segment_timings_for_subtitle_publish() -> None:
    """Subtitle cues must ride the SAME boundaries the lip-sync used.

    Without segments in the summary, a client would re-estimate durations and
    the captions would drift from the mouths."""

    result = apply_dialogue_lip_sync(scene_script(), DIALOGUE)
    segments = result.summary["segments"]

    assert len(segments) == 3
    assert [(s["character_id"], s["text"]) for s in segments] == [
        ("char_a", DIALOGUE[0]["text"]),
        ("char_a", DIALOGUE[1]["text"]),
        ("char_b", DIALOGUE[2]["text"]),
    ]
    for segment in segments:
        assert segment["start_time"] < segment["end_time"]
        assert segment["end_time"] <= result.summary["scene_total_seconds"]
    # Ordered and non-overlapping: safe to publish as subtitle cues in order.
    starts = [s["start_time"] for s in segments]
    assert starts == sorted(starts)


def test_summary_segments_use_aligned_times_when_pretimed() -> None:
    """C mode: forced-aligned lines keep their measured start in the summary
    (the lip-sync timeline must not re-time them)."""

    pretimed = [
        {"character_id": "char_a", "text": "第一句。", "start_time": 1.0, "end_time": 2.4},
        {"character_id": "char_b", "text": "第二句。", "start_time": 3.0, "end_time": 4.2},
    ]
    result = apply_dialogue_lip_sync(scene_script(), pretimed)
    summary = result.summary

    assert summary["duration_source"] == "aligned"
    assert [(s["start_time"], s["end_time"]) for s in summary["segments"]] == [
        (1.0, 2.4),
        (3.0, 4.2),
    ]


def test_summary_carries_shot_advisories_from_the_speech_timeline() -> None:
    """"说多久 → 分镜多长": the lip-sync summary notices where the cuts and
    the dialogue disagree (advisory only — the author keeps the chair)."""

    # A cut at 2s lands inside the first line: the advisory fires.
    script = scene_script()
    script.shots[0].end_frame = 59
    script.shots.append(
        script.shots[0].model_copy(update={"id": "shot2", "start_frame": 60, "end_frame": 179})
    )
    result = apply_dialogue_lip_sync(script, DIALOGUE)
    advisories = result.summary["shot_advisories"]

    assert isinstance(advisories, list) and advisories
    for advisory in advisories:
        assert advisory["code"]
        assert advisory["message"]
        assert advisory["remedy"]  # every finding carries its fix
        assert advisory["severity"] == "warning"
    codes = [advisory["code"] for advisory in advisories]
    assert "line_crosses_cut" in codes


# ---------------------------------------------------------------------------
# §14.13 锁 Visual 重做 Audio：音频重做不许把 authored 运动踩碎
# ---------------------------------------------------------------------------


def test_reapplying_lip_sync_does_not_quantize_a_walk() -> None:
    """A character authored to walk 0→6m across frames 0–90 (the renderer
    interpolates linearly). Applying lip-sync inserts talk frames INSIDE that
    window; if they inherit the at-or-before keyframe's raw position, the walk
    becomes hold-at-origin-then-jump — an audio redo silently degrading the
    visual layer (V0.2 §14.13). The inserted frames must sit ON the path."""

    script = SceneScriptRoot.model_validate(
        {
            "scene": {
                "name": "走廊",
                "environment": "indoor",
                "lighting": "cool",
                "duration": 3.0,
                "frame_rate": 30,
            },
            "characters": [
                {
                    "id": "lin",
                    "type": "lowpoly_human",
                    "appearance": {"color": "#E74C3C", "height": 1.7, "scale": 1.0},
                    # The walk: 0 → 6m across frames 0..90, facing +X.
                    "keyframes": [
                        {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "walk"},
                        {"frame": 90, "position": [6, 0, 0], "rotation_y": 90, "action": "stand"},
                    ],
                }
            ],
            "props": [],
            "environment": [],
            "cameras": [
                {
                    "id": "cam1",
                    "shot_type": "wide",
                    "keyframes": [{"frame": 0, "position": [3, -4, 2], "look_at": [0, 0, 1]}],
                }
            ],
            "shots": [{"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 89}],
            "speech_bindings": [],
        }
    )
    # A line that starts a second in and runs past the halfway point.
    dialogue = [
        {"character_id": "lin", "text": "就是这里，信号源在墙后面。", "start_time": 1.0},
    ]

    result = apply_dialogue_lip_sync(script, dialogue)
    character = result.scene_script.characters[0]
    keyframes = sorted(character.keyframes, key=lambda keyframe: keyframe.frame)

    # The authored endpoints survive untouched.
    by_frame = {keyframe.frame: keyframe for keyframe in keyframes}
    assert by_frame[0].position == [0, 0, 0]
    assert by_frame[90].position == [6, 0, 0]

    # Every inserted frame in the MIDDLE of the walk lies on the authored
    # path (linear interpolation), not held at either endpoint.
    middle = [
        keyframe for keyframe in keyframes if 0 < keyframe.frame < 90
    ]
    assert middle, "the merge inserted no frames inside the walk"
    for keyframe in middle:
        expected_x = 6.0 * keyframe.frame / 90.0
        assert keyframe.position[0] == pytest.approx(expected_x, abs=1e-6), (
            f"frame {keyframe.frame} sits off the walk path: "
            f"x={keyframe.position[0]} expected {expected_x}"
        )


def test_reapplying_lip_sync_does_not_snap_a_turn() -> None:
    """The same lock for rotation: a character turning from 0° to 90° across
    the window must keep turning through the inserted frames, not snap."""

    script = SceneScriptRoot.model_validate(
        {
            "scene": {
                "name": "走廊",
                "environment": "indoor",
                "lighting": "cool",
                "duration": 3.0,
                "frame_rate": 30,
            },
            "characters": [
                {
                    "id": "lin",
                    "type": "lowpoly_human",
                    "appearance": {"color": "#E74C3C", "height": 1.7, "scale": 1.0},
                    "keyframes": [
                        {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "walk"},
                        {"frame": 60, "position": [2, 0, 0], "rotation_y": 90, "action": "stand"},
                    ],
                }
            ],
            "props": [],
            "environment": [],
            "cameras": [
                {
                    "id": "cam1",
                    "shot_type": "wide",
                    "keyframes": [{"frame": 0, "position": [3, -4, 2], "look_at": [0, 0, 1]}],
                }
            ],
            "shots": [{"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 59}],
            "speech_bindings": [],
        }
    )
    result = apply_dialogue_lip_sync(
        script, [{"character_id": "lin", "text": "就是这里。", "start_time": 0.5}]
    )
    keyframes = sorted(result.scene_script.characters[0].keyframes, key=lambda k: k.frame)
    middle = [keyframe for keyframe in keyframes if 0 < keyframe.frame < 60]
    assert middle
    for keyframe in middle:
        expected_yaw = 90.0 * keyframe.frame / 60.0
        assert keyframe.rotation_y == pytest.approx(expected_yaw, abs=1e-6)


def test_interpolated_yaw_holds_inside_the_schema_blind_zone() -> None:
    """The interpolation is guard-aware: an interpolated yaw that lands in the
    schema's radian blind zone (0 < |yaw| <= 2*pi — refused because a tiny
    degree value is indistinguishable from a radian one) falls back to the
    at-or-before keyframe's yaw. Positions still interpolate exactly, and the
    whole merged script re-validates (the service asserts it)."""

    script = SceneScriptRoot.model_validate(
        {
            "scene": {
                "name": "走廊",
                "environment": "indoor",
                "lighting": "cool",
                "duration": 3.0,
                "frame_rate": 30,
            },
            "characters": [
                {
                    "id": "lin",
                    "type": "lowpoly_human",
                    "appearance": {"color": "#E74C3C", "height": 1.7, "scale": 1.0},
                    # A 90-degree turn across frames 0..90; the interpolated yaw
                    # only enters the blind zone for frames < ~6.
                    "keyframes": [
                        {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "walk"},
                        {"frame": 90, "position": [3, 0, 0], "rotation_y": 90, "action": "stand"},
                    ],
                }
            ],
            "props": [],
            "environment": [],
            "cameras": [
                {
                    "id": "cam1",
                    "shot_type": "wide",
                    "keyframes": [{"frame": 0, "position": [3, -4, 2], "look_at": [0, 0, 1]}],
                }
            ],
            "shots": [{"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 89}],
            "speech_bindings": [],
        }
    )
    # A line that starts at frame 3 (0.1s): its first inserted frame would
    # interpolate to yaw 3 degrees — inside the blind zone.
    result = apply_dialogue_lip_sync(
        script, [{"character_id": "lin", "text": "就是这里。", "start_time": 0.1}]
    )
    keyframes = sorted(result.scene_script.characters[0].keyframes, key=lambda k: k.frame)
    by_frame = {keyframe.frame: keyframe for keyframe in keyframes}

    # Inside the blind zone: the authored yaw is held (frame 3 -> yaw 0).
    blind = [f for f in by_frame if 0 < f < 90 and (90.0 * f / 90.0) <= 2 * math.pi]
    assert blind, "no inserted frame landed in the blind zone"
    for frame in blind:
        assert by_frame[frame].rotation_y == 0
    # Past the blind zone: the turn interpolates exactly.
    for frame, keyframe in by_frame.items():
        if 0 < frame < 90 and (90.0 * frame / 90.0) > 2 * math.pi:
            assert keyframe.rotation_y == pytest.approx(frame, abs=1e-6)
        # Positions interpolate exactly everywhere.
        if 0 < frame < 90:
            assert keyframe.position[0] == pytest.approx(3.0 * frame / 90.0, abs=1e-6)


def test_applied_lip_sync_moves_the_mouth_with_the_words() -> None:
    """The end-to-end upgrade (V0.2 §14.9): with word timings the mouth opens
    and closes per WORD through the real service, not on a metronome."""

    script = {
        "scene": {
            "name": "走廊",
            "environment": "indoor",
            "lighting": "cool",
            "duration": 4.0,
            "frame_rate": 30,
        },
        "characters": [
            {
                "id": "lin",
                "type": "lowpoly_human",
                "appearance": {"color": "#E74C3C", "height": 1.7, "scale": 1.0},
                "keyframes": [
                    {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"}
                ],
            }
        ],
        "props": [],
        "environment": [],
        "cameras": [
            {
                "id": "cam1",
                "shot_type": "wide",
                "keyframes": [{"frame": 0, "position": [3, -4, 2], "look_at": [0, 0, 1]}],
            }
        ],
        "shots": [{"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 119}],
        "speech_bindings": [],
    }
    result = apply_dialogue_lip_sync(
        script,
        [
            {
                "character_id": "lin",
                "text": "别出声",
                "start_time": 1.0,
                "end_time": 2.8,
                "word_timings": [
                    {"text": "别", "start": 1.0, "end": 1.5},
                    {"text": "出声", "start": 1.6, "end": 2.3},
                ],
            }
        ],
    )
    keyframes = sorted(result.scene_script.characters[0].keyframes, key=lambda k: k.frame)
    talk_frames = [keyframe.frame for keyframe in keyframes if keyframe.action == "talk"]

    # 1.0s -> frame 30 (the line's own start) plus each word's start (1.6s ->
    # 48). The metronome would have filled the window with alternating keys.
    assert 30 in talk_frames
    assert 48 in talk_frames
    # The word's END closes the mouth: a stand frame at 2.3s (frame 69) and
    # at 1.5s (frame 45).
    stand_frames = [keyframe.frame for keyframe in keyframes if keyframe.action == "stand"]
    assert 45 in stand_frames
    assert 69 in stand_frames


def test_applied_lip_sync_without_word_timings_keeps_the_metronome() -> None:
    """The upgrade is strictly additive: no word timings, no behaviour change."""

    script = {
        "scene": {
            "name": "走廊",
            "environment": "indoor",
            "lighting": "cool",
            "duration": 4.0,
            "frame_rate": 30,
        },
        "characters": [
            {
                "id": "lin",
                "type": "lowpoly_human",
                "appearance": {"color": "#E74C3C", "height": 1.7, "scale": 1.0},
                "keyframes": [
                    {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"}
                ],
            }
        ],
        "props": [],
        "environment": [],
        "cameras": [
            {
                "id": "cam1",
                "shot_type": "wide",
                "keyframes": [{"frame": 0, "position": [3, -4, 2], "look_at": [0, 0, 1]}],
            }
        ],
        "shots": [{"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 119}],
        "speech_bindings": [],
    }
    result = apply_dialogue_lip_sync(
        script,
        [{"character_id": "lin", "text": "别出声", "start_time": 1.0, "end_time": 2.8}],
    )
    talk_frames = [
        keyframe.frame
        for keyframe in result.scene_script.characters[0].keyframes
        if keyframe.action == "talk"
    ]
    # The syllable metronome still fills the window: more talk frames than the
    # word-level path would produce (line start + 2 word starts = 3).
    assert len(talk_frames) > 3
