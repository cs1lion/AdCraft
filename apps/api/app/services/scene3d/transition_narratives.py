"""LLM narrative polish for Transition Intent proposals.

The transition catalogue (``transition_proposals.py``) decides WHICH readings
are possible and WHAT each would do; the narratives it ships are honest rule
text. This module adds the LLM layer the V0.2 research asks for (§6.2/§15:
"LLM 负责扩展创作者的镜头想象、解释不同方案的叙事含义") in two bounded roles:

1. EXPLAIN — given the readings for a concrete shot pair, rewrite each
   narrative as the director-style explanation of WHY that cut works HERE.
2. PROPOSE — suggest readings BEYOND the rule catalogue.

Both roles run under one hard boundary: **the LLM never gains executable
authority**. Explanations only touch prose. Proposed readings must validate
against the operation vocabulary and the scene's own ids (see
:func:`validate_proposed_reading`); anything unverifiable is dropped with a
named reason, never smuggled into the operation list. That is how "LLM 提案"
stays advisory (V0.2 §6.3: LLM proposes, the creator chooses) — the machine
may imagine, but only the checked imagination reaches the picker.

Every failure mode degrades to the rule catalogue WITH a reported reason
(engineering standard §4 — silent fallbacks are forbidden).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.schemas.scene_script import (
    SceneCamera,
    SceneCharacter,
    SceneShot,
)
from app.services.scene3d.transition_proposals import TransitionOperation, TransitionProposal

NARRATIVE_SYSTEM_PROMPT = (
    "你是短片导演助手。给你若干「镜头衔接方案」（每条有 id、名称、规则解释和它将执行的"
    "具体操作），请为每一条写一句中文叙事理由：为什么这个切法在这次 A→B 的衔接上成立、"
    "它把观众的注意力引向哪里。只解释，不新增操作，不改变操作含义。"
    "以 JSON 返回：{\"narratives\": {\"<方案id>\": \"<一句中文>\"}}。"
    "没有意见的方案不要放进 JSON（调用方会保留原解释）。"
)

# The proposal fields the LLM may see. Operations are included as RATIONALE
# TEXT only — the LLM reads what a reading does but cannot change it.
_NARRATIVE_KEYS = ("id", "label", "narrative", "operations")


def build_narrative_prompt(
    *,
    shot_a_id: str,
    shot_b_id: str,
    proposals: list[TransitionProposal],
) -> tuple[str, str]:
    """The (system, user) prompt asking the LLM to explain the readings."""

    readings = [
        {
            "id": proposal.id,
            "label": proposal.label,
            "rule_narrative": proposal.narrative,
            "operations": [
                {"kind": operation.kind, "rationale": operation.rationale}
                for operation in proposal.operations
            ],
        }
        for proposal in proposals
    ]
    user_text = json.dumps(
        {
            "shot_pair": {"from": shot_a_id, "to": shot_b_id},
            "readings": readings,
        },
        ensure_ascii=False,
    )
    return NARRATIVE_SYSTEM_PROMPT, user_text


def parse_narrative_response(text: str) -> dict[str, str]:
    """Extract ``{proposal_id: narrative}`` from an LLM response.

    Fence-tolerant and fail-quiet: anything unparsable yields an empty map,
    which the caller treats as "no polish" (the rule narratives stand).
    Unknown keys are the VALIDATION step's problem, not this function's.
    """

    candidate = (text or "").strip()
    for attempt in (candidate, _strip_code_fence(candidate)):
        if not attempt:
            continue
        try:
            payload = json.loads(attempt)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("narratives"), dict):
            return {
                str(key): str(value)
                for key, value in payload["narratives"].items()
                if isinstance(value, str) and value.strip()
            }
    return {}


def _strip_code_fence(text: str) -> str:
    for fence in ("```json", "```"):
        if fence not in text:
            continue
        start = text.find(fence) + len(fence)
        end = text.find("```", start)
        if end > start:
            return text[start:end].strip()
    return ""


def apply_polished_narratives(
    proposals: list[TransitionProposal],
    polished: dict[str, str],
) -> list[TransitionProposal]:
    """Return the proposals with polished narratives where they exist.

    Only ids the caller asked about are honoured; a reading the LLM skipped
    keeps its rule narrative. Operations are never touched here — the map
    only contains narrative strings.
    """

    known = {proposal.id for proposal in proposals}
    from dataclasses import replace

    return [
        replace(proposal, narrative=polished[proposal.id])
        if proposal.id in polished and proposal.id in known
        else proposal
        for proposal in proposals
    ]


@dataclass(frozen=True)
class NarrativePolishResult:
    """The outcome of one polish attempt (degradation included)."""

    proposals: list[TransitionProposal]
    source: str  # "llm" | "rules"
    degraded_reason: str | None = None
    polished_ids: tuple[str, ...] = ()


def polish_transition_narratives(
    *,
    shot_a_id: str,
    shot_b_id: str,
    proposals: list[TransitionProposal],
    llm_call=None,
) -> NarrativePolishResult:
    """Explain the readings with an LLM, degrading honestly.

    ``llm_call`` is a seam: ``(system, user_text) -> str``. Tests inject a
    fake; production passes :func:`default_llm_call`, which raises a coded
    ``NarrativePolishUnavailable`` when the LLM is not configured or fails.
    """

    call = llm_call or default_llm_call
    system_prompt, user_text = build_narrative_prompt(
        shot_a_id=shot_a_id,
        shot_b_id=shot_b_id,
        proposals=proposals,
    )
    try:
        raw = call(system_prompt, user_text)
    except NarrativePolishUnavailable as error:
        return NarrativePolishResult(
            proposals=proposals,
            source="rules",
            degraded_reason=str(error),
        )
    polished = parse_narrative_response(raw)
    if not polished:
        return NarrativePolishResult(
            proposals=proposals,
            source="rules",
            degraded_reason="LLM 未返回可用的叙事 JSON，保留规则解释。",
        )
    merged = apply_polished_narratives(proposals, polished)
    # Compare each merged proposal against its ORIGINAL narrative (not the
    # replaced one — that comparison would always be false): "applied" means
    # the prose the creator sees actually changed.
    applied = tuple(
        original.id
        for original, merged_proposal in zip(proposals, merged)
        if polished.get(original.id) and merged_proposal.narrative != original.narrative
    )
    return NarrativePolishResult(
        proposals=merged,
        source="llm" if applied else "rules",
        degraded_reason=None if applied else "LLM 未覆盖任何读法，保留规则解释。",
        polished_ids=applied,
    )


class NarrativePolishUnavailable(Exception):
    """The LLM layer cannot run right now (config, HTTP, transport)."""


def default_llm_call(system_prompt: str, user_text: str) -> str:
    """The production LLM seam: same client conventions as the scene analyzers."""

    import httpx

    from app.core.config import get_settings

    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_base_url:
        raise NarrativePolishUnavailable(
            "LLM 未配置（LLM_API_KEY / LLM_BASE_URL），保留规则解释。"
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
        raise NarrativePolishUnavailable(f"LLM 调用失败：{error}") from error
    if response.status_code != 200:
        raise NarrativePolishUnavailable(
            f"LLM 返回 {response.status_code}，保留规则解释。"
        )
    try:
        payload = response.json()
        return str(payload["choices"][0]["message"]["content"])
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise NarrativePolishUnavailable(f"LLM 响应形状异常：{error}") from error


# ---------------------------------------------------------------------------
# Role 2: PROPOSE — readings beyond the rule catalogue, validated fail-closed
# ---------------------------------------------------------------------------

# The executable vocabulary. Parity contract (same ids on both sides, both
# pinned by tests): cameraMotionPresets.ts / characterMotionPresets.ts on the
# web. The LLM may only speak these words; anything else is dropped.
CAMERA_MOTION_PRESET_IDS: frozenset[str] = frozenset(
    {
        "push_in",
        "pull_out",
        "orbit_left",
        "orbit_right",
        "pan_left",
        "pan_right",
        "crane_up",
        "crane_down",
    }
)
CHARACTER_MOTION_PRESET_IDS: frozenset[str] = frozenset(
    {"walk_to", "turn_to", "approach", "mark_talk"}
)
OPERATION_KINDS: frozenset[str] = frozenset(
    {"camera_preset", "character_preset", "camera_place", "cut"}
)

PROPOSAL_SYSTEM_PROMPT = (
    "你是短片导演助手，为「镜头 A → 镜头 B」的衔接**补充规则目录之外的新读法**。"
    "每条读法 = 一个 id、一个中文名、一句叙事理由、以及一组可执行操作。"
    "操作只能使用给定词表：camera_preset（相机预设）/ character_preset（角色预设）/ "
    "camera_place（摆放新机位）/ cut（移动剪切点）。"
    "相机/角色的 id 必须来自场景清单；cut 必须给出 at_seconds 与 shot_id。"
    "不要重复已有的读法 id。以 JSON 返回："
    "{\"readings\": [{\"id\": \"...\", \"label\": \"...\", \"narrative\": \"...\", "
    "\"operations\": [{\"kind\": \"...\", \"preset_id\": \"...\", \"camera_id\": \"...\", "
    "\"character_id\": \"...\", \"at_seconds\": 0, \"shot_id\": \"...\"}]}]}。"
    "没有新的想法就返回 {\"readings\": []}——空答案是诚实且被接受的。"
)

# An id the LLM may invent: short, no whitespace, no path/quote characters.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class SceneVocabulary:
    """The scene ids an LLM-proposed operation may reference."""

    camera_ids: frozenset[str]
    character_ids: frozenset[str]
    shot_ids: frozenset[str]
    reserved_ids: frozenset[str]

    @classmethod
    def from_scene(
        cls,
        *,
        shots: list[SceneShot],
        characters: list[SceneCharacter],
        cameras: list[SceneCamera],
        reserved_ids: list[str],
    ) -> "SceneVocabulary":
        return cls(
            camera_ids=frozenset(camera.id for camera in cameras),
            character_ids=frozenset(character.id for character in characters),
            shot_ids=frozenset(shot.id for shot in shots),
            reserved_ids=frozenset(reserved_ids),
        )

    def with_exclusions(self, exclude_ids: list[str]) -> "SceneVocabulary":
        """The same vocabulary with extra reserved ids.

        This is the multi-round memory (V0.2 §15): readings the author already
        applied or dismissed are reserved for the next round, so the LLM is
        asked for something NEW rather than re-pitching the same idea.
        """

        return SceneVocabulary(
            camera_ids=self.camera_ids,
            character_ids=self.character_ids,
            shot_ids=self.shot_ids,
            reserved_ids=self.reserved_ids | frozenset(exclude_ids),
        )


def build_proposal_prompt(
    *,
    shot_a_id: str,
    shot_b_id: str,
    vocabulary: SceneVocabulary,
    existing_labels: list[str],
) -> tuple[str, str]:
    """The (system, user) prompt asking for NEW readings for this pair."""

    user_text = json.dumps(
        {
            "shot_pair": {"from": shot_a_id, "to": shot_b_id},
            "scene_ids": {
                "cameras": sorted(vocabulary.camera_ids),
                "characters": sorted(vocabulary.character_ids),
                "shots": sorted(vocabulary.shot_ids),
            },
            "preset_vocabulary": {
                "camera_presets": sorted(CAMERA_MOTION_PRESET_IDS),
                "character_presets": sorted(CHARACTER_MOTION_PRESET_IDS),
            },
            # The rule catalogue plus everything the author already engaged
            # with (applied or dismissed): the LLM reads them as TAKEN and
            # builds on them instead of repeating them.
            "existing_readings": existing_labels,
        },
        ensure_ascii=False,
    )
    return PROPOSAL_SYSTEM_PROMPT, user_text


def parse_proposed_readings(text: str) -> list[dict[str, object]]:
    """Extract the ``readings`` list from an LLM response (fence-tolerant).

    Unparsable output yields an empty list — the caller treats that as "no new
    ideas", which is an honest outcome, not a failure.
    """

    candidate = (text or "").strip()
    for attempt in (candidate, _strip_code_fence(candidate)):
        if not attempt:
            continue
        try:
            payload = json.loads(attempt)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("readings"), list):
            return [item for item in payload["readings"] if isinstance(item, dict)]
    return []


def _clean_id(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and _SAFE_ID.match(value.strip()) else None


def _replace_operation(
    operation: TransitionOperation,
    **changes: object,
) -> TransitionOperation:
    from dataclasses import replace

    return replace(operation, **changes)


def _validate_operation(
    raw: object,
    vocabulary: SceneVocabulary,
) -> tuple[TransitionOperation | None, str | None]:
    """Validate ONE proposed operation against the vocabulary and the scene."""

    if not isinstance(raw, dict):
        return None, "操作不是对象"
    kind = raw.get("kind")
    if kind not in OPERATION_KINDS:
        return None, f"未知操作类型 {kind!r}"
    rationale = raw.get("rationale")
    rationale_text = (
        rationale.strip()[:200]
        if isinstance(rationale, str) and rationale.strip()
        else "LLM 建议的操作"
    )
    start_frame = raw.get("start_frame")
    duration_frames = raw.get("duration_frames")
    operation = TransitionOperation(
        kind=kind,  # type: ignore[arg-type]
        rationale=rationale_text,
        preset_id=None,
        camera_id=None,
        character_id=None,
        start_frame=int(start_frame) if isinstance(start_frame, (int, float)) else None,
        duration_frames=(
            int(duration_frames) if isinstance(duration_frames, (int, float)) else None
        ),
        at_seconds=None,
        shot_id=None,
    )
    if kind == "camera_preset":
        preset_id = raw.get("preset_id")
        camera_id = raw.get("camera_id")
        if preset_id not in CAMERA_MOTION_PRESET_IDS:
            return None, f"未知相机预设 {preset_id!r}"
        if camera_id not in vocabulary.camera_ids:
            return None, f"未知相机 {camera_id!r}"
        return _replace_operation(operation, preset_id=preset_id, camera_id=camera_id), None
    if kind == "character_preset":
        preset_id = raw.get("preset_id")
        character_id = raw.get("character_id")
        if preset_id not in CHARACTER_MOTION_PRESET_IDS:
            return None, f"未知角色预设 {preset_id!r}"
        if character_id not in vocabulary.character_ids:
            return None, f"未知角色 {character_id!r}"
        return (
            _replace_operation(operation, preset_id=preset_id, character_id=character_id),
            None,
        )
    if kind == "camera_place":
        camera_id = raw.get("camera_id")
        if camera_id not in vocabulary.camera_ids:
            return None, f"未知相机 {camera_id!r}"
        return _replace_operation(operation, camera_id=camera_id), None
    # cut
    at_seconds = raw.get("at_seconds")
    shot_id = raw.get("shot_id")
    if not isinstance(at_seconds, (int, float)) or at_seconds < 0:
        return None, "cut 操作缺少有效的 at_seconds"
    if shot_id not in vocabulary.shot_ids:
        return None, f"cut 指向未知镜头 {shot_id!r}"
    return _replace_operation(operation, at_seconds=float(at_seconds), shot_id=shot_id), None


def validate_proposed_reading(
    raw: dict[str, object],
    vocabulary: SceneVocabulary,
    *,
    taken_ids: frozenset[str],
) -> tuple[TransitionProposal | None, str | None]:
    """Validate one proposed reading. Returns (proposal, None) or (None, reason).

    Fail-closed per reading: a reading that cannot be verified is DROPPED with
    its reason, and the other readings still arrive. The rule catalogue's ids
    are reserved — an LLM reading may not impersonate one.
    """

    reading_id = _clean_id(raw.get("id"))
    if reading_id is None:
        return None, "id 缺失或含非法字符"
    if reading_id in vocabulary.reserved_ids:
        return None, f"id {reading_id!r} 与规则读法冲突"
    if reading_id in taken_ids:
        return None, f"id {reading_id!r} 在本次响应里重复"
    label = raw.get("label")
    narrative = raw.get("narrative")
    if not (isinstance(label, str) and label.strip()):
        return None, "缺少 label"
    if not (isinstance(narrative, str) and narrative.strip()):
        return None, "缺少 narrative"

    raw_operations = raw.get("operations")
    if not isinstance(raw_operations, list) or not raw_operations:
        # A zero-operation reading adds nothing the catalogue's own "keep the
        # cut" reading doesn't already say; the bar for an LLM reading is that
        # it DOES something verifiable.
        return None, "没有可执行操作"

    operations: list[TransitionOperation] = []
    for raw_operation in raw_operations:
        operation, reason = _validate_operation(raw_operation, vocabulary)
        if operation is None:
            return None, f"操作校验失败：{reason}"
        operations.append(operation)

    return (
        TransitionProposal(
            id=reading_id,
            label=label.strip(),
            narrative=narrative.strip(),
            feasible=True,
            operations=tuple(operations),
            origin="llm",
        ),
        None,
    )


@dataclass(frozen=True)
class AdditionalReadingsResult:
    """The outcome of one proposal attempt (degradation included)."""

    readings: tuple[TransitionProposal, ...] = ()
    source: str = "rules"  # "llm" when at least one reading survived validation
    degraded_reason: str | None = None
    dropped: tuple[str, ...] = ()  # human-readable reasons for what was dropped


def propose_additional_readings(
    *,
    shot_a_id: str,
    shot_b_id: str,
    vocabulary: SceneVocabulary,
    existing_labels: list[str],
    exclude_ids: list[str] | None = None,
    llm_call=None,
) -> AdditionalReadingsResult:
    """Ask the LLM for new readings; validate every one; degrade honestly.

    ``exclude_ids`` are readings the author already engaged with (applied or
    dismissed in earlier rounds): they are reserved in the vocabulary, so a
    re-pitch is dropped with a named reason instead of silently re-listed.
    """

    call = llm_call or default_llm_call
    vocabulary = vocabulary.with_exclusions(list(exclude_ids or []))
    system_prompt, user_text = build_proposal_prompt(
        shot_a_id=shot_a_id,
        shot_b_id=shot_b_id,
        vocabulary=vocabulary,
        existing_labels=existing_labels,
    )
    try:
        raw = call(system_prompt, user_text)
    except NarrativePolishUnavailable as error:
        return AdditionalReadingsResult(degraded_reason=str(error))
    candidates = parse_proposed_readings(raw)
    if not candidates:
        return AdditionalReadingsResult(
            degraded_reason="LLM 未提出新读法（或响应不可解析），保留规则目录。",
        )

    accepted: list[TransitionProposal] = []
    dropped: list[str] = []
    taken: set[str] = set()
    for candidate in candidates:
        proposal, reason = validate_proposed_reading(
            candidate, vocabulary, taken_ids=frozenset(taken)
        )
        if proposal is None:
            candidate_id = _clean_id(candidate.get("id")) or "?"
            dropped.append(f"LLM 读法 {candidate_id} 被拒绝：{reason}")
            continue
        taken.add(proposal.id)
        accepted.append(proposal)

    if not accepted:
        return AdditionalReadingsResult(
            degraded_reason="LLM 提出的读法全部未通过校验，保留规则目录。",
            dropped=tuple(dropped),
        )
    return AdditionalReadingsResult(
        readings=tuple(accepted),
        source="llm",
        dropped=tuple(dropped),
    )
