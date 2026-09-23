"""Tests for SceneScript derivation service (P1b)."""

from __future__ import annotations

import pytest

from app.schemas.agent_canvas_ad_media import StoryboardPanelV2
from app.schemas.scene_script import SceneScriptRoot
from app.services.scenescript_derivation import SceneScriptDerivationService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_panel(**kwargs) -> StoryboardPanelV2:
    """Create a StoryboardPanelV2 with sensible defaults."""
    defaults = {
        "panel_index": 1,
        "beat": "A character walks into a room.",
        "composition": "Wide establishing shot",
        "camera": "High angle",
        "subject_action": "Character walks in",
        "continuity_from_previous": "First panel",
    }
    defaults.update(kwargs)
    return StoryboardPanelV2(**defaults)


# ---------------------------------------------------------------------------
# Basic derivation
# ---------------------------------------------------------------------------

class TestBasicDerivation:
    def test_full_panel_derives_valid_scenescript(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(
            shot_type="wide",
            camera_move="static",
            duration_seconds=5.0,
            character_ids=("char_1",),
            prop_ids=("prop_1",),
            scene_id="scene_1",
        )
        result = service.derive(panel=panel)
        assert isinstance(result.scene_script, SceneScriptRoot)
        assert result.scene_script.scene.duration == 5.0
        assert result.scene_script.scene.frame_rate == 30
        assert result.scene_script.total_frames == 150
        assert len(result.scene_script.characters) == 1
        assert len(result.scene_script.props) == 1
        assert len(result.scene_script.environment) == 1
        assert len(result.scene_script.cameras) == 1
        assert len(result.scene_script.shots) == 1
        assert result.scene_script.shots[0].camera == "cam_0"
        assert result.scene_script.shots[0].start_frame == 0
        assert result.scene_script.shots[0].end_frame == 149

    def test_minimal_panel_uses_defaults(self):
        service = SceneScriptDerivationService()
        panel = _make_panel()  # no shot_type, camera_move, duration, assets
        result = service.derive(panel=panel)
        assert result.scene_script.scene.duration == 5.0  # default
        assert len(result.scene_script.characters) == 0
        assert len(result.scene_script.props) == 0
        assert len(result.scene_script.environment) == 0
        assert len(result.warnings) >= 2  # no characters + no scene

    def test_derived_fields_recorded(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(character_ids=("c1",), scene_id="s1")
        result = service.derive(panel=panel)
        assert "scene.duration" in result.derived_fields
        assert "characters (from character_ids)" in result.derived_fields
        assert "environment (from scene_id)" in result.derived_fields

    def test_custom_frame_rate(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(duration_seconds=2.0)
        result = service.derive(panel=panel, default_frame_rate=24)
        assert result.scene_script.scene.frame_rate == 24
        assert result.scene_script.total_frames == 48


# ---------------------------------------------------------------------------
# Shot type mapping
# ---------------------------------------------------------------------------

class TestShotTypeMapping:
    @pytest.mark.parametrize(
        "panel_shot_type,expected_scene_shot_type,expected_z",
        [
            ("wide", "wide", 10.0),
            ("medium", "medium", 5.0),
            ("close-up", "closeup", 2.0),
            ("ecu", "closeup", 1.0),
            ("ots", "over_shoulder", 2.0),
        ],
    )
    def test_shot_type_maps_to_camera(self, panel_shot_type, expected_scene_shot_type, expected_z):
        service = SceneScriptDerivationService()
        panel = _make_panel(shot_type=panel_shot_type, camera_move="static")
        result = service.derive(panel=panel)
        camera = result.scene_script.cameras[0]
        assert camera.shot_type == expected_scene_shot_type
        assert camera.keyframes[0].position[2] == expected_z

    def test_none_shot_type_defaults_to_medium(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(shot_type=None, camera_move="static")
        result = service.derive(panel=panel)
        assert result.scene_script.cameras[0].shot_type == "medium"


# ---------------------------------------------------------------------------
# Camera move keyframes
# ---------------------------------------------------------------------------

class TestCameraMove:
    @pytest.mark.parametrize(
        "camera_move,expected_keyframe_count",
        [
            ("static", 1),
            ("pan", 2),
            ("tilt", 2),
            ("dolly", 2),
            ("zoom", 2),
            ("crane", 2),
            ("handheld", 3),
        ],
    )
    def test_camera_move_generates_keyframes(self, camera_move, expected_keyframe_count):
        service = SceneScriptDerivationService()
        panel = _make_panel(shot_type="medium", camera_move=camera_move, duration_seconds=4.0)
        result = service.derive(panel=panel)
        camera = result.scene_script.cameras[0]
        assert len(camera.keyframes) == expected_keyframe_count
        # First keyframe always at frame 0
        assert camera.keyframes[0].frame == 0

    def test_pan_changes_look_at_x(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(shot_type="medium", camera_move="pan")
        result = service.derive(panel=panel)
        kf = result.scene_script.cameras[0].keyframes
        assert kf[0].look_at[0] < kf[1].look_at[0]  # left → right

    def test_dolly_changes_position_z(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(shot_type="medium", camera_move="dolly")
        result = service.derive(panel=panel)
        kf = result.scene_script.cameras[0].keyframes
        assert kf[0].position[2] != kf[1].position[2]

    def test_none_camera_move_defaults_static(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(camera_move=None)
        result = service.derive(panel=panel)
        assert len(result.scene_script.cameras[0].keyframes) == 1


# ---------------------------------------------------------------------------
# Character action inference
# ---------------------------------------------------------------------------

class TestCharacterAction:
    @pytest.mark.parametrize(
        "subject_action,expected_action",
        [
            ("walks into the room", "walk"),
            ("runs away", "walk"),
            ("enters the scene", "walk"),
            ("speaks to the camera", "talk"),
            ("shouts loudly", "talk"),
            ("points at the door", "gesture"),
            ("waves goodbye", "gesture"),
            ("sits down", "sit"),
            ("stands still", "stand"),
        ],
    )
    def test_action_inference(self, subject_action, expected_action):
        service = SceneScriptDerivationService()
        panel = _make_panel(subject_action=subject_action, character_ids=("c1",))
        result = service.derive(panel=panel)
        char = result.scene_script.characters[0]
        assert char.keyframes[0].action == expected_action

    def test_walk_generates_two_keyframes(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(subject_action="walks in", character_ids=("c1",), duration_seconds=3.0)
        result = service.derive(panel=panel)
        char = result.scene_script.characters[0]
        assert len(char.keyframes) == 2
        assert char.keyframes[0].action == "walk"
        assert char.keyframes[1].action == "stand"
        # Position changes (moves from left to right)
        assert char.keyframes[0].position[0] < char.keyframes[1].position[0]

    def test_multiple_characters_get_distinct_positions(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(character_ids=("c1", "c2", "c3"))
        result = service.derive(panel=panel)
        positions = [c.keyframes[0].position[0] for c in result.scene_script.characters]
        assert len(set(positions)) == 3  # all distinct


# ---------------------------------------------------------------------------
# Asset binding
# ---------------------------------------------------------------------------

class TestAssetBinding:
    def test_character_asset_id_set(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(character_ids=("char_abc",))
        result = service.derive(panel=panel)
        assert result.scene_script.characters[0].character_asset_id == "char_abc"

    def test_prop_asset_id_set(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(prop_ids=("prop_xyz",))
        result = service.derive(panel=panel)
        assert result.scene_script.props[0].prop_asset_id == "prop_xyz"

    def test_scene_asset_id_set(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(scene_id="scene_main")
        result = service.derive(panel=panel)
        assert result.scene_script.environment[0].scene_asset_id == "scene_main"

    def test_multiple_props_get_distinct_positions(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(prop_ids=("p1", "p2"))
        result = service.derive(panel=panel)
        assert len(result.scene_script.props) == 2
        assert result.scene_script.props[0].position[0] != result.scene_script.props[1].position[0]


# ---------------------------------------------------------------------------
# Scene info
# ---------------------------------------------------------------------------

class TestSceneInfo:
    def test_scene_name_includes_panel_index_and_beat(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(panel_index=3, beat="The hero draws their sword.")
        result = service.derive(panel=panel)
        assert "Panel 3" in result.scene_script.scene.name
        assert "hero draws" in result.scene_script.scene.name

    def test_shot_description_uses_beat(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(beat="Character opens the door.")
        result = service.derive(panel=panel)
        assert result.scene_script.shots[0].description == "Character opens the door."

    def test_duration_drives_total_frames(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(duration_seconds=10.0)
        result = service.derive(panel=panel)
        assert result.scene_script.total_frames == 300
        assert result.scene_script.shots[0].end_frame == 299


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------

class TestWarnings:
    def test_no_characters_warning(self):
        service = SceneScriptDerivationService()
        panel = _make_panel()  # no character_ids
        result = service.derive(panel=panel)
        assert any("No character_ids" in w for w in result.warnings)

    def test_no_scene_warning(self):
        service = SceneScriptDerivationService()
        panel = _make_panel()  # no scene_id
        result = service.derive(panel=panel)
        assert any("No scene_id" in w for w in result.warnings)

    def test_camera_free_text_not_parsed_warning(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(camera="Slow dolly in from the left side")
        result = service.derive(panel=panel)
        assert any("not parsed in P1b baseline" in w for w in result.warnings)

    def test_complete_panel_has_only_camera_warning(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(
            shot_type="wide",
            camera_move="static",
            character_ids=("c1",),
            prop_ids=("p1",),
            scene_id="s1",
            camera="Eye level",
        )
        result = service.derive(panel=panel)
        # Only warning should be the camera free-text not-parsed warning
        assert len(result.warnings) == 1
        assert "not parsed in P1b baseline" in result.warnings[0]


# ---------------------------------------------------------------------------
# Validation (SceneScriptRoot cross-field validators)
# ---------------------------------------------------------------------------

class TestValidation:
    def test_shot_camera_reference_valid(self):
        service = SceneScriptDerivationService()
        panel = _make_panel()
        result = service.derive(panel=panel)
        # If this doesn't raise, the shot references a valid camera
        assert result.scene_script.shots[0].camera in result.scene_script.camera_ids

    def test_unique_ids(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(character_ids=("c1", "c2"), prop_ids=("p1", "p2"))
        result = service.derive(panel=panel)
        char_ids = [c.id for c in result.scene_script.characters]
        prop_ids = [p.id for p in result.scene_script.props]
        assert len(char_ids) == len(set(char_ids))
        assert len(prop_ids) == len(set(prop_ids))


# ---------------------------------------------------------------------------
# Speech bindings integration (P2)
# ---------------------------------------------------------------------------

class TestSpeechBindingsIntegration:
    def test_speech_bindings_filled_from_character_speech_map(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(
            character_ids=("char_1",),
            character_speech_map={"char_1": "speech_asset_1"},
        )
        result = service.derive(panel=panel)
        assert len(result.scene_script.speech_bindings) == 1
        binding = result.scene_script.speech_bindings[0]
        assert binding.character == "char_1"
        assert binding.speech_asset == "speech_asset_1"
        assert binding.mode == "bound"

    def test_multiple_speech_bindings(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(
            character_ids=("char_1", "char_2"),
            character_speech_map={
                "char_1": "speech_1",
                "char_2": "speech_2",
            },
        )
        result = service.derive(panel=panel)
        assert len(result.scene_script.speech_bindings) == 2
        chars = {b.character for b in result.scene_script.speech_bindings}
        assert chars == {"char_1", "char_2"}

    def test_no_speech_map_empty_bindings(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(character_ids=("char_1",))
        result = service.derive(panel=panel)
        assert result.scene_script.speech_bindings == []

    def test_invalid_character_not_in_bindings(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(
            character_ids=("char_1",),
            character_speech_map={"char_not_in_panel": "speech_1"},
        )
        result = service.derive(panel=panel)
        assert result.scene_script.speech_bindings == []
        assert any("not in character_ids" in w for w in result.warnings)

    def test_speech_bindings_in_derived_fields(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(
            character_ids=("char_1",),
            character_speech_map={"char_1": "speech_1"},
        )
        result = service.derive(panel=panel)
        assert "speech_bindings (from character_speech_map)" in result.derived_fields

    def test_bound_mode_warning(self):
        service = SceneScriptDerivationService()
        panel = _make_panel(
            character_ids=("char_1",),
            character_speech_map={"char_1": "speech_1"},
        )
        result = service.derive(panel=panel)
        assert any("bound-mode speech binding" in w for w in result.warnings)

    def test_speech_binding_character_reference_valid(self):
        """Speech binding's character must reference an existing character (SceneScriptRoot validator)."""
        service = SceneScriptDerivationService()
        panel = _make_panel(
            character_ids=("char_1", "char_2"),
            character_speech_map={
                "char_1": "speech_1",
                "char_2": "speech_2",
            },
        )
        result = service.derive(panel=panel)
        # If this doesn't raise, all speech bindings reference valid characters
        for binding in result.scene_script.speech_bindings:
            assert binding.character in result.scene_script.character_ids
