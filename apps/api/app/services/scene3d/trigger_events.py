"""When/then event triggers for director commands.

The director command bar's next layer: "wait for him to sit down, then the
light goes out". This module owns the pure expansion from a small
``when/then`` event table into ``add_keyframe`` ops that ride the existing
all-or-nothing gate.

The table is intentionally tiny and deterministic — the same trigger words
the LLM already knows from the CharacterAction enum plus a handful of
derived events ("arrive", "line_spoken"). A new trigger means adding one
entry here; the gate and the schema are unchanged.

Event shape
-----------
Each entry maps a named trigger to the ``CharacterKeyframe`` fields that
constitute its "done" state, plus the op a director would issue in the
``then`` clause. The expansion runs *before* the gate so the trigger is a
pure math-to-ops bridge, exactly like ``director_motion.py``.

Every rejection is a named ``TriggerError`` code, and every argument the
caller must supply is checked before anything is expanded: a trigger that
cannot fire is worse than a rejected one, because the director sees
nothing happen.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Trigger vocabulary
# ---------------------------------------------------------------------------
# Keys are the trigger names the LLM / director bar would emit.
# Values describe the "done" condition as a keyframe field check on the
# target character (or a camera shot boundary for "line_spoken").

#: Character-level trigger conditions.
#: ``frame_field`` is the keyframe field that signals the event fired.
#: ``value`` is the value that constitutes "done" (for actions) or
#: ``None`` (for "arrive" — any position change counts).
CHARACTER_TRIGGERS: dict[str, dict[str, Any]] = {
    # "He sat down" — action == "sit" at the sampled frame
    "sit": {
        "frame_field": "action",
        "value": "sit",
        "description": "character has seated (action == 'sit')",
    },
    # "He stood up" — action transitions stand→talk/gesture/walk
    "stand": {
        "frame_field": "action",
        "value": "stand",
        "description": "character is standing (action == 'stand')",
    },
    # "He arrived" — position matches target within epsilon
    "arrive": {
        "frame_field": "position",
        "value": None,  # caller supplies the target position
        "description": "character has reached the target position",
    },
    # "He turned to face X" — rotation_y matches the target yaw
    "face": {
        "frame_field": "rotation_y",
        "value": None,  # caller supplies the target yaw
        "description": "character has rotated to face the target",
    },
    # "He finished talking" — action transitions talk→stand
    "line_spoken": {
        "frame_field": "action",
        "value": "talk",
        "description": "character's dialogue line has been spoken (action == 'talk')",
    },
}

#: The op kinds that can appear in the ``then`` clause of a trigger.
#: A new op kind in this list must also be in the gate's ``OP_KINDS``.
THEN_OP_KINDS = frozenset(
    {
        "add_keyframe",   # "the light goes out at that moment"
        "set_camera",     # "cut to a close-up when he sits"
        "rotate_object",  # "swing the flag when he arrives"
        "scale_object",   # "the smoke grows when the door closes"
        "move_object",    # "the table slides back when he stands"
    }
)


class TriggerError(ValueError):
    """Raised when a when/then event cannot be expanded into valid ops."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


def _as_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TriggerError("trigger_target_invalid", f"{field} must be numeric")
    return float(value)


