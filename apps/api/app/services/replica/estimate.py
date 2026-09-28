"""拉片复刻 · 口播时长预估（hypit ``packages/estimate`` 的 AdCraft 落地，P4）。

hypit 在 TTS **之前**用语言/语速预估口播时长：一句台词按某语速要讲多久，
和它的段落窗比一比——超窗的句子要么删词要么加窗，等 TTS 合成完再发现
"这段话 6 秒才念得完但镜头只有 3 秒"就太晚了（钱已付）。

本模块是这一思想的纯函数落地（无 IO、无 LLM、无 HTTP）：

- ``detect_language``：脚本判定（CJK 表意/假名 vs 拉丁），不引检测库；
- ``estimate_speech_seconds``：分段求和——CJK 按**字**、拉丁按**词**各用
  自己的速率（混排文本如 "第7天 DAY 7" 分段算再加和，一个速率打天下会
  把中文按词速、英文按字速算错一个量级）；
- ``pace`` 三档缩放（slow 0.8 / normal 1.0 / fast 1.3）——与 hypit 的
  ``speechEstimatePolicySchema`` 同档位。

速率表是**预估**不是测量——表值与出处写在注释里，测试锁定表本身（改速率
是显式决定）。预估只用于"要不要重写/加窗"的预检，不用于生成时间码。
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 速率表（预估值，附出处与理由；改速率 = 显式决定，测试锁定）
# ---------------------------------------------------------------------------

#: CJK（中/日）正常语速：约 4.8 字/秒。依据：汉语普通话新闻播音约
#: 240-300 字/分钟（4-5 字/s），短视频口播偏快取上限附近。
CJK_CHARS_PER_SECOND = 4.8

#: 拉丁语（英/西等）正常语速：约 2.8 词/秒（≈168 词/分钟）。依据：
#: 英语演讲/播客常见 150-180 wpm，短视频偏快取上限附近。
LATIN_WORDS_PER_SECOND = 2.8

#: pace 缩放（hypit speechEstimatePolicy 同档位）
PACE_FACTORS = {"slow": 0.8, "normal": 1.0, "fast": 1.3}

#: CJK 判定：表意文字 + 假名 + 谚文（中文/日文/韩文口播速率接近同档）
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
#: 拉丁词：连续字母数字（含撇号连字符内的）
_LATIN_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’\-]*")


def detect_language(text: str) -> str:
    """文本 → 语言档位（"cjk" / "latin" / "empty"）。无检测库，脚本判定。"""
    if _CJK_RE.search(text or ""):
        return "cjk"
    if _LATIN_WORD_RE.search(text or ""):
        return "latin"
    return "empty"


def _pace_factor(pace: str) -> float:
    return PACE_FACTORS.get(pace, PACE_FACTORS["normal"])


def estimate_speech_seconds(text: str, *, pace: str = "normal") -> float:
    """预估口播时长（秒）。分语种分段求和，pace 缩放，保留 3 位小数。

    空文本 → 0.0。混合文本（"第7天 DAY 7"）= CJK 3 字 / 4.8 + 拉丁 2 词
    / 2.8，再乘 pace 因子——**不**用一个速率打天下。
    """
    if not text or not text.strip():
        return 0.0
    factor = _pace_factor(pace)
    cjk_chars = len(_CJK_RE.findall(text))
    latin_words = len(_LATIN_WORD_RE.findall(text))
    cjk_part = cjk_chars / CJK_CHARS_PER_SECOND if cjk_chars else 0.0
    latin_part = latin_words / LATIN_WORDS_PER_SECOND if latin_words else 0.0
    return round((cjk_part + latin_part) * factor, 3)


def estimate_beat_pace(
    *, text: str, window_seconds: float, pace: str = "normal", grace: float = 0.05
) -> dict:
    """一句台词 vs 它的段落窗 → 预检结论（可行动的告警数据）。

    ``fits=False`` 的充分条件：预估算完 > 窗 × (1 + grace)—— grace 是标点
    停顿与口播松紧的余量。返回的 dict 直接进可行性门的 pace_warnings（每个
    字段都有去处：beat_id 定位、字数/窗口让人判断删词还是加窗）。
    """
    estimated = estimate_speech_seconds(text, pace=pace)
    language = detect_language(text)
    budget = round(window_seconds * (1.0 + grace), 3)
    unit = {
        "cjk": "chars",
        "latin": "words",
        "empty": "chars",
    }[language]
    return {
        "text": text,
        "language": language,
        "pace": pace,
        "count": (
            len(_CJK_RE.findall(text))
            if language == "cjk"
            else len(_LATIN_WORD_RE.findall(text))
        ),
        "unit": unit,
        "estimated_seconds": estimated,
        "window_seconds": round(window_seconds, 3),
        "budget_seconds": budget,
        "ratio": round(estimated / window_seconds, 3) if window_seconds > 0 else None,
        "fits": estimated <= budget if window_seconds > 0 else True,
    }
