"""Locks explicit authoring semantics against legacy sequence-mode defaults."""

from dataclasses import replace

import pytest

from app.core.config import Settings
from app.schemas.workflow_v2 import WorkflowV2Timeline
from app.services.v2_composition_render_mode import effective_composition_render_mode
from app.services.v2_final_composition_timeline import V2FinalCompositionTimelineService

pytestmark = pytest.mark.integration


def timeline(metadata=None):
    return WorkflowV2Timeline(
        timeline_id="timeline-mode",
        version=1,
        duration_seconds=8,
        fps=30,
        resolution={"width": 1280, "height": 720},
        tracks=[{"track_id": "subtitles", "track_type": "subtitle", "order": 1}],
        clips=[{"clip_id": "caption", "track_id": "subtitles", "clip_type": "subtitle", "start_time": 0, "duration": 8, "text": "Caption"}],
        metadata=metadata or {},
    )


def test_legacy_system_default_keeps_its_configured_mode():
    assert effective_composition_render_mode(" SIMPLE_SEQUENCE ", timeline()) == "simple_sequence"


@pytest.mark.parametrize(
    "metadata", [{"requires_timeline_editor": True}, {"edit_mode": "user_edited"}]
)
def test_authored_multitrack_uses_canonical_without_changing_installation(metadata, tmp_path):
    settings = Settings(media_data_dir=tmp_path, final_composition_render_mode="simple_sequence")
    saved = timeline(metadata)
    service = V2FinalCompositionTimelineService(settings)
    assert (
        effective_composition_render_mode(settings.final_composition_render_mode, saved)
        == "timeline_editor"
    )
    payload = service._provider_payload(saved, {}, simple_plan=None)
    assert payload["canonical_timeline"]["duration_seconds"] == 8
    assert service._composition_capabilities(saved).supports_timeline_controls
    assert settings.final_composition_render_mode == "simple_sequence"
    worker_settings = replace(settings, final_composition_render_mode="timeline_editor")
    assert worker_settings.final_composition_render_mode == "timeline_editor"
