"""Cache identity follows effective composition, not UI-only metadata.

Each mutation below must break reuse while a no-op must preserve it.
"""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from app.core.config import Settings
from app.schemas.workflow_v2 import WorkflowV2Timeline, WorkflowV2TimelineRenderSettings
from app.schemas.workflow_v2_composition import V2SimpleCompositionPlan
from app.services.v2_final_composition_fingerprint import V2FinalCompositionFingerprintService

pytestmark = pytest.mark.integration


def timeline():
    return WorkflowV2Timeline.model_validate(
        {
            "timeline_id": "test",
            "duration_seconds": 4,
            "tracks": [
                {"track_id": "v", "track_type": "video", "order": 1},
                {"track_id": "a", "track_type": "audio", "order": 2},
                {"track_id": "s", "track_type": "subtitle", "order": 3},
            ],
            "clips": [
                {
                    "clip_id": "v",
                    "track_id": "v",
                    "clip_type": "video",
                    "source_asset_id": "video",
                    "source_version_id": "v1",
                    "duration": 4,
                },
                {
                    "clip_id": "a",
                    "track_id": "a",
                    "clip_type": "audio",
                    "source_asset_id": "audio",
                    "source_version_id": "a1",
                    "duration": 4,
                    "metadata": {"role": "bgm"},
                },
                {
                    "clip_id": "s",
                    "track_id": "s",
                    "clip_type": "subtitle",
                    "start_time": 1,
                    "duration": 2,
                    "text": "新鲜",
                    "metadata": {"visible_start_seconds": 0.9, "visible_end_seconds": 3.2},
                },
            ],
        }
    )


def service():
    result = V2FinalCompositionFingerprintService(settings=Settings(media_mode="mock"))
    result._asset_store = Mock()
    result._asset_store.asset_content_sha256.side_effect = lambda asset, version: (
        f"hash-{asset}-{version}"
    )
    return result


def fingerprint(subject, mode="timeline_editor"):
    simple = (
        V2SimpleCompositionPlan(
            workflow_id="wf",
            bgm_status="not_requested",
            videos=[
                {
                    "shot_id": "s1",
                    "item_id": "i1",
                    "slot_id": "slot1",
                    "shot_index": 1,
                    "asset_id": "video",
                    "version_id": "v1",
                }
            ],
        )
        if mode == "simple_sequence"
        else None
    )
    return service().build_for_composition(
        workflow_id="wf",
        slot_id="final",
        timeline=subject,
        render_settings=WorkflowV2TimelineRenderSettings(),
        render_mode=mode,
        audio_mode="full",
        simple_plan=simple,
    )


@pytest.mark.parametrize(
    "field,value", [("text", "刚刚好"), ("start_time", 1.5), ("duration", 1.5)]
)
def test_subtitle_content_or_semantic_window_invalidates_cache(field, value):
    original = timeline()
    changed = deepcopy(original)
    setattr(changed.clips[2], field, value)
    assert fingerprint(original).fingerprint != fingerprint(changed).fingerprint


@pytest.mark.parametrize(
    "field,value",
    [
        ("lead_seconds", 0.2),
        ("tail_seconds", 0.3),
        ("handoff", "cut"),
        ("font_size", 64),
        ("color", "#FF0000"),
    ],
)
def test_subtitle_recipe_invalidates_cache(field, value):
    original = timeline()
    changed = deepcopy(original)
    setattr(changed.clips[2].subtitle_style, field, value)
    assert fingerprint(original).fingerprint != fingerprint(changed).fingerprint


@pytest.mark.parametrize(
    "field,value", [("visible_start_seconds", 0.5), ("visible_end_seconds", 3.5)]
)
def test_effective_visible_window_invalidates_cache(field, value):
    original = timeline()
    changed = deepcopy(original)
    changed.clips[2].metadata[field] = value
    assert fingerprint(original).fingerprint != fingerprint(changed).fingerprint


def test_program_tail_and_audio_role_invalidate_cache():
    original = timeline()
    duration = deepcopy(original)
    duration.duration_seconds = 8
    role = deepcopy(original)
    role.clips[1].metadata["role"] = "voice"
    assert fingerprint(original).fingerprint != fingerprint(duration).fingerprint
    assert fingerprint(original).fingerprint != fingerprint(role).fingerprint


