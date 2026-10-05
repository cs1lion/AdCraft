"""The published previs clip must be able to land on the timeline.

A previs clip node is created by ``PrevisClipPublisher`` with ``status="ready"``
and its output asset already set, so it never takes an execution lease. The
auto-clip creator is driven from the lease-completion path
(`AgentCanvasRuntime._on_lease_succeeded` -> `media_ready_publisher`), which
means that hook never fires for a clip node. `publish_media_to_timeline` is the
bridge; these tests pin its two jobs:

1. hand the clip node to the same media-ready publisher an executed node gets
2. refuse node types the timeline has no track for, instead of throwing

The publisher itself is faked here — the timeline repository needs a real
database and that path is covered by the auto-clip tests. What is NOT covered
elsewhere is the wiring, which is exactly what regressed once already (clips
existed on canvas and never reached the timeline).
"""

from __future__ import annotations

from typing import Any

from datetime import datetime, timezone

from app.schemas.agent_canvas import CanvasNodeV2
from app.services.agent_canvas_runtime import DynamicCanvasScheduler


def _clip_node(node_type: str = "video") -> CanvasNodeV2:
    now = datetime.now(timezone.utc)
    return CanvasNodeV2(
        node_id="node_clip",
        workflow_id="wf_1",
        node_type=node_type,
        creative_role="scene_3d_previs_clip",
        title="预演片段 · 飞船起飞",
        status="ready",
        output_asset_id="asset_clip",
        position={"x": 0.0, "y": 0.0},
        revision=1,
        created_at=now,
        updated_at=now,
    )


def _runtime_with_publisher(publisher: Any) -> DynamicCanvasScheduler:
    """A scheduler carrying only the collaborator this method reads.

    ``__init__`` demands the whole execution graph; this method reads one
    attribute, so the instance is built directly rather than through a
    constructor whose every other argument would be decorative here.
    """

    runtime = object.__new__(DynamicCanvasScheduler)
    runtime._media_ready_publisher = publisher
    return runtime


class TestPublishMediaToTimeline:
    def test_hands_the_clip_to_the_same_publisher_an_executed_node_gets(self) -> None:
        seen: list[CanvasNodeV2] = []
        runtime = _runtime_with_publisher(
            lambda node, *, desired_start_time=None: seen.append(node)
        )
        node = _clip_node()

        assert runtime.publish_media_to_timeline(node) is True
        assert seen == [node]

    def test_forwards_the_shots_own_start_so_the_track_plays_in_order(self) -> None:
        """Publish order is not play order.

        A director publishing shot 2 before shot 1 still gets a timeline that
        opens on shot 1, which only works if the clip's position travels with
        the publish instead of being decided by append order.
        """

        starts: list[float | None] = []
        runtime = _runtime_with_publisher(
            lambda node, *, desired_start_time=None: starts.append(desired_start_time)
        )

        assert (
            runtime.publish_media_to_timeline(_clip_node(), desired_start_time=6.0) is True
        )
        assert starts == [6.0]

    def test_refuses_a_node_type_the_timeline_has_no_track_for(self) -> None:
        # A text node has no media track; handing it over would make the
        # publisher log a warning for something that was never pixelled.
        seen: list[CanvasNodeV2] = []
        runtime = _runtime_with_publisher(
            lambda node, *, desired_start_time=None: seen.append(node)
        )

        assert runtime.publish_media_to_timeline(_clip_node("text")) is False
        assert seen == []

    def test_reports_when_no_publisher_is_wired(self) -> None:
        runtime = object.__new__(DynamicCanvasScheduler)
        runtime._media_ready_publisher = None

        assert runtime.publish_media_to_timeline(_clip_node()) is False

    def test_accepts_every_mapping_node_type(self) -> None:
        # The same set the lease path admits; a previs clip is a video node, but
        # scene-3d/voice-cast/image/audio all resolve to tracks too.
        from app.services.timeline_clip_auto_creator import (
            NODE_TYPE_TO_TRACK,
        )

        for node_type in NODE_TYPE_TO_TRACK:
            seen: list[CanvasNodeV2] = []
            runtime = _runtime_with_publisher(
                lambda node, *, desired_start_time=None: seen.append(node)
            )
            assert runtime.publish_media_to_timeline(_clip_node(node_type)) is True
            assert len(seen) == 1
