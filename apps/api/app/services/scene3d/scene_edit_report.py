"""Per-segment edit report: what a batch of ops actually changed, by shot.

An applied op batch says WHICH operations ran. That is not what a director
asked: they asked "did the thing I wanted happen, and to WHICH shot". The
reference framework answers in one sentence — "飞船起飞的动画已加在「机位05 |
飞船俯瞰」对应的镜像段（4.5s-8.0s）" — and this module computes the structured
facts behind that sentence so every consumer (workbench, agent report, render
scheduler) reads the same numbers.

Design constraints that shaped it:

- **Pure computation, no model.** The prose in the reference is generated; the
  FACTS it quotes are not. Everything here is derived from before/after scripts
  plus the applied ops, so it is testable and cannot hallucinate a change that
  did not happen. A caller that wants prose can render these facts into one.
- **Diff the objects, not the ops.** An op is an instruction; the report must
  describe the RESULT, so a no-op instruction (``rotate_object`` on a camera,
  which the gate rejects, or a move to the position already held) is reported as
  what changed rather than as what was asked for.
- **A shot is the unit.** SceneScript's time axis is shots, so "which segment"
  is always a shot's frame range converted with the script's own frame rate —
  the same inclusive reading ``ShotStrip`` uses for its bars.
"""

from __future__ import annotations

from typing import Any

from app.schemas.scene_script import SceneScriptRoot

# Change codes a report entry may carry. Kept as plain strings (not an enum)
# because they travel to the frontend as JSON and are matched there.
CHANGE_CAMERA_MOVED = "camera_moved"
CHANGE_CAMERA_AIMED = "camera_aimed"
CHANGE_CAMERA_RENAMED = "camera_renamed"
CHANGE_CAMERA_SHOT_TYPE = "camera_shot_type"
CHANGE_CAMERA_ADDED = "camera_added"
CHANGE_CAMERA_REMOVED = "camera_removed"
CHANGE_OBJECT_MOVED = "object_moved"
CHANGE_OBJECT_ROTATED = "object_rotated"
CHANGE_OBJECT_SCALED = "object_scaled"
CHANGE_OBJECT_ADDED = "object_added"
CHANGE_OBJECT_REMOVED = "object_removed"
CHANGE_CHARACTER_ACTION = "character_action"
CHANGE_SHOT_ADDED = "shot_added"
CHANGE_SHOT_REMOVED = "shot_removed"
CHANGE_SHOT_REPOINTED = "shot_repointed"

# Human labels for the change codes. The frontend renders these, so they live
# here (one place) rather than being re-spelled per caller.
CHANGE_LABELS: dict[str, str] = {
    CHANGE_CAMERA_MOVED: "机位移动",
    CHANGE_CAMERA_AIMED: "机位朝向",
    CHANGE_CAMERA_RENAMED: "机位改名",
    CHANGE_CAMERA_SHOT_TYPE: "景别切换",
    CHANGE_CAMERA_ADDED: "新增机位",
    CHANGE_CAMERA_REMOVED: "移除机位",
    CHANGE_OBJECT_MOVED: "位置移动",
    CHANGE_OBJECT_ROTATED: "旋转调整",
    CHANGE_OBJECT_SCALED: "缩放调整",
    CHANGE_OBJECT_ADDED: "新增对象",
    CHANGE_OBJECT_REMOVED: "移除对象",
    CHANGE_CHARACTER_ACTION: "动作变化",
    CHANGE_SHOT_ADDED: "新增镜头",
    CHANGE_SHOT_REMOVED: "移除镜头",
    CHANGE_SHOT_REPOINTED: "镜头改绑机位",
}


def camera_display_name(camera: Any, index: int) -> str:
    """The camera's label as the workbench spells it: "机位05 | 飞船俯瞰".

    ``index`` is the camera's position in ``script.cameras`` — the ordinal is
    positional, not derived from the id, so it stays stable as cameras are
    added and removed in the middle of a list.
    """

    ordinal = f"机位{index + 1:02d}"
    authored = getattr(camera, "display_name", None)
    if isinstance(authored, str) and authored.strip():
        return f"{ordinal} | {authored.strip()}"
    return ordinal


def _camera_index(script: SceneScriptRoot, camera_id: str) -> int:
    for index, camera in enumerate(script.cameras):
        if camera.id == camera_id:
            return index
    return 0


