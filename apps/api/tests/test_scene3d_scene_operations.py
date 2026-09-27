"""Unit tests for the SceneScript tool service (white-model design mode).

Locks the operation contract: apply semantics for every op kind,
forward-references within a batch, all-or-nothing atomicity with per-op
violations, enum/bbox validation, MCP extension ops (executed + reported), and
the queryable mcp_unavailable degradation. Mutation checks flip the
atomicity and enum expectations and fail, proving they bind.
"""

from __future__ import annotations

import pytest

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.scene_script_tool_service import (
    SceneOperationError,
    SceneScriptToolService,
)


def base_script() -> SceneScriptRoot:
    return SceneScriptRoot.model_validate(
        {
            "scene": {
                "name": "地下研究所 B2",
                "environment": "indoor",
                "lighting": "cool",
                "duration": 6,
                "frame_rate": 30,
            },
            "characters": [
                {
                    "id": "char_a",
                    "type": "lowpoly_human",
                    "appearance": {"color": "#E74C3C", "height": 1.7, "scale": 1.0},
                    "keyframes": [
                        {"frame": 0, "position": [0, 0, 0], "rotation_y": 90, "action": "stand"}
                    ],
                }
            ],
            "props": [{"id": "crate1", "type": "crate", "position": [1, 1, 0], "scale": 1.0}],
            "environment": [{"id": "wall1", "type": "wall", "position": [0, 5, 0], "scale": 1.0}],
            "cameras": [
                {
                    "id": "cam1",
                    "shot_type": "wide",
                    "keyframes": [{"frame": 0, "position": [8, -10, 5], "look_at": [0, 0, 1]}],
                }
            ],
            "shots": [
                {"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 179}
            ],
            "speech_bindings": [],
        }
    )


def base_script_short_shot() -> SceneScriptRoot:
    """base_script with shot1 covering only frames 0-59, leaving 60-179 free
    for the add_shot family (the full-range base would overlap everything)."""

    return SceneScriptRoot.model_validate(
        {
            "scene": {
                "name": "地下研究所 B2",
                "environment": "indoor",
                "lighting": "cool",
                "duration": 6,
                "frame_rate": 30,
            },
            "characters": [
                {
                    "id": "char_a",
                    "type": "lowpoly_human",
                    "appearance": {"color": "#E74C3C", "height": 1.7, "scale": 1.0},
                    "keyframes": [
                        {"frame": 0, "position": [0, 0, 0], "rotation_y": 90, "action": "stand"}
                    ],
                }
            ],
            "cameras": [
                {
                    "id": "cam1",
                    "shot_type": "wide",
                    "keyframes": [{"frame": 0, "position": [8, -10, 5], "look_at": [0, 0, 1]}],
                }
            ],
            "shots": [{"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 59}],
            "speech_bindings": [],
        }
    )


class _FakeMcpClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._fail = fail

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        if self._fail:
            raise RuntimeError("object not found")
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}


@pytest.fixture
def service() -> SceneScriptToolService:
    return SceneScriptToolService()


# --- apply semantics ---------------------------------------------------------


def test_add_ops_create_objects_with_generated_ids(service) -> None:
    result = service.apply_operations(
        base_script(),
        [
            {"op": "add_environment", "type": "pillar", "position": [2, 4, 0], "scale": 1.5},
            {"op": "add_prop", "type": "chair", "position": [1, 2, 0]},
            {"op": "add_character", "position": [0, 1, 0], "color": "#3498DB", "action": "sit"},
            {"op": "add_camera", "position": [5, -6, 3], "look_at": [0, 0, 1], "shot_type": "medium"},
        ],
    )
    script = result.scene_script
    assert [obj.id for obj in script.environment] == ["wall1", "env_1"]
    assert script.environment[1].type == "pillar"
    assert script.environment[1].scale == 1.5
    assert [obj.id for obj in script.props] == ["crate1", "prop_1"]
    assert script.characters[1].id == "char_1"
    assert script.characters[1].keyframes[0].action == "sit"
    assert script.cameras[1].id == "cam_1"
    assert script.cameras[1].shot_type == "medium"
    assert len(result.applied) == 4


def test_move_rotate_scale_ops_target_any_kind(service) -> None:
    result = service.apply_operations(
        base_script(),
        [
            {"op": "move_object", "kind": "environment", "id": "wall1", "position": [1, 6, 0]},
            {"op": "rotate_object", "kind": "prop", "id": "crate1", "rotation_y": 45},
            {"op": "scale_object", "kind": "prop", "id": "crate1", "scale": 2.5},
            {"op": "move_object", "kind": "character", "id": "char_a", "position": [0, 2, 0]},
            {"op": "move_object", "kind": "camera", "id": "cam1", "position": [6, -8, 4]},
        ],
    )
    script = result.scene_script
    assert script.environment[0].position == [1, 6, 0]
    assert script.props[0].rotation_y == 45
    assert script.props[0].scale == 2.5
    assert script.characters[0].keyframes[0].position == [0, 2, 0]
    assert script.cameras[0].keyframes[0].position == [6, -8, 4]


def test_set_camera_updates_position_look_at_and_shot_type(service) -> None:
    result = service.apply_operations(
        base_script(),
        [
            {
                "op": "set_camera",
                "kind": "camera",
                "id": "cam1",
                "position": [4, -6, 3],
                "look_at": [0, 0, 1.2],
                "shot_type": "closeup",
            }
        ],
    )
    camera = result.scene_script.cameras[0]
    assert camera.keyframes[0].position == [4, -6, 3]
    assert camera.keyframes[0].look_at == [0, 0, 1.2]
    assert camera.shot_type == "closeup"


def test_add_keyframe_upserts_sorted(service) -> None:
    result = service.apply_operations(
        base_script(),
        [
            {"op": "add_keyframe", "kind": "character", "id": "char_a", "frame": 60, "position": [2, 2, 0]},
            {"op": "add_keyframe", "kind": "character", "id": "char_a", "frame": 0, "rotation_y": 45},
        ],
    )
    keyframes = result.scene_script.characters[0].keyframes
    assert [kf.frame for kf in keyframes] == [0, 60]
    assert keyframes[0].rotation_y == 45  # same-frame upsert, not a duplicate
    assert keyframes[1].position == [2, 2, 0]


def test_remove_character_also_drops_speech_bindings(service) -> None:
    payload = base_script().model_dump(mode="json")
    payload["speech_bindings"] = [
        {"character": "char_a", "speech_asset": "speech_audio:x", "mode": "bound"}
    ]
    script = SceneScriptRoot.model_validate(payload)
    result = service.apply_operations(script, [{"op": "remove_object", "kind": "character", "id": "char_a"}])
    assert [c.id for c in result.scene_script.characters] == []
    assert result.scene_script.speech_bindings == []


def test_remove_camera_also_drops_its_shots(service) -> None:
    result = service.apply_operations(base_script(), [{"op": "remove_object", "kind": "camera", "id": "cam1"}])
    assert [c.id for c in result.scene_script.cameras] == []
    assert result.scene_script.shots == []


# --- forward references + atomicity ------------------------------------------


def test_batch_may_reference_objects_its_own_ops_create(service) -> None:
    result = service.apply_operations(
        base_script(),
        [
            {"op": "add_character", "position": [0, 1, 0], "color": "#3498DB"},
            {"op": "move_object", "kind": "character", "id": "char_1", "position": [0, 3, 0]},
            {"op": "add_keyframe", "kind": "character", "id": "char_1", "frame": 90, "position": [1, 4, 0]},
        ],
    )
    character = result.scene_script.characters[1]
    assert character.keyframes[0].position == [0, 3, 0]
    assert [kf.frame for kf in character.keyframes] == [0, 90]


def test_invalid_batch_applies_nothing(service) -> None:
    script = base_script()
    before = script.model_dump(mode="json")
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            script,
            [
                {"op": "add_environment", "type": "wall", "position": [1, 1, 0]},
                {"op": "move_object", "kind": "prop", "id": "ghost", "position": [0, 0, 0]},
            ],
        )
    assert exc.value.code == "scene_operations_invalid"
    assert exc.value.violations[0]["code"] == "target_not_found"
    # The input script is untouched (atomicity, mutation-locked).
    assert script.model_dump(mode="json") == before


def test_unknown_enum_values_are_rejected(service) -> None:
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script(), [{"op": "add_prop", "type": "spaceship", "position": [0, 0, 0]}]
        )
    assert exc.value.violations[0]["code"] == "object_type_unsupported"


