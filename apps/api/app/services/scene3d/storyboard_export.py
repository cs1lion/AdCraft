"""Storyboard export for a SceneScript — batch frame capture + shot list.

"出分镜" (storyboard) is a V3 capability: any moment in the director flow
the creator asks for a storyboard and the pipeline emits a shot list
(shot id, shot type, camera, start/end frame, duration, description,
representative keyframe frames) and a flat storyboard strip (one entry
per shot, with its 5 keyframe frame numbers from the existing
``_shot_keyframe_frames`` helper). No new asset pipeline, no Blender
work — the export is pure math on the validated SceneScript.

The frame numbers are 0-based SceneScript frames, matching the draft
pass's keyframe render contract (``keyframe_render_frames`` in
``blender_converter.py``). A consumer that needs actual rendered frames
calls ``/scene-3d/keyframes`` with those numbers; this module owns the
*list*, not the pixels.

The module is deterministic: same script in → same storyboard out, so
the "rerun / A-B take" invariant from ADR 0012 extends to the
storyboard.

Deterministic is not the same as *sound*: the schema rejects overlapping
shots and shots past the end, but it says nothing about shots that leave a
hole — frames that belong to no shot render nothing, so the strip the
creator walks through silently skips part of their own film. Rather than
reject the script (the storyboard is a read-only view) the export ships
the strip plus ``check_storyboard_span`` — named, queryable findings a
caller can surface next to the strip (engineering standard §4 — no silent
degradation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.scene_script import SceneCamera, SceneScriptRoot
from app.services.scene3d.keyframes import _shot_keyframe_frames


@dataclass(frozen=True, slots=True)
class StoryboardShotEntry:
    """One shot in the storyboard strip."""

    shot_id: str
    camera_id: str
    shot_type: str
    start_frame: int
    end_frame: int
    duration_frames: int
    description: str
    transition_intent: str | None
    #: The 5 keyframe frame numbers this shot's draft pass renders.
    keyframe_frames: tuple[int, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable entry (the shape ``/scene-3d/storyboard`` returns)."""
        return {
            "shot_id": self.shot_id,
            "camera_id": self.camera_id,
            "shot_type": self.shot_type,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "duration_frames": self.duration_frames,
            "description": self.description,
            "transition_intent": self.transition_intent,
            "keyframe_frames": list(self.keyframe_frames),
        }


