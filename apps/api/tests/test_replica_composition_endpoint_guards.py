"""Invalid version and user edits block automatic assembly before SQL writes."""

import asyncio
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import creation, replica

pytestmark = pytest.mark.integration


def prepare(monkeypatch, user_edited=False):
    shot = NS(node_id="shot", node_type="video", output_asset_id="v", output_asset_version_id="vv")
    root = NS(node_id="replica", node_type="replica", structured_content={"shots": []})
    workflow = NS(
        nodes=[shot, root],
        assets=[NS(asset_id="a", version_id="av", media_type="audio", duration_seconds=4)],
    )
    monkeypatch.setattr(
        replica, "_canvas_node_service", lambda: (None, NS(get_workflow=lambda _: workflow))
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: NS(media_data_dir="unused"))
    monkeypatch.setattr(
        "app.services.v2_final_composition_timeline.V2FinalCompositionTimelineService",
        lambda _: NS(
            _load_timeline=lambda _: (
                NS(metadata={"edit_mode": "user_edited"}) if user_edited else None
            )
        ),
    )
    database = Mock(side_effect=AssertionError("SQL must not open"))
    monkeypatch.setattr("app.persistence.database.create_v2_database", database)
    return database


def test_user_edits_are_preserved_before_sql_open(monkeypatch):
    database = prepare(monkeypatch, True)
    result = asyncio.run(
        creation.assemble_film(
            creation.AssembleFilmRequest(
                workflow_id="wf",
                node_ids=["shot"],
                replica_node_id="replica",
                include_captions=True,
            )
        )
    )
    assert not result.success
    assert result.warnings == ["replica_user_timeline_preserved"]
    database.assert_not_called()


def test_audio_version_mutation_is_rejected_before_sql_open(monkeypatch):
    database = prepare(monkeypatch)
    request = creation.AssembleFilmRequest(
        workflow_id="wf",
        node_ids=["shot"],
        replica_node_id="replica",
        audio_clips=[dict(role="bgm", asset_id="a", asset_version_id="wrong", duration_seconds=4)],
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(creation.assemble_film(request))
    assert error.value.status_code == 422
    database.assert_not_called()


def test_audio_trim_mutation_is_rejected_before_sql_open(monkeypatch):
    database = prepare(monkeypatch)
    request = creation.AssembleFilmRequest(
        workflow_id="wf",
        node_ids=["shot"],
        replica_node_id="replica",
        audio_clips=[
            dict(
                role="bgm",
                asset_id="a",
                asset_version_id="av",
                duration_seconds=4,
                trim_start_seconds=1,
            )
        ],
    )
    with pytest.raises(HTTPException, match="trim exceeds"):
        asyncio.run(creation.assemble_film(request))
    database.assert_not_called()
