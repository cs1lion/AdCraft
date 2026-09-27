"""Immutable connection and input-role policy for Agent Canvas authoring."""

from __future__ import annotations

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    CanvasBindingKindV2,
    CanvasConnectionDecisionV2,
    CanvasConnectionPolicyV2,
    CanvasConnectionRoleRuleV2,
    CanvasInputRoleV2,
    CanvasNodeTypeV2,
)


class AgentCanvasConnectionPolicyService:
    """Own the versioned, deterministic Canvas connection policy.

    The rules are immutable by construction: a caller who mints an
    ``agent_canvas_v1`` payload for another policy version has that payload
    dropped, and the rules stay.

    Two tables, not one, because they answer different questions.  ``_roles``
    answers "what may a node of this type contribute to a node of that type";
    ``image_asset_targets`` answers the narrower question "what may an uploaded
    asset contribute", which is only ever a *reference* -- an asset carries no
    text a text or script node could use, which is why those targets are absent.

    ``decide`` narrows ``_roles`` through ``image_asset_targets`` whenever the
    source is an asset, so an asset target missing here silently retires the
    ``_roles`` rule above it.  That is what happened to scene-3d: the rule
    ``("image", "scene-3d"): ("image_reference",)`` has been in place since the
    3D previs shipped, yet binding a scene design board or a character
    turnaround to a previs node failed with ``canvas_connection_incompatible``,
    because the one source type that can carry those artifacts -- an asset --
    was the one type this table did not list.  The previs nodes therefore ran
    with no scene reference at all while the video node next to them accepted
    the same assets happily.

    Adding scene-3d here restores the declared rule instead of weakening the
    table: the asset still only ever contributes a reference, never a text
    context, and the number of asset types any target accepts stays unchanged
    for every other node type.
    """

    policy_version = "agent_canvas_connection_policy_v1"

    #: Uploaded image assets may contribute a reference to these target node
    #: types.  scene-3d takes the same ``image_reference`` the ``_roles`` entry
    #: below grants a generated image node; the previs is the node that most
    #: needs the scene board and the turnaround, so omitting it here made the
    #: declared rule unreachable for exactly the sources that carry them.
    image_asset_targets = {
        "image": ("image_reference",),
        "video": ("image_reference",),
        "scene-3d": ("image_reference",),
    }

    _target_node_types: dict[CanvasNodeTypeV2, tuple[CanvasNodeTypeV2, ...]] = {
        "text": ("text", "script"),
        "script": ("text", "script"),
        "image": ("text", "script", "image"),
        "video": ("text", "script", "image", "video", "audio", "editing", "scene-3d"),
        "audio": ("text", "script"),
        "editing": ("video", "audio", "editing"),
        "scene-3d": ("text", "script", "image", "video"),
        "voice-cast": ("text", "script"),
        "replica": ("script",),
    }
    _binding_kinds: dict[CanvasNodeTypeV2, CanvasBindingKindV2] = {
        "text": "text_context",
        "script": "text_context",
        "image": "image_reference",
        "video": "video_reference",
        "audio": "audio_reference",
        "editing": "video_reference",
        "scene-3d": "video_reference",
        "voice-cast": "audio_reference",
        "replica": "text_context",
    }
    _input_types = {
        "text": "text",
        "script": "text",
        "image": "image",
        "video": "video",
        "audio": "audio",
        "editing": "video",
        "scene-3d": "video",
        "voice-cast": "audio",
        "replica": "text",
    }
    _roles: dict[tuple[CanvasNodeTypeV2, CanvasNodeTypeV2], tuple[CanvasInputRoleV2, ...]] = {
        ("text", "text"): ("text_context",),
        ("text", "script"): ("text_context",),
        ("text", "image"): ("text_context",),
        ("text", "video"): ("text_context",),
        ("text", "audio"): ("text_context",),
        ("text", "scene-3d"): ("text_context",),
        ("script", "text"): ("text_context",),
        ("script", "script"): ("text_context",),
        ("script", "image"): ("text_context",),
        ("script", "video"): ("text_context",),
        ("script", "audio"): ("text_context",),
        ("script", "scene-3d"): ("text_context",),
        ("image", "image"): ("image_reference",),
        ("image", "video"): ("image_reference",),
        ("image", "scene-3d"): ("image_reference",),
        ("video", "video"): ("video_reference",),
        ("video", "editing"): ("video_reference",),
        ("video", "scene-3d"): ("video_reference",),
        ("audio", "video"): ("audio_reference",),
        ("audio", "editing"): ("audio_reference",),
        ("editing", "video"): ("video_reference",),
        ("editing", "editing"): ("video_reference",),
        ("scene-3d", "video"): ("video_reference",),
        ("text", "voice-cast"): ("text_context",),
        ("script", "voice-cast"): ("text_context",),
        ("voice-cast", "video"): ("audio_reference",),
        ("voice-cast", "editing"): ("audio_reference",),
        # 拉片复刻蓝图是规划文档：只能作为 text 上下文流向 script（实例化产物）
        ("replica", "script"): ("text_context",),
    }

    def public_policy(self) -> CanvasConnectionPolicyV2:
        return CanvasConnectionPolicyV2(
            policy_version=self.policy_version,
            target_node_types=self._target_node_types,
            input_roles=tuple(
                CanvasConnectionRoleRuleV2(
                    source_node_type=source,
                    target_node_type=target,
                    roles=roles,
                    default_role=roles[0],
                )
                for (source, target), roles in self._roles.items()
            ),
            image_asset_targets=dict(self.image_asset_targets),
            binding_kind_by_source_type=self._binding_kinds,
            model_validation={"explicit_model": "authoring_and_run", "automatic_model": "run"},
        )

    def decide(
        self,
        *,
        source_node_type: CanvasNodeTypeV2,
        target_node_type: CanvasNodeTypeV2,
        input_role: CanvasInputRoleV2 | None,
        is_image_asset: bool = False,
    ) -> CanvasConnectionDecisionV2:
        roles = self._roles.get((source_node_type, target_node_type), ())
        if is_image_asset and source_node_type == "image":
            roles = self.public_policy().image_asset_targets.get(target_node_type, ())
        if not roles:
            return CanvasConnectionDecisionV2(
                accepted=False,
                error_code="canvas_connection_incompatible",
                source_node_type=source_node_type,
                target_node_type=target_node_type,
            )
        normalized_role = input_role or roles[0]
        if normalized_role not in roles:
            return CanvasConnectionDecisionV2(
                accepted=False,
                error_code="canvas_input_role_invalid",
                source_node_type=source_node_type,
                target_node_type=target_node_type,
                input_role=normalized_role,
                allowed_roles=roles,
            )
        return CanvasConnectionDecisionV2(
            accepted=True,
            source_node_type=source_node_type,
            target_node_type=target_node_type,
            input_role=normalized_role,
            allowed_roles=roles,
            binding_kind=self._binding_kinds[source_node_type],
            input_type=self._input_types[source_node_type],
        )

    def require(
        self,
        *,
        source_node_type: CanvasNodeTypeV2,
        target_node_type: CanvasNodeTypeV2,
        input_role: CanvasInputRoleV2 | None,
        is_image_asset: bool = False,
    ) -> CanvasConnectionDecisionV2:
        decision = self.decide(
            source_node_type=source_node_type,
            target_node_type=target_node_type,
            input_role=input_role,
            is_image_asset=is_image_asset,
        )
        if decision.accepted:
            return decision
        error = V2PersistenceError(
            decision.error_code or "canvas_connection_incompatible",
            "Canvas connection is not compatible with the authoritative policy.",
            stage="agent_canvas_connection_policy",
        )
        error.details = {
            "policy_version": self.policy_version,
            "source_node_type": decision.source_node_type,
            "target_node_type": decision.target_node_type,
            "input_role": decision.input_role,
            "allowed_roles": list(decision.allowed_roles),
        }
        raise error
