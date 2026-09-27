"""SceneScript tool service: structured scene operations -> canonical SceneScript.

The single validation-and-application point for the white-model design mode.
An agent (the ``video_agent_3d_white_model`` skill) or a future editor emits
*operations* — ``add_environment``/``move_object``/``set_camera``/… — not whole
SceneScripts, so every step is previewable, replayable, and undoable one op at
a time. This service is the gate:

- every op is validated BEFORE anything is applied; a batch with a single
  invalid op is rejected whole (a half-built scene is harder to reason about
  than a rejected one), with per-op violations listed for the caller to
  repair — the same structured-submission discipline the agent-tools path
  already uses;
- ops may only name objects/kinds the SceneScript schema knows (enum-checked
  via ``typing.get_args``, so a new backend kind needs no edit here);
- ``mcp_request`` ops are the extension vocabulary: they execute against the
  Blender MCP client when available and are REPORTED (the geometry lives in
  Blender — SceneScript's ``extra="forbid"`` models cannot carry vendor
  geometry, and the video-prompt pipeline must keep consuming one format).
  Without a client they are rejected with ``mcp_unavailable`` — a queryable
  degradation, never a silent skip.

SceneScript's schema has no version field (``extra="forbid"``), so version
management stays at the node level: the caller persists the returned script
under the node's ETag optimistic lock and stamps its own revision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, get_args

from app.schemas.scene_script import (
    CameraKeyframe,
    CharacterAction,
    CharacterKeyframe,
    EnvironmentType,
    PropType,
    SceneCamera,
    SceneCharacter,
    SceneEnvironmentObject,
    SceneProp,
    SceneScriptRoot,
    SceneShot,
    ShotType,
)

# Scene bounds (mirrors the MCP client's client-side bbox).
BBOX_HALF_EXTENT = 50.0
BBOX_MAX_HEIGHT = 30.0

OP_KINDS = (
    "add_environment",
    "add_prop",
    "add_character",
    "add_camera",
    "add_shot",
    "set_shot_camera",
    "move_object",
    "rotate_object",
    "scale_object",
    "set_camera",
    "add_keyframe",
    "remove_object",
    "mcp_request",
)

# Ops whose ``frame`` field writes a keyframe on a time-capable target.
_TIMED_OBJECT_OPS = ("move_object", "rotate_object", "set_camera")

# Collected kinds a caller may name in move/rotate/scale/remove ops.
TARGET_KINDS = ("environment", "prop", "character", "camera")


class SceneOperationError(Exception):
    """A rejected batch: nothing was applied; violations explain why."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        violations: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.violations = violations or []


@dataclass
class SceneOperationResult:
    """Outcome of an applied batch."""

    scene_script: SceneScriptRoot
    applied: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mcp_results: list[dict[str, Any]] = field(default_factory=list)


