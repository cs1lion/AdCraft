"""Unit tests for the replica node type wiring in the AdMedia role registry.

Locks that the new ``replica`` / ``replica_blueprint`` pair is registered,
maps to the blueprint content model, and passes structured-content
validation — the guard rails a new canvas node type must satisfy.
"""

from __future__ import annotations

import pytest

from app.services.agent_canvas_ad_media import AdMediaRoleRegistry
from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2


def test_replica_role_registered() -> None:
    registry = AdMediaRoleRegistry()
    contract = registry.get("replica_blueprint")
    assert contract.node_type == "replica"
    assert contract.output_media_type == "text"
    assert contract.content_schema_ref == "ReplicaBlueprintContentV2"
    # 不冲突：node_type 与 role 对得上
    registry.validate_node_type("replica", "replica_blueprint")


def test_replica_content_validation_rejects_wrong_version() -> None:
    registry = AdMediaRoleRegistry()
    with pytest.raises(Exception):
        registry.validate_structured_content(
            "replica_blueprint",
            {"blueprint_version": "replica-blueprint-v2"},
        )


def test_replica_content_validation_accepts_blueprint() -> None:
    registry = AdMediaRoleRegistry()
    model = ReplicaBlueprintContentV2(format_name="talking-head")
    registry.validate_structured_content(
        "replica_blueprint", model.model_dump(mode="json")
    )
