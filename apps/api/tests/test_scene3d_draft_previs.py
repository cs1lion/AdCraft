"""The draft previs pass: keyframes only, and the clip still tells the truth.

Rendering every frame of a 6-shot animation costs ~19 minutes; rendering each
shot's 5 keyframes costs ~20 seconds and produces the same images at the same
instants.  That trade is only safe if the draft is *consumable* by the same
downstream code as a full render, so three properties are pinned here:

1. The generated Blender script renders stills at the keyframes only, with the
   same ``frame_<n>.png`` names a full pass emits, so ``extract_keyframes`` and
   ``encode_png_sequence`` read a draft without knowing it is one.
2. ``RenderResult.rendered_frames`` reports which pass ran, and the node
   metadata carries it -- a consumer that measures the clip against the scene
   duration must be able to tell "slideshow of keyframes" from "animation".
3. The encoded draft is roughly as long as the real animation rather than
   flashing past in under a second.
"""

from __future__ import annotations

import re

import pytest

from app.core.config import Settings
from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.blender_converter import (
    keyframe_render_frames,
    scene_script_to_blender,
)
from app.services.scene3d.blender_renderer import RenderResult
from app.services.scene3d.encoder import _frame_durations
from app.services.scene3d.keyframes import _shot_keyframe_frames