def _position(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        return [float(component) for component in value]
    except (TypeError, ValueError):
        return None


def _in_bounds(position: list[float]) -> bool:
    x, y, z = position
    return abs(x) <= BBOX_HALF_EXTENT and abs(y) <= BBOX_HALF_EXTENT and 0 <= z <= BBOX_MAX_HEIGHT


def _enum_members(enum_type: Any) -> tuple[str, ...]:
    return tuple(str(member) for member in get_args(enum_type))


def _next_id(existing: list[str], prefix: str) -> str:
    index = 1
    while f"{prefix}_{index}" in existing:
        index += 1
    return f"{prefix}_{index}"


def _is_frame_number(value: Any) -> bool:
    """A non-negative int (bool is excluded: ``True`` is not a frame)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _ranges_overlap(
    start: int, end: int, other_start: int, other_end: int
) -> bool:
    """Whether two inclusive frame ranges share at least one frame."""
    return start <= other_end and other_start <= end


class SceneScriptToolService:
    """Validates and applies structured scene operations to a SceneScript."""

    @staticmethod
    def _as_scene_script(value: SceneScriptRoot | dict[str, Any]) -> SceneScriptRoot:
        """Accept a validated model or a raw dict (endpoint/agent JSON path).

        A malformed dict fails closed here rather than half-applying ops onto
        a script that was never a script.
        """

        if isinstance(value, SceneScriptRoot):
            return value
        try:
            return SceneScriptRoot.model_validate(value)
        except Exception as exc:
            raise SceneOperationError(
                "scene_script_invalid",
                f"The SceneScript failed schema validation: {str(exc)[:300]}",
                violations=[{"path": "scene_script", "code": "schema_validation"}],
            ) from exc

    def apply_operations(
        self,
        scene_script: SceneScriptRoot | dict[str, Any],
        operations: list[dict[str, Any]],
        *,
        mcp_client: Any | None = None,
    ) -> SceneOperationResult:
        if not isinstance(operations, list) or not operations:
            raise SceneOperationError(
                "scene_operations_required",
                "At least one scene operation is required.",
            )
        scene_script = self._as_scene_script(scene_script)

        violations: list[dict[str, Any]] = []
        mcp_failures: list[dict[str, Any]] = []
        applied: list[dict[str, Any]] = []
        warnings: list[str] = []
        mcp_results: list[dict[str, Any]] = []

        # Validate-and-apply against the IN-PROGRESS script, so a batch may
        # reference objects its own earlier ops create ("add the character,
        # then move it"). Atomicity is preserved by the working copy: any
        # violation discards it, so a rejected batch applies nothing.
        working = scene_script.model_copy(deep=True)
        for index, operation in enumerate(operations):
            if not isinstance(operation, dict):
                violations.append(
                    {"path": f"operations[{index}]", "code": "operation_not_object"}
                )
                continue
            op_kind = operation.get("op")
            if op_kind not in OP_KINDS:
                violations.append(
                    {
                        "path": f"operations[{index}].op",
                        "code": "operation_kind_unsupported",
                        "message": f"unknown op '{op_kind}'",
                    }
                )
                continue
            op_violations = self._validate_operation(working, operation, index)
            if op_violations:
                violations.extend(op_violations)
                continue
            if op_kind == "mcp_request":
                result = self._run_mcp_request(operation, mcp_client)
                if result.get("rejected"):
                    mcp_failures.append(
                        {
                            "path": f"operations[{index}]",
                            "code": result["code"],
                            "message": result.get("message"),
                            "tool": result.get("tool"),
                            "target": result.get("target"),
                        }
                    )
                    continue
                mcp_results.append(result)
                applied.append({"index": index, "op": op_kind, "target": self._target_of(operation)})
                continue
            working = self._apply_operation(working, operation)
            applied.append({"index": index, "op": op_kind, "target": self._target_of(operation)})

        if violations:
            raise SceneOperationError(
                "scene_operations_invalid",
                f"{len(violations)} operation(s) failed validation; nothing was applied.",
                violations=violations,
            )

        # A runtime MCP failure rejects the batch: the caller asked for
        # geometry that did not happen, so the script it would receive is a
        # lie. Nothing was persisted — the caller retries or drops the op.
        if mcp_failures:
            raise SceneOperationError(
                "scene_operations_mcp_failed",
                f"{len(mcp_failures)} MCP extension op(s) failed; nothing was applied.",
                violations=mcp_failures,
            )

        # The final schema validation is the backstop: an op sequence that
        # individually validates must still produce a legal SceneScript.
        try:
            result_script = SceneScriptRoot.model_validate(working.model_dump(mode="json"))
        except Exception as exc:
            raise SceneOperationError(
                "scene_script_invalid_after_apply",
                f"Applying the operations produced an invalid SceneScript: {str(exc)[:300]}",
                violations=[{"path": "scene_script", "code": "schema_validation"}],
            ) from exc

        return SceneOperationResult(
            scene_script=result_script,
            applied=applied,
            warnings=warnings,
            mcp_results=mcp_results,
        )

    # -- validation ------------------------------------------------------------

    def _validate_operation(
        self, script: SceneScriptRoot, operation: dict[str, Any], index: int
    ) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []
        kind = operation["op"]

        def reject(code: str, message: str | None = None, path: str | None = None) -> None:
            entry: dict[str, Any] = {"path": path or f"operations[{index}]", "code": code}
            if message:
                entry["message"] = message
            violations.append(entry)

        if kind in {"add_environment", "add_prop", "add_character"}:
            enum_type = {
                "add_environment": EnvironmentType,
                "add_prop": PropType,
            }.get(kind)
            object_type = operation.get("type")
            if enum_type is not None and object_type not in _enum_members(enum_type):
                reject(
                    "object_type_unsupported",
                    f"type '{object_type}' is not a known {enum_type.__name__}",
                    path=f"operations[{index}].type",
                )
            position = _position(operation.get("position"))
            if position is None:
                reject("position_invalid", "position must be [x, y, z]", path=f"operations[{index}].position")
            elif not _in_bounds(position):
                reject(
                    "position_out_of_bounds",
                    f"position {position} is outside the scene bounds",
                    path=f"operations[{index}].position",
                )
            if kind == "add_character":
                action = operation.get("action", "stand")
                if action not in _enum_members(CharacterAction):
                    reject(
                        "action_unsupported",
                        f"action '{action}' is not a known CharacterAction",
                        path=f"operations[{index}].action",
                    )
            return violations

        if kind == "add_camera":
            shot_type = operation.get("shot_type", "wide")
            if shot_type not in _enum_members(ShotType):
                reject(
                    "shot_type_unsupported",
                    f"shot_type '{shot_type}' is not a known ShotType",
                    path=f"operations[{index}].shot_type",
                )
            position = _position(operation.get("position"))
            if position is None or not _in_bounds(position):
                reject("position_invalid", None, path=f"operations[{index}].position")
            look_at = _position(operation.get("look_at"))
            if look_at is None:
                reject("look_at_invalid", None, path=f"operations[{index}].look_at")
            # A camera coming on later than frame 0 places its first keyframe
            # there: the schema requires every camera keyframe to fall inside a
            # shot that uses it, so "side angle from frame 60" is one camera
            # keyframe at 60 plus a shot covering 60 — not a keyframe at 0.
            frame = operation.get("frame", 0)
            if not _is_frame_number(frame) or frame > script.total_frames:
                reject(
                    "frame_invalid",
                    f"frame must be an integer in [0, {script.total_frames}]",
                    path=f"operations[{index}].frame",
                )
            return violations

        if kind == "add_shot":
            # A shot is a time range bound to an EXISTING camera: the camera
            # is where the look lives, the shot is when it is on screen. An
            # agent that adds a camera without a shot has added nothing the
            # renderer can show (the consistency gate flags camera_unused).
            camera_id = operation.get("camera")
            if not isinstance(camera_id, str) or not camera_id.strip():
                reject("shot_camera_required", None, path=f"operations[{index}].camera")
            elif not self._object_exists(script, "camera", camera_id):
                reject(
                    "target_not_found",
                    f"no camera '{camera_id}' in the SceneScript",
                    path=f"operations[{index}].camera",
                )
            start = operation.get("start_frame")
            end = operation.get("end_frame")
            if not _is_frame_number(start):
                reject(
                    "frame_invalid",
                    "start_frame must be a non-negative integer",
                    path=f"operations[{index}].start_frame",
                )
            if not _is_frame_number(end):
                reject(
                    "frame_invalid",
                    "end_frame must be a non-negative integer",
                    path=f"operations[{index}].end_frame",
                )
            if _is_frame_number(start) and _is_frame_number(end):
                if end <= start:
                    reject(
                        "shot_range_invalid",
                        f"end_frame ({end}) must be greater than start_frame ({start})",
                        path=f"operations[{index}].end_frame",
                    )
                elif end > script.total_frames:
                    reject(
                        "frame_out_of_range",
                        f"end_frame {end} exceeds the scene's total frames "
                        f"({script.total_frames})",
                        path=f"operations[{index}].end_frame",
                    )
                else:
                    overlap = next(
                        (
                            shot.id
                            for shot in script.shots
                            if _ranges_overlap(start, end, shot.start_frame, shot.end_frame)
                        ),
                        None,
                    )
                    if overlap is not None:
                        reject(
                            "shot_range_overlaps",
                            f"range [{start}, {end}] overlaps shot '{overlap}'; "
                            "shots may not share frames",
                            path=f"operations[{index}].start_frame",
                        )
            shot_id = operation.get("id")
            if shot_id is not None:
                if not isinstance(shot_id, str) or not shot_id.strip():
                    reject("target_id_required", None, path=f"operations[{index}].id")
                elif any(shot.id == shot_id for shot in script.shots):
                    reject(
                        "object_id_conflict",
                        f"a shot with id '{shot_id}' already exists",
                        path=f"operations[{index}].id",
                    )
            description = operation.get("description")
            if description is not None and not isinstance(description, str):
                reject(
                    "description_invalid",
                    "description must be a string",
                    path=f"operations[{index}].description",
                )
            return violations

        if kind == "set_shot_camera":
            shot_id = operation.get("id") or operation.get("target")
            if not isinstance(shot_id, str) or not shot_id.strip():
                reject("target_id_required", None, path=f"operations[{index}].id")
                return violations
            if not any(shot.id == shot_id for shot in script.shots):
                reject(
                    "target_not_found",
                    f"no shot '{shot_id}' in the SceneScript",
                    path=f"operations[{index}].id",
                )
            camera_id = operation.get("camera")
            if not isinstance(camera_id, str) or not camera_id.strip():
                reject("shot_camera_required", None, path=f"operations[{index}].camera")
            elif not self._object_exists(script, "camera", camera_id):
                reject(
                    "target_not_found",
                    f"no camera '{camera_id}' in the SceneScript",
                    path=f"operations[{index}].camera",
                )
            return violations

        if kind in {"move_object", "rotate_object", "scale_object", "set_camera", "add_keyframe", "remove_object"}:
            target_kind = operation.get("kind")
            if target_kind not in TARGET_KINDS:
                reject(
                    "target_kind_unsupported",
                    f"kind '{target_kind}' is not one of {TARGET_KINDS}",
                    path=f"operations[{index}].kind",
                )
                return violations
            # A camera has no rotation of its own: it aims through look_at.
            # The old application wrote keyframes[0].rotation_y, which
            # CameraKeyframe (extra="forbid") does not have — the op reported
            # success and changed nothing. Reject instead of lying.
            if kind == "rotate_object" and target_kind == "camera":
                reject(
                    "rotation_not_supported",
                    "cameras aim via position/look_at, not rotation_y; use set_camera",
                    path=f"operations[{index}].kind",
                )
                return violations
            target_id = operation.get("id") or operation.get("target")
            if not isinstance(target_id, str) or not target_id.strip():
                reject("target_id_required", None, path=f"operations[{index}].id")
                return violations
            if not self._object_exists(script, target_kind, target_id):
                reject(
                    "target_not_found",
                    f"no {target_kind} '{target_id}' in the SceneScript",
                    path=f"operations[{index}].id",
                )
                return violations
            if kind == "move_object" or (kind == "set_camera" and operation.get("position")):
                position = _position(operation.get("position"))
                if position is None or not _in_bounds(position):
                    reject("position_invalid", None, path=f"operations[{index}].position")
            if (
                kind == "set_camera"
                and operation.get("look_at") is not None
                and _position(operation.get("look_at")) is None
            ):
                reject("look_at_invalid", None, path=f"operations[{index}].look_at")
            # ``frame`` turns a restage into a beat: the op writes a keyframe
            # at that frame instead of rewriting frame 0. Only time-capable
            # targets accept it — environment/props have no keyframes in the
            # schema, and a character's scale is appearance, not motion.
            frame = operation.get("frame")
            if frame is not None:
                if kind == "scale_object":
                    reject(
                        "frame_not_supported",
                        "scale is not a per-frame property; drop 'frame'",
                        path=f"operations[{index}].frame",
                    )
                elif kind in _TIMED_OBJECT_OPS and target_kind in ("environment", "prop"):
                    reject(
                        "frame_not_supported",
                        f"{target_kind} objects have no keyframes in the schema; "
                        "only characters and cameras animate",
                        path=f"operations[{index}].frame",
                    )
                elif (
                    kind in _TIMED_OBJECT_OPS
                    and (not _is_frame_number(frame) or frame > script.total_frames)
                ):
                    reject(
                        "frame_invalid",
                        f"frame must be an integer in [0, {script.total_frames}]",
                        path=f"operations[{index}].frame",
                    )
            if kind == "add_keyframe":
                frame = operation.get("frame")
                if not isinstance(frame, int) or isinstance(frame, bool) or frame < 0:
                    reject("frame_invalid", "frame must be a non-negative integer", path=f"operations[{index}].frame")
                elif frame > script.total_frames:
                    reject(
                        "frame_out_of_range",
                        f"frame {frame} exceeds total frames ({script.total_frames})",
                        path=f"operations[{index}].frame",
                    )
            return violations

        if kind == "mcp_request":
            tool = operation.get("tool")
            if not isinstance(tool, str) or not tool.strip():
                reject("mcp_tool_required", None, path=f"operations[{index}].tool")
            arguments = operation.get("arguments", {})
            if arguments is not None and not isinstance(arguments, dict):
                reject("mcp_arguments_invalid", None, path=f"operations[{index}].arguments")
            return violations

        return violations

    def _object_exists(self, script: SceneScriptRoot, kind: str, object_id: str) -> bool:
        if kind == "environment":
            return any(obj.id == object_id for obj in script.environment)
        if kind == "prop":
            return any(obj.id == object_id for obj in script.props)
        if kind == "character":
            return any(obj.id == object_id for obj in script.characters)
        if kind == "camera":
            return any(obj.id == object_id for obj in script.cameras)
        return False

    # -- application -----------------------------------------------------------

    @staticmethod
    def _upsert_character_keyframe(
        character: SceneCharacter,
        frame: int,
        *,
        position: list[float] | None = None,
        rotation_y: float | None = None,
        action: str | None = None,
    ) -> None:
        """Write a character keyframe at ``frame`` (update, never duplicate).

        Omitted fields inherit from frame 0, the single rule every time-aware
        op shares (``add_keyframe`` and the ``frame`` forms of move/rotate).
        One rule matters because the preview's interpolation forward-inherits:
        a keyframe inserted at frame 90 without a rotation must not reset the
        character's facing to the frame-0 value at that moment — and inheriting
        from frame 0 is exactly what the existing contract documents.
        """

        base = character.keyframes[0]
        existing = next((kf for kf in character.keyframes if kf.frame == frame), None)
        if existing is not None:
            existing.position = list(base.position if position is None else position)
            existing.rotation_y = (
                base.rotation_y if rotation_y is None else rotation_y
            )
            existing.action = (base.action or "stand") if action is None else action
            return
        character.keyframes.append(
            CharacterKeyframe(
                frame=frame,
                position=list(base.position if position is None else position),
                rotation_y=base.rotation_y if rotation_y is None else rotation_y,
                action=(base.action or "stand") if action is None else action,
            )
        )
        character.keyframes.sort(key=lambda kf: kf.frame)

    @staticmethod
    def _upsert_camera_keyframe(
        camera: SceneCamera,
        frame: int,
        *,
        position: list[float] | None = None,
        look_at: list[float] | None = None,
    ) -> None:
        """Write a camera keyframe at ``frame`` (update, never duplicate).

        Same inheritance rule as characters; a camera's aim is its ``look_at``
        target, so a position-only move keeps the current aim.
        """

        base = camera.keyframes[0]
        existing = next((kf for kf in camera.keyframes if kf.frame == frame), None)
        if existing is not None:
            existing.position = list(base.position if position is None else position)
            existing.look_at = list(base.look_at if look_at is None else look_at)
            return
        camera.keyframes.append(
            CameraKeyframe(
                frame=frame,
                position=list(base.position if position is None else position),
                look_at=list(base.look_at if look_at is None else look_at),
            )
        )
        camera.keyframes.sort(key=lambda kf: kf.frame)

    def _target_of(self, operation: dict[str, Any]) -> str | None:
        for key in ("id", "target"):
            value = operation.get(key)
            if isinstance(value, str):
                return value
        return None

    def _apply_operation(
        self, script: SceneScriptRoot, operation: dict[str, Any]
    ) -> SceneScriptRoot:
        kind = operation["op"]
        target_id = operation.get("id") or operation.get("target")

        if kind == "add_environment":
            object_id = operation.get("id") or _next_id(
                [obj.id for obj in script.environment], "env"
            )
            script.environment.append(
                SceneEnvironmentObject(
                    id=object_id,
                    type=operation["type"],
                    position=[float(v) for v in operation["position"]],
                    scale=float(operation.get("scale", 1.0)),
                    rotation_y=float(operation.get("rotation_y", 0.0)),
                )
            )
            return script

        if kind == "add_prop":
            object_id = operation.get("id") or _next_id([obj.id for obj in script.props], "prop")
            script.props.append(
                SceneProp(
                    id=object_id,
                    type=operation["type"],
                    position=[float(v) for v in operation["position"]],
                    scale=float(operation.get("scale", 1.0)),
                    rotation_y=float(operation.get("rotation_y", 0.0)),
                )
            )
            return script

        if kind == "add_character":
            object_id = operation.get("id") or _next_id(
                [obj.id for obj in script.characters], "char"
            )
            script.characters.append(
                SceneCharacter(
                    id=object_id,
                    type="lowpoly_human",
                    appearance={
                        "color": str(operation.get("color", "#8B4513")),
                        "height": float(operation.get("height", 1.7)),
                        "scale": float(operation.get("scale", 1.0)),
                    },
                    keyframes=[
                        {
                            "frame": 0,
                            "position": [float(v) for v in operation["position"]],
                            "rotation_y": float(operation.get("rotation_y", 0.0)),
                            "action": operation.get("action", "stand"),
                        }
                    ],
                )
            )
            return script

        if kind == "add_camera":
            object_id = operation.get("id") or _next_id(
                [obj.id for obj in script.cameras], "cam"
            )
            script.cameras.append(
                SceneCamera(
                    id=object_id,
                    shot_type=operation.get("shot_type", "wide"),
                    keyframes=[
                        {
                            "frame": int(operation.get("frame", 0)),
                            "position": [float(v) for v in operation["position"]],
                            "look_at": [float(v) for v in operation["look_at"]],
                        }
                    ],
                )
            )
            return script

        if kind == "add_shot":
            shot_id = operation.get("id") or _next_id(
                [shot.id for shot in script.shots], "shot"
            )
            script.shots.append(
                SceneShot(
                    id=shot_id,
                    camera=str(operation["camera"]),
                    start_frame=int(operation["start_frame"]),
                    end_frame=int(operation["end_frame"]),
                    description=str(operation.get("description") or ""),
                )
            )
            # Chronological order keeps the render schedule and the workbench's
            # shot rail stable regardless of the order ops arrived in.
            script.shots.sort(key=lambda shot: shot.start_frame)
            return script

        if kind == "set_shot_camera":
            shot = next(
                (item for item in script.shots if item.id == target_id),
                None,
            )
            if shot is not None:
                shot.camera = str(operation["camera"])
            return script

        if kind == "move_object" and _is_frame_number(operation.get("frame")):
            frame = int(operation["frame"])
            target_kind = operation.get("kind")
            if target_kind == "character":
                character = next(
                    (char for char in script.characters if char.id == target_id),
                    None,
                )
                if character is not None:
                    self._upsert_character_keyframe(
                        character,
                        frame,
                        position=[float(v) for v in operation["position"]],
                    )
            elif target_kind == "camera":
                camera = next(
                    (cam for cam in script.cameras if cam.id == target_id),
                    None,
                )
                if camera is not None:
                    self._upsert_camera_keyframe(
                        camera,
                        frame,
                        position=[float(v) for v in operation["position"]],
                    )
            return script

        if kind == "rotate_object" and _is_frame_number(operation.get("frame")):
            frame = int(operation["frame"])
            # Cameras are rejected at validation (no rotation_y on the schema).
            character = next(                (char for char in script.characters if char.id == target_id),
                None,
            )
            if character is not None:
                self._upsert_character_keyframe(
                    character,
                    frame,
                    rotation_y=float(operation["rotation_y"]),
                )
            return script

        if kind == "move_object":
            position = [float(v) for v in operation["position"]]
            for obj in script.environment:
                if obj.id == target_id:
                    obj.position = position
            for obj in script.props:
                if obj.id == target_id:
                    obj.position = position
            for character in script.characters:
                if character.id == target_id:
                    character.keyframes[0].position = position
            for camera in script.cameras:
                if camera.id == target_id:
                    camera.keyframes[0].position = position
            return script

        if kind == "rotate_object":
            rotation = float(operation["rotation_y"])
            for obj in script.environment:
                if obj.id == target_id:
                    obj.rotation_y = rotation
            for obj in script.props:
                if obj.id == target_id:
                    obj.rotation_y = rotation
            for character in script.characters:
                if character.id == target_id:
                    character.keyframes[0].rotation_y = rotation
            return script

        if kind == "scale_object":
            scale = float(operation["scale"])
            for obj in script.environment:
                if obj.id == target_id:
                    obj.scale = scale
            for obj in script.props:
                if obj.id == target_id:
                    obj.scale = scale
            for character in script.characters:
                if character.id == target_id:
                    character.appearance.scale = scale
            return script

        if kind == "set_camera" and _is_frame_number(operation.get("frame")):
            frame = int(operation["frame"])
            camera = next(
                (cam for cam in script.cameras if cam.id == target_id),
                None,
            )
            if camera is not None:
                self._upsert_camera_keyframe(
                    camera,
                    frame,
                    position=(
                        [float(v) for v in operation["position"]]
                        if operation.get("position") is not None
                        else None
                    ),
                    look_at=(
                        [float(v) for v in operation["look_at"]]
                        if operation.get("look_at") is not None
                        else None
                    ),
                )
                if operation.get("shot_type"):
                    camera.shot_type = operation["shot_type"]
            return script

        if kind == "set_camera":
            camera = next(
                (cam for cam in script.cameras if cam.id == target_id),
                None,
            )
            if camera is not None:
                if operation.get("position") is not None:
                    camera.keyframes[0].position = [float(v) for v in operation["position"]]
                if operation.get("look_at") is not None:
                    camera.keyframes[0].look_at = [float(v) for v in operation["look_at"]]
                if operation.get("shot_type"):
                    camera.shot_type = operation["shot_type"]
            return script
        if kind == "add_keyframe":
            target_kind = operation["kind"]
            frame = int(operation["frame"])
            if target_kind == "character":
                character = next(
                    (char for char in script.characters if char.id == target_id),
                    None,
                )
                if character is not None:
                    self._upsert_character_keyframe(
                        character,
                        frame,
                        position=(
                            [float(v) for v in operation["position"]]
                            if operation.get("position") is not None
                            else None
                        ),
                        rotation_y=(
                            float(operation["rotation_y"])
                            if operation.get("rotation_y") is not None
                            else None
                        ),
                        action=operation.get("action"),
                    )
            elif target_kind == "camera":
                camera = next(
                    (cam for cam in script.cameras if cam.id == target_id),
                    None,
                )
                if camera is not None:
                    self._upsert_camera_keyframe(
                        camera,
                        frame,
                        position=(
                            [float(v) for v in operation["position"]]
                            if operation.get("position") is not None
                            else None
                        ),
                        look_at=(
                            [float(v) for v in operation["look_at"]]
                            if operation.get("look_at") is not None
                            else None
                        ),
                    )
            return script

        if kind == "remove_object":
            target_kind = operation["kind"]
            target = target_id
            if target_kind == "environment":
                script.environment = [obj for obj in script.environment if obj.id != target]
            elif target_kind == "prop":
                script.props = [obj for obj in script.props if obj.id != target]
            elif target_kind == "character":
                script.characters = [obj for obj in script.characters if obj.id != target]
                script.speech_bindings = [
                    binding for binding in script.speech_bindings if binding.character != target
                ]
            elif target_kind == "camera":
                script.cameras = [obj for obj in script.cameras if obj.id != target]
                script.shots = [shot for shot in script.shots if shot.camera != target]
            return script

        return script

    # -- MCP extension ops -----------------------------------------------------

    def _run_mcp_request(
        self, operation: dict[str, Any], mcp_client: Any | None
    ) -> dict[str, Any]:
        tool = str(operation.get("tool") or "")
        arguments = operation.get("arguments") or {}
        target = operation.get("target") or operation.get("id")
        if mcp_client is None:
            return {
                "rejected": True,
                "code": "mcp_unavailable",
                "message": (
                    f"No Blender MCP client is configured; the '{tool}' extension op "
                    "was not executed. SceneScript-native ops still applied in this batch."
                ),
                "tool": tool,
                "target": target,
            }
        try:
            result = mcp_client.call_tool(tool, arguments)
        except Exception as exc:  # noqa: BLE001 - reported, never crashes the batch.
            code = getattr(exc, "code", "mcp_tool_error")
            return {
                "rejected": True,
                "code": str(code),
                "message": str(exc)[:300],
                "tool": tool,
                "target": target,
            }
        return {
            "tool": tool,
            "target": target,
            "arguments": arguments,
            "is_error": bool(result.get("isError")),
            # The geometry lives in Blender; only the outcome travels back.
            "content": result.get("content"),
        }
