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

        A keyframe the converter drops is a still frame in the final clip.

        Asserted per authored keyframe rather than as a global count: the pose pass
        legitimately adds its own location keys (the vertical bob rides an empty per
        frame) and rotation keys (the limb pivots), so a total stopped being the
        measure of whether anything was dropped. What must hold is that EVERY
        authored keyframe is present, at its own frame, on the wrapper -- and that a
        dropped one now fails this instead of hiding inside a changed total.
        """

        script = _generate(keyframes_only=False)
        scene = _scene()

        for character in scene.characters:
            for keyframe in character.keyframes:
                blender_frame = keyframe.frame + 1
                assert (
                    f"char_obj.keyframe_insert(data_path='location', frame={blender_frame})"
                    in script
                ), f"{character.id} frame {keyframe.frame} lost its location key"
                assert (
                    f"char_obj.keyframe_insert(data_path='rotation_euler', frame={blender_frame})"
                    in script
                ), f"{character.id} frame {keyframe.frame} lost its yaw key"

        # Each camera keyframe writes the camera's location AND its focus target's.
        for camera in scene.cameras:
            for keyframe in camera.keyframes:
                blender_frame = keyframe.frame + 1
                assert (
                    f"cam.keyframe_insert(data_path='location', frame={blender_frame})"
                    in script
                )
                assert (
                    f"target.keyframe_insert(data_path='location', frame={blender_frame})"
                    in script
                )

    def test_a_walking_character_animates_its_limbs(self) -> None:
        """`action` must reach Blender, not just the preview.

        The converter read `position` and `rotation_y` and ignored `action`, so under
        the DEFAULT backend a `walk` rendered as a figure sliding with its limbs welded
        in place -- and nothing said so. Two properties pin it:

        - each limb pivots at its PROXIMAL end, because a Blender primitive's origin
          is its centre and rotating there orbits the limb instead of swinging it;
        - the pivots carry rotation keys, and a walk is keyed every frame because its
          phase comes from distance travelled.
        """

        script = _generate(keyframes_only=False)
        scene = _scene()
        walkers = [c for c in scene.characters if any(k.action == "walk" for k in c.keyframes)]
        assert walkers, "the fixture has no walking character, so this proves nothing"

        for character in walkers:
            for limb in ("LegL", "LegR", "ArmL", "ArmR"):
                assert f'"{character.id}_{limb}_pivot"' in script, (
                    f"{limb} has no pivot, so it would orbit its own centre"
                )
                assert f"_p_{character.id}{limb}.rotation_euler.x" in script
                assert f"_p_{character.id}{limb}.keyframe_insert(" in script
            assert f'"{character.id}_Head_pivot"' in script
            # The bob rides its own empty so the wrapper's location keeps carrying the
            # authored position rather than position+bob.
            assert f'bob_{character.id}.keyframe_insert(' in script

    def test_a_character_that_only_stands_gets_a_constant_pose(self) -> None:
        """A held action is keyed once, not every frame.

        Otherwise a 720-frame scene's script grows by thousands of lines that all say
        the same thing, and the whole animation pass becomes unreviewable.
        """

        script = _generate(keyframes_only=False)
        scene = _scene()
        standers = [
            c for c in scene.characters
            if all(k.action in {"stand", "talk", "sit", "gesture"} for k in c.keyframes)
        ]
        for character in standers:
            # The bob is keyed every frame regardless -- it is cheap, and keeping it
            # uniform means the frame loop has no branch.
            assert script.count(f"bob_{character.id}.keyframe_insert(") >= len(
                [k for k in character.keyframes]
            )
            assert script.count(f"_p_{character.id}LegL.keyframe_insert(") == 1

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
