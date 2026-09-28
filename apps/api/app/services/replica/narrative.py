"""拉片复刻 · narrative token 层（hypit P1 主项的落地，2026-09-28）。

hypit 的 ``packages/narrative`` 把"锚定"从**时间**上移到**授权序**上：
每个词是一个 token（带授权顺序、所属 segment、``normalized`` 拼写），
selection 是 anchor 对之间的 **token 区间**——"independent of material
placement and frame timing"。时间只是 token 序列的**投影**：改台词、重
转写、重配音之后，绑定天然存活，秒数重算即可。

本模块是这一思想的纯函数落地（无 IO、无 LLM、无 HTTP）：

- ``normalize_text``：授权拼写（去标点/大小写/空白）——匹配对格式脆弱
  说再见；
- ``tokenize``：CJK 字符级 + 拉丁词级（不引分词依赖，确定性可测）；
- ``Narrative``：segments（蓝图段落）+ tokens（授权序）+ anchor 索引；
- **6 种 anchor**（对齐 hypit ``SemanticAnchor``）：program 起止、
  segment 起止、token 起止；
- ``narrative_selection_tokens``：anchor 对 → token 区间，**不查时间线**；
- ``narrative_from_blueprint``：tokens 取自段落词流（转录实测切分），
  无词流时从 ``line`` 文本切分——两种来源都产出同一授权序；
- ``token_range_for_text``：在段落的 token 序列里定位一段文本（normalized
  包含匹配），返回 token 区间——锚点解析的确定性基础；
- ``project_seconds``：token 区间 → 秒数跨度（**投影**：用段落词流的
  实测时间，没有词流就不是投影而是没有时间）。

时间与锚定解耦的标志性性质（测试锁定）：改动蓝图上任何秒数字段，
selection 的 token 区间**逐字节不变**。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from app.schemas.agent_canvas_ad_media import ReplicaBeatV2, ReplicaBlueprintContentV2

# ---------------------------------------------------------------------------
# normalize（授权拼写）
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def normalize_text(value: str) -> str:
    """授权拼写：去空白/标点/大小写（NFKC + 仅留字母数字与 CJK）。

    锚点匹配对"格式脆弱"说再见——全角/半角、标点有无、大小写差异都不
    影响匹配。匹配两边都过这个函数，不匹配原始子串。
    """
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    return _PUNCT_RE.sub("", text).casefold()


# ---------------------------------------------------------------------------
# tokenize（CJK 字符级 + 拉丁词级，无外部依赖）
# ---------------------------------------------------------------------------


def _char_class(char: str) -> str:
    if re.match(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]", char):
        return "cjk"
    if char.isalnum():
        return "latin"
    return "other"


def tokenize(value: str) -> tuple[str, ...]:
    """文本 → token 序列（确定性，无分词依赖）。

    - **CJK 逐字成 token**：没有可靠的无依赖中文分词器，字符级是诚实的
      粒度（也正好让 ``token_range_for_text`` 的定位精确到字）；
    - 拉丁/数字连续段成一个 token（词级）；
    - 其余（标点空白）丢弃——它们不是授权内容。
    """
    tokens: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            tokens.append("".join(buffer))
            buffer.clear()

    for char in str(value or ""):
        kind = _char_class(char)
        if kind == "other":
            flush()
            continue
        if kind == "cjk":
            flush()
            tokens.append(char)
            continue
        buffer.append(char)
    flush()
    return tuple(tokens)


# ---------------------------------------------------------------------------
# Narrative 模型（对齐 hypit narrative/src/types.ts 的最小集）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NarrativeToken:
    """授权序里的一个词：身份是（segment, index），与时间无关。"""

    token_id: str
    segment_id: str
    index: int
    text: str
    normalized: str


@dataclass(frozen=True)
class NarrativeSegment:
    """一段授权内容（蓝图的一个段落/beat）。秒数是投影槽，不是身份。"""

    segment_id: str
    token_start: int
    token_end_exclusive: int


@dataclass(frozen=True)
class Narrative:
    """完整授权内容：segments + tokens（无帧、无实测时间）。"""

    narrative_id: str
    segments: tuple[NarrativeSegment, ...]
    tokens: tuple[NarrativeToken, ...]

    def segment(self, segment_id: str) -> NarrativeSegment | None:
        return next((s for s in self.segments if s.segment_id == segment_id), None)

    def token(self, token_id: str) -> NarrativeToken | None:
        return next((t for t in self.tokens if t.token_id == token_id), None)

    def segment_tokens(self, segment_id: str) -> tuple[NarrativeToken, ...]:
        segment = self.segment(segment_id)
        if segment is None:
            return ()
        return self.tokens[segment.token_start : segment.token_end_exclusive]


# ---------------------------------------------------------------------------
# anchor：6 种 kind（program/segment/token × 起止），对齐 hypit SemanticAnchor
# ---------------------------------------------------------------------------

PROGRAM_START = "program:start"
PROGRAM_END = "program:end"


def segment_start_anchor(segment_id: str) -> str:
    return f"segment:{segment_id}:start"


def segment_end_anchor(segment_id: str) -> str:
    return f"segment:{segment_id}:end"


def token_start_anchor(token_id: str) -> str:
    return f"token:{token_id}:start"


def token_end_anchor(token_id: str) -> str:
    return f"token:{token_id}:end"


def anchor_kind(anchor_id: str) -> str:
    """anchor id → kind（program-start/end、segment-start/end、token-start/end）。"""
    if anchor_id == PROGRAM_START:
        return "program-start"
    if anchor_id == PROGRAM_END:
        return "program-end"
    if anchor_id.startswith("segment:") and anchor_id.endswith(":start"):
        return "segment-start"
    if anchor_id.startswith("segment:") and anchor_id.endswith(":end"):
        return "segment-end"
    if anchor_id.startswith("token:") and anchor_id.endswith(":start"):
        return "token-start"
    if anchor_id.startswith("token:") and anchor_id.endswith(":end"):
        return "token-end"
    raise KeyError(f"Unknown narrative anchor: {anchor_id}")


def anchor_token_boundary(narrative: Narrative, anchor_id: str) -> int:
    """anchor → 授权序边界（token 下标）。 Hypit 同名函数的秒制-free 版本。"""
    kind = anchor_kind(anchor_id)
    if kind == "program-start":
        return 0
    if kind == "program-end":
        return len(narrative.tokens)
    if kind in {"segment-start", "segment-end"}:
        segment_id = anchor_id.split(":")[1]
        segment = narrative.segment(segment_id)
        if segment is None:
            raise KeyError(f"Narrative has no segment {segment_id}")
        return (
            segment.token_start
            if kind == "segment-start"
            else segment.token_end_exclusive
        )
    token_id = anchor_id.split(":")[1]
    try:
        index = next(
            i for i, token in enumerate(narrative.tokens) if token.token_id == token_id
        )
    except StopIteration as exc:
        raise KeyError(f"Narrative has no token {token_id}") from exc
    return index if kind == "token-start" else index + 1


def narrative_selection_tokens(
    narrative: Narrative, start_anchor_id: str, end_anchor_id: str
) -> tuple[NarrativeToken, ...]:
    """selection = 两个 anchor 间的 token 区间——**不查时间线、不查帧**。

    改任何秒数字段都不影响本函数的结果（测试锁定的标志性性质）。
    """
    start = anchor_token_boundary(narrative, start_anchor_id)
    end = anchor_token_boundary(narrative, end_anchor_id)
    if end < start:
        raise ValueError(
            f"Selection {start_anchor_id} → {end_anchor_id} has invalid anchor order"
        )
    return narrative.tokens[start:end]


# ---------------------------------------------------------------------------
# 蓝图 → Narrative
# ---------------------------------------------------------------------------


def narrative_from_blueprint(
    blueprint: ReplicaBlueprintContentV2, *, narrative_id: str = "replica"
) -> Narrative:
    """蓝图段落 → token 授权序。

    **token 只来自授权文本（``beat.line``）**——与 hypit 的 Script↔media
    模型一致：Script（作者写的词序）是真相源，转录词流只是**对齐**
    （把 token 投影到媒体时间）。若 token 随词流粒度变化（词流存在时词级、
    不存在时字符级），token id 会在解析/重投影之间换空间，binding 必然
    丢失——那是把投影源当真相源的错误。

    推论（如实记录）：只有台词段落进授权序；纯字幕片（无 line）没有
    token 层，锚点保持"文本 + 秒数"形态（向后兼容路径）。

    段内 token id = ``{segment_id}#{index}``（同一条 line 永远切出同一
    序列——确定性，可重投影）。
    """
    tokens: list[NarrativeToken] = []
    segments: list[NarrativeSegment] = []
    cursor = 0
    for beat in blueprint.beats:
        raw_tokens = tokenize(beat.line)
        start = cursor
        for index, text in enumerate(raw_tokens):
            tokens.append(
                NarrativeToken(
                    token_id=f"{beat.beat_id}#{index}",
                    segment_id=beat.beat_id,
                    index=index,
                    text=text,
                    normalized=normalize_text(text),
                )
            )
            cursor += 1
        segments.append(
            NarrativeSegment(
                segment_id=beat.beat_id,
                token_start=start,
                token_end_exclusive=cursor,
            )
        )
    return Narrative(narrative_id=narrative_id, segments=tuple(segments), tokens=tuple(tokens))


# ---------------------------------------------------------------------------
# 定位与投影
# ---------------------------------------------------------------------------


def token_range_for_text(
    narrative: Narrative, segment_id: str, needle: str, *, occurrence: int = 0
) -> tuple[str, str] | None:
    """在段落授权序里定位一段文本 → (start_token_id, end_token_id)。

    normalized 包含匹配；``occurrence`` 选第几次出现（重复子串不再永远
    锁死第一次——锚点可以指向第二次出现）。找不到返回 None。
    """
    tokens = narrative.segment_tokens(segment_id)
    target = normalize_text(needle)
    if not target or not tokens:
        return None
    # 字符 → token 下标映射：normalized 拼接后匹配，再映射回 token 边界
    char_token: list[int] = []
    parts: list[str] = []
    for position, token in enumerate(tokens):
        if not token.normalized:
            continue
        parts.append(token.normalized)
        char_token.extend([position] * len(token.normalized))
    stream = "".join(parts)
    start_index = -1
    for _ in range(occurrence + 1):
        start_index = stream.find(target, start_index + 1)
        if start_index < 0:
            return None
    first = char_token[start_index]
    last = char_token[start_index + len(target) - 1]
    return (tokens[first].token_id, tokens[last].token_id)


def selection_text(tokens: tuple[NarrativeToken, ...]) -> str:
    """token 区间 → 文本（无分隔拼接——CJK 无语种空格，拉丁场景由原作者 Punctuation 决定）。"""
    return "".join(token.text for token in tokens)


def project_seconds(
    beat: ReplicaBeatV2,
    tokens: tuple[NarrativeToken, ...],
) -> tuple[float, float] | None:
    """token 区间 → 秒数跨度（**投影**，hypit "时间是投影"的落地）。

    用段落词流的实测时间：把区间文本在词流拼接文本里 normalized 定位，
    覆盖的首末词时间即投影结果。没有词流（无转录）时返回 None——
    **没有时间就不是 projection 的问题，是没有测量**；调用方退回段落窗
    并如实标注，不插值、不编造。
    """
    if not tokens:
        return None
    words = [word for word in beat.words if word.text.strip()]
    if not words:
        return None
    target = normalize_text(selection_text(tokens))
    if not target:
        return None
    char_word: list[int] = []
    parts: list[str] = []
    for position, word in enumerate(words):
        normalized = normalize_text(word.text)
        if not normalized:
            continue
        parts.append(normalized)
        char_word.extend([position] * len(normalized))
    stream = "".join(parts)
    start_index = stream.find(target)
    if start_index < 0:
        return None
    first = char_word[start_index]
    last = char_word[start_index + len(target) - 1]
    return (round(float(words[first].start_seconds), 3), round(float(words[last].end_seconds), 3))


def narrative_summary(narrative: Narrative) -> dict[str, Any]:
    """可查询摘要（测试/调试用：不暴露内部结构也给得出规模）。"""
    return {
        "narrative_id": narrative.narrative_id,
        "segments": len(narrative.segments),
        "tokens": len(narrative.tokens),
        "tokens_per_segment": {
            segment.segment_id: segment.token_end_exclusive - segment.token_start
            for segment in narrative.segments
        },
    }
