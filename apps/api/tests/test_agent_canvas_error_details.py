"""Structured error details for canvas Run admission and role validation.

ISSUE-08/ISSUE-11 (2026-09-19 E2E run): the canvas answered a refused Run with
a bare reason code and answered invalid structured content with an opaque
``invalid_role_content``. Both left the operator guessing which request field
to change and which nodes it applied to. ``_persistence_http_error`` already
forwards ``details``; these tests lock in the two raise sites that never filled
it in.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from app.services.agent_canvas_ad_media import (
    AdMediaDraftValidationService,
    AdMediaRoleRegistry,
)
from app.services.agent_canvas_runtime import _skip_error_details
from app.services.agent_canvas_execution_state import (
    MAX_NODE_ERROR_MESSAGE_CHARS,
    bounded_error_message,
    safe_execution_error,
)
from app.schemas.agent_canvas import CanvasNodeV2, CanvasNodeLatestAttemptV2
from app.services.v2_provider_error_classification import classify_provider_error


class _ProviderFailure(Exception):
    """A provider failure exactly as ``v2_provider_executor`` raises one."""

    def __init__(self, message: str, *, status: int) -> None:
        super().__init__(message)
        code, retryable = classify_provider_error(status_code=status)
        self.code = code
        self.details = {"retryable": retryable}


def _node(
    node_id: str = "node_image_1",
    *,
    status: str = "failed",
    latest_attempt_execution_id: str | None = None,
) -> CanvasNodeV2:
    now = datetime.now(timezone.utc)
    latest_attempt = None
    if latest_attempt_execution_id is not None:
        latest_attempt = CanvasNodeLatestAttemptV2(
            execution_id=latest_attempt_execution_id,
            member_id="member_1",
            status="failed",
            created_at=now,
        )
    return CanvasNodeV2(
        node_id=node_id,
        workflow_id="wf_details",
        node_type="image",
        creative_role="scene",
        title="details node",
        status=status,  # type: ignore[arg-type]
        latest_attempt=latest_attempt,
        # A ready node is one that already produced media, so the schema
        # refuses to model one without an asset id.
        output_asset_id="asset_details_1" if status == "ready" else None,
        position={"x": 0, "y": 0},
        revision=1,
        created_at=now,
        updated_at=now,
    )


class TestRunSkipDetails:
    """The 409 must name the field to change and the nodes it blocks."""

    def test_failed_node_retry_required_names_retry_failed(self) -> None:
        details = _skip_error_details("failed_node_retry_required", _node(status="failed"))
        assert details["missing_field"] == "retry_failed"
        assert details["expected_value"] is True
        assert details["node_ids"] == ["node_image_1"]

    def test_already_ready_names_node_ids(self) -> None:
        details = _skip_error_details("node_already_ready", _node(status="ready"))
        assert details["missing_field"] == "node_ids"
        assert details["node_status"] == "ready"

    def test_node_prompt_empty_names_generation_prompt(self) -> None:
        details = _skip_error_details("node_prompt_empty", _node(status="draft"))
        assert details["missing_field"] == "generation_prompt"
        assert "prompt_preparation_status" in details

    def test_unknown_reason_still_carries_node_ids(self) -> None:
        details = _skip_error_details("some_future_reason", _node())
        assert details == {"node_ids": ["node_image_1"]}


class TestStructuredContentDetails:
    """The 422 must name the Pydantic paths and the model to satisfy."""

    def _invalid(self, role: str, node_type: str, content: dict[str, object]) -> Any:
        service = AdMediaDraftValidationService()
        with pytest.raises(Exception) as excinfo:
            service.validate(
                node_type=node_type,
                semantic_role=role,
                structured_content=content,
            )
        return excinfo.value

    def test_storyboard_panels_report_validation_paths(self) -> None:
        error = self._invalid(
            "storyboard_sequence",
            "image",
            {"panels": [{"shot_index": "not-a-number"}]},
        )
        details = error.details
        assert details["content_schema_ref"] == "StoryboardGridContentV2"
        assert details["validation_paths"], "no validation path reported"
        assert any("panels" in path for path in details["validation_paths"])

    def test_bgm_role_gets_accurate_schema_ref(self) -> None:
        # Regression: every role that is not scene/storyboard fell through to
        # the shared ``invalid_role_content`` code, so the caller had no way to
        # learn which model to read. BGM now names its own.
        error = self._invalid("bgm", "audio", {"duration_seconds": -1})
        assert error.details["content_schema_ref"] == "BgmContentV2"
        assert error.code == "invalid_role_content"
        assert error.details["validation_paths"]

    def test_scene_role_keeps_specific_code(self) -> None:
        error = self._invalid("scene", "image", {"panels": []})
        assert error.code == "scene_design_board_contract_invalid"

    def test_valid_content_still_passes(self) -> None:
        service = AdMediaDraftValidationService()
        contract = service.validate(
            node_type="audio",
            semantic_role="bgm",
            structured_content={
                "music_summary": "Warm piano over a soft rain bed.",
                "duration_seconds": 12.0,
                "pace": "slow",
                "energy_curve": "gentle swell",
                "instrumentation": "felt piano",
                "mood": "tender",
                "instrumental_only": True,
                "no_vocals": True,
            },
        )
        assert contract.semantic_role == "bgm"


class TestNodeTypeMismatchDetails:
    def test_mismatch_names_both_node_types(self) -> None:
        registry = AdMediaRoleRegistry()
        with pytest.raises(Exception) as excinfo:
            registry.validate_node_type("video", "scene")
        details = excinfo.value.details
        assert details["semantic_role"] == "scene"
        assert details["expected_node_type"] == "image"
        assert details["received_node_type"] == "video"


class TestBoundedNodeErrorMessage:
    """A capped message must say it was capped.

    A provider failure embeds the whole request payload, so the 1024-character
    ceiling is hit routinely.  Cutting there with no marker left the stored
    message ending mid-JSON -- ``"watermark": fa`` -- which reads as a complete
    thought and sends the operator hunting for a tail that was never stored.
    That cost real time while diagnosing the 2026-09-21 image 503: the payload
    is where the size and the prompt length are visible, and it was exactly the
    part that got dropped.
    """

    def test_a_short_message_is_untouched(self) -> None:
        assert bounded_error_message(RuntimeError("boom"), fallback="Execution failed.") == "boom"

    def test_an_empty_message_falls_back(self) -> None:
        assert bounded_error_message(RuntimeError(""), fallback="Execution failed.") == (
            "Execution failed."
        )

    def test_a_long_message_stays_within_the_ceiling(self) -> None:
        message = bounded_error_message(RuntimeError("x" * 5000), fallback="fallback")
        assert len(message) <= MAX_NODE_ERROR_MESSAGE_CHARS

    def test_the_marker_names_the_real_length(self) -> None:
        message = bounded_error_message(RuntimeError("y" * 4321), fallback="fallback")
        assert message.endswith("... [truncated, 4321 chars total]")

    @pytest.mark.parametrize("total", [1025, 2048, 9999, 99999, 1234567])
    def test_the_marker_never_pushes_past_the_ceiling(self, total: int) -> None:
        """The total's digit count must not overflow the reserved space."""

        message = bounded_error_message(RuntimeError("z" * total), fallback="fallback")
        assert len(message) == MAX_NODE_ERROR_MESSAGE_CHARS

    def test_the_truncation_is_visible_in_a_projected_node_error(self) -> None:
        """End to end through the shape the provider executor actually raises.

        The executor classifies the status and attaches the code plus
        ``retryable`` itself; ``safe_execution_error`` only projects them.  So
        this pins both halves of the contract on one real failure: the marker
        survives, and the two-gate retry decision still comes out transient.
        """

        error = safe_execution_error(
            _ProviderFailure("p" * 4000, status=503),
            default_code="provider_request_failed",
        )
        assert "truncated" in error.message
        assert len(error.message) <= MAX_NODE_ERROR_MESSAGE_CHARS
        assert error.code == "provider_temporary_unavailable"
        assert error.retryable is True
