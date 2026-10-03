"""Replica ownership remains authoring-only; unknown model inputs still fail."""

from datetime import datetime, timezone

import pytest

from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_runtime import CanvasProviderModelCapabilityV2
from app.services.agent_canvas_execution_parameters import _manual_parameters
from app.services.agent_canvas_provider_capabilities import _parameters_compatible
from app.services.agent_canvas_video_parameter_compiler import _compilation_plan

pytestmark = pytest.mark.integration


def node(**parameters):
    now = datetime.now(timezone.utc)
    return CanvasNodeV2(
        node_id="shot",
        workflow_id="acceptance",
        node_type="video",
        creative_role="general_video",
        title="replica shot",
        status="draft",
        generation_prompt="A slow camera move.",
        model_selection_mode="explicit",
        model_ref="volcengine_ark:agnes-video-2.5-flash",
        parameters=parameters,
        position={"x": 0, "y": 0},
        revision=1,
        created_at=now,
        updated_at=now,
    )


def capability():
    return CanvasProviderModelCapabilityV2(
        provider="volcengine_ark",
        model_id="agnes-video-2.5-flash",
        output_type="video",
        accepted_input_types=frozenset({"text", "image"}),
        max_references=5,
        supported_parameters=frozenset(
            {"duration_seconds", "resolution", "aspect_ratio", "generate_audio"}
        ),
        supported_aspect_ratios=("16:9",),
        supported_resolutions=("720p",),
        duration_range_seconds=(4, 12),
        available=True,
    )


def test_replica_owner_does_not_disqualify_flash():
    assert _parameters_compatible(
        node(
            replica_node_id="blueprint", duration_seconds=4, resolution="720p", aspect_ratio="16:9"
        ),
        (),
        capability(),
    )


def test_unknown_parameter_still_disqualifies_flash():
    # Mutation: an arbitrary new parameter must not inherit the owner exemption.
    assert not _parameters_compatible(
        node(replica_node_id="blueprint", unknown_provider_switch=True), (), capability()
    )


def test_owner_never_reaches_provider_manual_parameters_or_compilation():
    shot = node(
        replica_node_id="blueprint", duration_seconds=4, resolution="720p", aspect_ratio="16:9"
    )
    parameters, provenance = _manual_parameters(shot)
    assert "replica_node_id" not in parameters
    assert "replica_node_id" not in provenance
    assert parameters["duration_seconds"] == 4
    plan = _compilation_plan(shot, (), capability())
    assert "replica_node_id" not in plan.trusted_parameters
    assert "replica_node_id" not in plan.unresolved_fields
    assert shot.parameters["replica_node_id"] == "blueprint"
