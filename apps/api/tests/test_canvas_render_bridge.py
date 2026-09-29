"""Canvas → authoring 渲染桥测试（2026-09-29，Item 6）。

锁两件事：① 投影出的 WorkflowV2 形状让 v2 渲染栈认得出（storyboard 节点 +
completed 状态的 shot_video_segment slot + final-composition 节点 + audio_mode
none）；② 资产投影是**加法式**的——只补 workflow_asset_version 键，原
metadata 一个字节不动。
"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from app.services.creation.canvas_render_bridge import (
    BridgeShotV1,
    build_canvas_film_workflow,
    ensure_canvas_asset_projections,
)


def test_projected_workflow_shape_satisfies_the_v2_render_stack() -> None:
    workflow = build_canvas_film_workflow(
        workflow_id="adwf_v2_demo",
        project_id="proj_film_demo",
        name="拉片复刻成片",
        shots=[
            BridgeShotV1(index=1, asset_id="asset_a", asset_version_id="ver_a", duration_seconds=5.0),
            BridgeShotV1(index=2, asset_id="asset_b", asset_version_id=None, duration_seconds=6.0),
        ],
    )
    node_ids = {node.node_id for node in workflow.nodes}
    assert node_ids == {"storyboard", "final-composition"}

    storyboard = next(n for n in workflow.nodes if n.node_id == "storyboard")
    assert [item.shot_index for item in storyboard.items] == [1, 2]
    slot = storyboard.items[0].slots[0]
    assert slot.slot_type == "shot_video_segment"
    assert slot.status == "completed"  # 渲染结算只认 completed
    assert slot.selected_asset_id == "asset_a"

    final = next(n for n in workflow.nodes if n.node_id == "final-composition")
    assert final.items[0].slots[0].slot_type == "final_video"
    assert workflow.audio_mode == "none"  # 无 BGM：否则渲染栈索要 bgm slot


def test_asset_projection_is_additive(tmp_path) -> None:
    database = tmp_path / "v2" / "adcraft.sqlite3"
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    connection.execute(
        "create table asset_versions (asset_id text, version_id text, version_no integer,"
        " storage_key text, mime_type text, source_node_id text, source_slot_id text,"
        " metadata_json text)"
    )
    original_metadata = {"workflow_id": "adwf_v2_demo", "display_name": "镜头1"}
    connection.execute(
        "insert into asset_versions values (?, ?, ?, ?, ?, ?, ?, ?)",
        ("asset_a", "ver_a", 1, "assets/objects/x.mp4", "video/mp4", "node_1", None,
         json.dumps(original_metadata)),
    )
    connection.commit()
    connection.close()

    settings = SimpleNamespace(media_data_dir=tmp_path)
    patched = ensure_canvas_asset_projections(settings, ["asset_a", "asset_missing"])
    assert patched == 1  # 只处理存在的；缺资产不炸

    connection = sqlite3.connect(database)
    metadata = json.loads(
        connection.execute(
            "select metadata_json from asset_versions where asset_id = 'asset_a'"
        ).fetchone()[0]
    )
    connection.close()
    projection = metadata["workflow_asset_version"]
    assert projection["asset_id"] == "asset_a"
    assert projection["media_type"] == "video"
    assert projection["file_path"] == "assets/objects/x.mp4"
    assert projection["node_id"] == "node_1"
    # 原 metadata 原样保留
    assert metadata["workflow_id"] == "adwf_v2_demo"
    assert metadata["display_name"] == "镜头1"

    # 幂等：第二次不再补写
    assert ensure_canvas_asset_projections(settings, ["asset_a"]) == 0