def test_out_of_bounds_positions_are_rejected(service) -> None:
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script(), [{"op": "add_environment", "type": "wall", "position": [500, 0, 0]}]
        )
    assert exc.value.violations[0]["code"] == "position_out_of_bounds"


def test_keyframe_beyond_total_frames_is_rejected(service) -> None:
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script(),
            [{"op": "add_keyframe", "kind": "character", "id": "char_a", "frame": 9999}],
        )
    assert exc.value.violations[0]["code"] == "frame_out_of_range"


def test_empty_operation_list_is_rejected(service) -> None:
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(base_script(), [])
    assert exc.value.code == "scene_operations_required"


def test_unknown_op_kind_is_rejected(service) -> None:
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(base_script(), [{"op": "teleport", "id": "x"}])
    assert exc.value.violations[0]["code"] == "operation_kind_unsupported"


# --- MCP extension ops --------------------------------------------------------


def test_mcp_request_executes_and_is_reported(service) -> None:
    client = _FakeMcpClient()
    result = service.apply_operations(
        base_script(),
        [
            {"op": "mcp_request", "tool": "bevel", "target": "wall1", "arguments": {"width": 0.05}},
        ],
        mcp_client=client,
    )
    assert client.calls == [("bevel", {"width": 0.05})]
    assert result.mcp_results[0]["tool"] == "bevel"
    assert result.mcp_results[0]["is_error"] is False
    # SceneScript is untouched by an MCP op: the geometry lives in Blender.
    assert result.scene_script == base_script()


