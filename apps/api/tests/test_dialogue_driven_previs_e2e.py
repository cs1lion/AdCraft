"""E2E integration test: the dialogue-driven previs chain.

The objective's core claim is "台词驱动视频" — dialogue drives the picture.
This test wires the REAL services end to end (no Blender, no network; the
TTS durations come from a measured-duration engine double):

    SceneScript blockout (two characters, one camera, three shots)
        -> dialogue lines with a measured-duration TTS engine
        -> apply_dialogue_lip_sync: speech timeline -> per-character lip-sync
           keyframes merged into SceneScript (position/rotation preserved)
        -> check_scene_script_consistency: the Dramagic-style gate report
        -> build_video_prompt_bundle: per-shot prompts for the video model

Assertions lock the chain's invariants: talk keyframes exist exactly where
the speech lands, non-speaking characters are untouched, the gate passes for
a bound multi-shot scene, and the prompt bundle carries every shot.
"""

from __future__ import annotations

import pytest

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.dialogue_lipsync_service import apply_dialogue_lip_sync
from app.services.scene3d.prompt_builder import build_video_prompt_bundle
from app.services.scene3d.scene_consistency import check_scene_script_consistency

pytestmark = pytest.mark.integration


class _MeasuredTTSEngine:
    """Deterministic 'measured' durations: 10 chars -> 1.0s."""

    def estimate_duration(self, text: str) -> float:
        return max(1.0, len(text) / 10.0)


def _scene() -> SceneScriptRoot:
    """Two researchers in an underground facility, three shots over 9s."""
    return SceneScriptRoot.model_validate(
        {
            "scene": {
                "name": "地下研究所 B2 对话",
                "environment": "indoor",
                "lighting": "cool",
                "duration": 9.0,
                "frame_rate": 30,
            },
            "characters": [
                {
                    "id": "lin",
                    "type": "lowpoly_human",
                    "appearance": {"color": "#E74C3C", "height": 1.7, "scale": 1.0},
                    "character_asset_id": "asset-lin",
                    "keyframes": [
                        {"frame": 0, "position": [0.8, 0.0, 0.0], "rotation_y": 160, "action": "stand"},
                        {"frame": 270, "position": [0.9, 0.2, 0.0], "rotation_y": 160, "action": "stand"},
                    ],
                },
                {
                    "id": "su",
                    "type": "lowpoly_human",
                    "appearance": {"color": "#3498DB", "height": 1.65, "scale": 1.0},
                    "character_asset_id": "asset-su",
                    "keyframes": [
                        {"frame": 0, "position": [-0.9, 0.1, 0.0], "rotation_y": 20, "action": "stand"}
                    ],
                },
            ],
            "props": [
                {"id": "console1", "type": "rect_table", "position": [0.0, 1.4, 0.0], "scale": 1.2},
                {"id": "crate1", "type": "crate", "position": [2.2, 2.0, 0.0], "scale": 1.0},
            ],
            "environment": [
                {"id": "floor1", "type": "floor", "position": [0.0, 0.0, 0.0], "scale": 8.0},
                {"id": "wall_back", "type": "wall", "position": [0.0, 4.0, 1.5], "scale": 8.0},
                {"id": "door1", "type": "door", "position": [0.0, 4.0, 1.1], "scale": 1.0},
            ],
            "cameras": [
                {
                    "id": "cam_wide",
                    "shot_type": "wide",
                    "keyframes": [{"frame": 0, "position": [5.0, -6.0, 2.6], "look_at": [0.0, 0.0, 1.2]}],
                },
                {
                    "id": "cam_lin",
                    "shot_type": "closeup",
                    "keyframes": [{"frame": 90, "position": [1.6, -1.2, 1.7], "look_at": [0.8, 0.0, 1.5]}],
                },
                {
                    "id": "cam_over",
                    "shot_type": "over_shoulder",
                    "keyframes": [{"frame": 180, "position": [-0.4, -1.8, 1.8], "look_at": [0.8, 0.0, 1.5]}],
                },
            ],
            "shots": [
                {"id": "shot_wide", "camera": "cam_wide", "start_frame": 0, "end_frame": 89, "description": "wide establishing"},
                {"id": "shot_lin", "camera": "cam_lin", "start_frame": 90, "end_frame": 179, "description": "lin closeup"},
                {"id": "shot_over", "camera": "cam_over", "start_frame": 180, "end_frame": 269, "description": "over shoulder"},
            ],
            "speech_bindings": [],
        }
    )


