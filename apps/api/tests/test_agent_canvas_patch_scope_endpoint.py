"""Endpoint-level test: PATCH /nodes/{id} carries the ADR 0009 scope report.

The endpoint's heavy dependencies (runtime, DB) are faked; what is under
test is the CONTRACT the author relies on — the response states what the
edit touched and that no neighbour was affected.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v2.endpoints import agent_canvas as endpoint
from app.schemas.agent_canvas import (
    AgentCanvasWorkflowV2,
    CanvasNodePatchRequestV2,
    CanvasNodeV2,
)

pytestmark = [pytest.mark.integration]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _node() -> CanvasNodeV2:
    return CanvasNodeV2(
        node_id="scene-1",
        workflow_id="wf-1",
        node_type="scene-3d",
        creative_role="scene_3d_previs",
        title="scene",
        status="draft",
        summary_prompt=None,
        generation_prompt="a corridor",
        structured_content={
            "scene_script": {
                "scene": {"name": "lab", "duration": 6, "frame_rate": 30},
                "characters": [
                    {"id": "char_a", "type": "lowpoly_human", "keyframes": []}
                ],
            }
        },
        parameters={},
        metadata={},
        output_asset_id=None,
        position={"x": 0, "y": 0},
        revision=1,
        error=None,
        authoring_origin="user_free",
        created_at=_now().isoformat(),
        updated_at=_now().isoformat(),
    )


class _FakeNodes:
    def __init__(self, node: CanvasNodeV2) -> None:
        self.node = node
        self.patched: list[tuple[str, CanvasNodePatchRequestV2]] = []

    def patch(self, workflow_id: str, node_id: str, request, expected_revision=None):
        self.patched.append((node_id, request))
        return self.node


class _FakeRuntime:
    """Only the surface the patch endpoint touches."""

    def __init__(self, node: CanvasNodeV2) -> None:
        self.node = node
        self.workflows = self
        self.projects = self
        self.nodes = _FakeNodes(node)
        self.editing_responses = self
        self.ad_media_validation = self

    def get_node(self, workflow_id: str, node_id: str) -> CanvasNodeV2:
        return self.node

    def get_workflow(self, workflow_id: str) -> AgentCanvasWorkflowV2:
        return AgentCanvasWorkflowV2(
            workflow_id=workflow_id,
            project_id="proj-1",
            revision=2,
            nodes=(self.node,),
            bindings=(),
            assets=(),
        )

    def validate_workflow(self, workflow) -> None:
        return None

    def project_workflow(self, workflow):
        return workflow

    def validate(self, **_: Any) -> None:
        return None


@pytest.fixture
def client():
    node = _node()
    runtime = _FakeRuntime(node)
    app = FastAPI()
    app.include_router(endpoint.router)
    app.dependency_overrides[endpoint.get_agent_canvas_runtime] = lambda: runtime
    return TestClient(app), runtime


def test_patch_returns_the_scope_report_with_no_affected_neighbours(client) -> None:
    test_client, runtime = client

    response = test_client.patch(
        "/workflows/wf-1/nodes/scene-1",
        headers={"If-Match": '"workflow-wf-1-v2"'},
        json={
            "structured_content": {
                "scene_script": {
                    "scene": {"name": "lab", "duration": 6, "frame_rate": 30},
                    "characters": [
                        {"id": "char_a", "type": "lowpoly_human", "keyframes": []},
                        {"id": "char_b", "type": "lowpoly_human", "keyframes": []},
                    ],
                }
            }
        },
    )

    assert response.status_code == 200, response.text
    report = response.json()["scope_report"]
    # The author's question is answered: what changed, and who was NOT touched.
    assert report["affected_neighbours"] == []
    assert "场景脚本" in report["content_areas"]
    assert any("characters" in key for key in report["edited_keys"])
    assert any("不影响任何已绑定节点" in note for note in report["notes"])
    # And the patch really was applied (the endpoint did not become read-only).
    assert len(runtime.nodes.patched) == 1


def test_patch_without_any_change_reports_a_no_op(client) -> None:
    test_client, _ = client

    response = test_client.patch(
        "/workflows/wf-1/nodes/scene-1",
        headers={"If-Match": '"workflow-wf-1-v2"'},
        json={"structured_content": {}},
    )

    assert response.status_code == 200, response.text
    report = response.json()["scope_report"]
    assert report["edited_keys"] == []
    assert report["notes"] == ["补丁没有改变任何字段。"]
