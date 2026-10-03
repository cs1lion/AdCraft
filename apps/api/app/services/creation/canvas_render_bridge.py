"""Canvas → authoring 渲染桥（2026-09-29，Item 5 收尾）。

v2 final-composition 渲染栈綁定 authoring 存储，而真实工作流全在
agent_canvas_workflows（两座存储岛）。本模块搭一座单向桥：把画布上已
生成的镜头投影成一个最小 WorkflowV2（storyboard 节点 + 每镜
shot_video_segment slot 带选中资产 + final-composition 节点），写入
authoring 存储——此后标准的 get_timeline / start_render 全部够得着，
不建第二执行链（ADR 0010），渲染仍走 v2 渲染服务。

投影刷新：已桥接工作流按最新镜头重建；最终时间线保留用户编辑策略。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.schemas.workflow_v2 import (
    WorkflowItemV2,
    WorkflowNodeV2,
    WorkflowSlotV2,
    WorkflowV2,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BridgeShotV1:
    index: int
    asset_id: str
    asset_version_id: str | None
    duration_seconds: float


def build_canvas_film_workflow(
    *,
    workflow_id: str,
    project_id: str | None,
    name: str,
    shots: list[BridgeShotV1],
    composition_plan_hash: str | None = None,
    audio_mode: str = "none",
) -> WorkflowV2:
    now = datetime.now(timezone.utc).isoformat()
    shot_items = tuple(
        WorkflowItemV2(
            item_id=f"shot_{shot.index}",
            node_id="storyboard",
            item_type="shot",
            display_name=f"镜头 {shot.index}",
            shot_id=f"shot_{shot.index}",
            shot_index=shot.index,
            duration_seconds=shot.duration_seconds,
            slots=(
                WorkflowSlotV2(
                    slot_id=f"shot_video_segment_{shot.index}",
                    node_id="storyboard",
                    item_id=f"shot_{shot.index}",
                    slot_type="shot_video_segment",
                    media_type="video",
                    # 事实状态：这些镜头已经在画布上生成完毕（渲染桥只投影既成事实）。
                    status="completed",
                    selected_asset_id=shot.asset_id,
                    selected_version_id=shot.asset_version_id,
                ),
            ),
        )
        for shot in sorted(shots, key=lambda s: s.index)
    )
    final_item = WorkflowItemV2(
        item_id="final_composition",
        node_id="final-composition",
        item_type="final_composition",
        display_name="Final Composition",
        slots=(
            WorkflowSlotV2(
                slot_id="final_video",
                node_id="final-composition",
                item_id="final_composition",
                slot_type="final_video",
                media_type="video",
            ),
        ),
    )
    return WorkflowV2(
        workflow_id=workflow_id,
        project_id=project_id,
        name=name,
        description="拉片复刻一键成片（canvas → authoring 桥接投影）",
        prompt="拉片复刻一键成片",
        audio_mode=audio_mode,
        metadata={"replica_composition_plan_hash": composition_plan_hash}
        if composition_plan_hash
        else {},
        created_at=now,
        updated_at=now,
        nodes=(
            WorkflowNodeV2(
                node_id="storyboard",
                node_type="storyboard",
                title="Storyboard",
                status="ready",
                items=shot_items,
            ),
            WorkflowNodeV2(
                node_id="final-composition",
                node_type="final_composition",
                title="Final Composition",
                status="ready",
                items=(final_item,),
            ),
        ),
    )


def ensure_canvas_asset_projections(settings, asset_ids: list[str]) -> int:
    """给画布资产补 v2 渲染所需的 metadata 投影（加法式，不动原 metadata）。

    v2 渲染栈的 `load_asset_version` 要求 asset_versions.metadata 里有
    `workflow_asset_version`（WorkflowAssetVersionV2）投影；画布资产只带
    自己的 facts。这里从行内既有字段派生投影并写回——不新建、不覆写
    （原 metadata_json 整体保留，仅追加该键）。返回补写的条数。
    """

    if not asset_ids:
        return 0
    import sqlite3

    database = settings.media_data_dir / "v2" / "adcraft.sqlite3"
    patched = 0
    connection = sqlite3.connect(database)
    try:
        for asset_id in asset_ids:
            row = connection.execute(
                "select version_id, storage_key, mime_type, source_node_id,"
                " source_slot_id, metadata_json from asset_versions"
                " where asset_id = ? order by version_no desc limit 1",
                (asset_id,),
            ).fetchone()
            if row is None:
                continue
            version_id, storage_key, mime_type, node_id, slot_id, metadata_json = row
            metadata = json.loads(metadata_json or "{}")
            if isinstance(metadata.get("workflow_asset_version"), dict):
                continue
            projection = {
                "asset_id": asset_id,
                "version_id": version_id,
                "media_type": str(mime_type or "").split("/")[0] or "video",
                "source_type": "generated",
                "file_path": storage_key,
                "workflow_id": metadata.get("workflow_id"),
                "node_id": node_id or metadata.get("source_node_id"),
                "slot_id": slot_id or metadata.get("source_slot_id"),
            }
            metadata["workflow_asset_version"] = projection
            connection.execute(
                "update asset_versions set metadata_json = ? where asset_id = ? and version_id = ?",
                (json.dumps(metadata, ensure_ascii=False), asset_id, version_id),
            )
            patched += 1
        connection.commit()
    finally:
        connection.close()
    return patched


def _reset_bridged_workflow(settings, workflow_id: str) -> None:
    """删掉本桥此前写入的 authoring 投影（workflows/revisions/events 三表中的该
    workflow 行），使投影可按最新镜头重建。画布才是事实源，重建永远安全。"""

    from app.services.v2_workflow_authoring import create_workflow_authoring_runtime

    bridge_project_id = f"proj_film_{workflow_id.removeprefix('adwf_v2_')[-12:]}"
    # 与 create_planned_workflow 同一个引擎/连接池，避免跨连接的事务可见性错位。
    runtime = create_workflow_authoring_runtime(settings.media_data_dir)
    with runtime.database.engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            # FK 顺序：workflows.current_revision_id 引用 revisions，先置空再删。
            connection.exec_driver_sql(
                "update workflows set current_revision_id = NULL where workflow_id = ?",
                (workflow_id,),
            )
            for table in ("workflow_events", "workflow_revisions", "workflows"):
                connection.exec_driver_sql(
                    f"delete from {table} where workflow_id = ?", (workflow_id,)
                )
            # 桥接项目同属投影产物，一并删除以便重建（画布项目不受影响）。
            connection.exec_driver_sql(
                "delete from projects where project_id = ?", (bridge_project_id,)
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def _already_bridged(runtime, workflow_id: str) -> bool:
    try:
        runtime.read_model.assemble(workflow_id)
        return True
    except Exception:  # noqa: BLE001 - 未桥接判定：read model 对缺失工作流抛多种异常
        return False


def bridge_canvas_workflow(
    settings,
    workflow_id: str,
    project_id: str | None,
    name: str,
    shots: list[BridgeShotV1],
    *,
    composition_plan_hash: str | None = None,
    audio_mode: str = "none",
) -> bool:
    """把画布工作流投影进 authoring 存储。返回是否新建了投影。

    投影挂在**专属桥接项目**（proj_film_*）下而不是画布自己的 project：
    projects 表是两套存储共享的，直接复用画布 project_id 会撞 UNIQUE。
    桥接项目建后即归档——它是渲染投影，不占用户的项目列表。
    """

    from app.persistence.project_repository import ProjectRepository
    from app.services.v2_workflow_authoring import create_workflow_authoring_runtime

    runtime = create_workflow_authoring_runtime(settings.media_data_dir)
    if _already_bridged(runtime, workflow_id):
        # 投影常新：镜头增减/状态变化后重建，而不是复用过期文档。
        _reset_bridged_workflow(settings, workflow_id)
    bridge_project_id = f"proj_film_{workflow_id.removeprefix('adwf_v2_')[-12:]}"
    workflow = build_canvas_film_workflow(
        workflow_id=workflow_id,
        project_id=bridge_project_id,
        name=name,
        shots=shots,
        composition_plan_hash=composition_plan_hash,
        audio_mode=audio_mode,
    )
    runtime.service.create_planned_workflow(workflow)
    try:
        ProjectRepository(runtime.database).update(
            bridge_project_id,
            expected_version=1,
            changes={"status": "archived"},
        )
    except Exception as exc:  # noqa: BLE001 - 归档是 best-effort，失败不挡渲染
        # 归档失败不挡渲染：项目列表里多一条投影可见，但片子出得来说得上。
        logger.warning("bridge project archive failed for %s: %s", bridge_project_id, exc)
    return True
