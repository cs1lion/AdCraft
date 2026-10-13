"""Real evaluated FK and a rendered chip; mocks cannot prove compound axes."""

from __future__ import annotations

import copy
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.schemas.scene_script import SceneEnvironmentObject, SceneProp, SceneScriptRoot
from app.services.scene3d.blender_converter import scene_script_to_blender

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def evaluated_authored_pose(tmp_path_factory):
    executable = os.environ.get("BLENDER_EXECUTABLE") or shutil.which("blender")
    if executable is None and Path("D:/Blender/blender.exe").is_file():
        executable = "D:/Blender/blender.exe"
    if executable is None:
        pytest.skip("Blender executable is not installed")
    directory = tmp_path_factory.mktemp("authored_pose_blender")
    json_path = directory / "evaluated.json"
    png_path = directory / "chip-and-pose.png"
    script = SceneScriptRoot.model_validate({
        "scene": {"name": "compound-joints", "duration": 2, "frame_rate": 30},
        "characters": [{"id": "A", "appearance": {"height": 1.7}, "keyframes": [
            {"frame": 0, "position": [0, 0, 0], "rotation_y": 0,
             "pose": {"arm_r": 0, "arm_r_side": 0, "head": 0, "head_yaw": 0, "bob": 0}},
            {"frame": 30, "position": [0, 0, 0], "rotation_y": 0,
             "pose": {"arm_r": 0.8, "arm_r_side": 0.3, "head": 0.2,
                      "head_yaw": 0.6, "bob": 0.02}},
            {"frame": 60, "position": [0, 0, 0], "rotation_y": 0,
             "pose": {"arm_r": 0, "arm_r_side": 0, "head": 0, "head_yaw": 0, "bob": 0}},
        ]}],
        "props": [{"id": "token", "type": "chip", "position": [1, 0, 1],
                   "keyframes": [
                       {"frame": frame, "position": [
                           1 + 0.1 * (frame / 30 if frame <= 30 else (60 - frame) / 30), 0, 1,
                       ]} for frame in range(61)
                   ]},
                  {"id": "table", "type": "rect_table", "position": [0.7, 0, 0.225]}],
        "cameras": [{"id": "cam", "keyframes": [
            {"frame": 0, "position": [2, -2, 2], "look_at": [0.5, 0, 1]},
        ]}],
        "shots": [{"id": "s", "camera": "cam", "start_frame": 0, "end_frame": 60}],
    })
    turned = copy.deepcopy(script.characters[0])
    turned.id = "turned"
    for keyframe in turned.keyframes:
        keyframe.position = [2, 0, 0]
        keyframe.rotation_y = 60
    script.characters.append(turned)
    script.props.extend([
        SceneProp.model_validate({"id": "static_crate", "type": "crate", "position": [4, 2, 1],
                             "rotation_y": 60}),
        SceneProp.model_validate({"id": "moving_crate", "type": "crate", "position": [4, 2, 1],
                             "rotation_y": 35, "scale": 1.2, "keyframes": [
                                 {"frame": 0, "position": [4, 2, 1], "rotation": [20, 60, 30]},
                                 {"frame": 60, "position": [5, 3, 2], "rotation": [20, 60, 30]},
                             ]}),
    ])
    script.environment = [
        SceneEnvironmentObject.model_validate({"id": "static_wall", "type": "wall", "position": [4, 2, 1],
                                          "rotation_y": 60}),
        SceneEnvironmentObject.model_validate({"id": "moving_wall", "type": "wall", "position": [4, 2, 1],
                                          "rotation_y": 35, "scale": 1.2, "keyframes": [
                                              {"frame": 0, "position": [4, 2, 1], "rotation": [20, 60, 30]},
                                              {"frame": 60, "position": [5, 3, 2], "rotation": [20, 60, 30]},
                                          ]}),
    ]
    # Keep all production construction, material, camera and pose code; replace
    # only the full animation call with this fixture's measurement/still pass.
    code = scene_script_to_blender(script, directory.as_posix())
    code = code.split("# === RENDER ANIMATION ===", 1)[0]
    code += f"""
from mathutils import Vector
import json
rows = []
for frame in (0, 15, 30, 45, 60, 15, 0):
    scene.frame_set(frame + 1)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    arm = bpy.data.objects['A_ArmR'].evaluated_get(depsgraph)
    nose = bpy.data.objects['A_Nose'].evaluated_get(depsgraph)
    turned_arm = bpy.data.objects['turned_ArmR'].evaluated_get(depsgraph)
    turned_nose = bpy.data.objects['turned_Nose'].evaluated_get(depsgraph)
    assets = {{}}
    for name in ('static_crate', 'moving_crate', 'static_wall', 'moving_wall'):
        wrapper = bpy.data.objects[name]
        assert wrapper.type == 'EMPTY', (name, wrapper.type)
        assert bpy.data.objects[name + '_Mesh'].parent == wrapper
        evaluated = wrapper.evaluated_get(depsgraph)
        assets[name] = list(evaluated.matrix_world @ Vector((.4, .2, .3)))
    # Read the evaluated mesh directly: evaluated empty.children is not populated
    # consistently across Blender dependency graphs.
    assert bpy.data.objects['token_Disk'].parent.name == 'token'
    mesh = bpy.data.objects['token_Disk'].evaluated_get(depsgraph)
    corners = [mesh.matrix_world @ Vector(corner) for corner in mesh.bound_box]
    rows.append({{
        'frame': frame,
        'hand': list(arm.matrix_world @ Vector((0, 0, -0.5))),
        'nose': list(nose.matrix_world.translation),
        'turned_hand': list(turned_arm.matrix_world @ Vector((0, 0, -0.5))),
        'turned_nose': list(turned_nose.matrix_world.translation),
        'assets': assets,
        'chip_min': [min(c[i] for c in corners) for i in range(3)],
        'chip_max': [max(c[i] for c in corners) for i in range(3)],
    }})
with open({str(json_path)!r}, 'w', encoding='utf-8') as stream:
    json.dump(rows, stream)
scene.frame_set(16)
scene.render.resolution_x = 320
scene.render.resolution_y = 180
scene.render.resolution_percentage = 100
scene.render.filepath = {str(png_path)!r}
bpy.ops.render.render(write_still=True)
"""
    script_path = directory / "evaluate_and_render.py"
    script_path.write_text(code, encoding="utf-8")
    completed = subprocess.run(
        [executable, "--background", "--factory-startup", "--python-exit-code", "1",
         "--python", str(script_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
    )
    log = completed.stdout + "\n" + completed.stderr
    (directory / "blender.log").write_text(log, encoding="utf-8")
    assert completed.returncode == 0, log
    assert json_path.is_file() and png_path.is_file(), log
    print(f"Real authored pose FK: {json_path}; rendered still: {png_path}")
    return json.loads(json_path.read_text(encoding="utf-8")), png_path


def test_real_compound_arm_and_head_match_three_axis_order(evaluated_authored_pose):
    rows, _ = evaluated_authored_pose
    for row in rows:
        frame = row["frame"]
        fraction = frame / 30 if frame <= 30 else (60 - frame) / 30
        pitch, side, head, yaw = [fraction * n for n in (0.8, 0.3, 0.2, 0.6)]
        bob = fraction * 0.02 * 1.7
        # Three XYZ: rotationX(pitch) * rotationZ(side), then Y/Z reflection.
        expected_hand = [
            0.3111 + 0.51 * math.sin(side),
            -0.51 * math.sin(pitch) * math.cos(side),
            1.3345 - 0.51 * math.cos(pitch) * math.cos(side) + bob,
        ]
        y, z = 0.187 * 0.9, 0.187 * (0.85 + 0.08)
        expected_nose = [
            -y * math.sin(yaw),
            y * math.cos(yaw) * math.cos(head) + z * math.sin(head),
            1.411 - y * math.cos(yaw) * math.sin(head) + z * math.cos(head) + bob,
        ]
        assert row["hand"] == pytest.approx(expected_hand, abs=0.0003)
        assert row["nose"] == pytest.approx(expected_nose, abs=0.0003)
    assert rows[1] == rows[-2]  # seek backward to an already evaluated middle frame
    assert rows[0] == rows[-1]  # replay returns to the same starting state


def test_real_root_yaw_matches_three_reference(evaluated_authored_pose):
    rows, _ = evaluated_authored_pose
    for row in rows:
        for original, turned in (("hand", "turned_hand"), ("nose", "turned_nose")):
            x, y, z = row[original]
            angle = math.radians(-60)
            assert row[turned] == pytest.approx([
                2 + x * math.cos(angle) - y * math.sin(angle),
                x * math.sin(angle) + y * math.cos(angle), z,
            ], abs=0.0003)
    # Independently obtained from the production Three scene graph; remove only
    # this fixture's root translation and add its authored bob at frame 30.
    assert rows[2]["turned_hand"] == pytest.approx(
        [2 - .0717780892256803, -.574699480910385, .9950494357544327 + .034], abs=.0003,
    )
    assert rows[2]["turned_nose"] == pytest.approx(
        [2 + .10030351891848266, .16764068016619366, 1.5538474170084482 + .034], abs=.0003,
    )


def test_real_asset_yaw_compound_order_and_pivot_translation(evaluated_authored_pose):
    rows, _ = evaluated_authored_pose
    for row in rows:
        for name in ("static_crate", "static_wall"):
            angle = math.radians(-60)
            assert row["assets"][name] == pytest.approx([
                4 + .4 * math.cos(angle) - .2 * math.sin(angle),
                2 + .4 * math.sin(angle) + .2 * math.cos(angle), 1.3,
            ], abs=.0003)
        for name, offset in (("moving_crate", .45 * 1.2), ("moving_wall", 2.5 * 1.2)):
            x, y, z = .4, .2, .3 - offset
            # Actual preview: outer XYZ(pitch, 0, roll), inner yaw. Reflect its
            # Y/Z axes into canonical coordinates: Rx(-pitch) Ry(-roll) Rz(-yaw).
            yaw, roll, pitch = map(math.radians, (-60, -30, -20))
            x, y = x * math.cos(yaw) - y * math.sin(yaw), x * math.sin(yaw) + y * math.cos(yaw)
            x, z = x * math.cos(roll) + z * math.sin(roll), -x * math.sin(roll) + z * math.cos(roll)
            y, z = y * math.cos(pitch) - z * math.sin(pitch), y * math.sin(pitch) + z * math.cos(pitch)
            # Test authored endpoints: intermediate root motion currently uses
            # Blender Bezier interpolation and is outside this contract check.
            if row["frame"] in (0, 60):
                delta = row["frame"] / 60
                assert row["assets"][name] == pytest.approx(
                    [4 + delta + x, 2 + delta + y, 1 + delta + offset + z], abs=.0003,
                )


def test_real_chip_bounds_and_visible_render(evaluated_authored_pose):
    rows, png_path = evaluated_authored_pose
    for row in rows:
        frame = row["frame"]
        delta = 0.1 * (frame / 30 if frame <= 30 else (60 - frame) / 30)
        assert row["chip_min"] == pytest.approx([0.93 + delta, -0.07, 1], abs=0.0001)
        assert row["chip_max"] == pytest.approx([1.07 + delta, 0.07, 1.025], abs=0.0001)
    with Image.open(png_path) as image:
        assert image.size == (320, 180)
        # The token is the only green material in this fixture. A valid PNG
        # that never shows it must not count as a visible native-chip render.
        pixels = image.convert("RGB").tobytes()
        green = sum(g > r + 15 and g > b + 3
                    for r, g, b in zip(pixels[0::3], pixels[1::3], pixels[2::3]))
        assert green >= 2
