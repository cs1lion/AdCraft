"""Endpoint-level test: publishing a previs clip lands it at the shot's start.

The layer this pins is the one a mutation run showed was uncovered: the
endpoint computing the shot's position and handing it to the runtime. Every
layer below it (repository collision rules, scheduler pass-through) is tested
elsewhere and a mutation kills them; deleting the one line in the endpoint that
supplies ``desired_start_time`` used to leave the whole suite green while the
feature silently reverted to publish-order appending.

The runtime and DB are faked, so what is under test is exactly the wiring:
does the endpoint read the shot's own position out of the scene-3d node's
SceneScript and hand it over?
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
    CanvasBindingV2,
    CanvasBindingSourceNodeV2,
    CanvasNodeV2,
    CanvasPositionV2,
    ProjectAssetV2,
)

pytestmark = [pytest.mark.integration]


def _now() -> datetime:
    return datetime.now(timezone.utc)


#: A scene whose second shot starts at frame 90 of 30fps — i.e. 3.0 seconds.
#: Publishing shot 2 BEFORE shot 1 is the whole point: append order would put
#: it at 0.0s, the shot's own start puts it at 3.0s.
_SCENE_SCRIPT: dict[str, Any] = {
    "scene": {"name": "lab", "environment": "indoor", "lighting": "cool", "duration": 6, "frame_rate": 30},
    "characters": [],
    "props": [],
    "environment": [],
    "cameras": [
        {"id": "cam_1", "shot_type": "wide", "keyframes": [{"frame": 0, "position": [0, 0, 0], "look_at": [0, 0, 1]}]},
        {"id": "cam_2", "shot_type": "closeup", "keyframes": [{"frame": 90, "position": [0, 0, 0], "look_at": [0, 0, 1]}]},
    ],
    "shots": [
        {"id": "shot_1", "camera": "cam_1", "start_frame": 0, "end_frame": 89},
        {"id": "shot_2", "camera": "cam_2", "start_frame": 90, "end_frame": 179},
    ],
    "speech_bindings": [],
}


class _FakePublisher:
    """Stands in for PrevisClipPublisher: returns the clip node it built."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.published_node: CanvasNodeV2 | None = None

    def publish(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        now = _now()
        node = CanvasNodeV2(
            node_id="node_clip",
            workflow_id="wf-1",
            node_type="video",
            creative_role="scene_3d_previs_clip",
            title="预演片段 · shot_2",
            status="ready",
            structured_content={},
            output_asset_id="asset_clip",
            position=CanvasPositionV2(x=0.0, y=0.0),
            revision=1,
            created_at=now,
            updated_at=now,
        )
        self.published_node = node
        return type(
            "Published",
            (),
            {
                "node": node,
                "binding": CanvasBindingV2(
                    binding_id="binding_1",
                    workflow_id="wf-1",
                    source=CanvasBindingSourceNodeV2(source_node_id="scene-1"),
                    target_node_id="node_clip",
                    input_role="video_reference",
                    order=0,
                    created_at=now,
                    updated_at=now,
                ),
                "clip_asset": ProjectAssetV2(
                    asset_id="asset_clip",
                    version_id="ver_1",
                    media_type="video",
                    source_type="generated",
                    display_name="clip",
                    checksum="c" * 64,
                    mime_type="video/mp4",
                    status="ready",
                ),
                "keyframe_asset_ids": (),
            },
        )()


class _RecordingScheduler:
    """The only place the endpoint may ask for a timeline handoff.

    Deliberately named ``scheduler``: an earlier version of this fake carried
    ``publish_media_to_timeline`` directly on the runtime, so the endpoint
    calling the wrong object passed here and 500'd against a real server — the
    test agreed with the bug.
    """

    def __init__(self, calls: list[tuple[str, float | None]]) -> None:
        self._calls = calls

    def publish_media_to_timeline(
        self,
        node: CanvasNodeV2,
        desired_start_time: float | None = None,
    ) -> bool:
        self._calls.append((node.node_id, desired_start_time))
        return True


class _RecordingRuntime:
    """The runtime surface this endpoint touches, recording the timeline call.

    Shaped like the real ``AgentCanvasRuntime`` in the one way that matters:
    the handoff lives on ``scheduler``, not on the facade. Anything else raises
    instead of recording, so a regression in WHERE the endpoint reaches for the
    method fails here rather than in production.
    """

    def __init__(self, node: CanvasNodeV2) -> None:
        self.node = node
        self.workflows = self
        self.projects = self
        self.nodes = self
        self.editing_responses = self
        self.ad_media_validation = self
        self.assets = self
        self.publisher = _FakePublisher()
        self.timeline_calls: list[tuple[str, float | None]] = []
        self.scheduler = _RecordingScheduler(self.timeline_calls)
        # The endpoint projects its response out of a workflow it re-reads after
        # the publish; that read must contain the new clip node, or a request
        # that actually succeeded is reported as a 404.
        self.projected_workflow: AgentCanvasWorkflowV2 | None = None

    def __getattr__(self, name: str) -> Any:
        # The real runtime facade has no publish_media_to_timeline. Reaching for
        # one here is the exact bug that shipped, so make it loud.
        if "publish_media_to_timeline" in name:
            raise AssertionError(
                "the endpoint must call scheduler.publish_media_to_timeline, "
                "not a method on the runtime facade"
            )
        raise AttributeError(name)

    # --- an asset service surface the publisher constructor is handed -------
    def resolve_asset_path(self, asset_id: str) -> Any:
        raise AssertionError("the fake publisher never resolves a path")

    def publish_generated_bytes(self, **_: Any) -> Any:
        raise AssertionError("the fake publisher never publishes bytes")

    # --- repositories the endpoint asks for ---------------------------------
    def get_node(self, workflow_id: str, node_id: str) -> CanvasNodeV2:
        return self.node

    def get_workflow(self, workflow_id: str) -> AgentCanvasWorkflowV2:
        if self.projected_workflow is not None:
            return self.projected_workflow
        return AgentCanvasWorkflowV2(
            workflow_id=workflow_id,
            project_id="proj-1",
            revision=2,
            nodes=(self.node,),
            bindings=(),
            assets=(),
        )

    def project_workflow(self, workflow: AgentCanvasWorkflowV2) -> AgentCanvasWorkflowV2:
        return workflow

    def validate(self, **_: Any) -> None:
        return None


def _source_node() -> CanvasNodeV2:
    now = _now()
    return CanvasNodeV2(
        node_id="scene-1",
        workflow_id="wf-1",
        node_type="scene-3d",
        creative_role="scene_3d_previs",
        title="scene",
        status="ready",
        structured_content={"scene_script": _SCENE_SCRIPT},
        output_asset_id="asset_animatic",
        position=CanvasPositionV2(x=0.0, y=0.0),
        revision=1,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    runtime = _RecordingRuntime(_source_node())
    monkeypatch.setattr(
        endpoint, "PrevisClipPublisher", lambda **kwargs: runtime.publisher
    )
    app = FastAPI()
    app.include_router(endpoint.router)
    app.dependency_overrides[endpoint.get_agent_canvas_runtime] = lambda: runtime
    test_client = TestClient(app)
    # The endpoint re-reads the workflow after publishing to project its
    # response. Wrap the fake publisher so that read sees the clip it just
    # built -- the projection is not what these tests are about, but it has to
    # succeed for the timeline call underneath it to be reached at all.
    original_publish = runtime.publisher.publish

    def _publish_then_project(**kwargs):
        result = original_publish(**kwargs)
        _install_projection(runtime)
        return result

    runtime.publisher.publish = _publish_then_project
    return test_client, runtime


def _install_projection(runtime: _RecordingRuntime) -> None:
    """Make the post-publish re-read contain both the source node and the clip.

    The endpoint projects its response out of a workflow it re-reads, so that
    read has to see the new node — otherwise a request that actually succeeded
    is reported as a 404. That projection is not what these tests are about,
    but without it they cannot reach the call they ARE about.
    """

    runtime.projected_workflow = AgentCanvasWorkflowV2(
        workflow_id="wf-1",
        project_id="proj-1",
        revision=3,
        nodes=(runtime.node, runtime.publisher.published_node),
        bindings=(),
        assets=(),
    )


def _publish(test_client: TestClient, shot_id: str) -> Any:
    return test_client.post(
        "/workflows/wf-1/scene-3d-nodes/scene-1/previs-clips",
        headers={
            "Idempotency-Key": f"key-{shot_id}",
            "If-Match": '"workflow-wf-1-v2"',
        },
        json={"shot_id": shot_id},
    )


def test_the_published_clip_lands_at_its_own_shots_start(client) -> None:
    """Publishing shot 2 must not put it at 0.0s.

    3.0s is frame 90 of 30fps. Anything else means the clip was placed by publish
    order rather than by the shot it came from, and the timeline opens on the
    wrong cut.
    """

    test_client, runtime = client

    response = _publish(test_client, "shot_2")

    assert response.status_code == 201, response.text
    assert runtime.timeline_calls == [("node_clip", 3.0)]


def test_a_shot_whose_start_cannot_be_read_falls_back_to_appending(client) -> None:
    """No shot in the script (or no script at all) appends instead of guessing.

    A wrong position is worse than a merely out-of-order one, and a guessed
    position would be wrong silently.
    """

    test_client, runtime = client
    runtime.node.structured_content = {"scene_script": {**_SCENE_SCRIPT, "shots": []}}

    response = _publish(test_client, "shot_missing")

    assert response.status_code == 201, response.text
    # The endpoint still tried, and handed over "no opinion".
    assert runtime.timeline_calls == [("node_clip", None)]


def test_a_scene_without_a_script_still_publishes(client) -> None:
    test_client, runtime = client
    runtime.node.structured_content = {}

    response = _publish(test_client, "shot_2")

    assert response.status_code == 201, response.text
    assert runtime.timeline_calls == [("node_clip", None)]
