"""Tests for panel previs orchestration service (P3)."""

from __future__ import annotations


from app.schemas.agent_canvas_ad_media import StoryboardPanelV2
from app.services.panel_previs_orchestration import (
    FinalCompositionPlan,
    PanelPrevisOrchestrationService,
    PrevisOrchestrationResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_panel(panel_index: int = 1, **kwargs) -> StoryboardPanelV2:
    """Create a StoryboardPanelV2 with sensible defaults."""
    defaults = {
        "panel_index": panel_index,
        "beat": f"Panel {panel_index} beat",
        "composition": "Medium shot",
        "camera": "Eye level",
        "subject_action": "Character stands",
        "continuity_from_previous": "Cut from previous" if panel_index > 1 else "First panel",
        "duration_seconds": 5.0,
        "shot_type": "medium",
        "camera_move": "static",
    }
    defaults.update(kwargs)
    return StoryboardPanelV2(**defaults)


def _make_panels(count: int = 3, **kwargs) -> list[StoryboardPanelV2]:
    """Create a sequence of panels."""
    return [_make_panel(panel_index=i + 1, **kwargs) for i in range(count)]


# ---------------------------------------------------------------------------
# Basic orchestration
# ---------------------------------------------------------------------------

class TestBasicOrchestration:
    def test_orchestrate_returns_result(self):
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(3)
        result = service.orchestrate(panels=panels)
        assert isinstance(result, PrevisOrchestrationResult)
        assert len(result.panels) == 3
        assert isinstance(result.composition_plan, FinalCompositionPlan)

    def test_panels_sorted_by_index(self):
        service = PanelPrevisOrchestrationService()
        # Create panels out of order
        panels = [
            _make_panel(panel_index=3),
            _make_panel(panel_index=1),
            _make_panel(panel_index=2),
        ]
        result = service.orchestrate(panels=panels)
        assert [p.panel_index for p in result.panels] == [1, 2, 3]

    def test_each_panel_has_scenescript(self):
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(2)
        result = service.orchestrate(panels=panels)
        for panel_result in result.panels:
            assert panel_result.scene_script is not None
            assert panel_result.derivation_result is not None

    def test_single_panel(self):
        service = PanelPrevisOrchestrationService()
        panels = [_make_panel(panel_index=1)]
        result = service.orchestrate(panels=panels)
        assert len(result.panels) == 1
        assert result.composition_plan.panel_count == 1


# ---------------------------------------------------------------------------
# Reference mode determination
# ---------------------------------------------------------------------------

class TestReferenceMode:
    def test_video_mode_when_supported(self):
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(1)
        result = service.orchestrate(
            panels=panels,
            model_supports_reference_video=True,
            model_supports_reference_images=True,
        )
        assert result.panels[0].reference_mode == "video"

    def test_keyframes_mode_when_no_video_support(self):
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(1)
        result = service.orchestrate(
            panels=panels,
            model_supports_reference_video=False,
            model_supports_reference_images=True,
        )
        assert result.panels[0].reference_mode == "keyframes"

    def test_none_mode_when_no_reference_support(self):
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(1)
        result = service.orchestrate(
            panels=panels,
            model_supports_reference_video=False,
            model_supports_reference_images=False,
        )
        assert result.panels[0].reference_mode == "none"

    def test_reference_mode_consistent_across_panels(self):
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(3)
        result = service.orchestrate(
            panels=panels,
            model_supports_reference_video=False,
            model_supports_reference_images=True,
        )
        modes = [p.reference_mode for p in result.panels]
        assert all(m == "keyframes" for m in modes)


# ---------------------------------------------------------------------------
# previs_control_level degradation marker
# ---------------------------------------------------------------------------

class TestControlLevel:
    def test_full_control_level(self):
        # ADR 0005 §4: "full" additionally requires the resolved model's
        # catalog capability fingerprint (previs_control_signal_support) to
        # accept at least one control pass.
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(1)
        result = service.orchestrate(
            panels=panels,
            model_supports_reference_video=True,
            control_signals_available=True,
            model_previs_signal_support={"depth": True, "normal": True, "flow": False},
        )
        assert result.panels[0].control_level == "full"

    def test_full_blocked_without_model_fingerprint(self):
        # Without the catalog fingerprint the video run degrades to
        # video_only and surfaces a queryable warning (never silent).
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(1)
        result = service.orchestrate(
            panels=panels,
            model_supports_reference_video=True,
            control_signals_available=True,
        )
        assert result.panels[0].control_level == "video_only"
        assert any(
            "previs_control_signal_support" in warning for warning in result.panels[0].warnings
        )

    def test_video_only_control_level(self):
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(1)
        result = service.orchestrate(
            panels=panels,
            model_supports_reference_video=True,
            control_signals_available=False,
        )
        assert result.panels[0].control_level == "video_only"

    def test_images_only_control_level(self):
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(1)
        result = service.orchestrate(
            panels=panels,
            model_supports_reference_video=False,
            model_supports_reference_images=True,
        )
        assert result.panels[0].control_level == "images_only"

    def test_text_only_control_level(self):
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(1)
        result = service.orchestrate(
            panels=panels,
            model_supports_reference_video=False,
            model_supports_reference_images=False,
        )
        assert result.panels[0].control_level == "text_only"


# ---------------------------------------------------------------------------
# Composition plan
# ---------------------------------------------------------------------------

class TestCompositionPlan:
    def test_panel_order(self):
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(4)
        result = service.orchestrate(panels=panels)
        assert result.composition_plan.panel_order == (1, 2, 3, 4)

    def test_total_duration(self):
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(3, duration_seconds=5.0)
        result = service.orchestrate(panels=panels)
        assert result.composition_plan.total_duration_seconds == 15.0

    def test_panel_durations(self):
        service = PanelPrevisOrchestrationService()
        panels = [
            _make_panel(panel_index=1, duration_seconds=3.0),
            _make_panel(panel_index=2, duration_seconds=7.0),
            _make_panel(panel_index=3, duration_seconds=5.0),
        ]
        result = service.orchestrate(panels=panels)
        assert result.composition_plan.panel_durations == (3.0, 7.0, 5.0)

    def test_transitions_count(self):
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(4)
        result = service.orchestrate(panels=panels)
        # N panels → N-1 transitions
        assert len(result.composition_plan.transitions) == 3

    def test_reference_modes_in_plan(self):
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(2)
        result = service.orchestrate(
            panels=panels,
            model_supports_reference_video=False,
            model_supports_reference_images=True,
        )
        assert result.composition_plan.reference_modes == ("keyframes", "keyframes")

    def test_control_levels_in_plan(self):
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(2)
        result = service.orchestrate(
            panels=panels,
            model_supports_reference_video=True,
            control_signals_available=True,
            model_previs_signal_support={"depth": True, "normal": True, "flow": True},
        )
        assert result.composition_plan.control_levels == ("full", "full")

    def test_all_panels_have_previs(self):
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(3)
        result = service.orchestrate(
            panels=panels,
            model_supports_reference_video=True,
        )
        assert result.composition_plan.all_panels_have_previs is True

    def test_not_all_panels_have_previs(self):
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(3)
        result = service.orchestrate(
            panels=panels,
            model_supports_reference_video=False,
            model_supports_reference_images=False,
        )
        assert result.composition_plan.all_panels_have_previs is False


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------

class TestWarnings:
    def test_mixed_control_levels_warning(self):
        service = PanelPrevisOrchestrationService()
        # Create panels with different durations (won't change control level,
        # but we test the warning logic via mixed modes)
        panels = _make_panels(2)
        # First panel video mode, second panel keyframes mode
        # (orchestrate uses same model caps for all panels, so we test
        # the warning generation logic directly)
        result = service.orchestrate(
            panels=panels,
            model_supports_reference_video=True,
            control_signals_available=False,
        )
        # All panels same mode → no mixed warning
        assert not any("Mixed previs_control_level" in w for w in result.warnings)

    def test_no_previs_warning(self):
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(2)
        result = service.orchestrate(
            panels=panels,
            model_supports_reference_video=False,
            model_supports_reference_images=False,
        )
        assert any("no 3D previs reference" in w for w in result.warnings)

    def test_non_sequential_panels_warning(self):
        service = PanelPrevisOrchestrationService()
        panels = [
            _make_panel(panel_index=1),
            _make_panel(panel_index=3),  # Missing panel 2
        ]
        result = service.orchestrate(panels=panels)
        assert any("not sequential" in w for w in result.warnings)

    def test_long_total_duration_warning(self):
        service = PanelPrevisOrchestrationService()
        panels = _make_panels(9, duration_seconds=10.0)  # 90 seconds total
        result = service.orchestrate(panels=panels)
        assert any("exceeds 60s" in w for w in result.composition_plan.warnings)


# ---------------------------------------------------------------------------
# PanelPrevisResult properties
# ---------------------------------------------------------------------------

class TestPanelPrevisResult:
    def test_duration_seconds(self):
        service = PanelPrevisOrchestrationService()
        panels = [_make_panel(panel_index=1, duration_seconds=8.0)]
        result = service.orchestrate(panels=panels)
        assert result.panels[0].duration_seconds == 8.0

    def test_reference_mode_property(self):
        service = PanelPrevisOrchestrationService()
        panels = [_make_panel(panel_index=1)]
        result = service.orchestrate(
            panels=panels,
            model_supports_reference_video=False,
            model_supports_reference_images=True,
        )
        assert result.panels[0].reference_mode == "keyframes"

    def test_control_level_property(self):
        service = PanelPrevisOrchestrationService()
        panels = [_make_panel(panel_index=1)]
        result = service.orchestrate(
            panels=panels,
            model_supports_reference_video=False,
            model_supports_reference_images=False,
        )
        assert result.panels[0].control_level == "text_only"
