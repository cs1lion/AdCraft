"""Real temporary bridge + timeline store: automatic captions survive reconciliation."""

from types import SimpleNamespace as NS

import pytest

from app.core.config import Settings
from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2
from app.services.creation.canvas_render_bridge import BridgeShotV1, bridge_canvas_workflow
from app.services.creation.film_assembly import plan_assembly
from app.services.creation.replica_composition import plan_replica_composition
from app.services.v2_final_composition_timeline import V2FinalCompositionTimelineService
from tests.helpers.asset_factories import make_v2_asset_version

pytestmark = pytest.mark.integration


def test_real_system_save_preserves_version_and_caption_after_reload(v2_media_data_dir):
    settings = Settings(
        media_data_dir=v2_media_data_dir,
        media_mode="mock",
        agent_runtime_mode="fake",
        final_composition_render_mode="timeline_editor",
    )
    workflow_id = "adwf_v2_system_replica"
    make_v2_asset_version(
        v2_media_data_dir,
        workflow_id=workflow_id,
        asset_id="a",
        version_id="v",
        media_type="video",
        metadata={"duration_seconds": 5, "width": 1280, "height": 720},
    )
    node = NS(
        node_id="node",
        node_type="video",
        title="shot1",
        output_asset_id="a",
        output_asset_version_id="v",
        structured_content={"duration_seconds": 4},
    )
    result = plan_replica_composition(
        plan_assembly("video", [node]),
        replica_node_id="r",
        blueprint=ReplicaBlueprintContentV2(
            shots=[dict(index=1, start_seconds=0, end_seconds=1, on_screen_text="authored caption")]
        ),
    )
    bridge_canvas_workflow(
        settings,
        workflow_id,
        None,
        "film",
        [BridgeShotV1(1, "a", "v", 4)],
        composition_plan_hash=result.plan_hash,
    )
    service = V2FinalCompositionTimelineService(settings)
    current = service.get_timeline(workflow_id)
    saved = service.save_system_timeline(
        workflow_id, result.timeline, expected_version=current.timeline.version
    )
    reloaded = V2FinalCompositionTimelineService(settings).get_timeline(workflow_id)
    assert reloaded.timeline.version == saved.timeline.version
    assert (
        reloaded.timeline.metadata["source_selection_hash"]
        == saved.timeline.metadata["source_selection_hash"]
    )
    assert any(c.text == "authored caption" for c in reloaded.timeline.clips)
    assert reloaded.timeline.duration_seconds == 4
    from app.persistence.project_repository import ProjectRepository
    from app.persistence.database import create_v2_database

    database = create_v2_database(v2_media_data_dir)
    try:
        assert ProjectRepository(database).get("proj_film_stem_replica").status == "archived"
    finally:
        database.dispose()