def _keyframe_map(camera: Any) -> dict[int, tuple[list[float], list[float]]]:
    return {
        keyframe.frame: (list(keyframe.position), list(keyframe.look_at))
        for keyframe in camera.keyframes
    }


def _camera_changes(before: Any, after: Any) -> set[str]:
    """What changed about ONE camera between two scripts."""

    changes: set[str] = set()
    if before is None or after is None:
        return changes
    before_keyframes = _keyframe_map(before)
    after_keyframes = _keyframe_map(after)
    for frame, (position, look_at) in after_keyframes.items():
        previous = before_keyframes.get(frame)
        if previous is None:
            changes.add(CHANGE_CAMERA_MOVED)
            continue
        if previous[0] != position:
            changes.add(CHANGE_CAMERA_MOVED)
        if previous[1] != look_at:
            changes.add(CHANGE_CAMERA_AIMED)
    if any(frame not in after_keyframes for frame in before_keyframes):
        changes.add(CHANGE_CAMERA_MOVED)
    if getattr(before, "shot_type", None) != getattr(after, "shot_type", None):
        changes.add(CHANGE_CAMERA_SHOT_TYPE)
    if (before.display_name or None) != (after.display_name or None):
        changes.add(CHANGE_CAMERA_RENAMED)
    return changes


def _non_camera_changes(before: Any, after: Any, kind: str) -> set[str]:
    changes: set[str] = set()
    if before is None or after is None:
        return changes
    if kind == "character":
        before_keyframes = {
            keyframe.frame: (list(keyframe.position), keyframe.rotation_y, keyframe.action)
            for keyframe in before.keyframes
        }
        after_keyframes = {
            keyframe.frame: (list(keyframe.position), keyframe.rotation_y, keyframe.action)
            for keyframe in after.keyframes
        }
        for frame, value in after_keyframes.items():
            previous = before_keyframes.get(frame)
            if previous is None:
                changes.add(CHANGE_OBJECT_MOVED)
                continue
            if previous[0] != value[0]:
                changes.add(CHANGE_OBJECT_MOVED)
            if previous[1] != value[1]:
                changes.add(CHANGE_OBJECT_ROTATED)
            if previous[2] != value[2]:
                changes.add(CHANGE_CHARACTER_ACTION)
        if before.appearance.scale != after.appearance.scale:
            changes.add(CHANGE_OBJECT_SCALED)
        return changes
    if before.position != after.position:
        changes.add(CHANGE_OBJECT_MOVED)
    if getattr(before, "rotation_y", 0.0) != getattr(after, "rotation_y", 0.0):
        changes.add(CHANGE_OBJECT_ROTATED)
    if getattr(before, "scale", None) != getattr(after, "scale", None):
        changes.add(CHANGE_OBJECT_SCALED)
    return changes


def _collection_changes(
    before_items: list[Any],
    after_items: list[Any],
    diff: Any,
) -> dict[str, set[str]]:
    """Per-object change sets for one collection, keyed by object id."""

    before_by_id = {item.id: item for item in before_items}
    after_by_id = {item.id: item for item in after_items}
    result: dict[str, set[str]] = {}
    for object_id, item in after_by_id.items():
        previous = before_by_id.get(object_id)
        if previous is None:
            result[object_id] = {CHANGE_OBJECT_ADDED}
            continue
        changes = diff(previous, item)
        if changes:
            result[object_id] = changes
    for object_id in before_by_id:
        if object_id not in after_by_id:
            result[object_id] = {CHANGE_OBJECT_REMOVED}
    return result


