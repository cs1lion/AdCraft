"""拉片复刻 · ``.adreplica`` 文档层（AdSVML 序列化 + 回读）。

把复刻蓝图（``ReplicaBlueprintContentV2``，结构化 JSON）与 ``.adreplica``
标记语言文本互相转换——hypit 的"文件即真相源"思想在 AdCraft 的落地形态：

    blueprint（画布节点内容）──export──▶ .adreplica 文本（人/Agent 可读可改）
    .adreplica 文本 ──import──▶ blueprint（重新编译回画布节点内容）

词汇表对齐 docs/plans/hypit-replica-research.md §3.5（AdSVML 草案），语法
基因取自 hypit 一手样例（examples/interview/reference.svml 等）：

- ``during=`` 引用锚定：事件/镜头引用结构段落 id（如 ``b1``），不写绝对
  秒数——结构重排时锚点自动跟随（hypit: "structural span, no timeline
  drag"，docs/guide/studio-temporal-windows.md）；
- ``<events>`` 内元素名即事件类型（broll/caption/sfx/mg/transition），
  对齐 hypit 的语义组件元素；
- ``<cast>`` 槽位统一为 ``kind`` 属性，而非 hypit 把 provider 焊死在语言里
  的 ``<gpt:Image>``/``<seedance:ReferenceVideo>``——与 AdCraft 角色契约 +
  多 provider 抽象对齐（§3.5 设计原则：对标不照抄）。

v1 刻意不包含（等 WhisperX 词级锚定 / 实例化扩展后再加）：

- ``@{id}词@{/id}`` 行内词锚（P2 已实现）：``<line>``（段落台词原文）
  里的事件词绑定——whisperX 词级转录可用时由蓝图解析生成，也可手写；
  行内锚引用未声明的事件 id 会显式报错；
- ``<gen>``/``<render>``：蓝图是结构文档，物质层 prompt 属于实例化后的
  节点内容；
- ``instantiated_script_node_id``：画布运行时状态，不属于文档真相源。

解析遵循 SceneScript 的"normalize 兜底"经验：数字/布尔容忍、未知子元素
忽略；但结构性错误（根元素不符 / 重复 id / 未知 kind）显式报错——静默
降级是禁止的（docs/agents/engineering-standards.md §4）。

本模块全部为纯函数：无 IO、无 LLM、无 HTTP，便于完整单测。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from pydantic import ValidationError

from app.schemas.agent_canvas_ad_media import (
    ReplicaAnchorEventV2,
    ReplicaBlueprintContentV2,
    ReplicaShotV2,
    ReplicaSlotV2,
)

#: 文档语法版本（grammar version，区别于蓝图的 blueprint_version）
ADREPLICA_VERSION = "1"

_ROOT_TAG = "advideo"
_KIND = "replica-blueprint"

_SLOT_KINDS = ("character", "product", "script", "style", "voice", "scene")
_EVENT_KINDS = ("broll", "caption", "sfx", "mg", "transition")


class AdReplicaParseError(Exception):
    """``.adreplica`` 文本无法解析/校验为复刻蓝图。"""


# ---------------------------------------------------------------------------
# 蓝图 → .adreplica 文本
# ---------------------------------------------------------------------------


def adreplica_from_blueprint(blueprint: ReplicaBlueprintContentV2) -> str:
    """把复刻蓝图序列化为 ``.adreplica`` 标记文本（确定性输出）。"""
    root = ET.Element(
        _ROOT_TAG,
        {
            "version": ADREPLICA_VERSION,
            "kind": _KIND,
            "aspect": blueprint.aspect,
            "duration": _fmt(blueprint.duration_seconds),
        },
    )

    meta = ET.SubElement(
        root,
        "meta",
        {
            "source": blueprint.source_video_asset_id,
            "format": blueprint.format_name,
        },
    )
    _sub_with_text(meta, "goal", blueprint.replica_goal)
    _sub_with_text(meta, "reading", blueprint.whole_piece_reading)

    cast = ET.SubElement(root, "cast")
    for slot in blueprint.slots:
        # applied 不落盘：它是 replace_with 的派生标志（填充即置位），
        # 写进文档只会制造不一致——解析端按 replace_with 重导出。
        ET.SubElement(
            cast,
            "slot",
            {
                "kind": slot.kind,
                "label": slot.label,
                "source": slot.source_value,
                "replace-with": slot.replace_with,
            },
        )

    events_by_id = {e.event_id: e for e in blueprint.anchor_events}
    unwrapped_word_events: set[str] = set()
    script = ET.SubElement(root, "script")
    for beat in blueprint.beats:
        beat_el = ET.SubElement(
            script,
            "beat",
            {
                "id": beat.beat_id,
                "role": beat.role,
                "dur": f"{_fmt(beat.start_seconds)}-{_fmt(beat.end_seconds)}",
            },
        )
        beat_el.text = beat.description
        if beat.line or any(
            (events_by_id.get(i) is not None and events_by_id[i].word)
            for i in beat.anchor_event_ids
        ):
            line_text, unwrapped = _wrap_inline_anchors(
                beat.line, beat.anchor_event_ids, events_by_id
            )
            unwrapped_word_events |= unwrapped
            ET.SubElement(beat_el, "line").text = line_text

    timeline = ET.SubElement(root, "timeline")
    for shot in blueprint.shots:
        ET.SubElement(
            timeline,
            "shot",
            {
                "id": f"s{shot.index}",
                "size": shot.shot_size,
                "motion": shot.camera_motion,
                # start 绝对起点必须落盘：仅靠相对 dur 会在回读时丢失镜头
                # 在原片时间轴上的位置（拆解出的切点是蓝图数据的一部分）。
                "start": _fmt(shot.start_seconds),
                "dur": _fmt(max(0.0, shot.end_seconds - shot.start_seconds)),
                "cut": shot.transition_to_next,
                "text": shot.on_screen_text,
                "recreate": shot.recreate_hint,
                "during": _beat_for_midpoint(blueprint, _midpoint(shot)),
            },
        ).text = shot.subject_action

    events = ET.SubElement(root, "events")
    for anchor in blueprint.anchor_events:
        attributes = {
            "id": anchor.event_id,
            "during": anchor.beat_id,
            "trigger": anchor.trigger,
            "keep": _fmt_bool(anchor.keep),
        }
        # 词锚优先走 <line> 行内标记；词不在台词里（数据漂移/手工构造）时
        # 兜底写进 word 属性——两种路径都无损往返。
        if anchor.word:
            attributes["word"] = anchor.word
            # 段落级锚点省略 affinity 属性（默认 right）；词级显式落盘
            if anchor.affinity != "right":
                attributes["affinity"] = anchor.affinity
        ET.SubElement(events, anchor.kind, attributes).text = anchor.hint

    ET.SubElement(
        root,
        "rhythm",
        {
            "avg-shot": _fmt(blueprint.rhythm_avg_shot_seconds),
            "curve": blueprint.rhythm_energy_curve,
            "cuts": ",".join(_fmt(c) for c in blueprint.rhythm_cut_points_seconds),
        },
    )

    systems = ET.SubElement(
        root,
        "systems",
        {
            "captions": blueprint.systems_captions,
            "music": blueprint.systems_music,
        },
    )
    for graphics in blueprint.systems_graphics:
        _sub_with_text(systems, "graphics", graphics)
    for sfx in blueprint.systems_sfx:
        _sub_with_text(systems, "sfx", sfx)

    constraints = ET.SubElement(root, "constraints")
    for constraint in blueprint.constraints:
        _sub_with_text(constraints, "constraint", constraint)

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode") + "\n"


def adreplica_filename(blueprint: ReplicaBlueprintContentV2) -> str:
    """导出文件名建议：格式名 slug + ``.adreplica`` 后缀。"""
    slug = re.sub(r"[^a-z0-9_-]+", "-", blueprint.format_name.lower()).strip("-")
    return f"{slug or 'replica-blueprint'}.adreplica"


# ---------------------------------------------------------------------------
# .adreplica 文本 → 蓝图
# ---------------------------------------------------------------------------


def blueprint_from_adreplica(text: str) -> ReplicaBlueprintContentV2:
    """把 ``.adreplica`` 标记文本解析回复刻蓝图。

    非法结构抛 ``AdReplicaParseError``（端点层映射 422）；pydantic 校验
    失败（超长/超量/非法字面量）同样包装为该异常。
    """
    if not text or not text.strip():
        raise AdReplicaParseError("Empty .adreplica document")
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError as exc:
        raise AdReplicaParseError(f"Malformed XML in .adreplica document: {exc}") from exc

    if root.tag != _ROOT_TAG:
        raise AdReplicaParseError(
            f"Unexpected root element <{root.tag}>, expected <{_ROOT_TAG}>"
        )
    version = root.get("version", ADREPLICA_VERSION)
    if version != ADREPLICA_VERSION:
        raise AdReplicaParseError(
            f"Unsupported .adreplica version: {version!r} (supported: {ADREPLICA_VERSION})"
        )
    kind = root.get("kind", _KIND)
    if kind != _KIND:
        raise AdReplicaParseError(
            f"Unexpected document kind {kind!r}, expected {_KIND!r}"
        )

    # 分支里赋值的变量先给默认值：文档缺任一块时解析仍然完整
    source = ""
    format_name = "short-video"
    goal = ""
    reading = ""
    rhythm_avg = 0.0
    rhythm_curve = ""
    captions = ""
    music = ""

    slots: list[ReplicaSlotV2] = []
    events: list[ReplicaAnchorEventV2] = []
    shots: list[ReplicaShotV2] = []
    beats: list[dict[str, Any]] = []
    cut_points: list[float] = []
    graphics: list[str] = []
    sfx_list: list[str] = []
    constraints: list[str] = []

    seen_slot_kinds: set[str] = set()
    seen_beat_ids: set[str] = set()
    seen_event_ids: set[str] = set()

    for child in root:
        if child.tag == "meta":
            source = child.get("source", "")
            format_name = child.get("format", "") or "short-video"
            goal = _text_of(child.find("goal"))
            reading = _text_of(child.find("reading"))
        elif child.tag == "cast":
            for slot_el in child.findall("slot"):
                slot_kind = slot_el.get("kind", "")
                if slot_kind not in _SLOT_KINDS:
                    raise AdReplicaParseError(
                        f"Unknown slot kind {slot_kind!r} "
                        f"(known: {', '.join(_SLOT_KINDS)})"
                    )
                if slot_kind in seen_slot_kinds:
                    raise AdReplicaParseError(f"Duplicate slot kind: {slot_kind!r}")
                seen_slot_kinds.add(slot_kind)
                replace_with = slot_el.get("replace-with", "")
                slots.append(
                    ReplicaSlotV2(
                        kind=slot_kind,  # type: ignore[arg-type]
                        label=slot_el.get("label", "") or slot_kind,
                        source_value=slot_el.get("source", ""),
                        replace_with=replace_with,
                        # applied 是 replace_with 的派生标志（手改文本即生效）
                        applied=bool(replace_with),
                    )
                )
        elif child.tag == "script":
            for beat_el in child.findall("beat"):
                beat_id = beat_el.get("id", "")
                if not beat_id:
                    raise AdReplicaParseError("Beat element is missing required id")
                if beat_id in seen_beat_ids:
                    raise AdReplicaParseError(f"Duplicate beat id: {beat_id!r}")
                seen_beat_ids.add(beat_id)
                start, end = _parse_dur(beat_el.get("dur", ""))
                line_el = beat_el.find("line")
                raw_line = _text_of(line_el) if line_el is not None else ""
                line_spans = _extract_inline_anchors(raw_line)
                beats.append(
                    {
                        "beat_id": beat_id,
                        "role": beat_el.get("role", "") or "body",
                        "description": _text_of(beat_el),
                        # 行内锚剥离后的台词原文（绑定关系记在事件上）
                        "line": _strip_inline_anchors(raw_line),
                        "start_seconds": start,
                        "end_seconds": end,
                        "_line_spans": line_spans,
                    }
                )
        elif child.tag == "timeline":
            for index, shot_el in enumerate(child.findall("shot"), start=1):
                start = _as_float(shot_el.get("start"))
                end = start + max(0.0, _as_float(shot_el.get("dur")))
                shots.append(
                    ReplicaShotV2(
                        index=index,
                        start_seconds=start,
                        end_seconds=end,
                        shot_size=shot_el.get("size", "") or "medium",
                        camera_motion=shot_el.get("motion", "") or "static",
                        subject_action=_text_of(shot_el),
                        on_screen_text=shot_el.get("text", ""),
                        transition_to_next=shot_el.get("cut", "") or "cut",
                        recreate_hint=shot_el.get("recreate", ""),
                    )
                )
        elif child.tag == "events":
            for event_el in child:
                if event_el.tag not in _EVENT_KINDS:
                    raise AdReplicaParseError(
                        f"Unknown event element <{event_el.tag}> "
                        f"(known: {', '.join(_EVENT_KINDS)})"
                    )
                event_id = event_el.get("id", "")
                if not event_id:
                    raise AdReplicaParseError(
                        f"<{event_el.tag}> event is missing required id"
                    )
                if event_id in seen_event_ids:
                    raise AdReplicaParseError(f"Duplicate event id: {event_id!r}")
                seen_event_ids.add(event_id)
                affinity_raw = (event_el.get("affinity", "") or "right").strip().lower()
                if affinity_raw not in {"left", "right"}:
                    raise AdReplicaParseError(
                        f"Invalid affinity {event_el.get('affinity', '')!r} on event {event_id!r} "
                        f"(expected 'left' or 'right')"
                    )
                events.append(
                    ReplicaAnchorEventV2(
                        event_id=event_id,
                        trigger=event_el.get("trigger", ""),
                        beat_id=event_el.get("during", ""),
                        kind=event_el.tag,  # type: ignore[arg-type]
                        hint=_text_of(event_el),
                        keep=_as_bool(event_el.get("keep"), default=True),
                        word=event_el.get("word", ""),
                        affinity=affinity_raw,  # type: ignore[arg-type]
                    )
                )
        elif child.tag == "rhythm":
            rhythm_avg = _as_float(child.get("avg-shot"))
            rhythm_curve = child.get("curve", "")
            cut_points = _parse_float_list(child.get("cuts", ""))
        elif child.tag == "systems":
            captions = child.get("captions", "")
            music = child.get("music", "")
            graphics = [_text_of(g) for g in child.findall("graphics")]
            sfx_list = [_text_of(s) for s in child.findall("sfx")]
        elif child.tag == "constraints":
            constraints = [_text_of(c) for c in child.findall("constraint")]
        # 其他子元素（未来语法位，如 <gen>/<render>）忽略——向前兼容

    # 文档为唯一真相源：段落→锚点联动在 events 收完后按文档顺序重导出
    # （keep=true 且 during 指向该段落）。
    for beat in beats:
        beat["anchor_event_ids"] = [
            e.event_id for e in events if e.beat_id == beat["beat_id"] and e.keep
        ]

    # 行内词锚 → 事件绑定（引用未声明的事件 id 显式报错——文档完整性）
    events_by_id = {e.event_id: e for e in events}
    word_updates: dict[str, str] = {}
    for beat in beats:
        for span_id, span_word in beat.pop("_line_spans"):
            if span_id not in events_by_id:
                raise AdReplicaParseError(
                    f"Inline anchor @{{{span_id}}} references unknown event"
                )
            word_updates[span_id] = span_word
    if word_updates:
        events = [
            e.model_copy(update={"word": word_updates[e.event_id]})
            if e.event_id in word_updates
            else e
            for e in events
        ]

    payload = {
        "blueprint_version": "replica-blueprint-v1",
        "source_video_asset_id": source,
        "duration_seconds": _as_float(root.get("duration")),
        "aspect": root.get("aspect", ""),
        "replica_goal": goal,
        "whole_piece_reading": reading,
        "format_name": format_name,
        "slots": slots,
        "beats": beats,
        "anchor_events": events,
        "shots": shots,
        "rhythm_avg_shot_seconds": rhythm_avg,
        "rhythm_cut_points_seconds": cut_points,
        "rhythm_energy_curve": rhythm_curve,
        "systems_captions": captions,
        "systems_music": music,
        "systems_graphics": graphics,
        "systems_sfx": sfx_list,
        "constraints": constraints,
        "instantiated_script_node_id": None,
    }
    try:
        return ReplicaBlueprintContentV2.model_validate(payload)
    except ValidationError as exc:
        raise AdReplicaParseError(f"Invalid blueprint in .adreplica document: {exc}") from exc


# ---------------------------------------------------------------------------
# 行内词锚（hypit mixed content：@{id}词@{/id}）
# ---------------------------------------------------------------------------

_INLINE_ANCHOR_PATTERN = re.compile(r"@\{([^\s{}@]+)\}(.*?)@\{/\1\}", re.DOTALL)


def _strip_inline_anchors(text: str) -> str:
    """剥离行内锚标记，保留词文本（序列化幂等的基础）。"""
    return _INLINE_ANCHOR_PATTERN.sub(r"\2", text)


def _extract_inline_anchors(text: str) -> list[tuple[str, str]]:
    """提取行内锚：[(event_id, 绑定词)]（按文档顺序）。"""
    return [
        (match.group(1), match.group(2))
        for match in _INLINE_ANCHOR_PATTERN.finditer(text)
    ]


def _wrap_inline_anchors(
    line_text: str,
    event_ids: list[str] | tuple[str, ...],
    events_by_id: dict[str, Any],
) -> tuple[str, set[str]]:
    """把事件的词用 ``@{id}…@{/id}`` 包进台词文本。

    返回 (新文本, 未能包进的事件 id 集合——词不在台词里或位置已被先到的
    锚占位时走 word 属性兜底)。已存在的行内锚先剥离，保证幂等。
    """
    text = _strip_inline_anchors(line_text or "")
    written_ranges: list[tuple[int, int]] = []  # 已写入标记的 [start, end) 区间
    unwrapped: set[str] = set()

    def find_free_occurrence(haystack: str, needle: str) -> int:
        position = 0
        while True:
            position = haystack.find(needle, position)
            if position < 0:
                return -1
            end = position + len(needle)
            if all(end <= start or position >= span_end for start, span_end in written_ranges):
                return position
            position += 1

    for event_id in event_ids:
        event = events_by_id.get(event_id)
        if event is None or not event.word:
            continue
        open_tag = "@{" + event_id + "}"
        close_tag = "@{/" + event_id + "}"
        position = find_free_occurrence(text, event.word)
        if position < 0:
            unwrapped.add(event_id)
            continue
        end = position + len(event.word)
        text = text[:position] + open_tag + event.word + close_tag + text[end:]
        written_ranges.append((position, position + len(open_tag) + len(event.word) + len(close_tag)))
    return text, unwrapped


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fmt(value: float) -> str:
    return f"{value:g}"


def _fmt_bool(value: bool) -> str:
    return "true" if value else "false"


def _as_bool(raw: str | None, *, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"true", "1"}


def _as_float(raw: str | None) -> float:
    """容忍数字解析：缺失/非数/负数/NaN 归零（normalize 兜底）。"""
    if raw is None:
        return 0.0
    try:
        number = float(raw)
    except ValueError:
        return 0.0
    return number if number == number and number >= 0 else 0.0


def _parse_dur(raw: str) -> tuple[float, float]:
    """``"0-3"`` 形式的段落时窗；容忍缺省与非法值。"""
    parts = raw.split("-")
    start = _as_float(parts[0]) if parts else 0.0
    end = _as_float(parts[1]) if len(parts) > 1 else 0.0
    return start, end


def _parse_float_list(raw: str) -> list[float]:
    values: list[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(float(part))
        except ValueError:
            continue
    return values


def _text_of(elem: ET.Element | None) -> str:
    if elem is None:
        return ""
    return (elem.text or "").strip()


def _midpoint(shot: ReplicaShotV2) -> float:
    return (shot.start_seconds + shot.end_seconds) / 2


def _sub_with_text(parent: ET.Element, tag: str, text: str) -> ET.Element:
    child = ET.SubElement(parent, tag)
    child.text = text
    return child


def _beat_for_midpoint(blueprint: ReplicaBlueprintContentV2, midpoint: float) -> str:
    """镜头中点落在哪个段落窗内（与 render_replica_script 的归属规则一致）。"""
    for beat in blueprint.beats:
        if beat.start_seconds <= midpoint <= beat.end_seconds:
            return beat.beat_id
    return ""