VALID_SCENE_SCRIPT = {
    "scene": {
        "name": "draft-test",
        "environment": "indoor",
        "lighting": "warm",
        "duration": 8.0,
        "frame_rate": 30,
    },
    "characters": [
        {
            "id": "char1",
            "type": "lowpoly_human",
            "appearance": {"color": "#8B4513", "height": 1.7, "scale": 1.0},
            "keyframes": [
                {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"},
                {"frame": 239, "position": [1, 0, 0], "rotation_y": 90, "action": "walk"},
            ],
        }
    ],
    "props": [],
    "environment": [
        {"id": "wall1", "type": "wall", "position": [0, -5, 0], "scale": 1.0, "rotation_y": 0.0}
    ],
    "cameras": [
        {
            "id": "cam1",
            "shot_type": "wide",
            "keyframes": [
                {"frame": 0, "position": [10, -10, 5], "look_at": [0, 0, 1]},
                {"frame": 239, "position": [8, -8, 4], "look_at": [0, 0, 1]},
            ],
        }
    ],
    "shots": [
        {"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 60, "description": "a"},
        {"id": "shot2", "camera": "cam1", "start_frame": 60, "end_frame": 120, "description": "b"},
        {"id": "shot3", "camera": "cam1", "start_frame": 120, "end_frame": 180, "description": "c"},
        {"id": "shot4", "camera": "cam1", "start_frame": 180, "end_frame": 240, "description": "d"},
    ],
    "speech_bindings": [],
}


@pytest.fixture
def scene_script() -> SceneScriptRoot:
    return SceneScriptRoot.model_validate(VALID_SCENE_SCRIPT)


# ---------------------------------------------------------------------------
# 1. The generated script renders keyframe stills, not the animation
# ---------------------------------------------------------------------------


class TestDraftScript:
    def test_draft_omits_the_animation_pass(self, scene_script: SceneScriptRoot) -> None:
        script = scene_script_to_blender(
            scene_script, r"C:\tmp\out", keyframes_only=True
        )
        assert "render.render(animation=True)" not in script
        assert "write_still=True" in script

    def test_full_pass_is_unchanged_by_default(self, scene_script: SceneScriptRoot) -> None:
        script = scene_script_to_blender(scene_script, r"C:\tmp\out")
        assert "render.render(animation=True)" in script
        assert "write_still=True" not in script

    def test_draft_renders_every_shot_keyframe(self, scene_script: SceneScriptRoot) -> None:
        script = scene_script_to_blender(
            scene_script, r"C:\tmp\out", keyframes_only=True
        )
        declared = re.search(r"_keyframe_frames = \[([^\]]*)\]", script)
        assert declared, "the draft loop never declares the frames it renders"
        rendered = {int(frame) + 1 for frame in declared.group(1).split(",")}
        expected = {frame + 1 for frame in keyframe_render_frames(scene_script)}
        assert rendered == expected

    def test_draft_output_names_match_the_full_pass(
        self, scene_script: SceneScriptRoot
    ) -> None:
        """The 1-based naming is what ``extract_keyframes`` parses.

        SceneScript frames are 0-based and Blender's are 1-based, so the draft
        deliberately writes ``frame_<n + 1>``.  A draft that wrote 0-based names
        would be invisible to the keyframe extractor.
        """

        script = scene_script_to_blender(
            scene_script, r"C:\tmp\out", keyframes_only=True
        )
        # Both the frame seek and the filename use the 1-based instant, so the
        # still on disk is the one the frame was set to.
        assert "scene.frame_set(_f + 1)" in script
        assert "scene.render.filepath = r'" in script
        assert re.search(r"frame_'\s*\+\s*str\(_f\s*\+\s*1\)", script)
        assert re.search(r"frame_\d{4}\.png", script) is None

    def test_draft_is_far_smaller_than_the_full_loop(
        self, scene_script: SceneScriptRoot
    ) -> None:
        """The point of the draft: fewer frames, same stills at those instants."""

        total = scene_script.total_frames
        keyframes = len(keyframe_render_frames(scene_script))
        assert keyframes > 0
        assert keyframes < total / 3

    def test_a_scene_with_no_shots_renders_nothing_and_says_so(self) -> None:
        empty = SceneScriptRoot.model_validate(
            {**VALID_SCENE_SCRIPT, "shots": []}
        )
        assert keyframe_render_frames(empty) == []
        script = scene_script_to_blender(empty, r"C:\tmp\out", keyframes_only=True)
        assert "render.render(animation=True)" not in script
        assert "no shots, nothing to render" in script


# ---------------------------------------------------------------------------
# 2. keyframe_render_frames unions and sorts
# ---------------------------------------------------------------------------


class TestKeyframeRenderFrames:
    def test_frames_are_sorted_and_unique(self, scene_script: SceneScriptRoot) -> None:
        frames = keyframe_render_frames(scene_script)
        assert frames == sorted(set(frames))
        assert len(frames) == len(set(frames))

    def test_includes_both_shot_boundaries(self, scene_script: SceneScriptRoot) -> None:
        frames = keyframe_render_frames(scene_script)
        assert 0 in frames
        assert scene_script.total_frames - 1 in frames

    def test_a_short_shots_samples_collapse_to_one_still_each(self) -> None:
        """A still rendered twice would appear twice in the encoded cut.

        A 2-frame shot samples the *same* instant at 0%, 25% and 50% (banker's
        rounding), so without the per-shot dedup the union would hold eight
        entries for four frames and Blender would write the same PNG twice.
        """

        short = SceneScriptRoot.model_validate(
            {
                "scene": {"name": "short", "duration": 8.0, "frame_rate": 30},
                "cameras": [
                    {
                        "id": "cam1",
                        "shot_type": "wide",
                        "keyframes": [
                            {"frame": 0, "position": [10, -10, 5], "look_at": [0, 0, 1]},
                            {"frame": 3, "position": [8, -8, 4], "look_at": [0, 0, 1]},
                        ],
                    }
                ],
                "shots": [
                    {"id": "a", "camera": "cam1", "start_frame": 0, "end_frame": 2},
                    {"id": "b", "camera": "cam1", "start_frame": 2, "end_frame": 4},
                ],
            }
        )
        # The collapse is real, so the assertions below are not vacuous.
        assert _shot_keyframe_frames(short.shots[0]) == [0, 1]
        assert _shot_keyframe_frames(short.shots[1]) == [2, 3]

        frames = keyframe_render_frames(short)
        assert frames == [0, 1, 2, 3]
        assert len(frames) == len(set(frames))

    def test_a_single_shot_scene_still_reports_every_instant(
        self, scene_script: SceneScriptRoot
    ) -> None:
        """Only the union's uniqueness is guaranteed, not its count.

        A 60-frame shot samples 5 distinct instants; neighbouring shots share
        none, so the union is 5 x shots.  Pinning that catches an off-by-one in
        ``_keyframe_render_frames`` that would silently drop a shot.
        """

        frames = keyframe_render_frames(scene_script)
        assert len(frames) == 5 * len(scene_script.shots)


# ---------------------------------------------------------------------------
# 3. rendered_frames is queryable, never silenced
# ---------------------------------------------------------------------------


def _fake_result(frames: int = 20) -> object:
    return RenderResult(
        success=True,
        output_dir="unused",
        frame_count=frames,
        rendered_frames="keyframes",
    )


class TestRenderedFramesPlumbing:
    def test_the_renderer_reports_which_pass_ran(self) -> None:
        """``rendered_frames`` defaults to the conservative answer.

        A code path that constructs ``RenderResult`` without thinking about it
        must claim "animation" rather than silently assuming the draft.
        """

        assert _fake_result().rendered_frames == "keyframes"
        default = RenderResult(success=True, frame_count=1)
        assert default.rendered_frames == "animation"

    def test_config_defaults_to_the_full_animation(self) -> None:
        """The previs must move, so the default is the full animation.

        A previs is what an author watches to judge pacing, motion and cuts.
        Five stills cannot show any of those, so the draft pass is an explicit
        opt-in for node runs nobody watches — never the silent default.
        """

        assert Settings.from_env().scene3d_render_keyframes_only is False

    def test_operators_can_ask_for_a_draft_pass(self, monkeypatch) -> None:
        monkeypatch.setenv("SCENE3D_RENDER_KEYFRAMES_ONLY", "true")
        assert Settings.from_env().scene3d_render_keyframes_only is True

        monkeypatch.setenv("SCENE3D_RENDER_KEYFRAMES_ONLY", "false")
        assert Settings.from_env().scene3d_render_keyframes_only is False


# ---------------------------------------------------------------------------
# 4. The draft clip is watchable: durations follow the frame gaps
# ---------------------------------------------------------------------------


class TestDraftClipDuration:
    def test_a_full_animation_keeps_one_frame_of_duration_each(self) -> None:
        durations = _frame_durations(list(range(1, 241)), fps=30)
        assert durations == [1 / 30] * 240

    def test_keyframe_gaps_produce_a_realistic_clip_length(self) -> None:
        # 60-frame gaps at 30fps -> each still held for 2s -> ~4s clip,
        # which is the shot's real duration rather than 5/30 of a second.
        gaps = list(range(1, 122, 60))
        durations = _frame_durations(gaps, fps=30)
        assert durations == [2.0, 2.0, 2.0]
        assert sum(durations) == pytest.approx(6.0)

    def test_a_single_frame_still_has_a_duration(self) -> None:
        assert _frame_durations([7], fps=30) == [1 / 30]

    def test_durations_are_never_zero(self) -> None:
        """Two frames sharing a number would collapse the clip to nothing."""

        durations = _frame_durations([5, 5, 9], fps=24)
        assert all(d > 0 for d in durations)
