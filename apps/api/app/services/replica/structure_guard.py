"""拉片复刻 · 复刻结构恒等守卫（hypit gap 分析 P3 "swap 骨架恒等断言"）。

hypit 的经验：``swap-host.svml`` 与 ``reference.svml`` diff 346 行，但
**轨道/段落/锚点拓扑恒等**——变的是说话人/文本/配方引用，不变的是结构。
本模块把"复刻结构、不复刻像素"变成**可执行断言**：

- ``structure_diff(before, after)`` → 漂移清单（空 = 骨架恒等）；
- ``assert_same_structure(before, after)`` → 有漂移即抛 ``ReplicaStructureDrift``
  （携带逐条漂移，不写"结构不符"这种无法行动的消息）。

**允许变化的**：槽位替换值/应用位（``slots``：换人物/商品/风格/声音正是
复刻的目的）与一切派生自它们的展示字段。**不允许变化的**：镜头表拓扑
（数量/序号/时间窗）、段落拓扑（id/role/时间窗）、锚点拓扑（event_id/
挂靠段落/类型）、节奏切点、画幅与时长——改了这些，"复刻"就变成了另一条
片子，调用方必须显式决定而不是静默发生。

**故意不挂的路径（理由记录）**：``.adreplica`` **导入**。导入的语义正是
"作者手改文档"——删一行 ``<caption>``、加一个镜头都是合法编辑，在那里挂
恒等断言会把合法手改判成错误。守卫只挂在**系统生成派生图**的路径上
（变体渲染计划：换 skill/recipe 不得动结构），那是无人工决定的自动变换，
必须有机器看守。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.agent_canvas_ad_media import (
    ReplicaBlueprintContentV2,
    ReplicaShotV2,
)


class ReplicaStructureDrift(ValueError):
    """两份蓝图的复刻骨架不同（携带逐条漂移）。"""

    def __init__(self, drifts: tuple[str, ...]) -> None:
        self.drifts = drifts
        super().__init__("; ".join(drifts))


def _shot_signature(shot: ReplicaShotV2) -> tuple:
    """镜头骨架签名：序号 + 时间窗（**不含**文字/动作/提示——那些是内容）。"""
    return (shot.index, round(shot.start_seconds, 3), round(shot.end_seconds, 3))


def structure_diff(
    before: ReplicaBlueprintContentV2, after: ReplicaBlueprintContentV2
) -> tuple[str, ...]:
    """before → after 的骨架漂移清单（空 = 恒等）。

    逐项给出可行动的定位（哪个镜头/段落/锚点、期望什么、实际什么）——
    "结构不符"这种消息等于让人去 diff 两份 JSON。
    """
    drifts: list[str] = []

    # 画幅/时长：复刻的载体
    if before.aspect != after.aspect:
        drifts.append(f"aspect: {before.aspect!r} → {after.aspect!r}")
    if round(before.duration_seconds, 3) != round(after.duration_seconds, 3):
        drifts.append(
            f"duration_seconds: {before.duration_seconds} → {after.duration_seconds}"
        )

    # 镜头表拓扑
    before_shots = [_shot_signature(s) for s in before.shots]
    after_shots = [_shot_signature(s) for s in after.shots]
    if before_shots != after_shots:
        drifts.append(
            f"shots topology changed: {len(before.shots)} → {len(after.shots)} shots "
            f"({before_shots!r} → {after_shots!r})"
        )

    # 段落拓扑（id/role/时间窗；line/description/words 是内容不是骨架）
    def _beat_signature(b) -> tuple:
        return (b.beat_id, b.role, round(b.start_seconds, 3), round(b.end_seconds, 3))

    before_beats = [_beat_signature(b) for b in before.beats]
    after_beats = [_beat_signature(b) for b in after.beats]
    if before_beats != after_beats:
        drifts.append(
            f"beats topology changed: {len(before.beats)} → {len(after.beats)} beats "
            f"({[b[0] for b in before_beats]!r} → {[b[0] for b in after_beats]!r})"
        )

    # 锚点拓扑（事件身份 + 挂靠 + 类型；trigger/hint/keep 是内容或复刻时决策）
    def _anchor_signature(a) -> tuple:
        return (a.event_id, a.beat_id, a.kind)

    before_anchors = [_anchor_signature(a) for a in before.anchor_events]
    after_anchors = [_anchor_signature(a) for a in after.anchor_events]
    if before_anchors != after_anchors:
        drifts.append(
            f"anchor topology changed: {len(before.anchor_events)} → "
            f"{len(after.anchor_events)} events "
            f"({[a[0] for a in before_anchors]!r} → {[a[0] for a in after_anchors]!r})"
        )

    # 节奏切点（结构关系，不是内容）
    if [round(p, 3) for p in before.rhythm_cut_points_seconds] != [
        round(p, 3) for p in after.rhythm_cut_points_seconds
    ]:
        drifts.append("rhythm cut points changed")

    return tuple(drifts)


def assert_same_structure(
    before: ReplicaBlueprintContentV2, after: ReplicaBlueprintContentV2
) -> None:
    """骨架恒等断言（漂移即抛，携带逐条可行动定位）。"""
    drifts = structure_diff(before, after)
    if drifts:
        raise ReplicaStructureDrift(drifts)


@dataclass(frozen=True)
class StructureGuardReport:
    """守卫结果（供端点返回结构化错误或日志）。"""

    ok: bool
    drifts: tuple[str, ...]

    @classmethod
    def check(
        cls, before: ReplicaBlueprintContentV2, after: ReplicaBlueprintContentV2
    ) -> "StructureGuardReport":
        drifts = structure_diff(before, after)
        return cls(ok=not drifts, drifts=drifts)
