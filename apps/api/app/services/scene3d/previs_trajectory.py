"""The camera-trajectory half of a previs deliverable.

The Scene-3D node used to publish exactly one artefact: an MP4 of the rendered
frames.  That is the wrong shape for the consumers that actually matter.  A
downstream video model does not want to *watch* a slideshow -- it wants to know
where the camera was, when, and which frames it may bind as reference stills.
A reviewer wants the same facts without launching a player.

So the node also emits the *schedule* behind the render: per shot the camera,
its keyframes, the frame range in both frames and seconds, and which frames the
render pass actually wrote.  It costs nothing -- it is derived from the same
SceneScript Blender just consumed -- and it is the difference between "here is
a video" and "here is what the video shows" (ADR 0005 §4: the previs control
level must be queryable, never inferred).

Coordinates stay in SceneScript's own convention, which is Blender's Z-up.  The
browser preview converts to three.js Y-up on its own; converting here as well
would invent a third convention and guarantee that one of the two consumers is
wrong.
"""

from __future__ import annotations

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.blender_converter import keyframe_render_frames
from app.services.scene3d.keyframes import _shot_keyframe_frames


def _seconds(frame: int, frame_rate: int) -> float:
    return round(frame / frame_rate, 4) if frame_rate > 0 else 0.0


def previs_trajectory(
    scene_script: SceneScriptRoot,
    *,
    rendered_frames: str = "animation",
) -> dict:
    """Build the JSON-serialisable camera trajectory for a SceneScript.

    Args:
        scene_script: Validated SceneScript root.
        rendered_frames: ``"keyframes"`` for the draft pass, ``"animation"``
            for a full one.  A consumer must be able to tell the two apart: a
            draft is a set of stills at known instants, not a continuous
            sequence, so measuring its duration against ``total_frames`` is
            meaningless.

    Returns:
        A plain dict safe for ``json.dumps`` and for storage on a node's
        ``structured_content``.
    """

    frame_rate = scene_script.scene.frame_rate
    total_frames = scene_script.total_frames
    cameras_by_id = {camera.id: camera for camera in scene_script.cameras}
    keyframe_frames = (
        keyframe_render_frames(scene_script)
        if rendered_frames == "keyframes"
        else list(range(total_frames))
    )
    keyframe_set = set(keyframe_frames)

    shots: list[dict] = []
    for shot in scene_script.shots:
        camera = cameras_by_id.get(shot.camera)
        shot_frames = _shot_keyframe_frames(shot)
        shots.append(
            {
                "id": shot.id,
                "description": shot.description,
                "camera": shot.camera,
                # Absent when the shot references a camera this build does not
                # know; the schema forbids that, but a hand-edited script may
                # still arrive that way, and guessing a shot type would be a
                # silent fabrication.
                "shot_type": camera.shot_type if camera is not None else None,
                "start_frame": shot.start_frame,
                "end_frame": shot.end_frame,
                "start_seconds": _seconds(shot.start_frame, frame_rate),
                "end_seconds": _seconds(shot.end_frame, frame_rate),
                "keyframe_frames": shot_frames,
                # Frames of this shot the render pass actually produced.  In the
                # draft pass a shot contributes 5 of its ~30 frames; in a full
                # pass it contributes all of them.
                "rendered_frames": [f for f in shot_frames if f in keyframe_set],
                "camera_keyframes": [
                    {
                        "frame": kf.frame,
                        "position": list(kf.position),
                        "look_at": list(kf.look_at),
                    }
                    for kf in (camera.keyframes if camera is not None else [])
                ],
            }
        )

    return {
        "coordinate_system": "blender_z_up",
        "frame_rate": frame_rate,
        "total_frames": total_frames,
        "duration_seconds": scene_script.scene.duration,
        "rendered_frames": rendered_frames,
        # The frames that exist as images on disk after this pass, ascending.
        # This is what a consumer binds as reference stills.
        "keyframe_frames": keyframe_frames,
        "shots": shots,
    }
