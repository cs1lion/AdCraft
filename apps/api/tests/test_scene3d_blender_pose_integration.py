"""Real Blender FK regression: parent/inverse semantics cannot be mocked.

Run: BLENDER_EXECUTABLE=... uv run pytest -m integration \
    tests/test_scene3d_blender_pose_integration.py
Only builds primitives and evaluates frames; no images or video are rendered.
The JSON artifact contains actual world-space knee/ankle positions, not a second
Python simulation pretending to be Blender. Missing binaries may skip; a present
binary that crashes, times out, or produces invalid output must fail.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from app.services.scene3d import character_pose
from app.services.scene3d.blender_converter import _build_asset, _character_pose_code

pytestmark = pytest.mark.integration

TOTAL_FRAMES = 45
ACTION_FRAMES = [0, 5, 20, 30, 40]
ACTIONS = ["stand", "walk", "sit", "stand", "sit"]
CASES = [(height, scale) for height in (1.1, 1.85) for scale in (1.0, 1.5)]
POSITION_TOLERANCE = 0.001  # metres: one millimetre, including builder rounding
ANGLE_TOLERANCE = 2e-5


def _character(index: int, height: float, scale: float) -> NS:
    return NS(
        id=f"fk_char_{index}",
        type="lowpoly_human",
        appearance=NS(height=height, scale=scale, color="#8B4513"),
        keyframes=[
            NS(frame=frame, position=[3.0 * index, 2.0 + 0.08 * frame, 0.15],
               rotation_y=0.0, action=action)
            for frame, action in zip(ACTION_FRAMES, ACTIONS)
        ],
    )


# This runs INSIDE Blender, after executing the unmodified production fragments.
# Cube vertices are +/-0.5 because the builder uses primitive_cube_add(size=1).
# Do not use object.location or hand-composed parent matrices as actual FK:
# matrix_parent_inverse and dependency-graph evaluation are exactly the contract.
_MEASURE_CODE = r'''
from mathutils import Vector
rows = []
for frame in range(46):
    scene.frame_set(frame + 1)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for char_id in character_ids:
        def evaluated(suffix):
            return bpy.data.objects[char_id + suffix].evaluated_get(depsgraph)
        def endpoint(obj, z):
            return obj.matrix_world @ Vector((0, 0, z))
        root = bpy.data.objects[char_id].evaluated_get(depsgraph)
        row = {"character": char_id, "frame": frame, "legs": {},
               "root_world": list(root.matrix_world.translation)}
        for side in ("L", "R"):
            thigh = evaluated("_Leg" + side)
            shin = evaluated("_Shin" + side)
            hip = endpoint(thigh, 0.5)
            knee = endpoint(thigh, -0.5)
            shin_top = endpoint(shin, 0.5)
            ankle = endpoint(shin, -0.5)
            down = ankle - shin_top
            row["legs"][side] = {
                "hip": list(hip), "knee": list(knee),
                "shin_top": list(shin_top), "ankle": list(ankle),
                "connection_error": (knee - shin_top).length,
                "world_shin_pitch": math.atan2(down.y, -down.z),
                "thigh_local_pitch": float(evaluated("_Leg" + side + "_pivot").rotation_euler.x),
                "knee_local_pitch": float(evaluated("_Shin" + side + "_pivot").rotation_euler.x),
            }
        row["head_local_pitch"] = float(evaluated("_Head_pivot").rotation_euler.x)
        row["arm_local_pitch"] = [
            float(evaluated("_Arm" + side + "_pivot").rotation_euler.x)
            for side in ("L", "R")
        ]
        row["bob"] = list(bpy.data.objects[char_id + "_bob"].location)
        rows.append(row)
with open(json_path, "w", encoding="utf-8") as stream:
    json.dump(rows, stream, indent=2)
print("BLENDER_FK_JSON=" + json_path)
'''


@pytest.fixture(scope="module")
def blender_fk(tmp_path_factory):
    configured = os.environ.get("BLENDER_EXECUTABLE")
    executable = configured or shutil.which("blender")
    if executable is None and Path(r"D:\Blender\blender.exe").is_file():
        executable = r"D:\Blender\blender.exe"
    if executable is None or (
        not Path(executable).is_file() and shutil.which(executable) is None
    ):
        pytest.skip("Blender executable is not installed")

    directory = tmp_path_factory.mktemp("blender_world_fk")
    json_path = directory / "world_knees_ankles.json"
    script_path = directory / "evaluate_fk.py"
    chars = [_character(i, height, scale) for i, (height, scale) in enumerate(CASES)]
    script = NS(characters=chars, props=[])
    lines = [
        "import bpy, math, json",
        "bpy.ops.wm.read_factory_settings(use_empty=True)",
        "scene = bpy.context.scene",
        "scene.frame_start = 1",
        "scene.frame_end = 46",
        f"json_path = {str(json_path)!r}",
        f"character_ids = {[char.id for char in chars]!r}",
    ]
    for index, char in enumerate(chars):
        lines.append(_build_asset(
            char.id, char.type, char.keyframes[0].position, 0.0,
            scale=char.appearance.scale, color=char.appearance.color,
            height=char.appearance.height,
        ))
        lines.extend(_character_pose_code(char, script, total_frames=TOTAL_FRAMES))
        # Isolate the pose/rig contract from the separate root-motion interpolation
        # contract. An exact +Y path at each sampled frame gives absolute FK an
        # independent reference; no pose curve or parent inverse is rewritten.
        lines.append(f"root = bpy.data.objects[{char.id!r}]")
        for frame in range(TOTAL_FRAMES + 1):
            lines.extend([
                f"root.location = ({3.0 * index!r}, {2.0 + 0.08 * frame!r}, 0.15)",
                f"root.keyframe_insert(data_path='location', frame={frame + 1})",
            ])
    lines.append(_MEASURE_CODE)
    script_path.write_text("\n".join(lines), encoding="utf-8")
    completed = subprocess.run(
        [executable, "--background", "--factory-startup", "--python-exit-code", "1",
         "--python", str(script_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    log = completed.stdout + "\n" + completed.stderr
    (directory / "blender.log").write_text(log, encoding="utf-8")
    assert completed.returncode == 0, log
    assert "Traceback (most recent call last)" not in log, log
    assert json_path.is_file(), f"Blender did not write world FK JSON:\n{log}"
    rows = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(rows) == len(CASES) * (TOTAL_FRAMES + 1)
    print(f"Real Blender world knee/ankle JSON: {json_path}")
    return chars, {(row["character"], row["frame"]): row for row in rows}


@pytest.mark.parametrize("index", range(len(CASES)))
def test_real_world_stance_foot_sliding_below_half_percent(blender_fk, index):
    """Lock actual world-space planted-foot travel, not just matching FK."""
    chars, rows = blender_fk
    char = chars[index]
    leg_length = 0.5 * char.appearance.height * char.appearance.scale
    stride = character_pose.walk_stride_metres(leg_length)
    positions = [list(kf.position) for kf in char.keyframes]
    samples = []
    for side, offset in (("L", 0.0), ("R", character_pose.STANCE_FRACTION)):
        for frame in range(6, 20):
            pair = (frame - 1, frame)
            phases = [
                (character_pose.travelled_metres(positions, ACTION_FRAMES, f) / stride
                 + offset) % 1.0
                for f in pair
            ]
            if not all(phase < character_pose.STANCE_FRACTION for phase in phases):
                continue
            if phases[1] < phases[0]:
                continue  # Different stances across a cycle wrap.
            if any(abs(_expected_pose(char, f).get(f"knee_{side.lower()}", 0.0)) > 1e-9
                   for f in pair):
                continue
            before = rows[char.id, pair[0]]["legs"][side]
            after = rows[char.id, pair[1]]["legs"][side]
            foot_travel = math.dist(before["ankle"][:2], after["ankle"][:2])
            samples.append((side, frame, foot_travel / 0.08))
    assert samples, f"No consecutive same-side stance samples for {char.id}"
    worst = max(samples, key=lambda sample: sample[2])
    print(f"{char.id}: {len(samples)} stance pairs; worst sliding={worst[2]:.6%} "
          f"side={worst[0]} frame={worst[1]}")
    assert worst[2] < 0.005, (
        f"{char.id}: planted foot moved {worst[2]:.6%} of root travel "
        f"at side={worst[0]} frame={worst[1]} (limit <0.5%)"
    )


def _expected_pose(char: NS, frame: int) -> dict[str, float]:
    return character_pose.pose_at_frame(
        ACTIONS, [list(kf.position) for kf in char.keyframes], ACTION_FRAMES,
        frame, 0.5 * char.appearance.height * char.appearance.scale,
    )


def _expected_fk(char: NS, index: int, frame: int, side: str):
    """Independent Z-up planar FK: positive knee flexion subtracts from thigh."""
    pose = _expected_pose(char, frame)
    h = char.appearance.height * char.appearance.scale
    leg = 0.5 * h
    shin = leg * character_pose.KNEE_FRACTION_OF_LEG
    thigh = leg - shin
    suffix = side.lower()
    # Preview X pitch is mapped to negative Blender X pitch (Y-up -> Z-up).
    phi = -pose.get(f"leg_{suffix}", 0.0)
    pitch = phi + pose.get(f"knee_{suffix}", 0.0)
    hip = [3.0 * index + (-0.075 if side == "L" else 0.075) * h,
           2.0 + frame * 0.08, 0.15 + leg + pose.get("bob", 0.0) * h]
    knee = [hip[0], hip[1] + thigh * math.sin(phi), hip[2] - thigh * math.cos(phi)]
    ankle = [knee[0], knee[1] + shin * math.sin(pitch),
             knee[2] - shin * math.cos(pitch)]
    return hip, knee, ankle, pitch


@pytest.mark.parametrize("index,height,scale", [(i, *case) for i, case in enumerate(CASES)])
def test_real_world_joint_connection_and_absolute_fk(blender_fk, index, height, scale):
    chars, rows = blender_fk
    char = chars[index]
    assert (char.appearance.height, char.appearance.scale) == (height, scale)
    for frame in range(TOTAL_FRAMES + 1):
        row = rows[char.id, frame]
        pose = _expected_pose(char, frame)
        for side in ("L", "R"):
            actual = row["legs"][side]
            context = f"{char.id} height={height} scale={scale} frame={frame} side={side}"
            assert actual["connection_error"] <= POSITION_TOLERANCE, context
            hip, knee, ankle, pitch = _expected_fk(char, index, frame, side)
            for field, expected in (("hip", hip), ("knee", knee), ("ankle", ankle)):
                assert math.dist(actual[field], expected) <= POSITION_TOLERANCE, (
                    f"{context} {field}: actual={actual[field]} expected={expected}"
                )
            assert actual["world_shin_pitch"] == pytest.approx(
                pitch, abs=ANGLE_TOLERANCE
            ), context
            # Y-up preview -> Z-up Blender flips every pitch: knee is positive.
            assert actual["knee_local_pitch"] == pytest.approx(
                pose.get(f"knee_{side.lower()}", 0.0), abs=ANGLE_TOLERANCE
            ), context


@pytest.mark.parametrize("index", range(len(CASES)))
def test_real_action_boundaries_zero_resets_and_repeated_sit(blender_fk, index):
    chars, rows = blender_fk
    char = chars[index]
    # All frames around every boundary, including the immediately preceding one.
    # This catches both Bezier anticipation and globally deduplicated held poses.
    for frame in (0, 1, 4, 5, 6, 18, 19, 20, 21, 28, 29, 30, 31, 38, 39, 40, 41, 45):
        row = rows[char.id, frame]
        expected = _expected_pose(char, frame)
        context = f"{char.id} frame={frame}"
        assert row["head_local_pitch"] == pytest.approx(
            -expected.get("head", 0.0), abs=ANGLE_TOLERANCE
        ), context
        assert row["arm_local_pitch"] == pytest.approx(
            [-expected.get("arm_l", 0.0), -expected.get("arm_r", 0.0)],
            abs=ANGLE_TOLERANCE,
        ), context
        assert row["bob"] == pytest.approx(
            [0, 0, expected.get("bob", 0.0) * char.appearance.height * char.appearance.scale],
            abs=POSITION_TOLERANCE,
        ), context
        for side in ("L", "R"):
            leg = row["legs"][side]
            assert leg["thigh_local_pitch"] == pytest.approx(
                -expected.get(f"leg_{side.lower()}", 0.0), abs=ANGLE_TOLERANCE
            ), context
            assert leg["knee_local_pitch"] == pytest.approx(
                expected.get(f"knee_{side.lower()}", 0.0), abs=ANGLE_TOLERANCE
            ), context
        if character_pose.action_at_frame(ACTIONS, ACTION_FRAMES, frame) == "stand":
            assert row["head_local_pitch"] == pytest.approx(0.0, abs=ANGLE_TOLERANCE)
            for side in ("L", "R"):
                assert row["legs"][side]["knee_local_pitch"] == pytest.approx(
                    0.0, abs=ANGLE_TOLERANCE
                )
    first, repeated = rows[char.id, 20], rows[char.id, 40]
    for side in ("L", "R"):
        for field in ("thigh_local_pitch", "knee_local_pitch", "world_shin_pitch"):
            assert repeated["legs"][side][field] == pytest.approx(
                first["legs"][side][field], abs=ANGLE_TOLERANCE
            )
        # Subtract authored translation to compare the complete repeated pose.
        for field in ("hip", "knee", "ankle"):
            a = first["legs"][side][field]
            b = repeated["legs"][side][field]
            assert [b[0] - a[0], b[1] - a[1], b[2] - a[2]] == pytest.approx(
                [0, 0.08 * 20, 0], abs=POSITION_TOLERANCE
            )
    assert repeated["head_local_pitch"] == pytest.approx(
        first["head_local_pitch"], abs=ANGLE_TOLERANCE
    )
    assert repeated["arm_local_pitch"] == pytest.approx(
        first["arm_local_pitch"], abs=ANGLE_TOLERANCE
    )
    assert repeated["bob"] == pytest.approx(first["bob"], abs=POSITION_TOLERANCE)
