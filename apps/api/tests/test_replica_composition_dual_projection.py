"""SQL authoring and canonical exports agree on timing, mute, volume and ducking."""

import asyncio
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from app.api.v1.endpoints import creation, replica
from app.core.config import Settings
from app.persistence.database import create_v2_database
from app.persistence.timeline_repository import TimelineRepository
from test_timeline_persistence import _seed_workflow

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("locked_audio_track", [False, True])
def test_sql_projection_carries_canonical_audio_controls(
    v2_media_data_dir, monkeypatch, locked_audio_track
):
    settings = Settings(media_data_dir=v2_media_data_dir)
    nodes = [
        NS(
            node_id="shot",
            node_type="video",
            title="shot1",
            output_asset_id="a",
            output_asset_version_id="v",
            structured_content={"duration_seconds": 4},
        ),
        NS(
            node_id="replica",
            node_type="replica",
            structured_content={
                "shots": [dict(index=1, start_seconds=0, end_seconds=4, on_screen_text="caption")]
            },
        ),
    ]
    workflow = NS(
        nodes=nodes,
        assets=[NS(asset_id="music", version_id="mv", media_type="audio", duration_seconds=4)],
        project_id="project",
        name="film",
    )
    monkeypatch.setattr(
        replica, "_canvas_node_service", lambda: (None, NS(get_workflow=lambda _: workflow))
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    projected = []
    timeline_service = NS(
        _load_timeline=lambda _: None,
        get_timeline=lambda _: NS(timeline=NS(timeline_id="initial", version=1, metadata={})),
        save_system_timeline=lambda _, timeline, **kwargs: (
            projected.append(timeline) or NS(timeline=timeline)
        ),
    )
    monkeypatch.setattr(
        "app.services.v2_final_composition_timeline.V2FinalCompositionTimelineService",
        lambda _: timeline_service,
    )
    monkeypatch.setattr("app.services.creation.canvas_render_bridge.bridge_canvas_workflow", Mock())
    monkeypatch.setattr(
        "app.services.creation.canvas_render_bridge.ensure_canvas_asset_projections", Mock()
    )
    monkeypatch.setattr(
        "app.services.v2_final_composition_render_service.V2FinalCompositionRenderService",
        lambda _: NS(start_render=lambda *_: NS(render_id="render")),
    )
    database = create_v2_database(v2_media_data_dir)
    _seed_workflow(database, "wf")
    if locked_audio_track:
        with database.session_factory() as session:
            repo = TimelineRepository(session)
            tl = repo.get_by_workflow_id("wf")
            bgm = next(t for t in repo.get_tracks(tl.timeline_id) if t.type == "bgm")
            repo.update_track(bgm.track_id, locked=True)
            session.commit()
    request = creation.AssembleFilmRequest(
        workflow_id="wf",
        node_ids=["shot"],
        replica_node_id="replica",
        include_captions=True,
        ducking=True,
        audio_clips=[
            dict(
                role="bgm", asset_id="music", asset_version_id="mv", duration_seconds=4, volume=0.3
            )
        ],
    )
    result = asyncio.run(creation.assemble_film(request))
    if locked_audio_track:
        assert not result.success
        assert result.warnings == ["replica_manual_timeline_preserved"]
        assert not projected
        with database.session_factory() as session:
            repo = TimelineRepository(session)
            assert next(
                t for t in repo.get_tracks(tl.timeline_id) if t.track_id == bgm.track_id
            ).locked
            assert not repo.get_clips_for_track(bgm.track_id)
        return
    assert result.render_id == "render"
    with database.session_factory() as session:
        repo = TimelineRepository(session)
        tl = repo.get_by_workflow_id("wf")
        tracks = {t.type: t for t in repo.get_tracks(tl.timeline_id)}
        assert tracks["video"].muted
        assert tl.ducking.enabled
        bgm = repo.get_clips_for_track(tracks["bgm"].track_id)[0]
        canonical = next(c for c in projected[0].clips if c.clip_type == "audio")
        assert bgm.volume_keyframes[0].value == canonical.audio.volume == 0.3
        assert (bgm.start_time, bgm.duration) == (canonical.start_time, canonical.duration)
        assert repo.get_clips_for_track(tracks["subtitle"].track_id)[0].subtitle_text == "caption"
    # Reassembly is idempotent for owned clips and disables/removes owned subtitle+sound.
    second = asyncio.run(
        creation.assemble_film(
            creation.AssembleFilmRequest(
                workflow_id="wf",
                node_ids=["shot"],
                replica_node_id="replica",
                source_audio_policy="preserve",
            )
        )
    )
    assert second.render_id == "render"
    with database.session_factory() as session:
        repo = TimelineRepository(session)
        tl = repo.get_by_workflow_id("wf")
        tracks = {t.type: t for t in repo.get_tracks(tl.timeline_id)}
        assert not tracks["video"].muted
        assert not tl.ducking.enabled
        assert not repo.get_clips_for_track(tracks["bgm"].track_id)
        assert not repo.get_clips_for_track(tracks["subtitle"].track_id)
