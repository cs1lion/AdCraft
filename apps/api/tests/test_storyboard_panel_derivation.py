"""Tests for storyboard panel derivation service (P1a)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import Settings
from app.services.storyboard_panel_derivation import (
    DerivationResult,
    StoryboardPanelDerivationError,
    StoryboardPanelDerivationService,
)


# ---------------------------------------------------------------------------
# _extract_json_array
# ---------------------------------------------------------------------------

class TestExtractJsonArray:
    def test_plain_json_array(self):
        text = '[{"panel_index": 1, "beat": "test"}]'
        result = StoryboardPanelDerivationService._extract_json_array(text)
        assert result == text

    def test_markdown_code_block(self):
        text = 'Here is the result:\n```json\n[{"panel_index": 1}]\n```\nDone.'
        result = StoryboardPanelDerivationService._extract_json_array(text)
        assert result == '[{"panel_index": 1}]'

    def test_code_block_without_language(self):
        text = '```\n[{"panel_index": 1}]\n```'
        result = StoryboardPanelDerivationService._extract_json_array(text)
        assert result == '[{"panel_index": 1}]'

    def test_nested_arrays(self):
        text = '[{"items": [1, 2, 3]}, {"items": [4, 5]}]'
        result = StoryboardPanelDerivationService._extract_json_array(text)
        assert result == text

    def test_no_array_returns_none(self):
        text = "No JSON here."
        assert StoryboardPanelDerivationService._extract_json_array(text) is None

    def test_array_in_surrounding_text(self):
        text = 'Before [1, 2, 3] after'
        result = StoryboardPanelDerivationService._extract_json_array(text)
        assert result == '[1, 2, 3]'


# ---------------------------------------------------------------------------
# _parse_and_validate
# ---------------------------------------------------------------------------

class TestParseAndValidate:
    def _service(self) -> StoryboardPanelDerivationService:
        return StoryboardPanelDerivationService(Settings(llm_api_key="test", llm_base_url="http://test"))

    def test_valid_panels(self):
        service = self._service()
        raw = json.dumps([
            {
                "panel_index": 1,
                "beat": "Opening shot",
                "composition": "Wide establishing",
                "camera": "High angle",
                "subject_action": "Character walks in",
                "continuity_from_previous": "First panel",
                "shot_type": "wide",
                "camera_move": "static",
                "duration_seconds": 5.0,
            },
            {
                "panel_index": 2,
                "beat": "Close up",
                "composition": "Tight framing",
                "camera": "Eye level",
                "subject_action": "Character speaks",
                "continuity_from_previous": "Cut from wide",
                "shot_type": "close-up",
                "camera_move": "dolly",
                "duration_seconds": 3.0,
            },
        ])
        panels, warnings = service._parse_and_validate(raw)
        assert len(panels) == 2
        assert panels[0].panel_index == 1
        assert panels[0].shot_type == "wide"
        assert panels[1].camera_move == "dolly"
        assert warnings == []

    def test_panel_index_auto_assigned(self):
        service = self._service()
        raw = json.dumps([
            {"beat": "b1", "composition": "c1", "camera": "cam1", "subject_action": "a1", "continuity_from_previous": "cont1"},
            {"beat": "b2", "composition": "c2", "camera": "cam2", "subject_action": "a2", "continuity_from_previous": "cont2"},
        ])
        panels, _ = service._parse_and_validate(raw)
        assert panels[0].panel_index == 1
        assert panels[1].panel_index == 2

    def test_invalid_panel_skipped_with_warning(self):
        service = self._service()
        raw = json.dumps([
            {"beat": "valid", "composition": "c", "camera": "cam", "subject_action": "a", "continuity_from_previous": "cont"},
            "not an object",
            {"beat": "also valid", "composition": "c2", "camera": "cam2", "subject_action": "a2", "continuity_from_previous": "cont2"},
        ])
        panels, warnings = service._parse_and_validate(raw)
        assert len(panels) == 2
        assert len(warnings) == 1
        assert "not an object" in warnings[0]

    def test_no_json_raises(self):
        service = self._service()
        with pytest.raises(StoryboardPanelDerivationError, match="did not contain a valid JSON array"):
            service._parse_and_validate("No JSON here.")

    def test_invalid_json_raises(self):
        service = self._service()
        with pytest.raises(StoryboardPanelDerivationError, match="Failed to parse LLM output as JSON"):
            service._parse_and_validate("```json\n[{invalid}]\n```")

    def test_no_valid_panels_raises(self):
        service = self._service()
        with pytest.raises(StoryboardPanelDerivationError, match="No valid panels"):
            service._parse_and_validate('["not", "objects"]')

    def test_optional_fields_default_none(self):
        service = self._service()
        raw = json.dumps([
            {"beat": "b", "composition": "c", "camera": "cam", "subject_action": "a", "continuity_from_previous": "cont"},
        ])
        panels, _ = service._parse_and_validate(raw)
        assert panels[0].scene_id is None
        assert panels[0].character_ids == ()
        assert panels[0].shot_type is None
        assert panels[0].camera_move is None
        assert panels[0].duration_seconds is None
        assert panels[0].scene_script_id is None


# ---------------------------------------------------------------------------
# derive (error handling without LLM)
# ---------------------------------------------------------------------------

class TestDeriveErrorHandling:
    def test_empty_script_raises(self):
        service = StoryboardPanelDerivationService(Settings())
        with pytest.raises(StoryboardPanelDerivationError, match="Cannot derive panels from empty script"):
            service.derive(script_text="   ")

    def test_no_llm_config_raises(self):
        service = StoryboardPanelDerivationService(Settings(llm_api_key=None, llm_base_url=None))
        with pytest.raises(StoryboardPanelDerivationError, match="LLM API key and base URL are required"):
            service.derive(script_text="test script")


# ---------------------------------------------------------------------------
# derive (with mocked LLM)
# ---------------------------------------------------------------------------

class TestDeriveWithMock:
    def _mock_response(self, panels: list[dict]) -> MagicMock:
        mock = MagicMock()
        mock.json.return_value = {
            "choices": [{"message": {"content": json.dumps(panels)}}]
        }
        mock.raise_for_status = MagicMock()
        return mock

    def test_successful_derivation(self):
        settings = Settings(llm_api_key="test-key", llm_base_url="http://test.local")
        service = StoryboardPanelDerivationService(settings)
        panels_data = [
            {
                "beat": "Opening",
                "composition": "Wide",
                "camera": "High angle",
                "subject_action": "Walk in",
                "continuity_from_previous": "First",
                "shot_type": "wide",
                "camera_move": "static",
                "duration_seconds": 4.0,
            },
        ]
        with patch("httpx.Client.post", return_value=self._mock_response(panels_data)):
            result = service.derive(script_text="A character walks into a room.")
        assert isinstance(result, DerivationResult)
        assert len(result.panels) == 1
        assert result.panels[0].beat == "Opening"
        assert result.panels[0].panel_index == 1
        assert result.warnings == ()

    def test_world_setting_included_in_prompt(self):
        settings = Settings(llm_api_key="test-key", llm_base_url="http://test.local")
        service = StoryboardPanelDerivationService(settings)
        captured_payload = {}

        def mock_post(url, headers, json):
            captured_payload["payload"] = json
            return self._mock_response([
                {"beat": "b", "composition": "c", "camera": "cam", "subject_action": "a", "continuity_from_previous": "cont"},
            ])

        with patch("httpx.Client.post", side_effect=mock_post):
            service.derive(
                script_text="test script",
                world_setting_summary="A cyberpunk city in 2087.",
            )
        user_content = captured_payload["payload"]["messages"][1]["content"]
        assert "World Setting" in user_content
        assert "cyberpunk city" in user_content

    def test_target_panel_count_in_prompt(self):
        settings = Settings(llm_api_key="test-key", llm_base_url="http://test.local")
        service = StoryboardPanelDerivationService(settings)
        captured_payload = {}

        def mock_post(url, headers, json):
            captured_payload["payload"] = json
            return self._mock_response([
                {"beat": "b", "composition": "c", "camera": "cam", "subject_action": "a", "continuity_from_previous": "cont"},
            ])

        with patch("httpx.Client.post", side_effect=mock_post):
            service.derive(script_text="test", target_panel_count=6)
        user_content = captured_payload["payload"]["messages"][1]["content"]
        assert "6 panels" in user_content
