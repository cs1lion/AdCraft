"""Tests for creation flow guidance service (P4)."""

from __future__ import annotations

import pytest

from app.schemas.agent_canvas import CanvasNodeV2
from app.services.creation_flow_guidance import (
    CreationFlowGuidanceService,
    CreationFlowStage,
    FLOW_STAGE_ORDER,
    FlowAssessment,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(
    node_id: str = "node_1",
    node_type: str = "text",
    creative_role: str = "general_text",
    status: str = "draft",
) -> CanvasNodeV2:
    """Create a minimal CanvasNodeV2 for testing."""
    from datetime import datetime, timezone

    return CanvasNodeV2(
        node_id=node_id,
        workflow_id="test_workflow",
        node_type=node_type,
        creative_role=creative_role,
        title=f"Test {node_type}",
        status=status,
        authoring_origin="user_free",
        position={"x": 0, "y": 0},
        revision=1,
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Basic flow assessment
# ---------------------------------------------------------------------------

class TestBasicAssessment:
    def test_empty_workflow_starts_at_world_setting(self):
        service = CreationFlowGuidanceService()
        result = service.assess_flow(nodes=[])
        assert isinstance(result, FlowAssessment)
        assert result.current_stage == CreationFlowStage.WORLD_SETTING
        assert result.current_stage_index == 0
        assert result.progress_percent == 0.0
        assert result.completed_stages == ()
        assert "Create World Setting" in result.next_action

    def test_all_stages_complete(self):
        service = CreationFlowGuidanceService()
        nodes = [
            _make_node("ws", "text", "world_setting", "ready"),
            _make_node("script", "script", "script", "ready"),
            _make_node("sb", "text", "storyboard_sequence", "ready"),
            _make_node("3d", "scene-3d", "scene_3d_previs", "ready"),
            _make_node("char", "text", "character", "ready"),
            _make_node("render", "text", "storyboard_video", "ready"),
        ]
        result = service.assess_flow(nodes=nodes)
        assert result.is_complete is True
        assert result.progress_percent == 100.0
        assert len(result.completed_stages) == 6
        assert "Flow complete" in result.next_action

    def test_partial_completion(self):
        service = CreationFlowGuidanceService()
        nodes = [
            _make_node("ws", "text", "world_setting", "ready"),
            _make_node("script", "script", "script", "ready"),
        ]
        result = service.assess_flow(nodes=nodes)
        assert result.current_stage == CreationFlowStage.STORYBOARD
        assert result.current_stage_index == 2
        assert result.progress_percent == pytest.approx(33.3, abs=0.1)
        assert len(result.completed_stages) == 2

    def test_nodes_exist_but_not_ready(self):
        service = CreationFlowGuidanceService()
        nodes = [
            _make_node("ws", "text", "world_setting", "draft"),
        ]
        result = service.assess_flow(nodes=nodes)
        assert result.current_stage == CreationFlowStage.WORLD_SETTING
        assert result.progress_percent == 0.0
        assert "Run" in result.next_action


# ---------------------------------------------------------------------------
# Stage status
# ---------------------------------------------------------------------------

class TestStageStatus:
    def test_stage_with_ready_node_is_completed(self):
        service = CreationFlowGuidanceService()
        nodes = [_make_node("script", "script", "script", "ready")]
        result = service.assess_flow(nodes=nodes)
        script_status = next(s for s in result.stage_statuses if s.stage == CreationFlowStage.SCRIPT)
        assert script_status.completed is True
        assert script_status.ready_nodes == 1
        assert script_status.total_nodes == 1

    def test_stage_without_nodes_is_not_completed(self):
        service = CreationFlowGuidanceService()
        result = service.assess_flow(nodes=[])
        for status in result.stage_statuses:
            assert status.completed is False
            assert status.has_nodes is False
            assert len(status.blockers) > 0

    def test_stage_with_draft_node_has_blocker(self):
        service = CreationFlowGuidanceService()
        nodes = [_make_node("script", "script", "script", "draft")]
        result = service.assess_flow(nodes=nodes)
        script_status = next(s for s in result.stage_statuses if s.stage == CreationFlowStage.SCRIPT)
        assert script_status.completed is False
        assert len(script_status.blockers) > 0
        assert "none are ready" in script_status.blockers[0]


# ---------------------------------------------------------------------------
# Next action generation
# ---------------------------------------------------------------------------

class TestNextAction:
    def test_create_action_when_no_nodes(self):
        service = CreationFlowGuidanceService()
        result = service.assess_flow(nodes=[])
        assert "Create" in result.next_action
        assert "World Setting" in result.next_action

    def test_run_action_when_nodes_not_ready(self):
        service = CreationFlowGuidanceService()
        nodes = [_make_node("ws", "text", "world_setting", "working")]
        result = service.assess_flow(nodes=nodes)
        assert "Run" in result.next_action

    def test_move_to_next_action_when_stage_complete(self):
        service = CreationFlowGuidanceService()
        nodes = [_make_node("ws", "text", "world_setting", "ready")]
        result = service.assess_flow(nodes=nodes)
        # When world_setting is complete, next stage is script (no nodes yet)
        assert result.current_stage == CreationFlowStage.SCRIPT
        assert "Create" in result.next_action
        assert "Script" in result.next_action

    def test_complete_action_when_all_done(self):
        service = CreationFlowGuidanceService()
        nodes = [
            _make_node("ws", "text", "world_setting", "ready"),
            _make_node("script", "script", "script", "ready"),
            _make_node("sb", "text", "storyboard_sequence", "ready"),
            _make_node("3d", "scene-3d", "scene_3d_previs", "ready"),
            _make_node("char", "text", "character", "ready"),
            _make_node("render", "text", "storyboard_video", "ready"),
        ]
        result = service.assess_flow(nodes=nodes)
        assert "Flow complete" in result.next_action


# ---------------------------------------------------------------------------
# Progress calculation
# ---------------------------------------------------------------------------

class TestProgress:
    def test_progress_0_for_empty(self):
        service = CreationFlowGuidanceService()
        result = service.assess_flow(nodes=[])
        assert result.progress_percent == 0.0

    def test_progress_100_for_all_complete(self):
        service = CreationFlowGuidanceService()
        nodes = [
            _make_node("ws", "text", "world_setting", "ready"),
            _make_node("script", "script", "script", "ready"),
            _make_node("sb", "text", "storyboard_sequence", "ready"),
            _make_node("3d", "scene-3d", "scene_3d_previs", "ready"),
            _make_node("char", "text", "character", "ready"),
            _make_node("render", "text", "storyboard_video", "ready"),
        ]
        result = service.assess_flow(nodes=nodes)
        assert result.progress_percent == 100.0

    def test_progress_increments_by_stage(self):
        service = CreationFlowGuidanceService()
        # 1 stage complete = 16.7%
        nodes = [_make_node("ws", "text", "world_setting", "ready")]
        result = service.assess_flow(nodes=nodes)
        assert result.progress_percent == pytest.approx(16.7, abs=0.1)


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------

class TestWarnings:
    def test_no_world_setting_warning(self):
        service = CreationFlowGuidanceService()
        nodes = [_make_node("script", "script", "script", "ready")]
        result = service.assess_flow(nodes=nodes)
        assert any("No world_setting node" in w for w in result.warnings)

    def test_no_warning_when_world_setting_exists(self):
        service = CreationFlowGuidanceService()
        nodes = [_make_node("ws", "text", "world_setting", "draft")]
        result = service.assess_flow(nodes=nodes)
        assert not any("No world_setting node" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Flow stage metadata
# ---------------------------------------------------------------------------

class TestFlowStageMetadata:
    def test_get_flow_stages_returns_all_stages(self):
        service = CreationFlowGuidanceService()
        stages = service.get_flow_stages()
        assert len(stages) == 6
        assert stages[0]["stage"] == "world_setting"
        assert stages[-1]["stage"] == "render"

    def test_get_stage_guidance(self):
        service = CreationFlowGuidanceService()
        guidance = service.get_stage_guidance(CreationFlowStage.SCRIPT)
        assert "display_name" in guidance
        assert "description" in guidance
        assert "next_stage" in guidance

    def test_flow_stage_order_is_complete(self):
        assert len(FLOW_STAGE_ORDER) == 6
        assert FLOW_STAGE_ORDER[0] == CreationFlowStage.WORLD_SETTING
        assert FLOW_STAGE_ORDER[-1] == CreationFlowStage.RENDER


# ---------------------------------------------------------------------------
# WorldSettingCoreV2 extension (P4)
# ---------------------------------------------------------------------------

class TestWorldSettingExtension:
    def test_owned_scene_ids_default_empty(self):
        from app.schemas.agent_canvas_world_setting import WorldSettingCoreV2
        ws = WorldSettingCoreV2(
            premise="Test premise",
            era_and_place="Test era",
            world_rules=("Rule 1",),
            visual_continuity=("Style 1",),
        )
        assert ws.owned_scene_ids == ()

    def test_owned_scene_ids_can_be_set(self):
        from app.schemas.agent_canvas_world_setting import WorldSettingCoreV2
        ws = WorldSettingCoreV2(
            premise="Test premise",
            era_and_place="Test era",
            world_rules=("Rule 1",),
            visual_continuity=("Style 1",),
            owned_scene_ids=("scene_1", "scene_2", "scene_3"),
        )
        assert ws.owned_scene_ids == ("scene_1", "scene_2", "scene_3")

    def test_owned_scene_ids_max_length(self):
        from app.schemas.agent_canvas_world_setting import WorldSettingCoreV2
        # 33 scene IDs should fail (max 32)
        too_many = tuple(f"scene_{i}" for i in range(33))
        with pytest.raises(Exception):
            WorldSettingCoreV2(
                premise="Test premise",
                era_and_place="Test era",
                world_rules=("Rule 1",),
                visual_continuity=("Style 1",),
                owned_scene_ids=too_many,
            )


# ---------------------------------------------------------------------------
# Speaker ↔ character orchestration warnings (dialogue-driven chain)
# ---------------------------------------------------------------------------


class TestSpeakerOrchestrationWarnings:
    """The bed's speaker names must equal the scene's character ids.

    apply_dialogue_lip_sync fails closed on unknown speakers; the flow
    guidance must say so BEFORE the author writes the whole bed.
    """

    @staticmethod
    def _scene_node(character_ids):
        node = _make_node(node_type="scene-3d", creative_role="scene_3d_previs")
        node.structured_content = {
            "scene_script": {
                "scene": {"name": "lab", "duration": 6, "frame_rate": 30},
                "characters": [
                    {"id": cid, "type": "lowpoly_human", "keyframes": []}
                    for cid in character_ids
                ],
            }
        }
        return node

    @staticmethod
    def _voice_node(speakers):
        node = _make_node(node_type="voice-cast", creative_role="voice_cast")
        node.structured_content = {
            "audio_bed": {
                "roles": [{"name": s} for s in speakers],
                "scripts": [{"speaker": s, "text": "台词"} for s in speakers],
            }
        }
        return node

    def test_unmatched_speaker_names_the_message_and_lists_valid_ids(self):
        service = CreationFlowGuidanceService()
        assessment = service.assess_flow(
            nodes=[self._scene_node(["lin", "su"]), self._voice_node(["lin", "旁白"])],
        )

        matched = [w for w in assessment.warnings if "do not match any scene-3d" in w]
        assert len(matched) == 1
        assert "旁白" in matched[0]
        assert "lin" not in matched[0].split("speaker(s)")[1].split(" do not match")[0]
        assert "Available character ids: lin, su." in matched[0]

    def test_matched_speakers_produce_no_warning(self):
        service = CreationFlowGuidanceService()
        assessment = service.assess_flow(
            nodes=[self._scene_node(["lin", "su"]), self._voice_node(["lin", "su"])],
        )

        assert not [w for w in assessment.warnings if "do not match any scene-3d" in w]

    def test_voice_node_without_bed_is_silent(self):
        service = CreationFlowGuidanceService()
        assessment = service.assess_flow(
            nodes=[self._scene_node(["lin"]), _make_node(node_type="voice-cast")],
        )

        assert not [w for w in assessment.warnings if "do not match any scene-3d" in w]

    def test_bed_without_scene_says_no_character_exists_yet(self):
        service = CreationFlowGuidanceService()
        assessment = service.assess_flow(nodes=[self._voice_node(["lin"])])

        warning = next(w for w in assessment.warnings if "do not match any scene-3d" in w)
        assert "No scene-3d character exists yet" in warning
