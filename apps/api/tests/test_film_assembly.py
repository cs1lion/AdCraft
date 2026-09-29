"""S8 镜头合成规划测试（2026-09-29 简约好用分支，canvas 时间线版）。"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.creation.film_assembly import plan_assembly


def _node(node_id: str, title: str, asset_id: str, duration: float = 5.0) -> SimpleNamespace:
    return SimpleNamespace(
        node_id=node_id,
        node_type="video",
        title=title,
        output_asset_id=asset_id,
        output_asset_version_id=f"version_{asset_id}",
        structured_content={"duration_seconds": duration},
    )


def test_plan_orders_by_shot_and_stacks_time_on_the_video_track() -> None:
    nodes = [
        _node("n3", "复刻镜头3", "asset_c", 4.0),
        _node("n1", "复刻镜头1", "asset_a", 5.0),
        _node("n2", "复刻镜头2", "asset_b", 6.0),
    ]
    plan = plan_assembly("track_v", nodes)
    assert [p.source_node_id for p in plan.placements] == ["n1", "n2", "n3"]
    assert [p.start_time for p in plan.placements] == [0.0, 5.0, 11.0]
    assert all(p.track_id == "track_v" for p in plan.placements)
    assert all(p.asset_version_id for p in plan.placements)


def test_plan_skips_nodes_without_output() -> None:
    nodes = [_node("n1", "复刻镜头1", "asset_a"), _node("n2", "复刻镜头2", "")]
    plan = plan_assembly("track_v", nodes)
    assert [p.asset_id for p in plan.placements] == ["asset_a"]