def _as_position(value: Any, field: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise TriggerError("trigger_target_invalid", f"{field} must be [x, y, z]")
    return [_as_float(component, f"{field}[{index}]") for index, component in enumerate(value)]


def _as_frame(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TriggerError("trigger_frame_invalid", f"{field} must be an integer frame")
    if value < 0:
        raise TriggerError("trigger_frame_invalid", f"{field} must be >= 0")
    return value


def _assert_frame_in_script(script: Any, frame: int, field: str, code: str) -> None:
    """Reject a frame past the scene's end.

    The keyframes land through the same gate as any other op, so a frame
    beyond the scene would either be rejected there as a cryptic schema
    error or, worse, be accepted and never play. Either way the director
    asked for a moment that does not exist — say so with the reason.
    """
    total_frames = getattr(script, "total_frames", None)
    if isinstance(total_frames, bool) or not isinstance(total_frames, int):
        return
    if frame > total_frames:
        raise TriggerError(
            code,
            f"{field} {frame} is past the scene's last frame ({total_frames})",
        )


def _character_ids(trigger_scene_script: Any) -> set[str]:
    """The character ids the script declares, object OR dict form.

    ``getattr`` alone silently answers "no characters" for a dict, which
    would fail every dict-shaped call with ``trigger_target_missing`` and
    send a caller hunting for a character that is right there.
    """
    characters = getattr(trigger_scene_script, "characters", None)
    if characters is None and isinstance(trigger_scene_script, dict):
        characters = trigger_scene_script.get("characters")
    ids: set[str] = set()
    for character in characters or []:
        if isinstance(character, dict):
            character_id = character.get("id")
        else:
            character_id = getattr(character, "id", None)
        if isinstance(character_id, str) and character_id:
            ids.add(character_id)
    return ids


# ---------------------------------------------------------------------------
# Expansion
# ---------------------------------------------------------------------------


def expand_trigger_event(
    *,
    trigger: str,
    trigger_target_id: str,
    trigger_scene_script: Any,
    trigger_frame: int,
    trigger_target_position: list[float] | None = None,
    trigger_target_yaw: float | None = None,
    then_ops: list[dict[str, Any]],
    then_frame: int,
) -> dict[str, Any]:
    """Expand a when/then trigger into a deterministic ops batch.

    Parameters
    ----------
    trigger:
        A key from ``CHARACTER_TRIGGERS``.
    trigger_target_id:
        The character whose action/position fires the trigger.
    trigger_scene_script:
        A ``SceneScriptRoot`` (or a dict with a ``characters`` list) used to
        validate that the trigger target exists.
    trigger_frame:
        The frame at which the trigger condition is evaluated.
    trigger_target_position:
        Required when ``trigger == "arrive"``; the position the character
        must have reached.
    trigger_target_yaw:
        Required when ``trigger == "face"``; the rotation-y the character
        must have turned to.
    then_ops:
        The ops the director wants to issue *at the moment the trigger
        fires*. Each op must have an ``op`` key in ``THEN_OP_KINDS``.
    then_frame:
        The frame the ``then`` ops are stamped with. Typically the same as
        ``trigger_frame`` (the trigger fires at that frame and the then-ops
        land in the same frame), but a director can also schedule them one
        frame later for a beat.

    Returns
    -------
    A dict with:
      - ``trigger``: the trigger name
      - ``trigger_frame``: the evaluation frame
      - ``then_frame``: the then-ops stamp
      - ``operations``: the validated then-ops list (ready for the gate)

    Raises ``TriggerError`` with a named code for every rejection: an
    unknown trigger, an unsupported then-op kind, a missing target
    argument, a target character the script does not declare, and a frame
    the scene does not contain.
    """
    if trigger not in CHARACTER_TRIGGERS:
        raise TriggerError(
            "trigger_unknown", f"unknown trigger '{trigger}'; known: {sorted(CHARACTER_TRIGGERS)}"
        )

    # Validate then-ops have a legal op kind.
    for index, op in enumerate(then_ops):
        if not isinstance(op, dict):
            raise TriggerError(
                "then_op_not_object", f"then_ops[{index}] is not an object"
            )
        op_kind = op.get("op")
        if op_kind not in THEN_OP_KINDS:
            raise TriggerError(
                "then_op_unknown",
                f"then_ops[{index}].op '{op_kind}' is not a supported then-op; "
                f"known: {sorted(THEN_OP_KINDS)}",
            )

    # Trigger-specific requirements.
    if trigger == "arrive" and trigger_target_position is None:
        raise TriggerError(
            "trigger_target_missing",
            "'arrive' requires trigger_target_position",
        )
    if trigger == "face" and trigger_target_yaw is None:
        raise TriggerError(
            "trigger_target_missing",
            "'face' requires trigger_target_yaw",
        )
    resolved_position: list[float] | None = None
    if trigger_target_position is not None:
        resolved_position = _as_position(trigger_target_position, "trigger_target_position")
    resolved_yaw = (
        None if trigger_target_yaw is None else _as_float(trigger_target_yaw, "trigger_target_yaw")
    )

    # Frames: whole, non-negative, and inside the scene.
    resolved_trigger_frame = _as_frame(trigger_frame, "trigger_frame")
    resolved_then_frame = _as_frame(then_frame, "then_frame")
    _assert_frame_in_script(
        trigger_scene_script, resolved_trigger_frame, "trigger_frame", "trigger_frame_out_of_range"
    )
    _assert_frame_in_script(
        trigger_scene_script, resolved_then_frame, "then_frame", "then_frame_out_of_range"
    )

    # Validate trigger target exists in the scene script.
    if trigger_target_id not in _character_ids(trigger_scene_script):
        raise TriggerError(
            "trigger_target_missing",
            f"character '{trigger_target_id}' not found in the scene script",
        )

    return {
        "trigger": trigger,
        "trigger_target_id": trigger_target_id,
        "trigger_frame": resolved_trigger_frame,
        "trigger_target_position": resolved_position,
        "trigger_target_yaw": resolved_yaw,
        "then_frame": resolved_then_frame,
        # Copies, not references: the caller keeps the request body it sent
        # and must be free to mutate it without editing a returned batch.
        "operations": [dict(op) for op in then_ops],
    }


def trigger_frame_to_keyframe(
    event: dict[str, Any],
    character_id: str,
) -> list[dict[str, Any]]:
    """Convert a trigger event into the character keyframes that mark the
    "done" state, so a caller can add them to the scene *before* the
    then-ops fire.

    For ``arrive`` and ``face`` the keyframe is the character's pose at the
    trigger frame (position or rotation matches the target). For the
    action-based triggers the keyframe is the action change at the trigger
    frame.

    This is the piece that makes the trigger *playable*: the director
    adds the keyframe to the character's track, and the playback engine
    interpolates toward it, so the "sit down" animation actually happens.

    A trigger whose target argument is missing yields a named error rather
    than an empty list — an empty list would look like "the trigger needs
    no pose", and the then-ops would fire on a character who never moved.
    """
    trigger = event.get("trigger")
    if trigger not in CHARACTER_TRIGGERS:
        raise TriggerError(
            "trigger_unknown", f"unknown trigger '{trigger}'; known: {sorted(CHARACTER_TRIGGERS)}"
        )
    frame = _as_frame(event.get("trigger_frame"), "trigger_frame")

    keyframes: list[dict[str, Any]] = []

    if trigger == "arrive":
        target_position = event.get("trigger_target_position")
        if target_position is None:
            raise TriggerError(
                "trigger_target_missing",
                "'arrive' requires trigger_target_position",
            )
        keyframes.append(
            {
                "op": "add_keyframe",
                "kind": "character",
                "id": character_id,
                "frame": frame,
                "position": list(_as_position(target_position, "trigger_target_position")),
                "action": "stand",
            }
        )
    elif trigger == "face":
        target_yaw = event.get("trigger_target_yaw")
        if target_yaw is None:
            raise TriggerError(
                "trigger_target_missing",
                "'face' requires trigger_target_yaw",
            )
        keyframes.append(
            {
                "op": "add_keyframe",
                "kind": "character",
                "id": character_id,
                "frame": frame,
                "rotation_y": _as_float(target_yaw, "trigger_target_yaw"),
            }
        )
    elif trigger == "sit":
        keyframes.append(
            {
                "op": "add_keyframe",
                "kind": "character",
                "id": character_id,
                "frame": frame,
                "action": "sit",
            }
        )
    elif trigger == "stand":
        keyframes.append(
            {
                "op": "add_keyframe",
                "kind": "character",
                "id": character_id,
                "frame": frame,
                "action": "stand",
            }
        )
    elif trigger == "line_spoken":
        keyframes.append(
            {
                "op": "add_keyframe",
                "kind": "character",
                "id": character_id,
                "frame": frame,
                "action": "talk",
            }
        )

    return keyframes
