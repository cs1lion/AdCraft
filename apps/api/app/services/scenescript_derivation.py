"""SceneScript derivation from storyboard panel (P1b).

Implements panel→SceneScript derivation: StoryboardPanelV2 fields
(camera/subject_action/composition/shot_type/camera_move/duration + bound
asset ids) → SceneScriptRoot with camera keyframes, character actions,
and asset binding auto-fill.

This is a deterministic derivation (rule-based mapping) as the P1b baseline.
LLM-assisted refinement can be layered on top later.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.agent_canvas_ad_media import StoryboardPanelV2
from app.schemas.scene_script import (
    CameraKeyframe,
    CharacterAction,
    CharacterAppearance,
    CharacterKeyframe,
    SceneCamera,
    SceneCharacter,
    SceneEnvironmentObject,
    SceneInfo,
    SceneProp,
    SceneScriptRoot,
    SceneShot,
    ShotType,
)
from app.services.panel_asset_binding import PanelAssetBindingService


# ---------------------------------------------------------------------------
# Mapping tables
# ---------------------------------------------------------------------------

_SHOT_TYPE_TO_CAMERA_DISTANCE: dict[str, tuple[float, float, float]] = {
    # shot_type from StoryboardPanelV2 → (x, y, z) camera position
    "wide": (0.0, 5.0, 10.0),
    "medium": (0.0, 2.0, 5.0),
    "close-up": (0.0, 1.5, 2.0),
    "ecu": (0.0, 1.5, 1.0),
    "ots": (1.0, 1.5, 2.0),
}

_SHOT_TYPE_TO_SCENE_SHOT: dict[str, ShotType] = {
    "wide": "wide",
    "medium": "medium",
    "close-up": "closeup",
    "ecu": "closeup",
    "ots": "over_shoulder",
}

_DEFAULT_CAMERA_POSITION = (0.0, 2.0, 5.0)
_DEFAULT_LOOK_AT = (0.0, 1.0, 0.0)
_DEFAULT_CHARACTER_POSITION = (0.0, 0.0, 0.0)
_DEFAULT_PROP_POSITION = (1.5, 0.0, 0.0)
_DEFAULT_ENV_POSITION = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class SceneScriptDerivationResult:
    """Result of a panel→SceneScript derivation."""

    scene_script: SceneScriptRoot
    warnings: tuple[str, ...] = ()
    derived_fields: tuple[str, ...] = ()


class SceneScriptDerivationService:
    """Derive SceneScriptRoot from a StoryboardPanelV2.

    Deterministic rule-based mapping (P1b baseline). LLM-assisted
    refinement can be layered on top by post-processing the output.
    """

    def derive(
        self,
        *,
        panel: StoryboardPanelV2,
        default_frame_rate: int = 30,
    ) -> SceneScriptDerivationResult:
        """Derive a SceneScriptRoot from a storyboard panel.

        Args:
            panel: The storyboard panel to derive from.
            default_frame_rate: Frame rate to use if not specified.

        Returns:
            SceneScriptDerivationResult with the derived SceneScriptRoot.
        """
        warnings: list[str] = []
        derived_fields: list[str] = []

        duration = panel.duration_seconds or 5.0
        frame_rate = default_frame_rate
        total_frames = max(1, int(duration * frame_rate))

        # --- SceneInfo ---
        scene_name = f"Panel {panel.panel_index}: {panel.beat[:50]}" if panel.beat else f"Panel {panel.panel_index}"
        scene_info = SceneInfo(
            name=scene_name,
            environment="indoor",
            lighting="warm",
            duration=duration,
            frame_rate=frame_rate,
        )
        derived_fields.append("scene.duration")

        # --- Characters ---
        characters: list[SceneCharacter] = []
        if panel.character_ids:
            for idx, char_id in enumerate(panel.character_ids):
                char = self._derive_character(
                    char_id=char_id,
                    subject_action=panel.subject_action,
                    total_frames=total_frames,
                    index=idx,
                )
                characters.append(char)
            derived_fields.append("characters (from character_ids)")
        else:
            warnings.append("No character_ids bound to panel; scene will have no characters.")

        # --- Props ---
        props: list[SceneProp] = []
        if panel.prop_ids:
            for idx, prop_id in enumerate(panel.prop_ids):
                prop = SceneProp(
                    id=prop_id,
                    type="box",
                    prop_asset_id=prop_id,
                    position=[
                        _DEFAULT_PROP_POSITION[0] + idx * 1.5,
                        _DEFAULT_PROP_POSITION[1],
                        _DEFAULT_PROP_POSITION[2],
                    ],
                    scale=1.0,
                    rotation_y=0.0,
                )
                props.append(prop)
            derived_fields.append("props (from prop_ids)")

        # --- Environment ---
        environment_objects: list[SceneEnvironmentObject] = []
        if panel.scene_id:
            env_obj = SceneEnvironmentObject(
                id=f"env_{panel.scene_id}",
                type="floor",
                scene_asset_id=panel.scene_id,
                position=list(_DEFAULT_ENV_POSITION),
                scale=10.0,
                rotation_y=0.0,
            )
            environment_objects.append(env_obj)
            derived_fields.append("environment (from scene_id)")
        else:
            warnings.append("No scene_id bound to panel; environment will be empty.")

        # --- Camera ---
        camera, camera_warnings = self._derive_camera(
            shot_type=panel.shot_type,
            camera_move=panel.camera_move,
            camera_text=panel.camera,
            total_frames=total_frames,
        )
        warnings.extend(camera_warnings)
        derived_fields.append("cameras (from shot_type + camera_move)")

        # --- Shot ---
        shot = SceneShot(
            id=f"shot_panel_{panel.panel_index}",
            camera=camera.id,
            start_frame=0,
            end_frame=total_frames - 1,
            description=panel.beat or "",
        )

        # --- Speech bindings (P2, per ADR bulletin Objection 3) ---
        binding_service = PanelAssetBindingService()
        asset_bundle = binding_service.aggregate(panel=panel)
        speech_bindings = asset_bundle.speech_bindings
        # Propagate binding warnings
        warnings.extend(asset_bundle.warnings)
        if speech_bindings:
            derived_fields.append("speech_bindings (from character_speech_map)")
            # Bound-mode note: shot timing should be driven by speech duration
            bound_count = sum(1 for b in speech_bindings if b.mode == "bound")
            if bound_count > 0:
                warnings.append(
                    f"{bound_count} bound-mode speech binding(s): shot timing should be "
                    f"driven by speech duration (ADR-0003 bound-mode semantics)."
                )

        # --- Assemble ---
        scene_script = SceneScriptRoot(
            scene=scene_info,
            characters=characters,
            props=props,
            environment=environment_objects,
            cameras=[camera],
            shots=[shot],
            speech_bindings=list(speech_bindings),
        )

        return SceneScriptDerivationResult(
            scene_script=scene_script,
            warnings=tuple(warnings),
            derived_fields=tuple(derived_fields),
        )

    # ------------------------------------------------------------------
    # Character derivation
    # ------------------------------------------------------------------

    def _derive_character(
        self,
        *,
        char_id: str,
        subject_action: str | None,
        total_frames: int,
        index: int,
    ) -> SceneCharacter:
        """Derive a SceneCharacter with keyframes from panel subject_action."""
        action = self._infer_action(subject_action)
        position = [
            _DEFAULT_CHARACTER_POSITION[0] + index * 1.2,
            _DEFAULT_CHARACTER_POSITION[1],
            _DEFAULT_CHARACTER_POSITION[2],
        ]

        keyframes: list[CharacterKeyframe] = []

        if action == "walk":
            # Walk: move from left to right
            start_pos = [position[0] - 2.0, position[1], position[2]]
            end_pos = [position[0] + 2.0, position[1], position[2]]
            keyframes.append(
                CharacterKeyframe(frame=0, position=start_pos, rotation_y=90.0, action="walk")
            )
            keyframes.append(
                CharacterKeyframe(
                    frame=total_frames - 1, position=end_pos, rotation_y=90.0, action="stand"
                )
            )
        elif action == "talk":
            keyframes.append(
                CharacterKeyframe(frame=0, position=position, rotation_y=0.0, action="talk")
            )
            if total_frames > 1:
                keyframes.append(
                    CharacterKeyframe(
                        frame=total_frames - 1, position=position, rotation_y=0.0, action="talk"
                    )
                )
        elif action == "gesture":
            keyframes.append(
                CharacterKeyframe(frame=0, position=position, rotation_y=0.0, action="gesture")
            )
            if total_frames > 1:
                keyframes.append(
                    CharacterKeyframe(
                        frame=total_frames - 1, position=position, rotation_y=15.0, action="stand"
                    )
                )
        elif action == "sit":
            sit_pos = [position[0], position[1], position[2]]
            keyframes.append(
                CharacterKeyframe(frame=0, position=sit_pos, rotation_y=0.0, action="sit")
            )
        else:  # stand
            keyframes.append(
                CharacterKeyframe(frame=0, position=position, rotation_y=0.0, action="stand")
            )

        return SceneCharacter(
            id=char_id,
            type="lowpoly_human",
            character_asset_id=char_id,
            appearance=CharacterAppearance(),
            keyframes=keyframes,
        )

    @staticmethod
    def _infer_action(subject_action: str | None) -> CharacterAction:
        """Infer CharacterAction from free-text subject_action."""
        if not subject_action:
            return "stand"
        text = subject_action.lower()
        if any(w in text for w in ("walk", "run", "move", "enter", "approach")):
            return "walk"
        if any(w in text for w in ("talk", "speak", "say", "shout", "whisper")):
            return "talk"
        if any(w in text for w in ("gesture", "point", "wave", "raise", "hand")):
            return "gesture"
        if any(w in text for w in ("sit", "seat", "down")):
            return "sit"
        return "stand"

    # ------------------------------------------------------------------
    # Camera derivation
    # ------------------------------------------------------------------

    def _derive_camera(
        self,
        *,
        shot_type: str | None,
        camera_move: str | None,
        camera_text: str | None,
        total_frames: int,
    ) -> tuple[SceneCamera, list[str]]:
        """Derive a SceneCamera with keyframes from panel camera fields."""
        warnings: list[str] = []

        # Shot type → scene shot type
        scene_shot_type = _SHOT_TYPE_TO_SCENE_SHOT.get(shot_type or "", "medium")
        if shot_type and shot_type not in _SHOT_TYPE_TO_SCENE_SHOT:
            warnings.append(f"Unknown shot_type '{shot_type}'; defaulting to medium.")

        # Base position
        base_pos = _SHOT_TYPE_TO_CAMERA_DISTANCE.get(shot_type or "", _DEFAULT_CAMERA_POSITION)
        look_at = list(_DEFAULT_LOOK_AT)

        # Generate keyframes based on camera_move
        keyframes = self._generate_camera_keyframes(
            base_pos=base_pos,
            look_at=look_at,
            camera_move=camera_move,
            total_frames=total_frames,
        )

        if camera_move and camera_move not in ("static", "pan", "tilt", "dolly", "zoom", "crane", "handheld"):
            warnings.append(f"Unknown camera_move '{camera_move}'; defaulting to static.")

        if camera_text:
            warnings.append(f"camera free-text '{camera_text[:50]}' not parsed in P1b baseline; LLM refinement needed.")

        camera = SceneCamera(
            id="cam_0",
            shot_type=scene_shot_type,
            keyframes=keyframes,
        )
        return camera, warnings

    @staticmethod
    def _generate_camera_keyframes(
        *,
        base_pos: tuple[float, float, float],
        look_at: list[float],
        camera_move: str | None,
        total_frames: int,
    ) -> list[CameraKeyframe]:
        """Generate camera keyframes based on camera_move type."""
        move = (camera_move or "static").lower()
        mid_frame = max(1, total_frames // 2)
        end_frame = max(1, total_frames - 1)

        if move == "static":
            return [CameraKeyframe(frame=0, position=list(base_pos), look_at=look_at)]

        if move == "pan":
            # Pan: rotate horizontally (look_at moves left→right)
            return [
                CameraKeyframe(frame=0, position=list(base_pos), look_at=[look_at[0] - 2, look_at[1], look_at[2]]),
                CameraKeyframe(frame=end_frame, position=list(base_pos), look_at=[look_at[0] + 2, look_at[1], look_at[2]]),
            ]

        if move == "tilt":
            # Tilt: rotate vertically (look_at moves down→up)
            return [
                CameraKeyframe(frame=0, position=list(base_pos), look_at=[look_at[0], look_at[1] - 1, look_at[2]]),
                CameraKeyframe(frame=end_frame, position=list(base_pos), look_at=[look_at[0], look_at[1] + 1, look_at[2]]),
            ]

        if move == "dolly":
            # Dolly: move forward/backward
            return [
                CameraKeyframe(frame=0, position=[base_pos[0], base_pos[1], base_pos[2] + 2], look_at=look_at),
                CameraKeyframe(frame=end_frame, position=[base_pos[0], base_pos[1], base_pos[2] - 2], look_at=look_at),
            ]

        if move == "zoom":
            # Zoom: simulate with dolly (SceneCamera has no fov field)
            return [
                CameraKeyframe(frame=0, position=[base_pos[0], base_pos[1], base_pos[2] + 1.5], look_at=look_at),
                CameraKeyframe(frame=end_frame, position=[base_pos[0], base_pos[1], base_pos[2] - 1.5], look_at=look_at),
            ]

        if move == "crane":
            # Crane: move up/down
            return [
                CameraKeyframe(frame=0, position=[base_pos[0], base_pos[1] - 1, base_pos[2]], look_at=look_at),
                CameraKeyframe(frame=end_frame, position=[base_pos[0], base_pos[1] + 2, base_pos[2]], look_at=look_at),
            ]

        if move == "handheld":
            # Handheld: subtle shake with 3 keyframes
            return [
                CameraKeyframe(frame=0, position=list(base_pos), look_at=look_at),
                CameraKeyframe(
                    frame=mid_frame,
                    position=[base_pos[0] + 0.1, base_pos[1] + 0.05, base_pos[2] + 0.1],
                    look_at=[look_at[0] + 0.05, look_at[1], look_at[2]],
                ),
                CameraKeyframe(
                    frame=end_frame,
                    position=[base_pos[0] - 0.08, base_pos[1] - 0.03, base_pos[2] - 0.08],
                    look_at=[look_at[0] - 0.04, look_at[1], look_at[2]],
                ),
            ]

        # Default: static
        return [CameraKeyframe(frame=0, position=list(base_pos), look_at=look_at)]
