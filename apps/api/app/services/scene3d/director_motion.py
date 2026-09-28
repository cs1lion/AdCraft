"""Director motion presets expanded into deterministic SceneScript operations.

This module implements the MVP director-command layer discussed for the
3D previs feature: natural-language intent such as "push in" or "let him
walk to the door" should land as small, gated, replayable SceneScript
operation batches. The module owns the pure expansion from intent-level
preset parameters to existing ops, so the LLM and web UI never invent raw
keyframe lists for common camera/character moves.

It intentionally does not modify ``SceneScriptToolService`` in this first
step. Callers can expand an intent into ops and feed the batch through the
existing all-or-nothing gate, which keeps the service boundary small.
"""

from __future__ import annotations

import math
from typing import Any

from app.schemas.scene_script import SceneScriptRoot

CAMERA_MOTION_PRESET_IDS = frozenset(
    {
        "push_in",
        "pull_out",
        "orbit_left",
        "orbit_right",
        "pan_left",
        "pan_right",
        "crane_up",
        "crane_down",
    }
)

CHARACTER_MOTION_PRESET_IDS = frozenset({"walk_to", "turn_to", "approach", "mark_talk"})

#: Which preset family each intent may name. A camera intent that arrives
#: with a character preset (or the reverse) is a caller mistake, not a
#: "missing preset" — naming it separately keeps the error actionable.
INTENT_PRESET_FAMILIES: dict[str, frozenset[str]] = {
    "camera_motion": CAMERA_MOTION_PRESET_IDS,
    "character_motion": CHARACTER_MOTION_PRESET_IDS,
}

MOTION_SAMPLE_STEP_FRAMES = 15


