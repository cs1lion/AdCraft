"""LLM narrative proposals for shot advisories (V0.2 §14.3/§14.5, §6.2/§15).

The shot advisor (``shot_advisor.py``) decides WHERE the shot list and the
speech timeline disagree and ships honest rule remedies. This module adds the
LLM layer the audit table asks for: given the advisories, the shots, and the
segments, the LLM proposes ADDITIONAL remedies in the creator's own language
("把 s2 缩短半秒，让 s1 有足够时间说完").

The hard boundary mirrors ``transition_narratives.py``: **the LLM never gains
executable authority**. A proposal must reference a shot that exists in this
scene, name a concrete remedy in prose, and is advisory only — the creator
reads it and decides. Anything unverifiable is dropped with a named reason,
never smuggled into the advisory list (V0.2 §6.3: LLM proposes, the creator
chooses). Every failure mode degrades to the rule catalogue WITH a reported
reason (engineering standard §4 — silent fallbacks are forbidden).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.schemas.scene_script import SceneShot
from app.services.scene3d.shot_advisor import ShotAdvisory
from app.services.scene3d.speech_orchestration import SpeechSegment

ADVISORY_SYSTEM_PROMPT = (
    "你是短片导演助手。给你一个场景的镜头列表、台词分段，以及规则版分镜顾问"
    "已经发现的问题（每条有 code、涉及的镜头、规则补救语）。请为每一条问题"
    "补充一句中文的可执行建议：具体怎么改、改哪个镜头、大概改动幅度。"
    "只补充建议，不改变规则发现的事实，不新增问题。"
    "以 JSON 返回：{\"proposals\": [{\"advisory_code\": \"<问题code>\", "
    "\"shot_id\": \"<涉及的镜头id>\", \"suggestion\": \"<一句中文建议>\"}]}。"
    "没有补充意见的问题不要放进 JSON（调用方会保留原补救语）。"
)

# The advisory fields the LLM may see. proposal_ids are included as text
# only — the LLM reads which Transition Intent readings exist but cannot
# create new ones.
_ADVISORY_KEYS = ("code", "shot_id", "message", "remedy", "proposal_ids")
_SHOT_KEYS = ("id", "camera", "start_frame", "end_frame", "description")
_SEGMENT_KEYS = ("segment_id", "character_id", "text", "start_time", "end_time")


@dataclass(frozen=True, slots=True)
class AdvisoryProposal:
    """One LLM-proposed remedy for a rule advisory."""

    advisory_code: str
    shot_id: str
    suggestion: str

    def to_dict(self) -> dict[str, object]:
        return {
            "advisory_code": self.advisory_code,
            "shot_id": self.shot_id,
            "suggestion": self.suggestion,
            "origin": "llm",
        }


def build_advisory_prompt(
    *,
    shots: list[SceneShot],
    segments: list[SpeechSegment],
    advisories: list[ShotAdvisory],
) -> tuple[str, str]:
    """The (system, user) prompt asking the LLM to propose remedies."""

    shot_payload = [
        {key: getattr(shot, key) for key in _SHOT_KEYS if hasattr(shot, key)}
        for shot in shots
    ]
    segment_payload = [
        {key: getattr(segment, key) for key in _SEGMENT_KEYS if hasattr(segment, key)}
        for segment in segments
    ]
    advisory_payload = [
        {key: getattr(advisory, key) for key in _ADVISORY_KEYS if hasattr(advisory, key)}
        for advisory in advisories
    ]
    user_prompt = json.dumps(
        {
            "shots": shot_payload,
            "segments": segment_payload,
            "advisories": advisory_payload,
        },
        ensure_ascii=False,
    )
    return ADVISORY_SYSTEM_PROMPT, user_prompt


def validate_proposed_advisory(
    raw: object,
    *,
    advisories: list[ShotAdvisory],
    valid_shot_ids: set[str],
) -> tuple[AdvisoryProposal | None, str | None]:
    """Validate one LLM proposal against the scene's own ids.

    Returns (proposal, None) on success or (None, reason) on rejection. A
    proposal must reference an advisory that EXISTS (the creator must be able
    to trace it back to a rule finding), a shot that EXISTS (a suggestion
    about a shot nobody authored is noise), and carry a non-empty suggestion.
    """

    if not isinstance(raw, dict):
        return None, "提案不是对象"
    code = str(raw.get("advisory_code") or "").strip()
    shot_id = str(raw.get("shot_id") or "").strip()
    suggestion = str(raw.get("suggestion") or "").strip()
    if not code:
        return None, "提案缺少 advisory_code"
    if not shot_id:
        return None, "提案缺少 shot_id"
    if shot_id not in valid_shot_ids:
        return None, f"shot_id「{shot_id}」不在本场景的镜头列表里"
    if not any(advisory.code == code for advisory in advisories):
        return None, f"advisory_code「{code}」不是规则顾问发现的问题"
    if not suggestion:
        return None, "提案缺少 suggestion"
    if len(suggestion) > 500:
        return None, f"suggestion 超过 500 字符（{len(suggestion)}）"
    return AdvisoryProposal(advisory_code=code, shot_id=shot_id, suggestion=suggestion), None


def parse_advisory_proposals(
    *,
    text: str,
    advisories: list[ShotAdvisory],
    valid_shot_ids: set[str],
) -> tuple[list[AdvisoryProposal], list[str]]:
    """Parse and validate the LLM's advisory proposals.

    Returns (accepted_proposals, dropped_reasons). Malformed JSON, a
    non-list ``proposals`` key, and every per-proposal validation failure
    land in the dropped list WITH a reason — the caller reports them rather
    than silently falling back.
    """

    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return [], ["LLM 返回的不是合法 JSON"]
    if not isinstance(payload, dict):
        return [], ["LLM 返回的不是对象"]
    raw_proposals = payload.get("proposals")
    if not isinstance(raw_proposals, list):
        return [], ["LLM 返回缺少 proposals 列表"]

    accepted: list[AdvisoryProposal] = []
    dropped: list[str] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_proposals):
        proposal, reason = validate_proposed_advisory(
            raw,
            advisories=advisories,
            valid_shot_ids=valid_shot_ids,
        )
        if proposal is None:
            dropped.append(f"proposals[{index}] 被丢弃：{reason}")
            continue
        key = (proposal.advisory_code, proposal.shot_id)
        if key in seen:
            dropped.append(f"proposals[{index}] 被丢弃：与已接受的提案重复")
            continue
        seen.add(key)
        accepted.append(proposal)
    return accepted, dropped


# ---------------------------------------------------------------------------
# The LLM call layer (same seam discipline as transition_narratives.py)
# ---------------------------------------------------------------------------


class AdvisoryProposalUnavailable(Exception):
    """The LLM layer cannot run right now (config, HTTP, transport)."""


def default_llm_call(system_prompt: str, user_text: str) -> str:
    """The production LLM seam: same client conventions as the scene analyzers."""

    import httpx

    from app.core.config import get_settings

    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_base_url:
        raise AdvisoryProposalUnavailable(
            "LLM 未配置（LLM_API_KEY / LLM_BASE_URL），保留规则补救语。"
        )
    model = settings.llm_scene_model or settings.llm_front_desk_model
    try:
        response = httpx.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                "max_tokens": 800,
                "temperature": 0.4,
            },
            timeout=60,
        )
    except httpx.HTTPError as error:
        raise AdvisoryProposalUnavailable(f"LLM 调用失败：{error}") from error
    if response.status_code != 200:
        raise AdvisoryProposalUnavailable(
            f"LLM 返回 {response.status_code}，保留规则补救语。"
        )
    try:
        payload = response.json()
        return str(payload["choices"][0]["message"]["content"])
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise AdvisoryProposalUnavailable(f"LLM 响应形状异常：{error}") from error


@dataclass(frozen=True, slots=True)
class AdvisoryProposalResult:
    """The outcome of asking the LLM to propose advisory remedies."""

    proposals: tuple[AdvisoryProposal, ...]
    dropped: tuple[str, ...]
    degraded_reason: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "proposals": [proposal.to_dict() for proposal in self.proposals],
            "dropped": list(self.dropped),
            "degraded_reason": self.degraded_reason,
        }


def propose_advisory_narratives(
    *,
    shots: list[SceneShot],
    segments: list[SpeechSegment],
    advisories: list[ShotAdvisory],
    llm_call=None,
) -> AdvisoryProposalResult:
    """Ask the LLM to propose remedies, degrading honestly.

    ``llm_call`` is a seam: ``(system, user_text) -> str``. Tests inject a
    fake; production passes :func:`default_llm_call`, which raises a coded
    :class:`AdvisoryProposalUnavailable` when the LLM is not configured or
    fails.

    Every proposal is validated against the scene's own ids before it
    reaches the response (see :func:`validate_proposed_advisory`); drops are
    reported with a named reason, never silent (engineering standard §4).
    """

    if not advisories:
        # No rule findings to build on: proposing would be guessing.
        return AdvisoryProposalResult(
            proposals=(),
            dropped=(),
            degraded_reason=None,
        )

    call = llm_call or default_llm_call
    system_prompt, user_text = build_advisory_prompt(
        shots=shots,
        segments=segments,
        advisories=advisories,
    )
    try:
        raw = call(system_prompt, user_text)
    except AdvisoryProposalUnavailable as error:
        return AdvisoryProposalResult(
            proposals=(),
            dropped=(),
            degraded_reason=str(error),
        )
    accepted, dropped = parse_advisory_proposals(
        text=raw,
        advisories=advisories,
        valid_shot_ids={shot.id for shot in shots},
    )
    if accepted:
        return AdvisoryProposalResult(
            proposals=tuple(accepted),
            dropped=tuple(dropped),
            degraded_reason=None,
        )
    # Nothing survived: say WHY (a parse failure and an all-dropped batch are
    # different problems for the author), never a bare "no proposals".
    reason = "LLM 未返回可用的补充建议，保留规则补救语。"
    if dropped:
        reason = f"{reason}（{'；'.join(dropped)}）"
    return AdvisoryProposalResult(
        proposals=(),
        dropped=tuple(dropped),
        degraded_reason=reason,
    )