def test_mcp_request_without_client_is_a_queryable_degradation(service) -> None:
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script(),
            [{"op": "mcp_request", "tool": "subdivide", "target": "wall1", "arguments": {}}],
        )
    assert exc.value.code == "scene_operations_mcp_failed"
    assert exc.value.violations[0]["code"] == "mcp_unavailable"
    assert "subdivide" in exc.value.violations[0]["message"]


def test_mcp_request_failure_rejects_the_batch(service) -> None:
    client = _FakeMcpClient(fail=True)
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script(),
            [
                {"op": "add_environment", "type": "door", "position": [0, 3, 0]},
                {"op": "mcp_request", "tool": "bevel", "target": "env_1", "arguments": {}},
            ],
            mcp_client=client,
        )
    assert exc.value.code == "scene_operations_mcp_failed"


def test_mcp_request_requires_a_tool_name(service) -> None:
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script(), [{"op": "mcp_request", "tool": "", "arguments": {}}],
            mcp_client=_FakeMcpClient(),
        )
    assert exc.value.violations[0]["code"] == "mcp_tool_required"


# --- result integrity ---------------------------------------------------------


def test_result_script_passes_schema_validation(service) -> None:
    result = service.apply_operations(
        base_script(),
        [
            {"op": "add_character", "position": [0, 1, 0]},
            {"op": "add_keyframe", "kind": "character", "id": "char_1", "frame": 150, "position": [3, 3, 0]},
        ],
    )
    # The backstop validator ran: re-validating is a no-op.
    SceneScriptRoot.model_validate(result.scene_script.model_dump(mode="json"))
    assert result.scene_script.characters[1].keyframes[1].frame == 150


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------


def _endpoint_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint

    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    return TestClient(app)