def build_scene_edit_report(
    before: SceneScriptRoot | dict[str, Any],
    after: SceneScriptRoot | dict[str, Any],
) -> dict[str, Any]:
    """Diff two SceneScripts into a per-shot edit report.

    Returns a JSON-ready dict::

        {
          "changes": {"cam_2": ["camera_moved"], ...},
          "shots": [
            {"id": "shot_2", "camera_id": "cam_2",
             "camera_label": "机位02 | 飞船俯瞰",
             "start_seconds": 2.0, "end_seconds": 4.0,
             "changes": ["camera_moved"],
             "objects_touched": ["cam_2"]},
          ],
          "shot_count": 2,
          "change_count": 1,
        }

    ``shots`` lists only shots whose content changed OR whose range moved; an
    untouched shot is not news. ``changes`` is the object-level view (including
    objects that belong to no shot, such as a prop nobody animated), because a
    review of "what did I just do" needs both.
    """

    if isinstance(before, dict):
        before = SceneScriptRoot.model_validate(before)
    if isinstance(after, dict):
        after = SceneScriptRoot.model_validate(after)

    camera_changes = _collection_changes(
        list(before.cameras), list(after.cameras), _camera_changes
    )
    # A camera that appeared or disappeared is news even though there is no
    # "before" to diff against — the add/remove code is the whole change.
    for camera in after.cameras:
        if camera_changes.get(camera.id) == {CHANGE_OBJECT_ADDED}:
            camera_changes[camera.id] = {CHANGE_CAMERA_ADDED, CHANGE_OBJECT_ADDED}
    for camera in before.cameras:
        if camera.id not in {item.id for item in after.cameras}:
            camera_changes[camera.id] = {CHANGE_CAMERA_REMOVED, CHANGE_OBJECT_REMOVED}

    object_changes: dict[str, set[str]] = dict(camera_changes)
    # Each collection's attribute name is its own (characters, props,
    # environment — not "environments"), so name them explicitly rather than
    # pluralising and tripping over the one that is already plural-looking.
    collections: tuple[tuple[str, str, Any], ...] = (
        ("characters", "character", lambda b, a: _non_camera_changes(b, a, "character")),
        ("props", "prop", lambda b, a: _non_camera_changes(b, a, "prop")),
        ("environment", "environment", lambda b, a: _non_camera_changes(b, a, "environment")),
    )
    for attribute, _kind, diff in collections:
        object_changes.update(
            _collection_changes(
                list(getattr(before, attribute)),
                list(getattr(after, attribute)),
                diff,
            )
        )

    # Shot-level: a shot is affected when its camera changed, when the shot
    # itself moved, or when the shot is new/gone.
    before_shots = {shot.id: shot for shot in before.shots}
    after_shots = {shot.id: shot for shot in after.shots}
    frame_rate = after.scene.frame_rate

    shot_reports: list[dict[str, Any]] = []
    for shot in sorted(after.shots, key=lambda item: item.start_frame):
        changes: set[str] = set(camera_changes.get(shot.camera, set()))
        previous = before_shots.get(shot.id)
        if previous is None:
            changes.add(CHANGE_SHOT_ADDED)
        else:
            if previous.camera != shot.camera:
                changes.add(CHANGE_SHOT_REPOINTED)
            if (
                previous.start_frame != shot.start_frame
                or previous.end_frame != shot.end_frame
            ):
                # A shot that moved is news for the render schedule even when
                # nothing inside it changed.
                changes.add(CHANGE_SHOT_ADDED)
                changes.add(CHANGE_SHOT_REMOVED)
        if not changes:
            continue
        shot_reports.append(
            {
                "id": shot.id,
                "camera_id": shot.camera,
                "camera_label": camera_display_name(
                    next((cam for cam in after.cameras if cam.id == shot.camera), None),
                    _camera_index(after, shot.camera),
                )
                if any(cam.id == shot.camera for cam in after.cameras)
                else shot.camera,
                # Inclusive bounds, matching ShotStrip's span measurement: a shot
                # covering frames 0..149 at 30fps is 5.0s, not 4.97s.
                "start_seconds": round(shot.start_frame / frame_rate, 3),
                "end_seconds": round((shot.end_frame + 1) / frame_rate, 3),
                "changes": sorted(changes),
                "objects_touched": sorted(
                    object_id
                    for object_id, object_change in object_changes.items()
                    if object_change & changes
                ),
            }
        )
    for shot_id, shot in before_shots.items():
        if shot_id in after_shots:
            continue
        shot_reports.append(
            {
                "id": shot_id,
                "camera_id": shot.camera,
                "camera_label": shot.camera,
                "start_seconds": round(shot.start_frame / frame_rate, 3),
                "end_seconds": round((shot.end_frame + 1) / frame_rate, 3),
                "changes": [CHANGE_SHOT_REMOVED],
                "objects_touched": [],
            }
        )
    shot_reports.sort(key=lambda item: item["start_seconds"])

    all_changes = sorted(
        {code for codes in object_changes.values() for code in codes}
        | {code for shot in shot_reports for code in shot["changes"]}
    )
    return {
        "changes": {
            object_id: sorted(codes) for object_id, codes in sorted(object_changes.items())
        },
        "shots": shot_reports,
        "shot_count": len(after.shots),
        "change_count": len(all_changes),
        "labels": CHANGE_LABELS,
    }
