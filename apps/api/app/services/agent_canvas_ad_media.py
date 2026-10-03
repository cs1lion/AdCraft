"""Semantic-role registry and structured Draft validation for Agent Canvas."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_ad_media import (
    AdMediaRoleContractV2,
    BgmContentV2,
    CharacterDesignAssetContentV2,
    DesignAssetContentV2,
    PrevisClipContentV2,
    ReplicaBlueprintContentV2,
    SceneDesignBoardContentV2,
    StoryboardGridContentV2,
    VideoSegmentContentV2,
)


@dataclass(frozen=True, slots=True)
class _RegisteredRole:
    contract: AdMediaRoleContractV2
    content_model: type[BaseModel] | None


class AdMediaRoleRegistry:
    """Resolve one immutable advertising contract per semantic role."""

    def __init__(self) -> None:
        self._roles = _role_registry()

    def get(self, semantic_role: str) -> AdMediaRoleContractV2:
        registered = self._roles.get(semantic_role)
        if registered is None:
            raise _error("invalid_semantic_role", "Semantic role is not registered.")
        return registered.contract

    def validate_node_type(self, node_type: str, semantic_role: str) -> None:
        contract = self.get(semantic_role)
        if contract.node_type != node_type:
            # Name both node types: the role registry already declares the
            # only node type a role may live on, so telling the caller what it
            # sent turns "incompatible" into a one-field correction.
            raise _error(
                "semantic_role_node_type_mismatch",
                "Semantic role is incompatible with the node type.",
                details={
                    "semantic_role": semantic_role,
                    "expected_node_type": contract.node_type,
                    "received_node_type": node_type,
                },
            )

    def validate_structured_content(
        self,
        semantic_role: str,
        content: dict[str, object],
    ) -> BaseModel | None:
        registered = self._roles.get(semantic_role)
        if registered is None:
            raise _error("invalid_semantic_role", "Semantic role is not registered.")
        if registered.content_model is None:
            return None
        try:
            return registered.content_model.model_validate(content)
        except ValidationError as error:
            code = {
                "scene": "scene_design_board_contract_invalid",
                "storyboard_sequence": "storyboard_grid_contract_invalid",
            }.get(semantic_role, "invalid_role_content")
            # Flatten Pydantic's error list into field paths. Without these
            # every role that is not scene/storyboard collapses to the same
            # opaque code, so the caller cannot tell what the model expects;
            # ``content_schema_ref`` names the model to read next.
            raise _error(
                code,
                "Structured role content is invalid.",
                details={
                    "semantic_role": semantic_role,
                    "content_schema_ref": registered.contract.content_schema_ref,
                    "validation_paths": _flatten_validation_paths(error),
                },
            ) from error


class AdMediaDraftValidationService:
    """Validate role compatibility without rewriting creative prose."""

    def __init__(self, registry: AdMediaRoleRegistry | None = None) -> None:
        self._registry = registry or AdMediaRoleRegistry()

    def validate(
        self,
        *,
        node_type: str,
        semantic_role: str,
        structured_content: dict[str, object],
    ) -> AdMediaRoleContractV2:
        self._registry.validate_node_type(node_type, semantic_role)
        self._registry.validate_structured_content(
            semantic_role,
            structured_content,
        )
        return self._registry.get(semantic_role)


def _role_registry() -> dict[str, _RegisteredRole]:
    roles: dict[str, _RegisteredRole] = {}

    def add(
        role: str,
        node_type: str,
        media_type: str,
        model: type[BaseModel] | None = None,
    ) -> None:
        roles[role] = _RegisteredRole(
            contract=AdMediaRoleContractV2(
                semantic_role=role,
                node_type=node_type,
                output_media_type=media_type,
                content_schema_ref=model.__name__ if model else "FreeformContentV2",
            ),
            content_model=model,
        )

    for role in ("creative_brief", "world_setting", "general_text"):
        add(role, "text", "text")
    add("script", "script", "text")
    add("general_image", "image", "image")
    for role in ("product", "prop"):
        add(role, "image", "image", DesignAssetContentV2)
    add("character", "image", "image", CharacterDesignAssetContentV2)
    add("scene", "image", "image", SceneDesignBoardContentV2)
    add("storyboard_sequence", "image", "image", StoryboardGridContentV2)
    add("general_video", "video", "video")
    add(
        "storyboard_video",
        "video",
        "video",
        VideoSegmentContentV2,
    )
    # 分镜预演参考片段（ADR 0017）：video 节点承载导演台按镜头发布的预演，
    # 血缘/关键帧在 PrevisClipContentV2；由发布端点创建，不走生成调度。
    add(
        "scene_3d_previs_clip",
        "video",
        "video",
        PrevisClipContentV2,
    )
    add("general_audio", "audio", "audio")
    add("bgm", "audio", "audio", BgmContentV2)
    add("editing", "editing", "video")
    add("scene_3d_previs", "scene-3d", "video")
    add("voice_cast", "voice-cast", "audio")
    # 拉片复刻蓝图：规划型节点，产出文本（复刻脚本），执行由实例化落到 script 节点
    add("replica_blueprint", "replica", "text", ReplicaBlueprintContentV2)
    return roles


def _flatten_validation_paths(error: ValidationError, *, limit: int = 32) -> list[str]:
    """Flatten Pydantic's error list into dotted field paths.

    Capped so a deeply invalid payload cannot blow the response body up on a
    client that is only going to read the first few entries anyway.
    """
    paths: list[str] = []
    for entry in error.errors():
        location = entry.get("loc") or ()
        path = ".".join(str(part) for part in location)
        if path and path not in paths:
            paths.append(path)
        if len(paths) >= limit:
            break
    return paths


def _error(
    code: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> V2PersistenceError:
    return V2PersistenceError(
        code,
        message,
        stage="ad_media_role_registry",
        details=details,
    )
