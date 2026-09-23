"""Unit tests for the previs camera-trajectory deliverable.

The trajectory is what a downstream video node binds and what a reviewer reads
instead of watching the clip, so its edge cases matter: a shot whose camera the
schema somehow does not know, a scene with no shots at all, and the difference
between a draft pass and a full one. Getting any of those wrong produces a
plausible-looking document that silently misdescribes the render.
"""

from __future__ import annotations

import json

import pytest

from app.schemas.scene_script import (
    CameraKeyframe,
    SceneCamera,
    SceneInfo,
    SceneScriptRoot,
    SceneShot,
)
from app.services.scene3d.previs_trajectory import previs_trajectory


def _script(
    *,
    shots: list[SceneShot] | None = None,
    cameras: list[SceneCamera] | None = None,
    duration: float = 3.0,
    frame_rate: int = 30,
) -> SceneScriptRoot:
    return SceneScriptRoot(
        scene=SceneInfo(name="t", duration=duration, frame_rate=frame_rate),
        cameras=cameras if cameras is not None else [],
        shots=shots if shots is not None else [],
    )


def _camera(camera_id: str = "cam1", *, at: tuple[int, ...] = (0,)) -> SceneCamera:
    return SceneCamera(
        id=camera_id,
        shot_type="wide",
        keyframes=[
            CameraKeyframe(frame=f, position=[1, 2, 3], look_at=[0, 0, 0]) for f in at
        ],
    )


def test_the_document_is_json_serialisable() -> None:
    """It is stored on a node's structured_content, so it must survive a round trip."""

    document = previs_trajectory(
        _script(
            shots=[SceneShot(id="s1", camera="cam1", start_frame=0, end_frame=90)],
            cameras=[_camera()],
        )
    )

    assert json.loads(json.dumps(document)) == document


def test_a_scene_with_no_shots_yields_an_empty_schedule_not_an_error() -> None:
    document = previs_trajectory(_script())

    assert document["shots"] == []
    assert document["total_frames"] == 90
    # Nothing was rendered, so nothing is bindable -- which is the honest
    # answer, not a guess at frame 0.
    assert document["keyframe_frames"] == list(range(90))


def test_a_shot_whose_camera_is_missing_reports_rather_than_invents() -> None:
    """``shot_type`` must not be fabricated for a shot with no camera.

    The schema rejects a dangling camera reference, so the only way to reach
    this branch is a document that never went through validation -- a
    hand-edited node column, or a schema that later loosens the check.
    Reporting ``None`` keeps the gap visible instead of asserting a shot type
    the scene never declared.
    """

    base = _script(
        shots=[SceneShot(id="s1", camera="cam1", start_frame=0, end_frame=90)],
        cameras=[_camera()],
    )
    script = base.model_copy(
        update={
            "shots": [SceneShot(id="s1", camera="ghost", start_frame=0, end_frame=90)]
        }
    )

    document = previs_trajectory(script)

    (shot,) = document["shots"]
    assert shot["shot_type"] is None
    assert shot["camera_keyframes"] == []


def test_a_draft_lists_only_the_frames_it_actually_wrote() -> None:
    """The point of the draft: five frames, named, out of ninety."""

    document = previs_trajectory(
        _script(
            shots=[SceneShot(id="s1", camera="cam1", start_frame=0, end_frame=90)],
            cameras=[_camera()],
        ),
        rendered_frames="keyframes",
    )

    assert document["keyframe_frames"] == [0, 22, 44, 67, 89]
    (shot,) = document["shots"]
    assert shot["rendered_frames"] == [0, 22, 44, 67, 89]


def test_a_full_pass_marks_every_frame_as_rendered() -> None:
    document = previs_trajectory(
        _script(
            shots=[SceneShot(id="s1", camera="cam1", start_frame=0, end_frame=90)],
            cameras=[_camera()],
        ),
        rendered_frames="animation",
    )

    assert document["keyframe_frames"] == list(range(90))
    (shot,) = document["shots"]
    assert shot["rendered_frames"] == [0, 22, 44, 67, 89]


def test_the_published_frame_list_is_the_union_of_the_shots() -> None:
    """``keyframe_frames`` is what a consumer binds, so it must be exact.

    Adjacent shots can sample the same frame (a shot's 0% is the previous
    shot's last frame), so the list is a deduplicated union -- and it is
    derived from the same per-shot numbers it publishes, which is what lets a
    consumer trust either one.
    """

    document = previs_trajectory(
        _script(
            shots=[
                SceneShot(id="s1", camera="cam1", start_frame=0, end_frame=11),
                SceneShot(id="s2", camera="cam2", start_frame=11, end_frame=21),
            ],
            cameras=[_camera("cam1", at=(0,)), _camera("cam2", at=(11,))],
        ),
        rendered_frames="keyframes",
    )

    per_shot = [f for shot in document["shots"] for f in shot["rendered_frames"]]
    assert document["keyframe_frames"] == sorted(set(per_shot))
    assert len(document["keyframe_frames"]) == len(per_shot)


@pytest.mark.parametrize(
    ("start", "end", "frame_rate", "expected"),
    [
        (0, 30, 30, (0.0, 1.0)),
        (0, 45, 30, (0.0, 1.5)),
        (60, 90, 24, (2.5, 3.75)),
    ],
)
def test_shot_boundaries_are_reported_in_seconds_too(
    start: int, end: int, frame_rate: int, expected: tuple[float, float]
) -> None:
    """Frames alone force every consumer to re-derive the frame rate."""

    document = previs_trajectory(
        _script(
            shots=[SceneShot(id="s1", camera="cam1", start_frame=start, end_frame=end)],
            cameras=[_camera(at=(start,))],
            frame_rate=frame_rate,
            duration=end / frame_rate,
        )
    )

    (shot,) = document["shots"]
    assert (shot["start_seconds"], shot["end_seconds"]) == expected