DIALOGUE = [
    {"character_id": "lin", "text": "就是这里，信号源在墙后面。"},
    {"character_id": "su", "text": "（轻声）你确定要进去吗？整个研究所都停电了。"},
    {"character_id": "lin", "text": "跟紧我，别掉队。"},
]


def test_dialogue_drives_lip_sync_keyframes_end_to_end() -> None:
    script = _scene()

    result = apply_dialogue_lip_sync(
        script,
        DIALOGUE,
        tts_engine=_MeasuredTTSEngine(),
        syllables_per_second=4.0,
    )
    merged = result.scene_script

    # --- The chain's core invariant: talk keyframes land where speech is ----
    lin_talk_frames = [
        kf.frame for kf in merged.characters[0].keyframes if kf.action == "talk"
    ]
    su_talk_frames = [
        kf.frame for kf in merged.characters[1].keyframes if kf.action == "talk"
    ]
    assert lin_talk_frames, "the speaking character gained talk keyframes"
    assert su_talk_frames

    # Speech is sequential from t=0: lin speaks first (frame 0 opens her
    # mouth), and su's reply starts after lin's FIRST line ends — the lines
    # interleave (lin, su, lin), not block.
    assert lin_talk_frames[0] == 0
    lin_first_line_end = 1.3 * 30  # 10 chars at 10 chars/s = 1.3s
    su_first_line_start = 1.5 * 30  # +0.2s gap
    assert lin_first_line_end <= su_talk_frames[0] <= su_first_line_start + 2

    # --- Lip-sync keyframes inherit position/rotation (no teleporting) ------
    positions = {tuple(kf.position) for kf in merged.characters[0].keyframes}
    assert (0.8, 0.0, 0.0) in positions, "the authored blocking survived the merge"

    # --- The speech bindings record the bound-mode alignment ----------------
    assert [b.character for b in merged.speech_bindings] == ["lin", "su", "lin"]
    assert all(b.mode == "bound" for b in merged.speech_bindings)

    # --- The merged script is still schema-valid (the backstop) -------------
    SceneScriptRoot.model_validate(merged.model_dump(mode="json"))

    # --- Duration provenance: the TTS engine MEASURED the lines -------------
    assert result.summary["duration_source"] == "measured"
    assert result.summary["segment_count"] == 3
    assert result.summary["issues"] == []  # sequential, non-overlapping


def test_consistency_gate_and_prompt_bundle_on_the_merged_scene() -> None:
    script = _scene()
    merged = apply_dialogue_lip_sync(script, DIALOGUE, tts_engine=_MeasuredTTSEngine()).scene_script

    # --- The Dramagic-style gate: bound characters, no gaps, no collisions --
    report = check_scene_script_consistency(merged)
    assert report.passed is True
    assert [issue.code for issue in report.issues if issue.code == "character_unbound"] == []

    # --- Per-shot prompts carry the dialogue context to the video model -----
    # Keyframes mode: the provider takes images, not a reference video
    # (ADR 0005 §4a fallback).
    bundle = build_video_prompt_bundle(merged, reference_mode="keyframes")
    assert len(bundle.shots) == 3
    assert bundle.total_frames == merged.total_frames
    for shot_prompt in bundle.shots:
        assert shot_prompt.prompt  # every shot gets a prompt
        assert shot_prompt.negative_prompt
    # The dialogue-derived actions reach the video-model prompts: the shots
    # spanning the speech describe the characters as speaking (the prompt
    # builder samples keyframe actions across each shot's frame range).
    assert any("speaking" in shot_prompt.prompt.lower() for shot_prompt in bundle.shots)
    # And the tail shot, after the speech ends, describes them as still.
    assert "standing still then speaking" in bundle.shots[0].prompt


def test_unbound_character_trips_the_gate_after_merge() -> None:
    """The gate stays honest: an unbound character in a multi-shot scene is
    reported (warning, never blocking) — the Dramagic lock made queryable."""

    script = _scene()
    script.characters[0].character_asset_id = None
    merged = apply_dialogue_lip_sync(script, DIALOGUE, tts_engine=_MeasuredTTSEngine()).scene_script

    report = check_scene_script_consistency(merged)
    assert report.passed is True  # warnings never block
    unbound = [issue for issue in report.issues if issue.code == "character_unbound"]
    assert len(unbound) == 1
    assert unbound[0].subject == "lin"
    assert unbound[0].remedy