class DirectorMotionError(ValueError):
    """Raised when a director intent cannot be expanded into valid ops."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _as_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DirectorMotionError("director_motion_invalid", f"{field} must be numeric")
    return float(value)


def _position(value: Any, field: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise DirectorMotionError("director_motion_invalid", f"{field} must be [x, y, z]")
    return [_as_float(component, f"{field}[{index}]") for index, component in enumerate(value)]


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DirectorMotionError("director_motion_invalid", f"{field} must be an integer")
    return value


def _normalize(vector: list[float]) -> list[float]:
    length = math.sqrt(sum(component * component for component in vector))
    if length < 1e-9:
        return [0.0, 0.0, 0.0]
    return [component / length for component in vector]


def _distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(
        sum((float(a[index]) - float(b[index])) ** 2 for index in range(3))
    )


def _anchor_camera_keyframes(
    camera_keyframes: list[Any], start_frame: int
) -> dict[str, Any]:
    if not camera_keyframes:
        return {"frame": start_frame, "position": [0.0, 0.0, 0.0], "look_at": [0.0, 0.0, 1.0]}
    before = [key for key in camera_keyframes if key.frame <= start_frame]
    chosen = before[-1] if before else camera_keyframes[0]
    return {
        "frame": chosen.frame,
        "position": [float(component) for component in chosen.position],
        "look_at": [float(component) for component in (chosen.look_at or [0.0, 0.0, 1.0])],
    }


def _anchor_character_keyframes(character_keyframes: list[Any], start_frame: int) -> dict[str, Any]:
    if not character_keyframes:
        return {"position": [0.0, 0.0, 0.0], "rotation_y": 0.0, "action": "stand"}
    before = [key for key in character_keyframes if key.frame <= start_frame]
    chosen = before[-1] if before else character_keyframes[0]
    return {
        "position": [float(component) for component in chosen.position],
        "rotation_y": float(chosen.rotation_y or 0.0),
        "action": chosen.action or "stand",
    }


def _sample_frames(start_frame: int, duration_frames: int) -> list[int]:
    step = max(1, MOTION_SAMPLE_STEP_FRAMES)
    frames: list[int] = []
    for frame in range(start_frame, start_frame + duration_frames + 1, step):
        frames.append(frame)
    if not frames or frames[-1] != start_frame + duration_frames:
        frames.append(start_frame + duration_frames)
    return frames


def _progress(frame: int, start_frame: int, duration_frames: int) -> float:
    """Normalised 0..1 position of ``frame`` inside the move.

    A zero-length move is a still, not a division by zero — the callers
    clamp the duration to >= 1, but the samplers stay total so a future
    caller cannot crash on a degenerate range.
    """
    if duration_frames <= 0:
        return 0.0
    return (frame - start_frame) / duration_frames


def _clamp_total_frames(script: SceneScriptRoot, frame: int) -> int:
    if frame < 0:
        raise DirectorMotionError("director_motion_frame_out_of_range", "frame must be >= 0")
    if frame > script.total_frames:
        raise DirectorMotionError(
            "director_motion_frame_out_of_range",
            f"frame {frame} exceeds total frames ({script.total_frames})",
        )
    return frame


def _clamp_duration(script: SceneScriptRoot, start_frame: int, duration_frames: int) -> int:
    if duration_frames < 1:
        raise DirectorMotionError(
            "director_motion_invalid", "duration_frames must be at least 1"
        )
    end_frame = _clamp_total_frames(script, start_frame + duration_frames)
    return end_frame - start_frame


def _resolve_window(
    script: SceneScriptRoot, start_frame: Any, duration_frames: Any
) -> tuple[int, int]:
    """Validate a motion window and return the window that will actually run.

    A move that would run past the scene's last frame is rejected with a
    named ``director_motion_frame_out_of_range`` rather than silently
    trimmed: a director who asked for 60 frames of push-in gets 60 frames
    or an error, never 20 they did not ask for. The resolved numbers are
    what the ops are stamped with, so a caller recording a batch must
    record *these* — echoing the raw request would make the record
    disagree with the ops it claims to describe.
    """
    resolved_start = _clamp_total_frames(script, _as_int(start_frame, "start_frame"))
    resolved_duration = _clamp_duration(
        script, resolved_start, _as_int(duration_frames, "duration_frames")
    )
    return resolved_start, resolved_duration


def _camera_motion_keyframes(
    preset_id: str,
    anchor: dict[str, Any],
    start_frame: int,
    duration_frames: int,
) -> list[dict[str, Any]]:
    position = [float(anchor["position"][0]), float(anchor["position"][1]), float(anchor["position"][2])]
    look_at = [float(anchor["look_at"][0]), float(anchor["look_at"][1]), float(anchor["look_at"][2])]
    radius = max(_distance(position, look_at), 0.001)

    def sample(frame: int) -> dict[str, Any]:
        t = _progress(frame, start_frame, duration_frames)
        next_position = [position[0], position[1], position[2]]
        next_look_at = [look_at[0], look_at[1], look_at[2]]
        if preset_id in {"push_in", "pull_out"}:
            direction = _normalize(
                [look_at[0] - position[0], look_at[1] - position[1], look_at[2] - position[2]]
                if preset_id == "push_in"
                else [position[0] - look_at[0], position[1] - look_at[1], position[2] - look_at[2]]
            )
            offset = radius * 0.5 * t
            next_position = [
                position[index] + direction[index] * offset for index in range(3)
            ]
        elif preset_id in {"orbit_left", "orbit_right"}:
            angle = math.pi / 2 * t * (1 if preset_id == "orbit_left" else -1)
            dx = position[0] - look_at[0]
            dy = position[1] - look_at[1]
            cos = math.cos(angle)
            sin = math.sin(angle)
            next_position = [
                look_at[0] + dx * cos - dy * sin,
                look_at[1] + dx * sin + dy * cos,
                position[2],
            ]
        elif preset_id in {"pan_left", "pan_right"}:
            angle = math.pi / 3 * t * (1 if preset_id == "pan_left" else -1)
            dx = look_at[0] - position[0]
            dy = look_at[1] - position[1]
            cos = math.cos(angle)
            sin = math.sin(angle)
            next_look_at = [
                position[0] + dx * cos - dy * sin,
                position[1] + dx * sin + dy * cos,
                position[2],
            ]
        elif preset_id in {"crane_up", "crane_down"}:
            sign = 1 if preset_id == "crane_up" else -1
            rise = 1.2 * t * sign
            next_position = [position[0], position[1], position[2] + rise]
            next_look_at = [look_at[0], look_at[1], look_at[2] + rise * 0.5]
        return {"position": next_position, "look_at": next_look_at}

    return [
        {"frame": frame, **sample(frame)} for frame in _sample_frames(start_frame, duration_frames)
    ]


def _yaw_facing(from_position: list[float], to_position: list[float]) -> float:
    dx = float(to_position[0]) - float(from_position[0])
    dy = float(to_position[1]) - float(from_position[1])
    degrees = math.atan2(dx, dy) * 180.0 / math.pi
    return ((degrees % 360.0) + 360.0) % 360.0


def _lerp_yaw(start: float, end: float, t: float) -> float:
    delta = ((end - start + 540.0) % 360.0) - 180.0
    raw = start + delta * t
    return ((raw % 360.0) + 360.0) % 360.0


def _character_motion_keyframes(
    preset_id: str,
    anchor: dict[str, Any],
    target: list[float],
    start_frame: int,
    duration_frames: int,
    stop_distance: float = 1.2,
) -> list[dict[str, Any]]:
    if preset_id == "mark_talk":
        return [
            {
                "frame": start_frame,
                "position": [float(component) for component in anchor["position"]],
                "rotation_y": float(anchor["rotation_y"]),
                "action": "talk",
            }
        ]
    if preset_id == "turn_to":
        target_yaw = _yaw_facing(anchor["position"], target)
        return [
            {
                "frame": frame,
                "position": [float(component) for component in anchor["position"]],
                "rotation_y": round(
                    _lerp_yaw(
                        float(anchor["rotation_y"]),
                        target_yaw,
                        _progress(frame, start_frame, duration_frames),
                    ),
                    2,
                ),
                "action": anchor["action"],
            }
            for frame in _sample_frames(start_frame, duration_frames)
        ]

    anchor_position = [float(component) for component in anchor["position"]]
    if preset_id == "walk_to":
        destination: list[float] = [float(target[0]), float(target[1]), anchor_position[2]]
    elif preset_id == "approach":
        gap = math.hypot(
            float(target[0]) - anchor_position[0],
            float(target[1]) - anchor_position[1],
        )
        reach = max(0.0, stop_distance)
        if gap <= reach + 1e-6:
            destination = anchor_position
        else:
            ratio = (gap - reach) / gap
            destination = [
                anchor_position[0] + (float(target[0]) - anchor_position[0]) * ratio,
                anchor_position[1] + (float(target[1]) - anchor_position[1]) * ratio,
                anchor_position[2],
            ]
    else:
        raise DirectorMotionError("director_motion_preset_unknown", f"unknown preset {preset_id}")

    arrival_yaw = _yaw_facing(anchor_position, destination)
    frames = _sample_frames(start_frame, duration_frames)
    keyframes: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        t = _progress(frame, start_frame, duration_frames)
        is_landing = index == len(frames) - 1
        keyframes.append(
            {
                "frame": frame,
                "position": [
                    anchor_position[0] + (destination[0] - anchor_position[0]) * t,
                    anchor_position[1] + (destination[1] - anchor_position[1]) * t,
                    anchor_position[2],
                ],
                "rotation_y": round(_lerp_yaw(float(anchor["rotation_y"]), arrival_yaw, t), 2),
                "action": "stand" if is_landing else "walk",
            }
        )
    return keyframes


def expand_camera_motion_preset(
    script: SceneScriptRoot,
    *,
    camera_id: str,
    preset_id: str,
    start_frame: int,
    duration_frames: int,
) -> list[dict[str, Any]]:
    """Expand a camera motion intent into backend-compatible ops.

    The expansion emits ``add_keyframe`` ops only. Callers that need the
    camera to stay visible must separately add a shot covering the camera;
    this keeps preset math pure and lets the existing gate catch missing
    shots at script validation time.
    """
    if preset_id not in CAMERA_MOTION_PRESET_IDS:
        raise DirectorMotionError(
            "director_motion_preset_unknown", f"unknown camera preset {preset_id}"
        )
    camera = next((item for item in script.cameras if item.id == camera_id), None)
    if camera is None:
        raise DirectorMotionError(
            "director_motion_camera_missing", f"camera {camera_id} not found"
        )
    start_frame, duration_frames = _resolve_window(script, start_frame, duration_frames)
    anchor = _anchor_camera_keyframes(list(camera.keyframes), start_frame)
    return [
        {
            "op": "add_keyframe",
            "kind": "camera",
            "id": camera_id,
            "frame": keyframe["frame"],
            "position": keyframe["position"],
            "look_at": keyframe["look_at"],
        }
        for keyframe in _camera_motion_keyframes(
            preset_id, anchor, start_frame, duration_frames
        )
    ]


def expand_character_motion_preset(
    script: SceneScriptRoot,
    *,
    character_id: str,
    preset_id: str,
    target: list[float],
    start_frame: int,
    duration_frames: int,
    stop_distance: float = 1.2,
) -> list[dict[str, Any]]:
    """Expand a character blocking intent into backend-compatible ops."""
    if preset_id not in CHARACTER_MOTION_PRESET_IDS:
        raise DirectorMotionError(
            "director_motion_preset_unknown", f"unknown character preset {preset_id}"
        )
    character = next((item for item in script.characters if item.id == character_id), None)
    if character is None:
        raise DirectorMotionError(
            "director_motion_character_missing", f"character {character_id} not found"
        )
    target = _position(target, "target")
    start_frame, duration_frames = _resolve_window(script, start_frame, duration_frames)
    stop_distance = _as_float(stop_distance, "stop_distance")
    anchor = _anchor_character_keyframes(list(character.keyframes), start_frame)
    keyframes = _character_motion_keyframes(
        preset_id,
        anchor,
        target,
        start_frame,
        duration_frames,
        stop_distance,
    )
    return [
        {
            "op": "add_keyframe",
            "kind": "character",
            "id": character_id,
            "frame": keyframe["frame"],
            "position": keyframe["position"],
            "rotation_y": keyframe["rotation_y"],
            "action": keyframe["action"],
        }
        for keyframe in keyframes
    ]


def expand_director_motion(
    script: SceneScriptRoot,
    *,
    intent: str,
    target_id: str | None = None,
    preset_id: str,
    start_frame: int = 0,
    duration_frames: int = 15,
    target: list[float] | None = None,
    stop_distance: float = 1.2,
) -> dict[str, Any]:
    """Return an intent-level director operation batch.

    The result shape is intentionally small: the caller keeps the command,
    the expanded raw ops, the parameters that produced them, and any target
    object name in one place. This is the contract the director command bar
    will POST through ``/scene-3d/apply-operations`` and reuse for optimistic
    preview/rollback — which is why the parameters ride along: a batch that
    cannot be re-expanded from what it records is not a replayable record.
    """
    if intent not in {"camera_motion", "character_motion"}:
        raise DirectorMotionError(
            "director_motion_invalid", "intent must be camera_motion or character_motion"
        )
    family = INTENT_PRESET_FAMILIES[intent]
    if preset_id not in family:
        other = sorted(set(INTENT_PRESET_FAMILIES) - {intent})
        raise DirectorMotionError(
            "director_motion_preset_intent_mismatch",
            f"preset '{preset_id}' is not a {intent} preset; "
            f"{intent} expects one of {sorted(family)}"
            + (f" (did you mean intent '{other[0]}'?)" if other else ""),
        )
    if intent == "camera_motion":
        if not target_id:
            raise DirectorMotionError(
                "director_motion_target_missing", "camera_motion requires target_id"
            )
        start_frame, duration_frames = _resolve_window(script, start_frame, duration_frames)
        operations = expand_camera_motion_preset(
            script,
            camera_id=target_id,
            preset_id=preset_id,
            start_frame=start_frame,
            duration_frames=duration_frames,
        )
        batch: dict[str, Any] = {
            "intent": intent,
            "target": target_id,
            "preset_id": preset_id,
            "start_frame": start_frame,
            "duration_frames": duration_frames,
            "operations": operations,
        }
        return batch

    if not target_id:
        raise DirectorMotionError(
            "director_motion_target_missing", "character_motion requires target_id"
        )
    if target is None:
        raise DirectorMotionError(
            "director_motion_target_missing", "character_motion requires target position"
        )
    start_frame, duration_frames = _resolve_window(script, start_frame, duration_frames)
    stop_distance = _as_float(stop_distance, "stop_distance")
    operations = expand_character_motion_preset(
        script,
        character_id=target_id,
        preset_id=preset_id,
        target=target,
        start_frame=start_frame,
        duration_frames=duration_frames,
        stop_distance=stop_distance,
    )
    return {
        "intent": intent,
        "target": target_id,
        "preset_id": preset_id,
        "start_frame": start_frame,
        "duration_frames": duration_frames,
        "stop_distance": stop_distance,
        "operations": operations,
    }
