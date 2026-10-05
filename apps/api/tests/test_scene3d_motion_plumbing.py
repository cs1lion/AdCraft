"""Verify the full-animation default actually reaches the Blender script.

This is the regression the default flip could have silently missed: if
``scene_script_to_blender`` ignored ``keyframes_only`` — or if the executor
passed it but the generator's branch were inverted — the setting would look
correct in config while Blender still rendered five stills. No Blender is
needed to catch that: the generated Python either contains the animation pass
or it does not.
"""

import json
from pathlib import Path

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.blender_converter import scene_script_to_blender

SCENE_FIXTURE = (
    Path(__file__).resolve().parents[3] / "test-materials" / "motion_scene.json"
)


def _scene() -> SceneScriptRoot:
    return SceneScriptRoot.model_validate(
        json.loads(SCENE_FIXTURE.read_text(encoding="utf-8"))
    )


def _generate(keyframes_only: bool) -> str:
    return scene_script_to_blender(
        _scene(), output_dir="unused", keyframes_only=keyframes_only
    )


class TestFullAnimationReachesBlender:
    def test_the_default_pass_renders_the_whole_animation(self) -> None:
        script = _generate(keyframes_only=False)

        # The one line that makes the previs move.
        assert "bpy.ops.render.render(animation=True)" in script
        # The draft pass must not also be emitted: two passes in one script
        # would double the wall clock for no extra frames.
        assert "_keyframe_frames" not in script

    def test_the_draft_pass_renders_only_the_keyframe_stills(self) -> None:
        script = _generate(keyframes_only=True)

        assert "bpy.ops.render.render(animation=True)" not in script
        assert "_keyframe_frames" in script

    def test_the_engine_is_eevee_and_the_resolution_is_the_previs_one(self) -> None:
        script = _generate(keyframes_only=False)

        assert "scene.render.engine = 'BLENDER_EEVEE'" in script
        assert "scene.render.resolution_x = 960" in script
        assert "scene.render.resolution_y = 540" in script

    def test_every_motion_keyframe_becomes_a_blender_keyframe(self) -> None:
        """The animation pass can only interpolate what was written.

        A keyframe the converter drops is a still frame in the final clip, so
        count them: two characters plus two cameras.
        """

        script = _generate(keyframes_only=False)
        scene = _scene()

        expected_character = sum(len(c.keyframes) for c in scene.characters)
        # Each camera keyframe writes the camera's location AND its focus
        # target's location.
        expected_camera = sum(len(c.keyframes) * 2 for c in scene.cameras)

        assert script.count("keyframe_insert(data_path='location'") == (
            expected_character + expected_camera
        )
        assert script.count("keyframe_insert(data_path='rotation_euler'") == (
            expected_character
        )

    def test_each_shot_gets_a_timeline_marker_bound_to_its_camera(self) -> None:
        """Markers are what makes the render cut between cameras."""

        script = _generate(keyframes_only=False)

        for shot in _scene().shots:
            assert f"timeline_markers.new('{shot.id}'" in script
            assert f"marker.camera = bpy.data.objects.get('{shot.camera}')" in script

    def test_the_keyframe_plan_is_published_for_both_passes(self) -> None:
        """The video model binds these instants whatever the render pass."""

        from app.services.scene3d.previs_trajectory import previs_trajectory

        scene = _scene()
        for rendered in ("animation", "keyframes"):
            trajectory = previs_trajectory(scene, rendered_frames=rendered)
            for shot in trajectory["shots"]:
                # Every shot contributes its own five instants in both passes;
                # only ``rendered_frames`` differs between them.
                assert len(shot["keyframe_frames"]) == 5
