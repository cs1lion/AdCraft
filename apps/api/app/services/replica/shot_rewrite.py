"""复刻改写：把原片镜头描述改写成"同风格、新元素"的版本。

拉片复刻的承诺是**风格复刻**，不是新旧元素拼贴。原片拆解出的镜头描述
里必然带着原产品/原品牌/原屏上文字（"Flat lay display of full Vita Coco
product line"），若原样喂给视频模型、只在尾部附一句槽位指令，模型会
把新元素**加进**原片场景——实测四镜全是 Vita Coco 瓶+椰子块+新苹果的
混合，作者当场判"完全达不到风格复刻"。

本模块在出片前用一次 LLM 调用，把每镜描述改写为：保留镜号/景别/机位/
时长/转场/节奏/构图逻辑，原主体、原产品、原品牌、原屏上文字按槽位替换
值整体换掉。改写结果按槽位指纹缓存在 replica 节点的 parameters 上，重试
时提示词稳定（不会每轮微漂移导致镜头反复回炉）。

实测两个模型侧坑，都已在本模块内消化：
- step 系推理模型偶发只回 reasoning、content 为空 → 自动重试一次；
- flash 小模型爱在描述里留"复刻原片 VITA COCO 的…" → 提示词按"重拍一
  条全新广告"框定，输出仍带原片名称的触发一次修复改写。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

_REWRITE_SYSTEM_PROMPT = """\
你是广告导演。一条原广告的分镜表要**重拍成全新主体的版本**：镜头语言
（景别/机位/时长/转场/节奏/构图）与原片一致，但画面里的一切主体、道具、
产品、品牌、屏上文字都换成新版本。

输入：原片每镜的拆解描述 + 槽位替换值。输出：逐镜的新版画面描述。

铁律：
- 只描述新版画面。绝不出现原品牌名、原产品名、原屏上文字，也不写
  "原片/原本/复刻自/参考原片"这类字眼——读者只能看到新版这一镜。
- 槽位给了的值必须体现在画面上；槽位没给的通用元素（环境、光线、
  色调、质感）保持与原片同一风格。
- 每镜 1–3 句中文，自包含：只看着这段文字也能拍出这一镜。

只输出 JSON，不要解释、不要推理过程：
{"shots": ["第1镜的新版描述", "第2镜的新版描述", ...]}