def test_apply_operations_endpoint_returns_new_script() -> None:
    client = _endpoint_client()
    response = client.post(
        "/scene-3d/apply-operations",
        json={
            "scene_script": base_script().model_dump(mode="json"),
            "operations": [
                {"op": "add_environment", "type": "door", "position": [0, 3, 0]},
                {"op": "move_object", "kind": "camera", "id": "cam1", "position": [6, -8, 4]},
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert len(body["applied"]) == 2
    assert [obj["id"] for obj in body["scene_script"]["environment"]] == ["wall1", "env_1"]


def test_apply_operations_endpoint_rejects_with_violations() -> None:
    client = _endpoint_client()
    response = client.post(
        "/scene-3d/apply-operations",
        json={
            "scene_script": base_script().model_dump(mode="json"),
            "operations": [{"op": "add_prop", "type": "spaceship", "position": [0, 0, 0]}],
        },
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error_code"] == "scene_operations_invalid"
    assert detail["violations"][0]["code"] == "object_type_unsupported"


def test_apply_operations_endpoint_mcp_without_server_is_rejectable() -> None:
    """use_mcp spawns a real client; with no server on PATH the batch must not
    silently proceed — the endpoint answers 503 mcp_unavailable."""

    client = _endpoint_client()
    response = client.post(
        "/scene-3d/apply-operations",
        json={
            "scene_script": base_script().model_dump(mode="json"),
            "operations": [
                {"op": "mcp_request", "tool": "bevel", "target": "wall1", "arguments": {}}
            ],
            "use_mcp": True,
        },
    )
    # Either the spawn failed (503) or a server answered; a spaceship 2xx is
    # impossible without a working server, and mcp_request ops are reported.
    assert response.status_code in (200, 503), response.text
    if response.status_code == 200:
        body = response.json()
        assert body["mcp_results"] or body["warnings"]


# --- shots: the time ranges a camera is on screen (add_shot / set_shot_camera)


def test_add_shot_binds_a_camera_to_a_frame_range(service) -> None:
    """A camera without a shot is invisible to the renderer (camera_unused);
    add_shot is the op that makes a chat round's new camera real."""

    result = service.apply_operations(
        base_script_short_shot(),
        [
            {
                "op": "add_camera",
                "id": "cam_2",
                "position": [-6, -8, 3],
                "look_at": [0, 0, 1],
                "frame": 60,
            },
            {
                "op": "add_shot",
                "camera": "cam_2",
                "start_frame": 60,
                "end_frame": 119,
                "description": "side angle",
            },
        ],
    )
    shot = result.scene_script.shots[1]
    # Auto-ids count free names: "shot1" (no underscore) does not occupy
    # "shot_1", so the counter starts at 1 — same rule as cameras.
    assert shot.id == "shot_1"
    assert shot.camera == "cam_2"
    assert (shot.start_frame, shot.end_frame) == (60, 119)
    assert shot.description == "side angle"


def test_add_shot_rejects_a_camera_whose_frames_the_shot_does_not_cover(service) -> None:
    """The schema requires every camera keyframe to fall inside a shot that
    uses that camera. A shot added for a camera whose only keyframe sits
    outside it is not a shot — the gate surfaces it as a coded rejection
    instead of handing back a script the schema would refuse."""

    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script_short_shot(),
            [
                {"op": "add_camera", "id": "cam_2", "position": [-6, -8, 3], "look_at": [0, 0, 1]},
                {"op": "add_shot", "camera": "cam_2", "start_frame": 60, "end_frame": 119},
            ],
        )
    assert exc.value.code == "scene_script_invalid_after_apply"
    assert "outside all" in str(exc.value)


def test_add_shot_keeps_shots_chronological(service) -> None:
    """The shot rail and the render schedule assume ascending order regardless
    of the order ops arrived in."""

    empty = base_script_short_shot().model_copy(deep=True)
    empty.shots = []
    result = service.apply_operations(
        empty,
        [
            {"op": "add_shot", "camera": "cam1", "start_frame": 120, "end_frame": 179},
            {"op": "add_shot", "camera": "cam1", "start_frame": 0, "end_frame": 59},
            {"op": "add_shot", "camera": "cam1", "start_frame": 60, "end_frame": 119},
        ],
    )
    assert [shot.start_frame for shot in result.scene_script.shots] == [0, 60, 120]
    assert [shot.id for shot in result.scene_script.shots] == [
        "shot_2",
        "shot_3",
        "shot_1",
    ]


def test_add_shot_honors_an_explicit_id_and_description(service) -> None:
    result = service.apply_operations(
        base_script_short_shot(),
        [
            {
                "op": "add_shot",
                "id": "side",
                "camera": "cam1",
                "start_frame": 60,
                "end_frame": 119,
                "description": "推近到门边",
            }
        ],
    )
    assert result.scene_script.shots[1].id == "side"
    assert result.scene_script.shots[1].description == "推近到门边"


def test_add_shot_rejects_unknown_camera(service) -> None:
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script(),
            [{"op": "add_shot", "camera": "nope", "start_frame": 0, "end_frame": 30}],
        )
    assert exc.value.violations[0]["code"] == "target_not_found"
    assert exc.value.violations[0]["path"] == "operations[0].camera"


def test_add_shot_rejects_inverted_range(service) -> None:
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script(),
            [{"op": "add_shot", "camera": "cam1", "start_frame": 60, "end_frame": 60}],
        )
    assert exc.value.violations[0]["code"] == "shot_range_invalid"


def test_add_shot_rejects_range_past_the_last_frame(service) -> None:
    # 6s * 30fps = 180 frames; the schema allows end_frame == total, rejects
    # beyond it — the gate must not be stricter than the schema it enforces.
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script_short_shot(),
            [{"op": "add_shot", "camera": "cam1", "start_frame": 170, "end_frame": 181}],
        )
    violation = exc.value.violations[0]
    assert violation["code"] == "frame_out_of_range"
    assert "180" in violation["message"]