@dataclass(frozen=True, slots=True)
class StoryboardStrip:
    """The full storyboard for a SceneScript: shot list + flat frame strip."""

    scene_name: str
    total_shots: int
    total_frames: int
    shots: tuple[StoryboardShotEntry, ...]
    #: Every keyframe frame across all shots, sorted, deduplicated.
    #: This is the flat strip a renderer or viewer iterates.
    all_keyframe_frames: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable strip (the shape ``/scene-3d/storyboard`` returns)."""
        return {
            "scene_name": self.scene_name,
            "total_shots": self.total_shots,
            "total_frames": self.total_frames,
            "shots": [entry.to_dict() for entry in self.shots],
            "all_keyframe_frames": list(self.all_keyframe_frames),
        }


@dataclass(frozen=True, slots=True)
class StoryboardFinding:
    """One named reason this strip does not cover the whole scene.

    Advisory only, like the rest of this family: the strip is still
    returned, the finding just rides next to it so the surface can say
    which frames are in doubt instead of failing a read-only view.
    """

    #: "storyboard_no_shots" | "storyboard_shots_leave_gap" |
    #: "storyboard_shot_keyframes_short"
    code: str
    #: The shot(s) — or frame range — the finding concerns.
    subject: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "subject": self.subject, "message": self.message}


def build_storyboard(scene_script: SceneScriptRoot) -> StoryboardStrip:
    """Expand a validated SceneScript into a deterministic storyboard strip.

    Raises ``ValueError`` when a shot references a camera that is not in the
    script (the gate normally catches this, but the export is called from
    surfaces that skip the gate).
    """
    cameras_by_id: dict[str, SceneCamera] = {camera.id: camera for camera in scene_script.cameras}

    entries: list[StoryboardShotEntry] = []
    frame_set: set[int] = set()

    for shot in scene_script.shots:
        if shot.camera not in cameras_by_id:
            raise ValueError(
                f"storyboard_shot_camera_missing: shot '{shot.id}' references camera "
                f"'{shot.camera}' which is not in the script"
            )
        camera = cameras_by_id[shot.camera]
        keyframes = tuple(_shot_keyframe_frames(shot))
        entries.append(
            StoryboardShotEntry(
                shot_id=shot.id,
                camera_id=shot.camera,
                shot_type=camera.shot_type,
                start_frame=shot.start_frame,
                end_frame=shot.end_frame,
                duration_frames=shot.end_frame - shot.start_frame,
                description=shot.description,
                transition_intent=shot.transition_intent,
                keyframe_frames=keyframes,
            )
        )
        frame_set.update(keyframes)

    return StoryboardStrip(
        scene_name=scene_script.scene.name,
        total_shots=len(entries),
        total_frames=scene_script.total_frames,
        shots=tuple(entries),
        all_keyframe_frames=tuple(sorted(frame_set)),
    )


def check_storyboard_span(strip: StoryboardStrip) -> list[StoryboardFinding]:
    """Named reasons this strip does not cover the whole scene.

    Pure and advisory: the strip itself is already built, this only reports
    where the shot list and the scene's frame range disagree so a caller can
    render a warning beside it. Three conditions are reachable through a
    schema-valid script:

    - ``storyboard_no_shots``: an empty storyboard is a real answer, but it
      should not look like a rendering fault.
    - ``storyboard_shots_leave_gap``: frames that belong to no shot render
      nothing, so the strip the creator walks through skips part of the film.
    - ``storyboard_shot_keyframes_short``: a very short shot cannot supply
      the 5 representative frames this strip advertises, and a consumer that
      assumes five would index past the end.

    The schema already rejects overlapping shots and shots past the end, so
    those are not re-litigated here.
    """
    findings: list[StoryboardFinding] = []

    if not strip.shots:
        findings.append(
            StoryboardFinding(
                code="storyboard_no_shots",
                subject="",
                message="这个场景还没有镜头，分镜是空的；先添加镜头再出分镜。",
            )
        )
        return findings

    ordered = sorted(strip.shots, key=lambda entry: entry.start_frame)

    # Frames with no shot: before the first, between two, and after the last.
    # ``end_frame`` is exclusive, so the last frame that exists is
    # ``total_frames - 1`` and a shot may legally end ON ``total_frames``.
    last_frame = strip.total_frames - 1
    gaps: list[tuple[str, int, int]] = []
    if ordered[0].start_frame > 0:
        gaps.append(("", 0, ordered[0].start_frame - 1))
    for previous, current in zip(ordered, ordered[1:]):
        if current.start_frame > previous.end_frame:
            gaps.append(
                (f"{previous.shot_id}→{current.shot_id}", previous.end_frame, current.start_frame - 1)
            )
    trailing_start = ordered[-1].end_frame
    if trailing_start <= last_frame:
        gaps.append(("", trailing_start, last_frame))
    for subject, first, last in gaps:
        findings.append(
            StoryboardFinding(
                code="storyboard_shots_leave_gap",
                subject=subject,
                message=(
                    f"第 {first}–{last} 帧（{last - first + 1} 帧）不属于任何镜头"
                    "：这些帧不会进分镜，成片会在那里空跳。"
                ),
            )
        )

    # A shot shorter than the sample contract cannot supply its 5 frames.
    for entry in ordered:
        if len(entry.keyframe_frames) < 5:
            findings.append(
                StoryboardFinding(
                    code="storyboard_shot_keyframes_short",
                    subject=entry.shot_id,
                    message=(
                        f"镜头「{entry.shot_id}」只有 {entry.duration_frames} 帧，"
                        f"代表帧取到 {len(entry.keyframe_frames)} 张而不是 5 张。"
                    ),
                )
            )

    return findings