def test_same_effective_timeline_reuses_cache_and_ignores_editor_metadata():
    original = timeline()
    changed = deepcopy(original)
    changed.clips[2].metadata["editor_selection"] = "selected"
    changed.metadata["last_saved_at"] = "tomorrow"
    assert fingerprint(original).fingerprint == fingerprint(changed).fingerprint
    assert fingerprint(original).canonical_payload["subtitle_sources"][0]["text"] == "新鲜"


def test_disabled_subtitle_does_not_invalidate_cache_when_edited():
    original = timeline()
    original.clips[2].enabled = False
    changed = deepcopy(original)
    changed.clips[2].text = "隐藏字幕不应影响成片"
    assert fingerprint(original).fingerprint == fingerprint(changed).fingerprint


def test_simple_sequence_ignores_unconsumed_canonical_subtitles_and_duration():
    original = timeline()
    changed = deepcopy(original)
    changed.duration_seconds = 12
    changed.clips[2].text = "此模式不消费字幕"
    changed.clips[2].subtitle_style.font_size = 64
    assert (
        fingerprint(original, "simple_sequence").fingerprint
        == fingerprint(changed, "simple_sequence").fingerprint
    )
    assert fingerprint(original, "simple_sequence").canonical_payload["subtitle_sources"] == []


def test_disabled_track_content_does_not_invalidate_cache():
    original = timeline()
    original.tracks[2].enabled = False
    changed = deepcopy(original)
    changed.clips[2].text = "disabled track"
    assert fingerprint(original).fingerprint == fingerprint(changed).fingerprint
    assert fingerprint(original).canonical_payload["subtitle_sources"] == []


@pytest.mark.parametrize(
    "field,value", [("threshold_db", -20), ("ratio", 4), ("attack_ms", 80), ("release_ms", 500)]
)
def test_enabled_ducking_settings_invalidate_cache(field, value):
    original = timeline()
    original.metadata["ducking"] = {"enabled": True}
    changed = deepcopy(original)
    changed.metadata["ducking"][field] = value
    assert fingerprint(original).fingerprint != fingerprint(changed).fingerprint


def test_disabled_ducking_ignores_inactive_parameters():
    original = timeline()
    changed = deepcopy(original)
    changed.metadata["ducking"] = {"enabled": False, "ratio": 4}
    assert fingerprint(original).fingerprint == fingerprint(changed).fingerprint


def test_audio_role_precedence_and_aliases_match_effective_bus():
    original = timeline()
    original.clips[1].metadata = {"audio_role": "narration", "role": "bgm"}
    equivalent = deepcopy(original)
    equivalent.clips[1].metadata["audio_role"] = "voice"
    changed = deepcopy(original)
    changed.clips[1].metadata["audio_role"] = "music"
    assert fingerprint(original).fingerprint == fingerprint(equivalent).fingerprint
    assert fingerprint(original).fingerprint != fingerprint(changed).fingerprint


def test_fps_changes_output_identity():
    original = timeline()
    changed = deepcopy(original)
    changed.fps = 30
    assert fingerprint(original).fingerprint != fingerprint(changed).fingerprint


def test_only_effective_metadata_is_serialized():
    original = timeline()
    changed = deepcopy(original)
    changed.metadata["api_key"] = "test-only-sentinel-not-a-secret"
    changed.clips[2].metadata["transient_error"] = "private-editor-note"
    changed.clips[1].metadata["credential"] = "test-only-credential-sentinel"
    result = fingerprint(changed)
    assert result.fingerprint == fingerprint(original).fingerprint
    assert "sentinel" not in str(result.canonical_payload)
    assert "private-editor-note" not in str(result.canonical_payload)


def test_null_role_priority_and_non_bus_roles_follow_filter_semantics():
    original = timeline()
    original.clips[1].metadata = {"audio_role": None, "role": "bgm"}
    equivalent = deepcopy(original)
    equivalent.clips[1].metadata = {"role": "sfx"}
    assert fingerprint(original).fingerprint == fingerprint(equivalent).fingerprint


def test_explicit_ducking_defaults_match_implicit_defaults():
    original = timeline()
    original.metadata["ducking"] = {"enabled": True}
    changed = deepcopy(original)
    changed.metadata["ducking"].update(
        {"threshold_db": -30.0, "ratio": 12.0, "attack_ms": 50.0, "release_ms": 250.0}
    )
    assert fingerprint(original).fingerprint == fingerprint(changed).fingerprint