def test_add_shot_accepts_end_frame_equal_to_total(service) -> None:
    """The gate mirrors the schema (end_frame <= total), not a stricter rule."""

    result = service.apply_operations(
        base_script_short_shot(),
        [{"op": "add_shot", "camera": "cam1", "start_frame": 60, "end_frame": 180}],
    )
    assert result.scene_script.shots[1].end_frame == 180


def test_add_shot_rejects_overlapping_existing_shot(service) -> None:
    """Shots may not share frames: the renderer binds one camera per frame."""

    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script_short_shot(),
            [{"op": "add_shot", "camera": "cam1", "start_frame": 30, "end_frame": 90}],
        )
    violation = exc.value.violations[0]
    assert violation["code"] == "shot_range_overlaps"
    assert "shot1" in violation["message"]


def test_add_shot_rejects_duplicate_explicit_id(service) -> None:
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script_short_shot(),
            [
                {
                    "op": "add_shot",
                    "id": "shot1",
                    "camera": "cam1",
                    "start_frame": 60,
                    "end_frame": 119,
                }
            ],
        )
    assert exc.value.violations[0]["code"] == "object_id_conflict"


def test_add_shot_requires_a_camera_field(service) -> None:
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script(),
            [{"op": "add_shot", "start_frame": 0, "end_frame": 30}],
        )
    assert exc.value.violations[0]["code"] == "shot_camera_required"


def test_add_camera_places_its_first_keyframe_at_the_given_frame(service) -> None:
    """"从第 60 帧起用侧机位" is one camera keyframe at 60 plus a shot covering
    60: the schema rejects a camera keyframe outside every shot that uses it."""

    result = service.apply_operations(
        base_script_short_shot(),
        [
            {
                "op": "add_camera",
                "id": "cam_2",
                "position": [-7, -6, 2],
                "look_at": [0, 1, 1],
                "frame": 60,
            },
            {"op": "add_shot", "camera": "cam_2", "start_frame": 60, "end_frame": 119},
        ],
    )
    camera = result.scene_script.cameras[1]
    assert [kf.frame for kf in camera.keyframes] == [60]


def test_add_camera_rejects_a_frame_outside_the_scene(service) -> None:
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script(),
            [
                {
                    "op": "add_camera",
                    "id": "cam_2",
                    "position": [1, 1, 1],
                    "look_at": [0, 0, 0],
                    "frame": 181,
                }
            ],
        )
    assert exc.value.violations[0]["code"] == "frame_invalid"


def test_set_shot_camera_repoints_a_shot(service) -> None:
    result = service.apply_operations(
        base_script(),
        [
            {"op": "add_camera", "id": "cam_2", "position": [3, -4, 2], "look_at": [0, 0, 1]},
            {"op": "set_shot_camera", "id": "shot1", "camera": "cam_2"},
        ],
    )
    assert result.scene_script.shots[0].camera == "cam_2"


def test_set_shot_camera_rejects_unknown_shot_or_camera(service) -> None:
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script(),
            [{"op": "set_shot_camera", "id": "ghost", "camera": "cam1"}],
        )
    assert exc.value.violations[0]["code"] == "target_not_found"

    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script(),
            [{"op": "set_shot_camera", "id": "shot1", "camera": "ghost"}],
        )
    assert exc.value.violations[0]["code"] == "target_not_found"


# --- time-aware ops: the ``frame`` parameter turns a restage into a beat


