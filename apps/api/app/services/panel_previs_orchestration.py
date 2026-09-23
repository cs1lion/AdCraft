"""Panel-level 3D previs orchestration for video generation (P3).

Orchestrates the handoff from storyboard panels → per-panel SceneScript →
per-panel video model inputs (with 3D previs reference) → final composition
plan. This is the编排层 that wires the structured-derivation flow (P0-P2)
into the existing video generation pipeline.

Architecture:
    StoryboardPanelV2[]
        │
        ▼ (SceneScriptDerivationService, P1b)
    SceneScriptRoot[] (one per panel)
        │
        ▼ (build_video_model_input, reference_assets.py)
    VideoModelInput[] (one per panel, with previs reference)
        │
        ▼ (determine_reference_mode, prompt_builder.py)
    reference_mode: "video" | "keyframes" | "none"
    previs_control_level: "full" | "video_only" | "images_only" | "text_only"
        │
        ▼
    FinalCompositionPlan (panel order, transitions, timing)

Per ADR 0005 §4a fallback strategy:
- Models that support reference video → rendered MP4 as reference
- Models that don't → 5 keyframe images per panel (0/25/50/75/100%)
- Prompt-only as last resort
- previs_control_level degradation marker is queryable, never silent
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.agent_canvas_ad_media import StoryboardPanelV2
from app.schemas.scene_script import SceneScriptRoot
from app.services.panel_asset_binding import PanelAssetBindingService
from app.services.scene3d.prompt_builder import determine_reference_mode
from app.services.scene3d.reference_assets import (
    VideoModelInput,
    build_video_model_input,
)
from app.services.scenescript_derivation import (
    SceneScriptDerivationResult,
    SceneScriptDerivationService,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PanelPrevisResult:
    """3D previs result for one storyboard panel."""

    panel_index: int
    scene_script: SceneScriptRoot
    derivation_result: SceneScriptDerivationResult
    requested_reference_mode: str  # "video" | "keyframes" | "none" (based on model capabilities)
    control_signals_available: bool = False
    video_model_input: VideoModelInput | None = None
    warnings: tuple[str, ...] = ()

    @property
    def reference_mode(self) -> str:
        """The reference mode for this panel (based on model capabilities).

        Returns the requested mode. If video_model_input is None, it means
        no rendered assets are available yet, but the model still supports
        this mode. Use `has_reference_assets` to check if actual assets exist.
        """
        return self.requested_reference_mode

    @property
    def has_reference_assets(self) -> bool:
        """Whether actual reference assets (video or keyframes) are available."""
        return self.video_model_input is not None and self.video_model_input.reference_mode != "none"

    @property
    def control_level(self) -> str:
        """ADR 0005 §4a previs_control_level degradation marker.

        Computed from the effective reference mode + control signal availability.
        """
        from app.services.scene3d.prompt_builder import previs_control_level
        return previs_control_level(self.reference_mode, self.control_signals_available)

    @property
    def duration_seconds(self) -> float:
        return self.scene_script.scene.duration


@dataclass(frozen=True)
class FinalCompositionPlan:
    """Plan for assembling per-panel videos into the final composition.

    This is a planning artifact — it does not execute the composition.
    The actual composition is handled by the existing final-composition node.
    """

    panel_count: int
    total_duration_seconds: float
    panel_order: tuple[int, ...]
    panel_durations: tuple[float, ...]
    transitions: tuple[str, ...]  # "cut" | "dissolve" | "fade" per panel boundary
    reference_modes: tuple[str, ...]
    control_levels: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def all_panels_have_previs(self) -> bool:
        """Whether all panels have non-"none" reference mode."""
        return all(mode != "none" for mode in self.reference_modes)

    @property
    def mixed_control_levels(self) -> bool:
        """Whether panels have different control levels (may cause visual inconsistency)."""
        return len(set(self.control_levels)) > 1


@dataclass(frozen=True)
class PrevisOrchestrationResult:
    """Complete result of panel-level previs orchestration."""

    panels: tuple[PanelPrevisResult, ...]
    composition_plan: FinalCompositionPlan
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Orchestration service
# ---------------------------------------------------------------------------


class PanelPrevisOrchestrationService:
    """Orchestrate panel-level 3D previs for video generation.

    This service wires the structured-derivation flow (P0-P2) into the
    existing video generation pipeline. It does NOT execute video generation
    or rendering — it produces the input packages and composition plan that
    the existing nodes consume.
    """

    def __init__(
        self,
        *,
        scenescript_deriver: SceneScriptDerivationService | None = None,
        binding_service: PanelAssetBindingService | None = None,
    ) -> None:
        self._scenescript_deriver = scenescript_deriver or SceneScriptDerivationService()
        self._binding_service = binding_service or PanelAssetBindingService()

    def orchestrate(
        self,
        *,
        panels: list[StoryboardPanelV2],
        model_supports_reference_video: bool = False,
        model_supports_reference_images: bool = True,
        control_signals_available: bool = False,
        model_previs_signal_support: dict[str, bool] | None = None,
        rendered_video_paths: dict[int, str] | None = None,
        rendered_frames_dirs: dict[int, str] | None = None,
        keyframes_output_dirs: dict[int, str] | None = None,
        default_frame_rate: int = 30,
    ) -> PrevisOrchestrationResult:
        """Orchestrate panel-level 3D previs for a sequence of storyboard panels.

        Args:
            panels: List of storyboard panels (must have panel_index 1..N).
            model_supports_reference_video: Whether the target video model
                accepts reference video input.
            model_supports_reference_images: Whether the target video model
                accepts reference image input.
            control_signals_available: Whether geometric control passes
                (depth/normal/flow) were produced.
            model_previs_signal_support: Optional catalog capability
                fingerprint for the resolved model
                (`previs_control_signal_support`, ADR 0005 §4) — a dict of
                pass name → supported. When present, the executor's
                `previs_control_level` marker only reports `full` for
                video-mode runs if this fingerprint accepts at least one
                pass. Absent → the marker conservatively stays `video_only`.
            rendered_video_paths: Optional dict of panel_index → rendered
                previs MP4 path (for "video" mode).
            rendered_frames_dirs: Optional dict of panel_index → directory
                containing rendered PNG frames (for keyframe extraction).
            keyframes_output_dirs: Optional dict of panel_index → directory
                to copy keyframe images to.
            default_frame_rate: Default frame rate for SceneScript derivation.

        Returns:
            PrevisOrchestrationResult with per-panel results and composition plan.
        """
        warnings: list[str] = []
        rendered_video_paths = rendered_video_paths or {}
        rendered_frames_dirs = rendered_frames_dirs or {}
        keyframes_output_dirs = keyframes_output_dirs or {}

        # --- Validate panel sequence ---
        sorted_panels = sorted(panels, key=lambda p: p.panel_index)
        panel_indices = [p.panel_index for p in sorted_panels]
        if panel_indices != list(range(1, len(sorted_panels) + 1)):
            warnings.append(
                f"Panel indices {panel_indices} are not sequential 1..{len(sorted_panels)}; "
                f"composition plan will use sorted order."
            )

        # --- Cross-panel binding consistency (P2) ---
        binding_warnings = self._binding_service.validate_binding_consistency(panels=sorted_panels)
        warnings.extend(binding_warnings)

        # --- Per-panel derivation and video model input ---
        panel_results: list[PanelPrevisResult] = []
        for panel in sorted_panels:
            result = self._orchestrate_panel(
                panel=panel,
                model_supports_reference_video=model_supports_reference_video,
                model_supports_reference_images=model_supports_reference_images,
                control_signals_available=control_signals_available,
                model_previs_signal_support=model_previs_signal_support,
                rendered_video_path=rendered_video_paths.get(panel.panel_index),
                rendered_frames_dir=rendered_frames_dirs.get(panel.panel_index),
                keyframes_output_dir=keyframes_output_dirs.get(panel.panel_index),
                default_frame_rate=default_frame_rate,
            )
            panel_results.append(result)
            warnings.extend(result.warnings)

        # --- Composition plan ---
        composition_plan = self._build_composition_plan(panel_results)

        # --- Global warnings ---
        if composition_plan.mixed_control_levels:
            warnings.append(
                "Mixed previs_control_level across panels: "
                f"{sorted(set(composition_plan.control_levels))}. "
                "This may cause visual inconsistency in the final composition. "
                "Consider re-rendering panels at the same control level."
            )
        if not composition_plan.all_panels_have_previs:
            none_panels = [
                idx + 1
                for idx, mode in enumerate(composition_plan.reference_modes)
                if mode == "none"
            ]
            warnings.append(
                f"Panels {none_panels} have no 3D previs reference (mode='none'). "
                "They will use prompt-only generation without camera/blocking guidance."
            )

        return PrevisOrchestrationResult(
            panels=tuple(panel_results),
            composition_plan=composition_plan,
            warnings=tuple(warnings),
        )

    def _orchestrate_panel(
        self,
        *,
        panel: StoryboardPanelV2,
        model_supports_reference_video: bool,
        model_supports_reference_images: bool,
        control_signals_available: bool,
        model_previs_signal_support: dict[str, bool] | None,
        rendered_video_path: str | None,
        rendered_frames_dir: str | None,
        keyframes_output_dir: str | None,
        default_frame_rate: int,
    ) -> PanelPrevisResult:
        """Orchestrate 3D previs for a single panel."""
        warnings: list[str] = []

        # Step 1: Derive SceneScript from panel (P1b)
        derivation = self._scenescript_deriver.derive(
            panel=panel,
            default_frame_rate=default_frame_rate,
        )
        warnings.extend(derivation.warnings)

        # Step 2: Determine reference mode (ADR 0005 §4a)
        reference_mode = determine_reference_mode(
            model_supports_reference_video=model_supports_reference_video,
            model_supports_reference_images=model_supports_reference_images,
            control_signals_available=control_signals_available,
        )

        # ADR 0005 §4: the executor's previs_control_level marker reports
        # "full" for video mode only when the model's catalog fingerprint
        # accepts at least one control pass. Without a fingerprint the run
        # degrades to video_only — queryable, never silently inflated.
        effective_control_signals = control_signals_available
        if reference_mode == "video" and model_previs_signal_support is None:
            effective_control_signals = False
            warnings.append(
                f"Panel {panel.panel_index}: previs_control_level stays "
                f"'video_only' — no previs_control_signal_support fingerprint "
                f"provided for the resolved model (ADR 0005 §4)."
            )

        # Step 3: Build video model input (if rendered assets available)
        video_model_input: VideoModelInput | None = None
        if reference_mode == "video" and rendered_video_path:
            video_model_input = build_video_model_input(
                scene_script=derivation.scene_script,
                rendered_video_path=rendered_video_path,
                model_supports_reference_video=True,
                model_supports_reference_images=model_supports_reference_images,
                control_signals_available=effective_control_signals,
            )
        elif reference_mode == "keyframes" and rendered_frames_dir:
            video_model_input = build_video_model_input(
                scene_script=derivation.scene_script,
                rendered_frames_dir=rendered_frames_dir,
                keyframes_output_dir=keyframes_output_dir,
                model_supports_reference_video=False,
                model_supports_reference_images=True,
                control_signals_available=effective_control_signals,
            )
        elif reference_mode == "none":
            # Prompt-only mode: build input with no reference assets
            video_model_input = build_video_model_input(
                scene_script=derivation.scene_script,
                model_supports_reference_video=False,
                model_supports_reference_images=False,
                control_signals_available=False,
            )
        else:
            # Reference mode requested but no rendered assets available yet
            # (video_model_input stays None; caller can render assets later)
            warnings.append(
                f"Panel {panel.panel_index}: reference_mode='{reference_mode}' requested "
                f"but no rendered assets available yet "
                f"(video_path={'set' if rendered_video_path else 'none'}, "
                f"frames_dir={'set' if rendered_frames_dir else 'none'}). "
                f"Render 3D previs assets to enable reference-guided generation."
            )

        return PanelPrevisResult(
            panel_index=panel.panel_index,
            scene_script=derivation.scene_script,
            derivation_result=derivation,
            requested_reference_mode=reference_mode,
            control_signals_available=effective_control_signals,
            video_model_input=video_model_input,
            warnings=tuple(warnings),
        )

    def _build_composition_plan(
        self,
        panel_results: list[PanelPrevisResult],
    ) -> FinalCompositionPlan:
        """Build a final composition plan from per-panel results."""
        panel_order = tuple(r.panel_index for r in panel_results)
        panel_durations = tuple(r.duration_seconds for r in panel_results)
        total_duration = sum(panel_durations)

        # Default transitions: cut between panels, dissolve at scene changes
        # (scene change detection would need scene_id comparison; simplified here)
        transitions: list[str] = []
        for i in range(len(panel_results) - 1):
            transitions.append("cut")  # Simplified: all cuts

        reference_modes = tuple(r.reference_mode for r in panel_results)
        control_levels = tuple(r.control_level for r in panel_results)

        warnings: list[str] = []
        if total_duration > 60:
            warnings.append(
                f"Total composition duration {total_duration:.1f}s exceeds 60s. "
                "Consider splitting into multiple compositions."
            )

        return FinalCompositionPlan(
            panel_count=len(panel_results),
            total_duration_seconds=total_duration,
            panel_order=panel_order,
            panel_durations=panel_durations,
            transitions=tuple(transitions),
            reference_modes=reference_modes,
            control_levels=control_levels,
            warnings=tuple(warnings),
        )
