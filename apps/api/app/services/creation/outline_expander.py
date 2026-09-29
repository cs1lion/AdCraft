"""From-one-outline creation (从 0 建片的第一步).

The author writes one outline; this module expands it into a shot list with
one LLM call (salvaged parse — see scene3d.llm_json_salvage) and turns a
confirmed shot list into canvas nodes: one script node (the outline as the
script), one 设定图 image node per shot and one video node per shot.  The
guided-flow stages stay internal.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.agent_canvas_ad_media import VideoSegmentContentV2
from app.services.replica.film import MAX_SHOT_SECONDS, MIN_SHOT_SECONDS

#: Title prefixes so re-running reuses nodes instead of duplicating them.
SETTING_NODE_TITLE_PREFIX = "设定图"
FILM_NODE_TITLE_PREFIX = "成片镜头"

_OUTLINE_SYSTEM_PROMPT = """\
你是广告导演。把用户的创作纲领展开为分镜清单。

只输出一个 JSON 对象，不要解释、不要推理过程：
{"shots": [{"summary": "这一镜一句话（中文）", "visual": "这一镜的画面描述（中文，构图/主体/动作/光线）", "duration_seconds": 5, "on_screen_text": "屏上文字，没有就空字符串"}]}

规则：
- 3–8 个镜头，总时长与纲领暗示的一致（没说就 15–30 秒）。
- duration_seconds 是 4–12 的整数。
- 每个镜头的 visual 自包含：不依赖其他镜头也能生成。
"""


class OutlineExpansionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class OutlineShotV1:
    summary: str
    visual: str
    duration_seconds: float
    on_screen_text: str


@dataclass(frozen=True)
class OutlinePlanV1:
    shots: list[OutlineShotV1]


def parse_outline_plan(content: str) -> OutlinePlanV1:
    """Parse (with salvage) the LLM's shot list."""

    import json

    from app.services.scene3d.llm_json_salvage import salvage_json_text

    repaired = salvage_json_text(content)
    if repaired is None:
        raise OutlineExpansionError("outline_expansion_invalid", "LLM 未返回可解析的分镜 JSON。")
    try:
        data = json.loads(repaired)
    except json.JSONDecodeError as exc:
        raise OutlineExpansionError("outline_expansion_invalid", f"分镜 JSON 解析失败：{exc}")
    if not isinstance(data, dict):
        raise OutlineExpansionError("outline_expansion_invalid", "分镜 JSON 不是对象。")
    raw_shots = data.get("shots")
    if not isinstance(raw_shots, list) or not raw_shots:
        raise OutlineExpansionError("outline_expansion_empty", "分镜清单为空。")
    shots: list[OutlineShotV1] = []
    for index, raw in enumerate(raw_shots):
        if not isinstance(raw, dict):
            raise OutlineExpansionError("outline_shot_invalid", f"第 {index + 1} 个镜头不是对象。")
        summary = str(raw.get("summary") or "").strip()
        visual = str(raw.get("visual") or "").strip()
        if not summary or not visual:
            raise OutlineExpansionError(
                "outline_shot_incomplete",
                f"第 {index + 1} 个镜头缺少 summary 或 visual。",
            )
        try:
            duration = float(raw.get("duration_seconds") or 5)
        except (TypeError, ValueError):
            duration = 5.0
        duration = min(MAX_SHOT_SECONDS, max(MIN_SHOT_SECONDS, duration))
        shots.append(
            OutlineShotV1(
                summary=summary,
                visual=visual,
                duration_seconds=duration,
                on_screen_text=str(raw.get("on_screen_text") or "").strip(),
            )
        )
    return OutlinePlanV1(shots=shots)


def request_outline_expansion(
    *,
    settings,
    outline: str,
    client_factory=None,
    timeout_seconds: float = 120.0,
) -> OutlinePlanV1:
    """One LLM call: outline → shot list."""

    import httpx

    if not settings.llm_api_key or not settings.llm_base_url:
        raise OutlineExpansionError("outline_llm_unconfigured", "LLM 未配置。")
    text = outline.strip()
    if not text:
        raise OutlineExpansionError("outline_missing", "请先写一条创作纲领。")
    factory = client_factory or httpx.Client
    client = factory(timeout=timeout_seconds)
    try:
        response = client.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": settings.llm_script_model or settings.llm_front_desk_model,
                "messages": [
                    {"role": "system", "content": _OUTLINE_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                "max_tokens": 2048,
                "temperature": 0.4,
            },
        )
    finally:
        client.close()
    if response.status_code != 200:
        raise OutlineExpansionError(
            "outline_llm_failed",
            f"LLM 调用失败 ({response.status_code})：{response.text[:200]}",
        )
    choices = response.json().get("choices")
    content = choices[0].get("message", {}).get("content") if choices else None
    if not isinstance(content, str) or not content.strip():
        raise OutlineExpansionError("outline_llm_empty", "LLM 返回了空内容。")
    return parse_outline_plan(content)


@dataclass(frozen=True)
class OutlineBuildPlanV1:
    script_title: str
    script_text: str
    settings_nodes: list[dict]
    film_nodes: list[dict]


def plan_outline_build(outline: str, plan: OutlinePlanV1) -> OutlineBuildPlanV1:
    """Turn a confirmed outline into canvas node requests (script + 设定图 + 成片)."""

    lines = [f"# 创作纲领\n{outline.strip()}\n", "## 分镜"]
    settings_nodes: list[dict] = []
    film_nodes: list[dict] = []
    for index, shot in enumerate(plan.shots, start=1):
        lines.append(
            f"{index}. {shot.summary}（{shot.duration_seconds:.0f}s）"
            + (f" 屏上文字：{shot.on_screen_text}" if shot.on_screen_text else "")
        )
        setting_prompt = (
            f"为广告分镜生成设定图：{shot.visual}"
            + (f"。屏上文字排版：{shot.on_screen_text}" if shot.on_screen_text else "")
            + "。统一商业广告视觉，清晰构图。"
        )
        settings_nodes.append(
            {
                "node_type": "image",
                "creative_role": "general_image",
                "title": f"{SETTING_NODE_TITLE_PREFIX}{index}",
                "generation_prompt": setting_prompt,
            }
        )
        segment = VideoSegmentContentV2(
            segment_summary=f"成片镜头{index}（{shot.duration_seconds:.0f}s）",
            duration_seconds=shot.duration_seconds,
            storyboard_content=shot.visual
            + (f"\n屏上文字：{shot.on_screen_text}" if shot.on_screen_text else ""),
        )
        film_nodes.append(
            {
                "node_type": "video",
                "creative_role": "storyboard_video",
                "title": f"{FILM_NODE_TITLE_PREFIX}{index}",
                "generation_prompt": segment.storyboard_content,
                "structured_content": segment.model_dump(mode="json"),
            }
        )
    return OutlineBuildPlanV1(
        script_title="创作纲领",
        script_text="\n".join(lines),
        settings_nodes=settings_nodes,
        film_nodes=film_nodes,
    )