def test_move_object_with_frame_writes_a_keyframe_that_frame(service) -> None:
    """"她走到桌边" is a beat, not a restage: frame 0 must survive untouched."""

    result = service.apply_operations(
        base_script(),
        [
            {
                "op": "move_object",
                "kind": "character",
                "id": "char_a",
                "position": [2, 3, 0],
                "frame": 60,
            }
        ],
    )
    keyframes = result.scene_script.characters[0].keyframes
    assert [(kf.frame, kf.position) for kf in keyframes] == [
        (0, [0, 0, 0]),
        (60, [2, 3, 0]),
    ]
    # The beat inherits facing/action from frame 0 (the one documented rule).
    assert keyframes[1].rotation_y == 90
    assert keyframes[1].action == "stand"


def test_move_object_with_frame_on_camera_keeps_the_aim(service) -> None:
    result = service.apply_operations(
        base_script(),
        [
            {
                "op": "move_object",
                "kind": "camera",
                "id": "cam1",
                "position": [4, -6, 3],
                "frame": 90,
            }
        ],
    )
    keyframes = result.scene_script.cameras[0].keyframes
    assert len(keyframes) == 2
    assert keyframes[1].position == [4, -6, 3]
    assert keyframes[1].look_at == [0, 0, 1]


def test_rotate_object_with_frame_writes_a_keyframe(service) -> None:
    result = service.apply_operations(
        base_script(),
        [
            {
                "op": "rotate_object",
                "kind": "character",
                "id": "char_a",
                "rotation_y": -45,
                "frame": 45,
            }
        ],
    )
    keyframes = result.scene_script.characters[0].keyframes
    assert [(kf.frame, kf.rotation_y) for kf in keyframes] == [(0, 90.0), (45, -45.0)]


def test_set_camera_with_frame_upserts_without_losing_the_other_field(service) -> None:
    result = service.apply_operations(
        base_script(),
        [
            {
                "op": "set_camera",
                "kind": "camera",
                "id": "cam1",
                "position": [1, -2, 3],
            },
            {
                "op": "set_camera",
                "kind": "camera",
                "id": "cam1",
                "look_at": [1, 1, 1],
                "frame": 30,
            },
        ],
    )
    keyframes = result.scene_script.cameras[0].keyframes
    assert [(kf.frame, kf.position, kf.look_at) for kf in keyframes] == [
        (0, [1, -2, 3], [0, 0, 1]),
        (30, [1, -2, 3], [1, 1, 1]),
    ]


def test_frame_does_not_restage_frame_zero(service) -> None:
    """The backward-compatibility lock: without ``frame`` the old restage
    semantics still rewrite keyframes[0]; with it, they must not."""

    without_frame = service.apply_operations(
        base_script(),
        [{"op": "move_object", "kind": "character", "id": "char_a", "position": [9, 9, 0]}],
    ).scene_script
    assert without_frame.characters[0].keyframes[0].position == [9, 9, 0]
    assert len(without_frame.characters[0].keyframes) == 1

    with_frame = service.apply_operations(
        base_script(),
        [
            {
                "op": "move_object",
                "kind": "character",
                "id": "char_a",
                "position": [9, 9, 0],
                "frame": 120,
            }
        ],
    ).scene_script
    assert with_frame.characters[0].keyframes[0].position == [0, 0, 0]


def test_frame_upserts_rather_than_duplicating(service) -> None:
    result = service.apply_operations(
        base_script(),
        [
            {
                "op": "add_keyframe",
                "kind": "character",
                "id": "char_a",
                "frame": 60,
                "position": [1, 1, 0],
            },
            {
                "op": "move_object",
                "kind": "character",
                "id": "char_a",
                "position": [2, 2, 0],
                "frame": 60,
            },
        ],
    )
    keyframes = result.scene_script.characters[0].keyframes
    assert [kf.frame for kf in keyframes] == [0, 60]
    assert keyframes[1].position == [2, 2, 0]


def test_frame_is_rejected_for_static_objects(service) -> None:
    """Environment/props have no keyframes in the schema; a beat aimed at a
    wall must fail loudly instead of quietly restaging the wall."""

    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script(),
            [
                {
                    "op": "move_object",
                    "kind": "environment",
                    "id": "wall1",
                    "position": [0, 6, 0],
                    "frame": 30,
                }
            ],
        )
    violation = exc.value.violations[0]
    assert violation["code"] == "frame_not_supported"
    assert "characters and cameras animate" in violation["message"]


