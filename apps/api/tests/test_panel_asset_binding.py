"""Tests for panel asset binding service (P2)."""

from __future__ import annotations

from app.schemas.agent_canvas_ad_media import StoryboardPanelV2
from app.schemas.scene_script import SpeechBinding
from app.services.panel_asset_binding import (
    PanelAssetBindingService,
    PanelAssetBundle,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_panel(**kwargs) -> StoryboardPanelV2:
    """Create a StoryboardPanelV2 with sensible defaults."""
    defaults = {
        "panel_index": 1,
        "beat": "A character speaks.",
        "composition": "Medium shot",
        "camera": "Eye level",
        "subject_action": "Character talks",
        "continuity_from_previous": "Cut from previous",
    }
    defaults.update(kwargs)
    return StoryboardPanelV2(**defaults)


# ---------------------------------------------------------------------------
# PanelAssetBindingService.aggregate
# ---------------------------------------------------------------------------

class TestAggregate:
    def test_basic_aggregation(self):
        service = PanelAssetBindingService()
        panel = _make_panel(
            character_ids=("char_1", "char_2"),
            scene_id="scene_1",
            prop_ids=("prop_1", "prop_2"),
        )
        bundle = service.aggregate(panel=panel)
        assert isinstance(bundle, PanelAssetBundle)
        assert bundle.panel_index == 1
        assert bundle.character_ids == ("char_1", "char_2")
        assert bundle.scene_id == "scene_1"
        assert bundle.prop_ids == ("prop_1", "prop_2")
        assert bundle.speech_bindings == ()
        assert bundle.warnings == ()

    def test_speech_bindings_generated(self):
        service = PanelAssetBindingService()
        panel = _make_panel(
            character_ids=("char_1",),
            character_speech_map={"char_1": "speech_asset_1"},
        )
        bundle = service.aggregate(panel=panel)
        assert len(bundle.speech_bindings) == 1
        binding = bundle.speech_bindings[0]
        assert isinstance(binding, SpeechBinding)
        assert binding.character == "char_1"
        assert binding.speech_asset == "speech_asset_1"
        assert binding.mode == "bound"  # default bound mode

    def test_multiple_speech_bindings(self):
        service = PanelAssetBindingService()
        panel = _make_panel(
            character_ids=("char_1", "char_2", "char_3"),
            character_speech_map={
                "char_1": "speech_1",
                "char_2": "speech_2",
            },
        )
        bundle = service.aggregate(panel=panel)
        assert len(bundle.speech_bindings) == 2
        assert bundle.bound_speech_count == 2
        assert bundle.has_speech is True

    def test_invalid_character_skipped_with_warning(self):
        service = PanelAssetBindingService()
        panel = _make_panel(
            character_ids=("char_1",),
            character_speech_map={"char_not_in_panel": "speech_1"},
        )
        bundle = service.aggregate(panel=panel)
        assert len(bundle.speech_bindings) == 0
        # At least the invalid-character warning (may also have no-speech warning)
        assert any("char_not_in_panel" in w and "not in character_ids" in w for w in bundle.warnings)

    def test_empty_speech_asset_skipped_with_warning(self):
        service = PanelAssetBindingService()
        panel = _make_panel(
            character_ids=("char_1",),
            character_speech_map={"char_1": ""},
        )
        bundle = service.aggregate(panel=panel)
        assert len(bundle.speech_bindings) == 0
        assert any("empty speech_asset_id" in w for w in bundle.warnings)

    def test_characters_without_speech_warning(self):
        service = PanelAssetBindingService()
        panel = _make_panel(
            character_ids=("char_1", "char_2"),
            character_speech_map={"char_1": "speech_1"},
        )
        bundle = service.aggregate(panel=panel)
        # char_2 has no speech → informational warning
        assert any("char_2" in w and "no speech_audio" in w for w in bundle.warnings)

    def test_no_speech_map_no_warnings(self):
        service = PanelAssetBindingService()
        panel = _make_panel(character_ids=("char_1",))
        bundle = service.aggregate(panel=panel)
        assert bundle.speech_bindings == ()
        assert bundle.warnings == ()  # no speech_map → no informational warning


# ---------------------------------------------------------------------------
# PanelAssetBundle properties
# ---------------------------------------------------------------------------

class TestPanelAssetBundle:
    def test_all_asset_ids_deduplicated(self):
        bundle = PanelAssetBundle(
            panel_index=1,
            character_ids=("c1", "c2"),
            scene_id="s1",
            prop_ids=("p1", "p2"),
            speech_bindings=(
                SpeechBinding(character="c1", speech_asset="sa1", mode="bound"),
            ),
        )
        ids = bundle.all_asset_ids
        assert len(ids) == len(set(ids))  # deduplicated
        assert "c1" in ids
        assert "c2" in ids
        assert "s1" in ids
        assert "p1" in ids
        assert "p2" in ids
        assert "sa1" in ids

    def test_has_speech(self):
        bundle_with = PanelAssetBundle(
            panel_index=1,
            speech_bindings=(SpeechBinding(character="c1", speech_asset="sa1", mode="bound"),),
        )
        bundle_without = PanelAssetBundle(panel_index=1)
        assert bundle_with.has_speech is True
        assert bundle_without.has_speech is False

    def test_bound_speech_count(self):
        bundle = PanelAssetBundle(
            panel_index=1,
            speech_bindings=(
                SpeechBinding(character="c1", speech_asset="sa1", mode="bound"),
                SpeechBinding(character="c2", speech_asset="sa2", mode="free"),
                SpeechBinding(character="c3", speech_asset="sa3", mode="bound"),
            ),
        )
        assert bundle.bound_speech_count == 2


# ---------------------------------------------------------------------------
# generate_speech_bindings
# ---------------------------------------------------------------------------

class TestGenerateSpeechBindings:
    def test_default_bound_mode(self):
        service = PanelAssetBindingService()
        panel = _make_panel(
            character_ids=("c1",),
            character_speech_map={"c1": "sa1"},
        )
        bindings = service.generate_speech_bindings(panel=panel)
        assert len(bindings) == 1
        assert bindings[0].mode == "bound"

    def test_free_mode_override(self):
        service = PanelAssetBindingService()
        panel = _make_panel(
            character_ids=("c1",),
            character_speech_map={"c1": "sa1"},
        )
        bindings = service.generate_speech_bindings(panel=panel, default_mode="free")
        assert len(bindings) == 1
        assert bindings[0].mode == "free"

    def test_no_speech_map_returns_empty(self):
        service = PanelAssetBindingService()
        panel = _make_panel(character_ids=("c1",))
        bindings = service.generate_speech_bindings(panel=panel)
        assert bindings == ()


# ---------------------------------------------------------------------------
# validate_binding_consistency
# ---------------------------------------------------------------------------

class TestValidateBindingConsistency:
    def test_consistent_panels_no_warnings(self):
        service = PanelAssetBindingService()
        panels = [
            _make_panel(panel_index=1, character_ids=("c1",), character_speech_map={"c1": "sa1"}, scene_id="s1"),
            _make_panel(panel_index=2, character_ids=("c1",), character_speech_map={"c1": "sa1"}, scene_id="s1"),
        ]
        warnings = service.validate_binding_consistency(panels=panels)
        assert warnings == []

    def test_speech_asset_change_warning(self):
        service = PanelAssetBindingService()
        panels = [
            _make_panel(panel_index=1, character_ids=("c1",), character_speech_map={"c1": "sa1"}),
            _make_panel(panel_index=2, character_ids=("c1",), character_speech_map={"c1": "sa2"}),
        ]
        warnings = service.validate_binding_consistency(panels=panels)
        assert len(warnings) == 1
        assert "speech_asset changes" in warnings[0]
        assert "sa1" in warnings[0]
        assert "sa2" in warnings[0]

    def test_scene_change_warning(self):
        service = PanelAssetBindingService()
        panels = [
            _make_panel(panel_index=1, scene_id="scene_interior"),
            _make_panel(panel_index=2, scene_id="scene_exterior"),
        ]
        warnings = service.validate_binding_consistency(panels=panels)
        assert len(warnings) == 1
        assert "Scene changes" in warnings[0]

    def test_multiple_issues_multiple_warnings(self):
        service = PanelAssetBindingService()
        panels = [
            _make_panel(panel_index=1, character_ids=("c1",), character_speech_map={"c1": "sa1"}, scene_id="s1"),
            _make_panel(panel_index=2, character_ids=("c1",), character_speech_map={"c1": "sa2"}, scene_id="s2"),
        ]
        warnings = service.validate_binding_consistency(panels=panels)
        assert len(warnings) == 2  # speech change + scene change
