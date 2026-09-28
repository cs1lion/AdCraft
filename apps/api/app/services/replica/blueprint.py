"""拉片复刻 · 复刻蓝图（Replica Blueprint）。

把 teardown 报告升级为**可编辑、可实例化**的复刻蓝图——拉片复刻从"读片"
进入"复刻"半场。设计对应 hypit 的三个工程概念：

1. **槽位（slots）**：结构 DNA 与物质素材分离（hypit 的组件化替换）。
   蓝图固定不变的是 beats/shots/锚点关系；人/货/词/风格/声音是槽位。
2. **锚点事件（anchor events）**：挂在结构段落上的 B-roll/字幕/音效/MG
   触发器（hypit 的 ``@{id}`` 词锚定的 MVP 形态；WhisperX 词级对齐落地
   后升级为真词锚定，见 docs/plans/replica-teardown.md P1）。
3. **实例化（instantiate）**：蓝图 → Canvas 节点创建请求，执行仍走既有
   工作流引擎——不引入第二套执行链路（hypit 的 Runtime 对应物）。

本模块全部为纯函数/纯数据：无 IO、无 LLM、无 HTTP，便于完整单测。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.schemas.agent_canvas_ad_media import (
    ReplicaAnchorEventV2,
    ReplicaBeatV2,
    ReplicaBeatWordV2,
    ReplicaBlueprintContentV2,
    ReplicaShotV2,
    ReplicaSlotV2,
)
from app.services.replica.narrative import (
    narrative_from_blueprint,
    narrative_selection_tokens,
    project_seconds,
    selection_text,
    token_end_anchor,
    token_range_for_text,
    token_start_anchor,
)

BLUEPRINT_VERSION = "replica-blueprint-v1"

#: 默认槽位：kind → 中文标签（source_value 由拆解报告/目标填充）
_DEFAULT_SLOTS: tuple[tuple[str, str], ...] = (
    ("character", "人物"),
    ("product", "商品"),
    ("script", "台词"),
    ("style", "风格"),
    ("voice", "声音"),
)

#: 复刻目标 → 预填的槽位 source_value 提示（来自端点的 goal 文案）
_GOAL_HINTS: dict[str, str] = {
    "换商品": "product",
    "换人物": "character",
    "换演员": "character",
    "换台词": "script",
    "换风格": "style",
}


# ---------------------------------------------------------------------------
# teardown 报告 → 蓝图
# ---------------------------------------------------------------------------


def blueprint_from_teardown(
    report: dict,
    *,
    source_asset_id: str = "",
    duration_seconds: float = 0.0,
    aspect: str = "",
    replica_goal: str = "",
) -> ReplicaBlueprintContentV2:
    """把 teardown 报告（TeardownReport dict）转换为复刻蓝图。

    纯函数：相同输入永远得到相同蓝图（实测锁定）。
    """
    reading = str(report.get("whole_piece_reading") or "")
    format_name = str(report.get("format_name") or "short-video")

    shots = _blueprint_shots(report)
    beats, anchor_events = _blueprint_beats(report, shots)
    slots = _blueprint_slots(replica_goal)
    transcript_words = _transcript_words(report)

    rhythm = report.get("rhythm") or {}
    systems = report.get("systems") or {}

    blueprint = ReplicaBlueprintContentV2(
        blueprint_version=BLUEPRINT_VERSION,
        source_video_asset_id=source_asset_id,
        duration_seconds=max(0.0, float(duration_seconds or 0.0)),
        aspect=aspect,
        replica_goal=replica_goal,
        whole_piece_reading=reading,
        format_name=format_name,
        slots=slots,
        beats=beats,
        anchor_events=anchor_events,
        shots=shots,
        rhythm_avg_shot_seconds=_as_float(rhythm.get("avg_shot_seconds")),
        rhythm_cut_points_seconds=[
            _as_float(c) for c in (rhythm.get("cut_points_seconds") or [])
        ],
        rhythm_energy_curve=str(rhythm.get("energy_curve") or ""),
        systems_captions=str(systems.get("captions") or ""),
        systems_music=str(systems.get("music") or ""),
        systems_graphics=[str(g) for g in (systems.get("graphics") or [])],
        systems_sfx=[str(s) for s in (systems.get("sfx") or [])],
        constraints=[str(c) for c in (report.get("constraints") or [])],
        instantiated_script_node_id=None,
    )
    # G4：token 区间绑定 + 秒数投影。reproject 在这里是**不变量强制**——
    # "节点里存的秒数永远是当前词流对 binding 的投影"由构造保证（新鲜路径
    # 上幂等；将来重新对齐/重配音触发重投影时，同一个函数就是入口）。
    return reproject_anchor_seconds(resolve_word_anchors(blueprint, transcript_words))


def _transcript_words(report: dict) -> list[dict]:
    """报告里的词级转录词流（无转录时为空列表）。"""
    transcript = report.get("transcript") or {}
    if not isinstance(transcript, dict):
        return []
    raw_words = transcript.get("words") or []
    if not isinstance(raw_words, list):
        return []
    return [w for w in raw_words if isinstance(w, dict)]


def _as_float(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return number if number == number else 0.0


def _blueprint_shots(report: dict) -> list[ReplicaShotV2]:
    shots: list[ReplicaShotV2] = []
    for i, raw in enumerate(report.get("shots") or [], start=1):
        if not isinstance(raw, dict):
            continue
        shots.append(
            ReplicaShotV2(
                index=i,
                start_seconds=_as_float(raw.get("start_seconds")),
                end_seconds=_as_float(raw.get("end_seconds")),
                shot_size=str(raw.get("shot_size") or "medium"),
                camera_motion=str(raw.get("camera_motion") or "static"),
                subject_action=str(raw.get("subject_action") or ""),
                on_screen_text=str(raw.get("on_screen_text") or ""),
                transition_to_next=str(raw.get("transition_to_next") or "cut"),
                recreate_hint=str(raw.get("note") or ""),
            )
        )
    return shots


def _blueprint_beats(
    report: dict, shots: list[ReplicaShotV2]
) -> tuple[list[ReplicaBeatV2], list[ReplicaAnchorEventV2]]:
    """结构段落 + 锚点事件。

    锚点事件 MVP 派生规则（全部来自拆解数据，无编造）：
    - 每个段落生成 1 个 ``caption`` 锚点（trigger=段落 role），提示"新文案
      写到该段落时此处挂字幕"；
    - 落在该段落时间窗内、且带屏上文字或 recreate_hint 的镜头，生成
      ``broll``/``caption`` 锚点（trigger=屏上文字前 12 字）。
    """
    beats: list[ReplicaBeatV2] = []
    anchor_events: list[ReplicaAnchorEventV2] = []
    for i, raw in enumerate(report.get("beats") or [], start=1):
        if not isinstance(raw, dict):
            continue
        beat_id = f"b{i}"
        start = _as_float(raw.get("start_seconds"))
        end = _as_float(raw.get("end_seconds"))
        role = str(raw.get("role") or "body")

        anchor_ids: list[str] = []
        anchors: list[ReplicaAnchorEventV2] = []

        caption_anchor = ReplicaAnchorEventV2(
            event_id=f"{beat_id}_caption",
            trigger=f"{role} 段落",
            beat_id=beat_id,
            kind="caption",
            hint="新文案写到这一段时，此处挂字幕/关键词高亮",
            keep=True,
        )
        anchors.append(caption_anchor)
        anchor_events.append(caption_anchor)
        anchor_ids.append(f"{beat_id}_caption")

        for shot in shots:
            midpoint = (shot.start_seconds + shot.end_seconds) / 2
            if not (start <= midpoint <= end):
                continue
            if shot.on_screen_text and shot.on_screen_text != "无":
                event_id = f"{beat_id}_shot{shot.index}_cap"
                cap_anchor = ReplicaAnchorEventV2(
                    event_id=event_id,
                    trigger=shot.on_screen_text[:12],
                    beat_id=beat_id,
                    kind="caption",
                    hint=f"对应第 {shot.index} 个镜头的屏上文字系统",
                    keep=True,
                )
                anchors.append(cap_anchor)
                anchor_events.append(cap_anchor)
                anchor_ids.append(event_id)
            if shot.recreate_hint:
                event_id = f"{beat_id}_shot{shot.index}_broll"
                broll_anchor = ReplicaAnchorEventV2(
                    event_id=event_id,
                    trigger=shot.subject_action[:12] or f"第{shot.index}镜",
                    beat_id=beat_id,
                    kind="broll",
                    hint=shot.recreate_hint,
                    keep=True,
                )
                anchors.append(broll_anchor)
                anchor_events.append(broll_anchor)
                anchor_ids.append(event_id)

        beats.append(
            ReplicaBeatV2(
                beat_id=beat_id,
                role=role,
                description=str(raw.get("description") or ""),
                line=str(raw.get("line") or ""),
                start_seconds=start,
                end_seconds=end,
                anchor_event_ids=anchor_ids,
            )
        )
    return beats, anchor_events


def _blueprint_slots(replica_goal: str) -> list[ReplicaSlotV2]:
    """默认五槽；goal 命中关键词时给对应槽位一个 source_value 提示。"""
    focused = ""
    for keyword, kind in _GOAL_HINTS.items():
        if keyword in replica_goal:
            focused = kind
            break
    slots: list[ReplicaSlotV2] = []
    for kind, label in _DEFAULT_SLOTS:
        source_value = ""
        if kind == focused:
            prefix = "复刻目标："
            focused_value = replica_goal if replica_goal.startswith(prefix) else f"{prefix}{replica_goal}"
            source_value = focused_value
        elif kind == "script":
            source_value = "保留原片台词结构与节奏，可整体重写"
        slots.append(
            ReplicaSlotV2(
                kind=kind,  # type: ignore[arg-type]
                label=label,
                source_value=source_value,
            )
        )
    return slots


# ---------------------------------------------------------------------------
# 词级锚定解析（whisperX 词流 → 锚点事件绑定具体词）
# ---------------------------------------------------------------------------


def resolve_word_anchors(
    blueprint: ReplicaBlueprintContentV2,
    transcript_words: list[dict] | tuple[dict, ...],
) -> ReplicaBlueprintContentV2:
    """把锚点事件解析到转录词流的具体词上（hypit ``@{word}`` 的数据层）。

    规则（确定性，无 LLM）：
    - 触发文本（``trigger``）需 ≥2 字符，在**所属段落时间窗内**的词流拼接
      文本里做子串匹配（中文无分词，拼接后匹配）；
    - 命中 → ``word`` = 触发文本、``word_start/end_seconds`` = 覆盖的首末词
      时间跨度；未命中 → 保持段落级（word=""）；
    - 锚不出段落：只搜本段落窗内的词。

    相同输入永远得到相同输出（纯函数，实测锁定）。
    """
    if not transcript_words:
        return blueprint
    events_by_id = {e.event_id: e for e in blueprint.anchor_events}
    new_events: list[ReplicaAnchorEventV2] = []
    # G4：授权序一次性建好——锚点除了记"词文本 + 秒数"（投影的当前值），
    # 还记 token 区间（与帧时间解耦的 binding）。秒数会过期，binding 不会。
    narrative = narrative_from_blueprint(blueprint)
    for event in blueprint.anchor_events:
        needle = event.trigger.strip()
        beat = next(
            (b for b in blueprint.beats if b.beat_id == event.beat_id), None
        )
        if beat is None:
            new_events.append(event)
            continue
        if len(needle) < 2:
            needle = ""
        window = _words_in_window(transcript_words, beat.start_seconds, beat.end_seconds)
        span = _match_word_span(window, needle, affinity=event.affinity) if needle else None
        if span is None and event.kind == "caption" and beat.line.strip():
            # 字幕锚点兜底：触发词未命中时绑定整句台词（字幕本就覆盖整句）
            needle = beat.line.strip()
            span = _match_word_span(window, needle, affinity=event.affinity)
        if span is None or not needle:
            new_events.append(event)
            continue
        word_start, word_end = span
        token_range = token_range_for_text(narrative, beat.beat_id, needle)
        new_events.append(
            event.model_copy(
                update={
                    "word": needle,
                    "word_start_seconds": round(word_start, 3),
                    "word_end_seconds": round(word_end, 3),
                    **(
                        {
                            "start_token_id": token_range[0],
                            "end_token_id": token_range[1],
                        }
                        if token_range
                        else {}
                    ),
                }
            )
        )
    del events_by_id

    # 词级 karaoke（G3 后半）：段落词窗从同一词流按段落时间窗归集。
    # 与锚点解析同源（中点归窗），但归属规则是**单归宿**——``[start, end)``，
    # 收尾段闭口：共享规则的包含端点会让边界词同时归两段（锚点匹配无害，
    # 词级字幕会重复渲染同一个词）。确定性优先，无转录时保持 identity。
    words_by_beat: dict[str, list[ReplicaBeatWordV2]] = {
        beat.beat_id: [] for beat in blueprint.beats
    }
    if words_by_beat:
        last_beat_id = blueprint.beats[-1].beat_id
        for raw in transcript_words:
            if not isinstance(raw, dict):
                continue
            try:
                w_start = float(raw.get("start_seconds", 0.0))
                w_end = float(raw.get("end_seconds", w_start))
            except (TypeError, ValueError):
                continue
            text = str(raw.get("text") or "")
            if not text.strip():
                continue
            midpoint = (w_start + w_end) / 2
            target = next(
                (
                    beat
                    for beat in blueprint.beats
                    if beat.start_seconds <= midpoint < beat.end_seconds
                ),
                None,
            )
            if target is None and midpoint >= blueprint.beats[-1].start_seconds:
                # 段落表没覆盖到的尾部词归最后一段（不丢词、不造词）
                target = blueprint.beats[-1]
            if target is None:
                continue
            try:
                words_by_beat[target.beat_id].append(
                    ReplicaBeatWordV2(
                        text=text,
                        start_seconds=round(w_start, 3),
                        end_seconds=round(w_end, 3),
                    )
                )
            except (TypeError, ValueError):
                continue  # 坏词条目逐项跳过（转录数据不可信）
    new_beats = [
        beat.model_copy(update={"words": words_by_beat.get(beat.beat_id, [])})
        for beat in blueprint.beats
    ]
    del last_beat_id
    return blueprint.model_copy(
        update={"anchor_events": new_events, "beats": new_beats}
    )


def reproject_anchor_seconds(
    blueprint: ReplicaBlueprintContentV2,
) -> ReplicaBlueprintContentV2:
    """把锚点秒数从**当前**授权序 + 词流重算（hypit "时间是投影"的兑付）。

    解决的正是锚定与时间耦合的老问题：改台词/重转写/换词流之后，锚点
    的 binding（token 区间）不变，秒数是重新投影的结果——

    - token 区间能在当前授权序里取到、且能在当前词流里投出时间 → 更新
      秒数，并用 token 区间的文本刷新词面绑定（词面也是投影）；
    - 投不出（词不在新词流里/无转录/区间失效）→ **清除词级绑定**退回
      段落级。不保留过期秒数——"看起来对的时间"比"没有时间"更坏。

    纯函数；无 token 区间的旧锚点原样保留（向后兼容）。
    """
    narrative = narrative_from_blueprint(blueprint)
    beats_by_id = {beat.beat_id: beat for beat in blueprint.beats}
    new_events: list[ReplicaAnchorEventV2] = []
    for event in blueprint.anchor_events:
        if not (event.start_token_id and event.end_token_id):
            new_events.append(event)
            continue
        start_token = narrative.token(event.start_token_id)
        end_token = narrative.token(event.end_token_id)
        if start_token is None or end_token is None:
            new_events.append(
                event.model_copy(
                    update={
                        "word": "",
                        "word_start_seconds": 0.0,
                        "word_end_seconds": 0.0,
                        "start_token_id": "",
                        "end_token_id": "",
                    }
                )
            )
            continue
        try:
            tokens = narrative_selection_tokens(
                narrative,
                token_start_anchor(event.start_token_id),
                token_end_anchor(event.end_token_id),
            )
        except (KeyError, ValueError):
            new_events.append(
                event.model_copy(
                    update={
                        "word": "",
                        "word_start_seconds": 0.0,
                        "word_end_seconds": 0.0,
                        "start_token_id": "",
                        "end_token_id": "",
                    }
                )
            )
            continue
        beat = beats_by_id.get(start_token.segment_id)
        projected = project_seconds(beat, tokens) if beat is not None else None
        if projected is None:
            new_events.append(
                event.model_copy(
                    update={
                        "word": "",
                        "word_start_seconds": 0.0,
                        "word_end_seconds": 0.0,
                    }
                )
            )
            continue
        new_events.append(
            event.model_copy(
                update={
                    "word": selection_text(tokens),
                    "word_start_seconds": projected[0],
                    "word_end_seconds": projected[1],
                }
            )
        )
    return blueprint.model_copy(update={"anchor_events": new_events})


def _words_in_window(
    words: list[dict] | tuple[dict, ...], start: float, end: float
) -> list[dict]:
    """落在段落时间窗内的词（按词中点归窗，与镜头归属规则一致）。"""
    selected: list[dict] = []
    for raw in words:
        try:
            w_start = float(raw.get("start_seconds", 0.0))
            w_end = float(raw.get("end_seconds", w_start))
        except (TypeError, ValueError):
            continue
        midpoint = (w_start + w_end) / 2
        if start <= midpoint <= end:
            selected.append(
                {
                    "text": str(raw.get("text") or ""),
                    "start_seconds": w_start,
                    "end_seconds": w_end,
                }
            )
    return selected


def _match_word_span(
    window_words: list[dict],
    needle: str,
    *,
    affinity: Literal["left", "right"] = "right",
) -> tuple[float, float] | None:
    """在窗口词流的拼接文本里找触发文本，返回覆盖的时间跨度。

    端点按 ``affinity`` 取（hypit 词锚的 left/right 语义）：
    - ``right``（默认）：起 = 首词首，止 = 末词**后**下一词首（间隙归前一事件）；
    - ``left``：起 = 首词**前**上一词尾，止 = 末词尾（间隙归后一事件）。
    越出窗口时退到可用的真实端点（不造时间）。
    """
    # 字符 → 词下标映射：中文无分词，拼接后做子串匹配，再映射回词边界
    char_word_index: list[int] = []
    parts: list[str] = []
    for index, word in enumerate(window_words):
        text = str(word["text"])
        parts.append(text)
        char_word_index.extend([index] * len(text))
    stream = "".join(parts)
    position = stream.find(needle)
    if position < 0 or position + len(needle) > len(char_word_index):
        return None
    first_index = char_word_index[position]
    last_index = char_word_index[position + len(needle) - 1]
    # right(默认): 起=首词首, 止=末词尾——窗口紧贴词, 间隙归相邻事件
    # left:  起=上一词尾(若有,否则首词首), 止=下一词首(若有,否则末词尾)
    #        ——窗口把间隙纳入自身, 与 right 互补(两事件相邻时恰好拼满间隙)
    if affinity == "right":
        start = float(window_words[first_index]["start_seconds"])
        end = float(window_words[last_index]["end_seconds"])
    else:
        start = (
            float(window_words[first_index - 1]["end_seconds"])
            if first_index > 0
            else float(window_words[first_index]["start_seconds"])
        )
        end = (
            float(window_words[last_index + 1]["start_seconds"])
            if last_index + 1 < len(window_words)
            else float(window_words[last_index]["end_seconds"])
        )
    return (start, end)


# ---------------------------------------------------------------------------
# 槽位编辑
# ---------------------------------------------------------------------------


def apply_slot_updates(
    blueprint: ReplicaBlueprintContentV2,
    updates: dict[str, str],
) -> ReplicaBlueprintContentV2:
    """应用槽位替换：{slot_kind: replace_with}。

    空字符串 = 清除替换（回到原片值）。applied 由 replace_with 是否非空决定。
    返回新对象（pydantic model_copy 深拷贝语义由 model_copy 保证）。
    """
    if not updates:
        return blueprint
    new_slots: list[ReplicaSlotV2] = []
    for slot in blueprint.slots:
        if slot.kind in updates:
            value = str(updates[slot.kind] or "").strip()
            new_slots.append(
                slot.model_copy(
                    update={"replace_with": value, "applied": bool(value)}
                )
            )
        else:
            new_slots.append(slot)
    return blueprint.model_copy(update={"slots": new_slots})


def toggle_anchor_event(
    blueprint: ReplicaBlueprintContentV2, event_id: str, keep: bool
) -> ReplicaBlueprintContentV2:
    """保留/移除某个锚点事件（复刻时增删系统，hypit transformations 透镜）。"""
    if not blueprint.beats:
        return blueprint
    # 从持久化的锚点事件反查所属段落：移除后 beat 列表里已无该 id，
    # 只有 anchor_events（带 beat_id）还能找到它——恢复路径依赖这一点。
    event = next((e for e in blueprint.anchor_events if e.event_id == event_id), None)
    if event is None:
        return blueprint
    target_beat = next(
        (b for b in blueprint.beats if b.beat_id == event.beat_id), None
    )
    if target_beat is None:
        return blueprint
    if keep:
        new_ids = [
            eid for eid in target_beat.anchor_event_ids if eid != event_id
        ]
        new_ids.append(event_id)
    else:
        new_ids = [eid for eid in target_beat.anchor_event_ids if eid != event_id]
    new_beats = [
        b.model_copy(update={"anchor_event_ids": new_ids})
        if b.beat_id == target_beat.beat_id
        else b
        for b in blueprint.beats
    ]
    new_events = [
        e.model_copy(update={"keep": keep}) if e.event_id == event_id else e
        for e in blueprint.anchor_events
    ]
    return blueprint.model_copy(
        update={"beats": new_beats, "anchor_events": new_events}
    )


# ---------------------------------------------------------------------------
# 复刻脚本渲染（确定性，不调 LLM）
# ---------------------------------------------------------------------------


def render_replica_script(blueprint: ReplicaBlueprintContentV2) -> str:
    """把蓝图渲染为中文复刻脚本（script 节点的 structured_content）。"""
    lines: list[str] = []
    lines.append("# 复刻脚本（拉片复刻 · replica-blueprint-v1）")
    if blueprint.replica_goal:
        lines.append(f"复刻目标：{blueprint.replica_goal}")
    lines.append(f"格式：{blueprint.format_name}")
    if blueprint.duration_seconds:
        lines.append(f"原片时长：{blueprint.duration_seconds:.1f}s")
    lines.append("")

    if blueprint.whole_piece_reading:
        lines.append("## 整片解读")
        lines.append(blueprint.whole_piece_reading.strip())
        lines.append("")

    applied = [s for s in blueprint.slots if s.applied]
    pending = [s for s in blueprint.slots if not s.applied]
    lines.append("## 槽位替换")
    if applied:
        for slot in applied:
            lines.append(
                f"- 【{slot.label}】原片「{slot.source_value or '—'}」→ "
                f"替换为「{slot.replace_with}」"
            )
    for slot in pending:
        lines.append(
            f"- 【{slot.label}】未替换（原片值：{slot.source_value or '—'}）"
        )
    lines.append("")

    lines.append("## 分场（锚点事件随段落走）")
    for beat in blueprint.beats:
        lines.append(
            f"### [{beat.start_seconds:.1f}–{beat.end_seconds:.1f}s] "
            f"{beat.role} — {beat.description or '（待补充）'}"
        )
        for event_id in beat.anchor_event_ids:
            anchor = _lookup_anchor(blueprint, event_id)
            if anchor is None:
                continue
            flag = "保留" if anchor.keep else "已移除"
            lines.append(
                f"  - @{{{event_id}}} [{anchor.kind}/{flag}] "
                f"触发「{anchor.trigger or '—'}」：{anchor.hint or '—'}"
            )
        for shot in _shots_in_window(blueprint, beat):
            lines.append(
                f"  - 镜头 {shot.index}：{shot.shot_size}/{shot.camera_motion}，"
                f"{shot.subject_action or '（动作未标注）'}"
                + (f"；屏上文字：{shot.on_screen_text}" if shot.on_screen_text else "")
                + f"；转场：{shot.transition_to_next}"
                + (f"；复刻提示：{shot.recreate_hint}" if shot.recreate_hint else "")
            )
        lines.append("")

    lines.append("## 节奏与系统")
    lines.append(f"平均镜头 {blueprint.rhythm_avg_shot_seconds:.1f}s")
    if blueprint.rhythm_cut_points_seconds:
        lines.append(
            "切点：" + ", ".join(f"{c:g}" for c in blueprint.rhythm_cut_points_seconds)
        )
    if blueprint.rhythm_energy_curve:
        lines.append(f"能量曲线：{blueprint.rhythm_energy_curve}")
    lines.append(f"字幕：{blueprint.systems_captions or '未检测到'}")
    lines.append(f"音乐：{blueprint.systems_music or '未检测到'}")
    lines.append(
        "图形/MG："
        + ("；".join(blueprint.systems_graphics) if blueprint.systems_graphics else "未检测到")
    )
    lines.append(
        "音效：" + ("；".join(blueprint.systems_sfx) if blueprint.systems_sfx else "未检测到")
    )
    lines.append("")

    lines.append("## 复刻提示")
    lines.append("- 保留：段落顺序、镜头节奏、转场方式与视觉系统关系。")
    lines.append("- 替换：槽位中已填写的替换值优先于原片值。")
    lines.append("- 锚点事件标记了'新内容写到哪里该挂什么'，写台词时逐条落实。")
    if blueprint.constraints:
        lines.append("- 边界：" + "；".join(blueprint.constraints[:2]))
    lines.append("")
    return "\n".join(lines)


def _lookup_anchor(
    blueprint: ReplicaBlueprintContentV2, event_id: str
) -> ReplicaAnchorEventV2 | None:
    """锚点事件是一等公民（blueprint.anchor_events），按 id 直接查。"""
    for anchor in blueprint.anchor_events:
        if anchor.event_id == event_id:
            return anchor
    return None


def _shots_in_window(
    blueprint: ReplicaBlueprintContentV2, beat: ReplicaBeatV2
) -> list[ReplicaShotV2]:
    return [
        s
        for s in blueprint.shots
        if beat.start_seconds <= (s.start_seconds + s.end_seconds) / 2 <= beat.end_seconds
    ]


# ---------------------------------------------------------------------------
# 实例化计划（蓝图 → Canvas 节点创建请求）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplicaInstantiationPlan:
    """蓝图 → script 节点创建请求 + replica→script 绑定请求。

    ``node_request`` 是 CanvasNodeCreateRequestV2 形状的 dict；
    ``binding`` 是 CanvasBindingV2 形状的 dict（source=replica 节点）。
    """

    node_request: dict
    binding: dict
    script_text: str


def plan_script_instantiation(
    blueprint: ReplicaBlueprintContentV2,
    *,
    replica_node_id: str,
    position: dict[str, float],
) -> ReplicaInstantiationPlan:
    """生成把蓝图落地为 script 节点的创建计划（纯函数）。"""
    script_text = render_replica_script(blueprint)
    node_request = {
        "node_type": "script",
        "creative_role": "script",
        "role_contract_version": "ad-media-role-v2",
        "title": f"复刻脚本 · {blueprint.format_name}",
        "summary_prompt": "拉片复刻生成的复刻脚本（结构来自参考片拆解，内容按槽位替换重写）",
        "generation_prompt": script_text,
        "structured_content": {
            "content": script_text,
            "script_text": script_text,
            "replica_source_node_id": replica_node_id,
            "replica_goal": blueprint.replica_goal,
        },
        "model_selection_mode": "default",
        "model_ref": None,
        "parameters": {},
        "position": {"x": float(position.get("x", 0.0)), "y": float(position.get("y", 0.0))},
        "source_asset_id": None,
        "authoring_origin": "agent_guided",
        "intent_hint": "replica_instantiate",
    }
    binding = {
        "source": {"kind": "node_output", "source_node_id": replica_node_id},
        "input_role": "text_context",
        "label": "复刻蓝图",
    }
    return ReplicaInstantiationPlan(
        node_request=node_request, binding=binding, script_text=script_text
    )