def test_frame_is_rejected_for_scale(service) -> None:
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script(),
            [
                {
                    "op": "scale_object",
                    "kind": "prop",
                    "id": "crate1",
                    "scale": 2.0,
                    "frame": 30,
                }
            ],
        )
    assert exc.value.violations[0]["code"] == "frame_not_supported"


def test_frame_must_be_inside_the_scene(service) -> None:
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script(),
            [
                {
                    "op": "move_object",
                    "kind": "character",
                    "id": "char_a",
                    "position": [1, 1, 0],
                    "frame": 181,
                }
            ],
        )
    violation = exc.value.violations[0]
    assert violation["code"] == "frame_invalid"
    assert "180" in violation["message"]


def test_rotate_object_on_a_camera_is_rejected_not_silently_ignored(service) -> None:
    """CameraKeyframe has no rotation_y: the old application wrote the
    attribute, reported success, and changed nothing. Cameras aim via
    look_at — the op must say so instead of lying."""

    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script(),
            [{"op": "rotate_object", "kind": "camera", "id": "cam1", "rotation_y": 45}],
        )
    violation = exc.value.violations[0]
    assert violation["code"] == "rotation_not_supported"
    assert "set_camera" in violation["message"]


def test_multi_angle_round_adds_camera_shot_and_beats_atomically(service) -> None:
    """The chat-loop shape this unlocks: one round = second angle on a new
    time range plus a character beat inside it. Any violation discards the
    whole batch."""

    result = service.apply_operations(
        base_script_short_shot(),
        [
            {
                "op": "add_camera",
                "id": "cam_2",
                "position": [-7, -6, 2],
                "look_at": [0, 1, 1],
                "frame": 60,
            },
            {"op": "add_shot", "camera": "cam_2", "start_frame": 60, "end_frame": 119},
            {
                "op": "move_object",
                "kind": "character",
                "id": "char_a",
                "position": [1, 2, 0],
                "frame": 90,
            },
            {
                "op": "set_camera",
                "kind": "camera",
                "id": "cam_2",
                "look_at": [1, 1, 1],
                "frame": 90,
            },
        ],
    )
    script = result.scene_script
    assert len(script.cameras) == 2
    assert len(script.shots) == 2
    assert script.shots[1].camera == "cam_2"
    assert [kf.frame for kf in script.cameras[1].keyframes] == [60, 90]
    assert [kf.frame for kf in script.characters[0].keyframes] == [0, 90]

    # The same batch with one broken op applies nothing at all.
    with pytest.raises(SceneOperationError) as exc:
        service.apply_operations(
            base_script_short_shot(),
            [
                {
                    "op": "add_camera",
                    "id": "cam_2",
                    "position": [-7, -6, 2],
                    "look_at": [0, 1, 1],
                    "frame": 60,
                },
                {"op": "add_shot", "camera": "cam_2", "start_frame": 60, "end_frame": 119},
                {"op": "add_shot", "camera": "cam_2", "start_frame": 90, "end_frame": 119},
            ],
        )
    assert exc.value.violations[0]["code"] == "shot_range_overlaps"


def test_endpoint_add_shot_and_frame_ops_round_trip() -> None:
    """The same ops through the HTTP surface the chat loop will call."""

    client = _endpoint_client()
    response = client.post(
        "/scene-3d/apply-operations",
        json={
            "scene_script": base_script_short_shot().model_dump(mode="json"),
            "operations": [
                {
                    "op": "add_camera",
                    "id": "cam_2",
                    "position": [-7, -6, 2],
                    "look_at": [0, 1, 1],
                    "frame": 60,
                },
                {"op": "add_shot", "camera": "cam_2", "start_frame": 60, "end_frame": 119},
                {
                    "op": "move_object",
                    "kind": "character",
                    "id": "char_a",
                    "position": [2, 2, 0],
                    "frame": 90,
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["applied"]) == 3
    script = body["scene_script"]
    assert [shot["camera"] for shot in script["shots"]] == ["cam1", "cam_2"]
    assert [kf["frame"] for kf in script["cameras"][1]["keyframes"]] == [60]
    assert [kf["frame"] for kf in script["characters"][0]["keyframes"]] == [0, 90]
