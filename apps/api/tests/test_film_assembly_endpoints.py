"""Assembly uses one ordered plan for SQL clips and the V2 render bridge."""

from __future__ import annotations
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from app.api.v1.endpoints import creation, replica
from app.persistence.database import create_v2_database
from app.persistence.timeline_repository import TimelineRepository

pytestmark = pytest.mark.integration


def test_assembly_refreshes_existing_clips_and_projects_order_duration(
    v2_media_data_dir, monkeypatch
):
    settings = NS(media_data_dir=v2_media_data_dir)
    nodes = [
        NS(
            node_id="a-last",
            node_type="video",
            title="复刻镜头2",
            output_asset_id="b",
            output_asset_version_id="vb",
            structured_content={"duration_seconds": 7.3},
        ),
        NS(
            node_id="z-first",
            node_type="video",
            title="复刻镜头1",
            output_asset_id="a",
            output_asset_version_id="va",
            structured_content={"duration_seconds": 2.1},
        ),
    ]
    workflow = NS(nodes=nodes, project_id="project", name="film")
    monkeypatch.setattr(
        replica, "_canvas_node_service", lambda: (None, NS(get_workflow=lambda _: workflow))
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    database = create_v2_database(v2_media_data_dir)
    from test_timeline_persistence import _seed_workflow

    _seed_workflow(database, "wf")
    with database.session_factory() as session:
        repo = TimelineRepository(session)
        tl = repo.get_by_workflow_id("wf")
        track = next(t for t in repo.get_tracks(tl.timeline_id) if t.type == "video")
        old = repo.add_clip(
            track_id=track.track_id,
            start_time=99,
            duration=5,
            asset_id="old",
            asset_version_id="old-v",
            source_node_id="z-first",
            label="author label",
        )
        manual = repo.add_clip(
            track_id=track.track_id, start_time=40, duration=1, asset_id="manual"
        )
        session.commit()
    projected = Mock()
    monkeypatch.setattr(
        "app.services.creation.canvas_render_bridge.bridge_canvas_workflow", projected
    )
    monkeypatch.setattr(
        "app.services.creation.canvas_render_bridge.ensure_canvas_asset_projections", Mock()
    )
    monkeypatch.setattr(
        "app.services.v2_final_composition_timeline.V2FinalCompositionTimelineService",
        lambda _: NS(get_timeline=lambda _: NS(timeline=NS(timeline_id="v2tl", version=1))),
    )
    monkeypatch.setattr(
        "app.services.v2_final_composition_render_service.V2FinalCompositionRenderService",
        lambda _: NS(start_render=lambda *_: NS(render_id="render")),
    )
    request = creation.AssembleFilmRequest(workflow_id="wf", node_ids=["a-last", "z-first"])
    first = asyncio.run(creation.assemble_film(request))
    assert first.render_id == "render"
    shots = projected.call_args.kwargs["shots"]
    assert [(s.index, s.asset_id, s.duration_seconds) for s in shots] == [
        (1, "a", 2.1),
        (2, "b", 7.3),
    ]
    with database.session_factory() as session:
        repo = TimelineRepository(session)
        clips = repo.get_clips_for_track(track.track_id)
        by_node = {c.source_node_id: c for c in clips}
        assert by_node["z-first"].clip_id == old.clip_id
        assert (
            by_node["z-first"].asset_id,
            by_node["z-first"].asset_version_id,
            by_node["z-first"].start_time,
            by_node["z-first"].duration,
        ) == ("a", "va", 0, 2.1)
        assert by_node["z-first"].label == "author label"
        assert by_node["a-last"].start_time == 2.1
        assert repo.get_clip(manual.clip_id).asset_id == "manual"
    second = asyncio.run(creation.assemble_film(request))
    assert second.clip_count == 0
    assert second.skipped == 2
    # Explicit None must clear a previously selected version, not retain old pointers.
    with database.session_factory() as session:
        repo = TimelineRepository(session)
        cleared = repo.update_clip(old.clip_id, asset_version_id=None)
        assert cleared.asset_version_id is None
        session.commit()