shots 数量必须与输入镜头数一致。"""

#: replica 节点 parameters 里缓存改写结果的键（槽位指纹 → 每镜新描述）。
REWRITE_CACHE_KEY = "shot_rewrites"


class ShotRewriteError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ShotRewriteInputV1:
    """One original shot as handed to the rewrite LLM."""

    index: int
    time_range: str
    shot_size: str
    camera_motion: str
    subject_action: str
    on_screen_text: str
    slot_directives: str


def shot_rewrite_fingerprint(slot_pairs: list[tuple[str, str]]) -> str:
    """稳定指纹：槽位没变 → 复用缓存（重试时提示词不漂移）。"""

    import hashlib

    payload = json.dumps(
        [{"kind": kind, "replace_with": value} for kind, value in slot_pairs],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_rewrite_inputs(blueprint) -> list[ShotRewriteInputV1]:
    """Blueprint + applied slots → per-shot rewrite inputs."""

    directives = [
        f"{slot.label}=「{slot.replace_with}」"
        for slot in blueprint.slots
        if slot.applied and slot.replace_with.strip()
    ]
    directive_text = "；".join(directives)
    inputs: list[ShotRewriteInputV1] = []
    for shot in blueprint.shots:
        inputs.append(
            ShotRewriteInputV1(
                index=shot.index,
                time_range=f"{shot.start_seconds:.1f}–{shot.end_seconds:.1f}s",
                shot_size=shot.shot_size or "中景",
                camera_motion=shot.camera_motion or "固定",
                subject_action=shot.subject_action or "",
                on_screen_text=shot.on_screen_text or "",
                slot_directives=directive_text,
            )
        )
    return inputs


def parse_shot_rewrite(content: str, expected: int) -> list[str]:
    """Salvage-parse the rewrite JSON; require exactly ``expected`` briefs."""

    from app.services.scene3d.llm_json_salvage import salvage_json_text

    repaired = salvage_json_text(content)
    if repaired is None:
        raise ShotRewriteError("rewrite_invalid", "LLM 未返回可解析的改写 JSON。")
    try:
        data = json.loads(repaired)
    except json.JSONDecodeError as exc:
        raise ShotRewriteError("rewrite_invalid", f"改写 JSON 解析失败：{exc}")
    raw = data.get("shots") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        raise ShotRewriteError("rewrite_invalid", "改写结果不是数组。")
    briefs = [str(item or "").strip() for item in raw]
    briefs = [brief for brief in briefs if brief]
    if len(briefs) != expected:
        raise ShotRewriteError(
            "rewrite_count_mismatch",
            f"改写得到 {len(briefs)} 镜，期望 {expected} 镜。",
        )
    return briefs


def _original_markers(blueprint) -> list[str]:
    """原片标识候选（用于检测改写是否还带着原产品/品牌）。"""

    markers: list[str] = []
    for slot in blueprint.slots:
        source = (slot.source_value or "").strip()
        if not source:
            continue
        # 槽位原值常是"品牌 品类"混排；取其中长度可观的词做标记
        for token in source.replace("，", " ").replace(",", " ").split():
            token = token.strip()
            if len(token) >= 3:
                markers.append(token.lower())
    return markers


def _contaminated(briefs: list[str], markers: list[str]) -> bool:
    if not markers:
        return False
    for brief in briefs:
        lowered = brief.lower()
        if any(marker in lowered for marker in markers):
            return True
    return False


def _call_rewrite(
    *,
    settings,
    user_text: str,
    extra_user_note: str,
    client_factory,
    timeout_seconds: float,
    expected: int,
) -> list[str]:
    import httpx

    if not settings.llm_api_key or not settings.llm_base_url:
        raise ShotRewriteError("rewrite_llm_unconfigured", "LLM 未配置。")
    content = extra_user_note + "\n" + user_text if extra_user_note else user_text
    factory = client_factory or httpx.Client
    client = factory(timeout=timeout_seconds)
    try:
        response = client.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": settings.llm_script_model or settings.llm_front_desk_model,
                "messages": [
                    {"role": "system", "content": _REWRITE_SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
                "max_tokens": 4096,
                "temperature": 0.3,
            },
        )
    finally:
        client.close()
    if response.status_code != 200:
        raise ShotRewriteError(
            "rewrite_llm_failed",
            f"LLM 调用失败 ({response.status_code})：{response.text[:200]}",
        )
    choices = response.json().get("choices")
    message = choices[0].get("message", {}) if choices else {}
    text = message.get("content") if isinstance(message, dict) else None
    if not isinstance(text, str) or not text.strip():
        # step 系推理模型偶发只回 reasoning——重试一次交给调用方的外层循环。
        raise ShotRewriteError("rewrite_llm_empty", "LLM 返回了空内容。")
    return parse_shot_rewrite(text, expected=expected)


def request_shot_rewrite(
    *,
    settings,
    blueprint,
    client_factory=None,
    timeout_seconds: float = 180.0,
    attempts: int = 3,
) -> list[str]:
    """LLM 改写：原镜头 + 槽位 → 每镜新版描述（带空响应重试+污染修复）。"""

    inputs = build_rewrite_inputs(blueprint)
    if not inputs:
        raise ShotRewriteError("rewrite_no_shots", "蓝图没有可改写的镜头。")
    lines = [f"整体格式：{blueprint.format_name}（同一视觉风格、节奏、质感）。", "原片镜头拆解："]
    for item in inputs:
        lines.append(
            f"镜头{item.index}（{item.time_range}，{item.shot_size}/{item.camera_motion}）："
            f"{item.subject_action}"
            + (f"\n  原屏上文字：{item.on_screen_text}" if item.on_screen_text else "")
        )
    lines.append(f"槽位替换值：{inputs[0].slot_directives}")
    user_text = "\n".join(lines)

    markers = _original_markers(blueprint)
    last_error: ShotRewriteError | None = None
    for attempt in range(max(1, attempts)):
        repair_note = ""
        if attempt == 1:
            repair_note = "（上一版输出不合格：请检查没有任何原品牌/原产品名称残留，重新输出。）"
        elif attempt >= 2:
            repair_note = (
                "（再次强调：输出里不允许出现任何原品牌名、原产品名、原屏上文字，"
                "也不允许出现'原片/复刻'字样。只描述新版画面。）"
            )
        try:
            briefs = _call_rewrite(
                settings=settings,
                user_text=user_text,
                extra_user_note=repair_note,
                client_factory=client_factory,
                timeout_seconds=timeout_seconds,
                expected=len(inputs),
            )
        except ShotRewriteError as exc:
            last_error = exc
            continue
        if not _contaminated(briefs, markers):
            return briefs
        last_error = ShotRewriteError("rewrite_contaminated", "改写结果仍带原片名称。")
    raise last_error or ShotRewriteError("rewrite_failed", "改写失败。")


def resolve_shot_rewrites(
    *,
    settings,
    node,
    blueprint,
    patch_node,
) -> list[str] | None:
    """拿每镜新版描述：先查 replica 节点 parameters 缓存，没有再调 LLM。

    ``patch_node(parameters)`` 由调用方提供（写回缓存用）；缓存写失败不
    影响本次出片（顶多下次重试时重新改写）。任何异常都向上抛，由调用方
    决定降级——拿不到改写就退回"原描述 + 槽位指令行"的旧行为。
    """

    applied = [
        (slot.kind, slot.replace_with)
        for slot in blueprint.slots
        if slot.applied and slot.replace_with.strip()
    ]
    if not applied or not blueprint.shots:
        return None
    fingerprint = shot_rewrite_fingerprint(applied)
    parameters = dict(getattr(node, "parameters", {}) or {})
    cache = parameters.get(REWRITE_CACHE_KEY)
    if isinstance(cache, dict):
        cached = cache.get(fingerprint)
        if isinstance(cached, list) and len(cached) == len(blueprint.shots):
            return [str(item) for item in cached]
    briefs = request_shot_rewrite(settings=settings, blueprint=blueprint)
    new_cache = dict(cache) if isinstance(cache, dict) else {}
    new_cache[fingerprint] = briefs
    parameters[REWRITE_CACHE_KEY] = new_cache
    try:
        patch_node(parameters)
    except Exception as exc:  # noqa: BLE001 - 缓存写失败不该阻断出片
        import logging

        logging.getLogger(__name__).warning("shot rewrite cache write failed: %s", exc)
    return briefs
