"""拉片复刻 · direct-execute 快车道（可行性门 + 零模型费计划）。

调研档 P3：纯字幕/MG 短片不调生成模型直出。**完整直出渲染器属于剪辑域**
（ADR 0008 两相位时间线 + editing 合成；.adreplica/蓝图只编译到画布节点，
不建第二执行链——§3.5 编译边界）。本模块提供渲染器前面缺失的那块：
**确定性的可行性门**——逐条检查蓝图，把复刻工作分类为：

- ``zero_model_steps``：字幕（drawtext）、音效库、音乐库、剪辑合成——
  零生成模型费即可执行；
- ``generation_steps``：镜头画面、角色一致性、语音合成——必须走生成；
- ``blockers``：连执行对象都没有的结构缺口（无镜头表等）。

``feasible`` = 零模型费可直出（generation_steps 与 blockers 均为空）。
判定规则（确定性，无 LLM）：

- 镜头：主体为纯屏上文字（``on_screen_text`` 非空且无 ``subject_action``）
  → 字幕渲染可出，零模型费；否则画面必须生成；
- 语音：任一段落有台词原文（``line``）→ 需语音合成（TTS 是模型调用）；
- 槽位：人物/商品已应用替换 → 需生成对应主体画面（蓝图不携带像素源）。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2


@dataclass(frozen=True)
class DirectExecutePlan:
    """direct-execute 可行性判定结果（可查询、可展示、无感觉成分）。"""

    feasible: bool
    blockers: tuple[str, ...]
    zero_model_steps: tuple[dict, ...]
    generation_steps: tuple[dict, ...]
    #: P4 pace 预检告警（预估口播时长超出段落窗的台词）。**不影响 feasible**：
    #: 这是内容问题不是成本问题——门回答"能不能零模型费直出"，pace 回答
    #: "这句台词念不念得完"。告警逐条可行动（删词 or 加窗）。
    pace_warnings: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {
            "feasible": self.feasible,
            "blockers": list(self.blockers),
            "zero_model_steps": list(self.zero_model_steps),
            "generation_steps": list(self.generation_steps),
            "pace_warnings": list(self.pace_warnings),
        }


def _step(step: str, detail: str) -> dict:
    return {"step": step, "detail": detail}


def plan_direct_execute(blueprint: ReplicaBlueprintContentV2) -> DirectExecutePlan:
    """蓝图 → direct-execute 可行性判定（纯函数，确定性）。"""
    blockers: list[str] = []
    zero_model: list[dict] = []
    generation: list[dict] = []

    if not blueprint.shots:
        blockers.append("蓝图无镜头表（未拆解或空蓝图），没有可执行对象")
    if not blueprint.beats:
        blockers.append("蓝图无结构段落，无法排布时间线")

    # 镜头：纯屏上文字镜头可由字幕渲染直出；其余需画面生成
    for shot in blueprint.shots:
        is_pure_text = bool(shot.on_screen_text.strip()) and not shot.subject_action.strip()
        if is_pure_text:
            zero_model.append(
                _step(
                    f"shot_{shot.index}",
                    f"纯屏上文字镜头（「{shot.on_screen_text}」）→ 字幕渲染直出",
                )
            )
        else:
            reason = "有画面主体（动作/场景描述）"
            if shot.recreate_hint:
                reason = f"复刻提示：{shot.recreate_hint}"
            generation.append(
                _step(f"shot_{shot.index}", f"镜头画面需生成（{reason}）")
            )

    # 语音：有台词 → TTS（模型调用）
    spoken = [beat for beat in blueprint.beats if beat.line.strip()]
    if spoken:
        generation.append(
            _step("voice", f"台词语音合成（{len(spoken)} 段台词需要 TTS）")
        )

    # P4 pace 预检（零成本）：每段台词的预估口播时长 vs 它的段落窗。
    # 超窗不拦截（内容问题不是成本问题），但必须在花钱合成前说出来。
    from app.services.replica.estimate import estimate_beat_pace

    pace_warnings: list[dict] = []
    for beat in spoken:
        window = max(0.0, beat.end_seconds - beat.start_seconds)
        check = estimate_beat_pace(text=beat.line, window_seconds=window)
        if not check["fits"]:
            pace_warnings.append(
                {
                    "beat_id": beat.beat_id,
                    "role": beat.role,
                    "text": beat.line,
                    **check,
                }
            )
    # 槽位：人物/商品替换已应用 → 需生成对应主体
    for slot in blueprint.slots:
        if slot.applied and slot.kind in {"character", "product"}:
            generation.append(
                _step(f"slot_{slot.kind}", f"替换主体「{slot.replace_with}」需生成参考/画面")
            )

    # 零模型费环节
    caption_beats = [beat for beat in blueprint.beats if beat.line.strip()]
    if blueprint.systems_captions.strip() or caption_beats:
        zero_model.append(
            _step("captions", "字幕系统 → drawtext/字幕渲染（零模型费）")
        )
    if blueprint.systems_sfx:
        zero_model.append(
            _step("sfx", f"音效 {len(blueprint.systems_sfx)} 项 → 音效库")
        )
    if blueprint.systems_music.strip():
        zero_model.append(_step("music", "配乐 → BGM 库（零模型费）"))
    zero_model.append(_step("editing", "剪辑合成 → 既有 editing 引擎（零模型费）"))

    feasible = not blockers and not generation
    return DirectExecutePlan(
        feasible=feasible,
        blockers=tuple(blockers),
        zero_model_steps=tuple(zero_model),
        generation_steps=tuple(generation),
        pace_warnings=tuple(pace_warnings),
    )
