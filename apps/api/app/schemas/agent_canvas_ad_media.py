"""Versioned advertising media contracts for Agent Canvas roles."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.schemas.agent_canvas import StorageAccessDescriptorV2
from app.schemas.agent_canvas_prompt_assertion import ProviderPromptAssertionEvidenceV1
from app.schemas.agent_canvas_role_prompt_preparation import CharacterGenderPresentationV1


AdMediaSemanticRoleV2 = Literal[
    "creative_brief",
    "world_setting",
    "script",
    "product",
    "prop",
    "character",
    "scene",
    "storyboard_sequence",
    "storyboard_video",
    "bgm",
    "general_text",
    "general_image",
    "general_video",
    "general_audio",
    "editing",
    "scene_3d_previs",
    "scene_3d_previs_clip",
    "voice_cast",
    "replica_blueprint",
]
VideoRepresentationModeV2 = Literal["illustrated", "illustration_to_live_action"]
SemanticReferenceRoleV2 = Literal[
    "world_setting_reference",
    "subject_reference",
    "environment_reference",
    "character_reference",
    "scene_reference",
    "product_reference",
    "prop_reference",
    "style_reference",
    "style_composition_reference",
    "storyboard_visual_reference",
]
GuidedReferenceKindV1 = Literal["character_main", "scene_main"]
GuidedReferencePurposeV1 = Literal["identity_guidance", "environment_guidance"]


#: Longest declared appearance palette (hex colours), shared with the
#: SceneScript side so an asset and the previs that proxies it agree on the
#: shape of the declaration (ADR 0011).
MAX_APPEARANCE_PALETTE_COLORS = 4


def _is_hex_color(value: str) -> bool:
    try:
        int(value[1:], 16)
    except ValueError:
        return False
    return True


class _AdMediaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VisualStyleContractV2(_AdMediaModel):
    style_prompt: str = Field(min_length=1, max_length=8_192)
    source: Literal["user", "video_skill", "references", "platform_default"]
    negative_style_constraints: tuple[str, ...] = Field(default=(), max_length=64)


class ProviderReferenceInstructionV1(_AdMediaModel):
    """Provider-only semantics for one explicitly selected guided reference."""

    reference_kind: GuidedReferenceKindV1
    semantic_purpose: GuidedReferencePurposeV1
    instruction: str = Field(min_length=1, max_length=512)


class DesignAssetContentV2(_AdMediaModel):
    asset_kind: Literal["main", "multi_view"] = "main"
    subject_identity: str = Field(min_length=1, max_length=4_096)
    design_summary: str = Field(min_length=1, max_length=8_192)
    style: VisualStyleContractV2
    explicit_inclusions: tuple[str, ...] = Field(default=(), max_length=64)
    negative_constraints: tuple[str, ...] = Field(default=(), max_length=64)


CharacterAssetKindV2 = Literal["identity_master", "turnaround"]
CharacterReferenceRenderingModeV2 = Literal["detailed_semi_realistic_illustration"]


class CharacterDesignAssetContentV2(DesignAssetContentV2):
    # None denotes absent historical proof, not an authored unspecified value.
    face_and_hair: str | None = Field(default=None, min_length=1, max_length=2_048)
    silhouette_and_proportions: str | None = Field(default=None, min_length=1, max_length=2_048)
    wardrobe: str | None = Field(default=None, min_length=1, max_length=2_048)
    accessories: str | None = Field(default=None, max_length=1_024)
    gender_presentation: CharacterGenderPresentationV1 | None = None
    # ADR 0011: the character's DECLARED wardrobe palette — the asset is the
    # source of truth for how this person looks, and the 3D previs is a proxy
    # that must not invent it. Optional and additive: an asset generated
    # before this contract existed simply has nothing to declare, and the
    # previs-side gate stays silent (nothing declared is not a drift).
    appearance_palette: tuple[str, ...] | None = Field(
        default=None,
        max_length=MAX_APPEARANCE_PALETTE_COLORS,
        description="Declared wardrobe palette (1-4 hex colors), ADR 0011",
    )
    character_asset_kind: CharacterAssetKindV2 = "identity_master"
    reference_rendering_mode: CharacterReferenceRenderingModeV2 = (
        "detailed_semi_realistic_illustration"
    )
    occurrence_id: str | None = Field(default=None, min_length=1, max_length=160)
    parent_source_node_id: str | None = Field(default=None, min_length=1, max_length=160)
    parent_source_node_revision: int | None = Field(default=None, ge=1)
    parent_asset_version_id: str | None = Field(default=None, min_length=1, max_length=160)
    identity_projection_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[a-f0-9]{64}$",
    )

    @field_validator("appearance_palette", mode="before")
    @classmethod
    def _coerce_appearance_palette(cls, value: object) -> object:
        # Same tolerance as the SceneScript palette: a free-text description
        # (an LLM writing "black coat" where hex belongs) is dropped rather
        # than failing the whole character design, and an unparsable hex is
        # NOT kept as a colour the drift gate would later compare against.
        if not isinstance(value, (list, tuple)) or not value:
            return None
        kept: list[str] = []
        for entry in value:
            if (
                isinstance(entry, str)
                and entry.startswith("#")
                and len(entry) in (4, 7)
                and _is_hex_color(entry)
            ):
                kept.append(entry.upper())
        return tuple(kept[:MAX_APPEARANCE_PALETTE_COLORS]) or None


class SceneBoardPanelV2(_AdMediaModel):
    panel_index: int = Field(ge=1, le=9)
    view_or_zone: str = Field(min_length=1, max_length=1_024)
    spatial_description: str = Field(min_length=1, max_length=4_096)
    lighting_material_detail: str = Field(min_length=1, max_length=2_048)


class SceneDesignBoardContentV2(_AdMediaModel):
    scene_identity: str = Field(min_length=1, max_length=4_096)
    environment_summary: str = Field(min_length=1, max_length=8_192)
    layout: str = Field(min_length=1, max_length=4_096)
    lighting: str = Field(min_length=1, max_length=2_048)
    materials: str = Field(min_length=1, max_length=2_048)
    time_of_day: str = Field(min_length=1, max_length=512)
    style: VisualStyleContractV2
    panels: tuple[SceneBoardPanelV2, ...] = Field(min_length=9, max_length=9)
    explicit_entity_reference_ids: tuple[str, ...] = Field(default=(), max_length=32)
    exclude_unreferenced_entities: Literal[True] = True
    no_narrative_progression: Literal[True] = True
    environment_projection_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[a-f0-9]{64}$",
    )

    @model_validator(mode="after")
    def validate_panel_sequence(self) -> "SceneDesignBoardContentV2":
        _require_panel_sequence(self.panels, "scene_design_board_contract_invalid")
        _require_distinct_panel_values(
            self.panels,
            lambda panel: (panel.view_or_zone, panel.spatial_description),
            "scene_design_board_contract_invalid",
        )
        return self


class StoryboardPanelV2(_AdMediaModel):
    panel_index: int = Field(ge=1, le=9)
    beat: str = Field(min_length=1, max_length=2_048)
    composition: str = Field(min_length=1, max_length=2_048)
    camera: str = Field(min_length=1, max_length=1_024)
    subject_action: str = Field(min_length=1, max_length=2_048)
    continuity_from_previous: str = Field(min_length=1, max_length=2_048)
    # --- Structured derivation fields (P0, 2026-09-15) ---
    scene_id: str | None = Field(default=None, max_length=160)
    character_ids: tuple[str, ...] = Field(default=(), max_length=16)
    prop_ids: tuple[str, ...] = Field(default=(), max_length=32)
    shot_type: Literal["wide", "medium", "close-up", "ecu", "ots"] | None = None
    camera_move: Literal["static", "pan", "tilt", "dolly", "zoom", "crane", "handheld"] | None = None
    duration_seconds: float | None = Field(default=None, ge=0.5, le=60)
    scene_script_id: str | None = Field(default=None, max_length=160)
    character_speech_map: dict[str, str] = Field(
        default_factory=dict,
        description="Maps character_id to speech_audio asset_id for lip-sync and bound-mode timing (P2, per ADR bulletin Objection 3)",
    )


class StoryboardGridContentV2(_AdMediaModel):
    sequence_summary: str = Field(min_length=1, max_length=8_192)
    narrative_goal: str = Field(min_length=1, max_length=4_096)
    style: VisualStyleContractV2
    panels: tuple[StoryboardPanelV2, ...] = Field(min_length=9, max_length=9)
    no_generated_text: Literal[True] = True

    @model_validator(mode="after")
    def validate_panel_sequence(self) -> "StoryboardGridContentV2":
        _require_panel_sequence(self.panels, "storyboard_grid_contract_invalid")
        _require_distinct_panel_values(
            self.panels,
            lambda panel: (
                panel.beat,
                panel.composition,
                panel.camera,
                panel.subject_action,
            ),
            "storyboard_grid_contract_invalid",
        )
        return self


class VideoSegmentContentV2(_AdMediaModel):
    segment_summary: str = Field(min_length=1, max_length=8_192)
    duration_seconds: float = Field(gt=0, le=3_600)
    storyboard_content: str = Field(min_length=1, max_length=16_384)
    representation_mode: VideoRepresentationModeV2 = "illustrated"
    style: VisualStyleContractV2 | None = None
    dialogue: str = Field(default="", max_length=8_192)
    voice_style: str = Field(default="", max_length=2_048)
    environment_sound: str = Field(default="", max_length=4_096)
    action_effects: str = Field(default="", max_length=4_096)
    negative_constraints: str = Field(default="", max_length=8_192)
    background_music: Literal[False] = False


class PrevisClipKeyframeV2(_AdMediaModel):
    """One keyframe image extracted from a published previs clip (ADR 0017).

    Published at clip publish time and carried in the clip node's structured
    content so the flash degradation channel can substitute these images for
    the un-deliverable video reference without touching ffmpeg at run time.
    """

    asset_id: str = Field(min_length=1, max_length=160)
    asset_version_id: str = Field(min_length=1, max_length=160)
    checksum: str = Field(min_length=8, max_length=128)
    offset_seconds: float = Field(ge=0)
    reference_instruction: str = Field(min_length=1, max_length=512)


class PrevisClipContentV2(_AdMediaModel):
    """分镜预演参考片段（ADR 0017）：scene-3d 节点按镜头裁切的预演视频。

    血缘是内容的一半：``scene_3d_node_id`` + ``shot_id`` 说明这段预演拍的是
    哪个 3D 场景的哪一镜，``source_asset_id`` 指回裁切源 animatic。关键帧
    （``previs_keyframes``）是发布时抽好的降级通道燃料——flash 档视频模型
    不吃视频参考时，吃的是它们。
    """

    previs_clip_version: Literal["previs-clip-v1"] = "previs-clip-v1"
    scene_3d_node_id: str = Field(min_length=1, max_length=160)
    scene_3d_node_title: str = Field(default="", max_length=512)
    shot_id: str = Field(min_length=1, max_length=160)
    shot_label: str = Field(default="", max_length=512)
    take_id: str | None = Field(default=None, max_length=160)
    source_asset_id: str = Field(min_length=1, max_length=160)
    clip_asset_id: str = Field(min_length=1, max_length=160)
    clip_asset_version_id: str = Field(min_length=1, max_length=160)
    frame_range: tuple[int, int] = Field(default=(0, 0))
    duration_seconds: float = Field(gt=0, le=3_600)
    previs_keyframes: tuple[PrevisClipKeyframeV2, ...] = Field(default=(), max_length=8)
    previs_control_level: Literal["video", "images_only", "none"] = "video"


class BgmContentV2(_AdMediaModel):
    music_summary: str = Field(min_length=1, max_length=8_192)
    duration_seconds: float = Field(gt=0, le=3_600)
    pace: str = Field(min_length=1, max_length=1_024)
    energy_curve: str = Field(min_length=1, max_length=2_048)
    instrumentation: str = Field(min_length=1, max_length=2_048)
    mood: str = Field(min_length=1, max_length=1_024)
    instrumental_only: Literal[True] = True
    no_vocals: Literal[True] = True


class ReferenceRequirementV2(_AdMediaModel):
    binding_kind: Literal[
        "text_context",
        "image_reference",
        "video_reference",
        "audio_reference",
    ]
    required_role: str | None = None
    minimum: int = Field(default=0, ge=0)
    maximum: int = Field(default=8, ge=1)


class ReplicaSlotV2(_AdMediaModel):
    """一个复刻槽位（hypit 组件化替换的"槽"）。

    ``source_value`` 是原片值（拆解所得），``replace_with`` 是用户替换值
    （资产 ID / 风格 skill ID / 自由文本）；``applied`` 由后端在填充
    ``replace_with`` 时置位，前端只读写两个字符串字段。
    """

    kind: Literal["character", "product", "script", "style", "voice", "scene"]
    label: str = Field(min_length=1, max_length=32)
    source_value: str = Field(default="", max_length=2_048)
    replace_with: str = Field(default="", max_length=2_048)
    applied: bool = False


class ReplicaAnchorEventV2(_AdMediaModel):
    """锚点事件：hypit 词锚定的落地形态（P1 段落级 → P2 词级升级）。

    ``trigger`` 是触发词/触发条件（拆解所得）；词级对齐（whisperX）可用时
    ``word``/``word_start_seconds``/``word_end_seconds`` 记录锚点绑定的具体
    词语与时间跨度——``.adreplica`` 里以行内 ``@{id}词@{/id}`` 表达。三个
    字段默认空值 = 未绑定词（段落级锚点，旧节点内容向后兼容）。
    """

    event_id: str = Field(min_length=1, max_length=64)
    trigger: str = Field(default="", max_length=256)
    beat_id: str = Field(default="", max_length=64)
    kind: Literal["broll", "caption", "sfx", "mg", "transition"]
    hint: str = Field(default="", max_length=1_024)
    keep: bool = True
    word: str = Field(default="", max_length=128)
    word_start_seconds: float = Field(default=0.0, ge=0)
    word_end_seconds: float = Field(default=0.0, ge=0)
    # 词锚窗口的端点亲和性（hypit 的 left/right 语义）：
    # right = 窗口端点取后一词首（默认，间隙归前一事件所有）；
    # left = 取前一词尾（间隙归后一事件所有）。
    # 仅对词级锚点（word 非空）有实际影响；段落级锚点忽略。
    affinity: Literal["left", "right"] = "right"
    # narrative token 层（G4，hypit P1 主项）：锚点绑定的**授权序区间**
    # （token id 对）——与帧时间解耦，改台词/重转写后 binding 天然存活，
    # 秒数是从词流重算的投影（reproject_anchor_seconds）。默认空 = 无
    # token 层的旧锚点（纯文本 + 已解析秒数，向后兼容）。
    start_token_id: str = Field(default="", max_length=96)
    end_token_id: str = Field(default="", max_length=96)


class ReplicaBeatWordV2(_AdMediaModel):
    """段落台词里的一个词（词级 karaoke 的时间原子，G3 后半）。

    来自词级转录（whisperX 词流按段落窗归集）：``text`` 是词面，时间为
    转录实测。**时间是派生数据**——与锚点词窗同纪律，不进 ``.adreplica``
    文档（文档存绑定、编译对时），因此手改文档导入后 words 为空、字幕退化为
    行级（不造假时间）。
    """

    text: str = Field(min_length=1, max_length=512)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)


class ReplicaBeatV2(_AdMediaModel):
    beat_id: str = Field(min_length=1, max_length=64)
    role: str = Field(default="body", max_length=32)
    description: str = Field(default="", max_length=2_048)
    # 段落台词原文（词级转录可用时来自转录）：词级锚定的文本载体
    line: str = Field(default="", max_length=2_048)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    anchor_event_ids: list[str] = Field(default_factory=list, max_length=64)
    # 词级 karaoke 的词窗（无转录时为空 → 行级字幕，向后兼容）
    words: list[ReplicaBeatWordV2] = Field(default_factory=list, max_length=512)


class ReplicaShotV2(_AdMediaModel):
    index: int = Field(ge=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    shot_size: str = Field(default="medium", max_length=32)
    camera_motion: str = Field(default="static", max_length=32)
    subject_action: str = Field(default="", max_length=2_048)
    on_screen_text: str = Field(default="", max_length=512)
    transition_to_next: str = Field(default="cut", max_length=32)
    recreate_hint: str = Field(default="", max_length=1_024)


class ReplicaBlueprintContentV2(_AdMediaModel):
    """拉片复刻蓝图：scene-3d 之外新增的 ``replica`` 节点的结构化内容。

    单一真相源：蓝图即节点内容；实例化（蓝图 → script 节点）由
    ``POST /api/v1/replica/instantiate`` 完成，执行仍走既有工作流引擎。
    """

    blueprint_version: Literal["replica-blueprint-v1"] = "replica-blueprint-v1"
    source_video_asset_id: str = Field(default="", max_length=128)
    duration_seconds: float = Field(default=0.0, ge=0)
    aspect: str = Field(default="", max_length=16)
    replica_goal: str = Field(default="", max_length=256)
    whole_piece_reading: str = Field(default="", max_length=8_192)
    format_name: str = Field(default="short-video", max_length=64)
    slots: list[ReplicaSlotV2] = Field(default_factory=list, max_length=16)
    beats: list[ReplicaBeatV2] = Field(default_factory=list, max_length=64)
    anchor_events: list[ReplicaAnchorEventV2] = Field(
        default_factory=list, max_length=256
    )
    shots: list[ReplicaShotV2] = Field(default_factory=list, max_length=128)
    rhythm_avg_shot_seconds: float = Field(default=0.0, ge=0)
    rhythm_cut_points_seconds: list[float] = Field(default_factory=list, max_length=256)
    rhythm_energy_curve: str = Field(default="", max_length=512)
    systems_captions: str = Field(default="", max_length=1_024)
    systems_music: str = Field(default="", max_length=1_024)
    systems_graphics: list[str] = Field(default_factory=list, max_length=32)
    systems_sfx: list[str] = Field(default_factory=list, max_length=32)
    constraints: list[str] = Field(default_factory=list, max_length=16)
    instantiated_script_node_id: str | None = Field(default=None, max_length=128)


class AdMediaRoleContractV2(_AdMediaModel):
    semantic_role: AdMediaSemanticRoleV2
    node_type: Literal[
        "text",
        "script",
        "image",
        "video",
        "audio",
        "editing",
        "scene-3d",
        "voice-cast",
        "replica",
    ]
    output_media_type: Literal["text", "image", "video", "audio"]
    role_contract_version: Literal["ad-media-role-v2"] = "ad-media-role-v2"
    content_schema_ref: str
    output_cardinality: Literal[1] = 1
    reference_requirements: tuple[ReferenceRequirementV2, ...] = ()


class ResolvedAdReferenceV2(_AdMediaModel):
    binding_id: str
    binding_revision: int | None = Field(default=None, ge=1, exclude=True)
    source_kind: Literal["node_output", "image_asset"]
    source_node_id: str | None = None
    source_node_revision: int | None = Field(default=None, ge=1, exclude=True)
    source_sequence_id: str | None = Field(default=None, min_length=1, exclude=True)
    source_semantic_role: str | None = None
    occurrence_id: str | None = Field(default=None, min_length=1)
    character_phase: Literal["main", "turnaround"] | None = None
    semantic_reference_role: SemanticReferenceRoleV2 | None = None
    reference_kind: GuidedReferenceKindV1 | None = None
    reference_purpose: GuidedReferencePurposeV1 | None = None
    reference_instruction: ProviderReferenceInstructionV1 | None = None
    storyboard_reference_purpose: Literal["sequence_visual_anchor"] | None = None
    asset_id: str
    asset_version_id: str = Field(min_length=1)
    media_type: Literal["image", "video", "audio"]
    display_order: int = Field(ge=0)
    source_identity_facts: dict[str, JsonValue] = Field(default_factory=dict)
    access_descriptor: StorageAccessDescriptorV2

    @model_validator(mode="after")
    def validate_character_identity(self) -> "ResolvedAdReferenceV2":
        if (self.occurrence_id is None) != (self.character_phase is None):
            raise ValueError("Resolved Character identity requires occurrence and phase.")
        return self


class AdReferenceBundleV2(_AdMediaModel):
    target_node_id: str
    references: tuple[ResolvedAdReferenceV2, ...]
    bundle_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class ProviderModelCapabilityV2(_AdMediaModel):
    model_id: str
    max_duration_seconds: float | None = Field(default=None, gt=0)
    supports_native_audio: bool = False
    max_reference_images: int = Field(default=8, ge=0)


class CompiledProviderPromptV2(_AdMediaModel):
    semantic_role: AdMediaSemanticRoleV2
    prompt_registry_ref: str
    prompt_registry_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    render_context_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reference_bundle_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    style_source: Literal["user", "video_skill", "references", "platform_default"]
    prompt: str
    negative_prompt: str
    provider_parameters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    reference_instructions: tuple[ProviderReferenceInstructionV1, ...] = ()
    assertion_evidence: ProviderPromptAssertionEvidenceV1 | None = None


def resolve_visual_style(
    *,
    user_style: VisualStyleContractV2 | None = None,
    video_skill_style: VisualStyleContractV2 | None = None,
    reference_style: VisualStyleContractV2 | None = None,
) -> VisualStyleContractV2:
    if user_style is not None:
        return user_style.model_copy(update={"source": "user"})
    if video_skill_style is not None:
        return video_skill_style.model_copy(update={"source": "video_skill"})
    if reference_style is not None:
        return reference_style.model_copy(update={"source": "references"})
    return VisualStyleContractV2(
        style_prompt="Detailed semi-realistic advertising illustration",
        source="platform_default",
    )


def _require_panel_sequence(panels: tuple[object, ...], error_code: str) -> None:
    if [getattr(panel, "panel_index") for panel in panels] != list(range(1, 10)):
        raise ValueError(error_code)


def _require_distinct_panel_values(
    panels: tuple[object, ...],
    signature: Callable[[object], object],
    error_code: str,
) -> None:
    values = [signature(panel) for panel in panels]
    if len(values) != len(set(values)):
        raise ValueError(error_code)
