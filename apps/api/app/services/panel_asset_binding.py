"""Panel-level asset binding aggregation (P2).

Aggregates asset references from StoryboardPanelV2 fields
(character_ids/scene_id/prop_ids/character_speech_map) into a structured
bundle, and generates SpeechBinding[] for SceneScript integration.

Per ADR bulletin §2 Objection 2: fields first, endpoint later. This module
provides the aggregation logic; the REST endpoint is deferred until the
"drag asset onto panel" UI ships.

Per ADR bulletin §2 Objection 3: panel-bound character + its speech_audio
→ automatically fills SceneScript.speech_bindings; bound mode derives shot
timing from speech duration.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.agent_canvas_ad_media import StoryboardPanelV2
from app.schemas.scene_script import SpeechBinding, SpeechMode


@dataclass(frozen=True)
class PanelAssetBundle:
    """Aggregated asset references from a storyboard panel.

    This is the output of panel-level asset binding aggregation. It is
    consumed by:
    - SceneScriptDerivationService (to fill character_asset_id etc.)
    - Reference bundle builder (to aggregate panel-level references)
    - Speech binding generation (for lip-sync and bound-mode timing)
    """

    panel_index: int
    character_ids: tuple[str, ...] = ()
    scene_id: str | None = None
    prop_ids: tuple[str, ...] = ()
    speech_bindings: tuple[SpeechBinding, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def all_asset_ids(self) -> tuple[str, ...]:
        """All asset IDs referenced by this panel (deduplicated)."""
        ids: list[str] = []
        ids.extend(self.character_ids)
        if self.scene_id:
            ids.append(self.scene_id)
        ids.extend(self.prop_ids)
        for binding in self.speech_bindings:
            ids.append(binding.speech_asset)
        return tuple(dict.fromkeys(ids))

    @property
    def has_speech(self) -> bool:
        """Whether this panel has any speech-bound characters."""
        return len(self.speech_bindings) > 0

    @property
    def bound_speech_count(self) -> int:
        """Number of speech bindings in bound mode."""
        return sum(1 for b in self.speech_bindings if b.mode == "bound")


class PanelAssetBindingService:
    """Aggregate panel-level asset references and generate speech bindings.

    This service reads the P0/P2 fields on StoryboardPanelV2 and produces
    a structured PanelAssetBundle. It does NOT persist anything — it is a
    pure transformation layer.
    """

    def aggregate(self, *, panel: StoryboardPanelV2) -> PanelAssetBundle:
        """Aggregate asset references from a storyboard panel.

        Args:
            panel: The storyboard panel to aggregate assets from.

        Returns:
            PanelAssetBundle with all aggregated references and speech bindings.
        """
        warnings: list[str] = []

        # --- Validate character_speech_map references ---
        valid_character_ids = set(panel.character_ids)
        speech_bindings: list[SpeechBinding] = []

        for char_id, speech_asset_id in panel.character_speech_map.items():
            if char_id not in valid_character_ids:
                warnings.append(
                    f"Panel {panel.panel_index}: character_speech_map references "
                    f"'{char_id}' which is not in character_ids {sorted(valid_character_ids)}; "
                    f"speech binding skipped."
                )
                continue
            if not speech_asset_id:
                warnings.append(
                    f"Panel {panel.panel_index}: character '{char_id}' has empty speech_asset_id; "
                    f"speech binding skipped."
                )
                continue
            # Bound mode by default (speech drives timing)
            binding = SpeechBinding(
                character=char_id,
                speech_asset=speech_asset_id,
                mode="bound",
            )
            speech_bindings.append(binding)

        # --- Warn about characters without speech (informational) ---
        characters_with_speech = set(panel.character_speech_map.keys())
        characters_without_speech = valid_character_ids - characters_with_speech
        if characters_without_speech and panel.character_speech_map:
            warnings.append(
                f"Panel {panel.panel_index}: characters {sorted(characters_without_speech)} "
                f"have no speech_audio binding; they will use free-mode animation."
            )

        return PanelAssetBundle(
            panel_index=panel.panel_index,
            character_ids=panel.character_ids,
            scene_id=panel.scene_id,
            prop_ids=panel.prop_ids,
            speech_bindings=tuple(speech_bindings),
            warnings=tuple(warnings),
        )

    def generate_speech_bindings(
        self,
        *,
        panel: StoryboardPanelV2,
        default_mode: SpeechMode = "bound",
    ) -> tuple[SpeechBinding, ...]:
        """Generate SpeechBinding[] from a panel's character_speech_map.

        This is a convenience method that returns only the speech bindings
        (used by SceneScriptDerivationService).

        Args:
            panel: The storyboard panel.
            default_mode: Default speech mode for bindings (default: bound).

        Returns:
            Tuple of valid SpeechBinding objects.
        """
        bundle = self.aggregate(panel=panel)
        if default_mode == "bound":
            return bundle.speech_bindings
        # Re-create with requested mode
        result: list[SpeechBinding] = []
        for binding in bundle.speech_bindings:
            result.append(
                SpeechBinding(
                    character=binding.character,
                    speech_asset=binding.speech_asset,
                    mode=default_mode,
                )
            )
        return tuple(result)

    def validate_binding_consistency(
        self,
        *,
        panels: list[StoryboardPanelV2],
    ) -> list[str]:
        """Validate binding consistency across a sequence of panels.

        Checks:
        - Same character_id has consistent speech_asset_id across panels
          (warn if different — may indicate intentional voice change)
        - scene_id is consistent across panels (warn if changes mid-sequence)

        Args:
            panels: List of storyboard panels to validate.

        Returns:
            List of warning messages (empty if fully consistent).
        """
        warnings: list[str] = []

        # Track character → speech_asset mapping across panels
        char_speech_map: dict[str, str] = {}
        scene_ids: set[str] = set()

        for panel in panels:
            if panel.scene_id:
                scene_ids.add(panel.scene_id)

            for char_id, speech_asset_id in panel.character_speech_map.items():
                if char_id in char_speech_map and char_speech_map[char_id] != speech_asset_id:
                    warnings.append(
                        f"Panel {panel.panel_index}: character '{char_id}' speech_asset changes "
                        f"from '{char_speech_map[char_id]}' to '{speech_asset_id}' "
                        f"(may indicate intentional voice change, verify)."
                    )
                char_speech_map[char_id] = speech_asset_id

        if len(scene_ids) > 1:
            warnings.append(
                f"Scene changes across panels: {sorted(scene_ids)}. "
                f"Ensure camera/lighting continuity at scene boundaries."
            )

        return warnings
