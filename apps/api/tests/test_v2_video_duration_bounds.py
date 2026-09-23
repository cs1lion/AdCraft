"""A clip length the provider accepts must be askable for.

The video prompt contracts declared ``provider_duration_seconds: Literal[5, 10]``
and the director snapped every requested duration onto one of those two values,
while ``provider_model_catalog._video_capability_metadata`` published
``duration_range_seconds`` of ``[1, 15]``.  Only the catalog is what the provider
accepts.  The cost of the mismatch was not theoretical: the rose end-to-end
cut asks for 6-8s per segment and every one of its 22 accepted segments came
back between 6.592s and 8.000s, so our own contract would have called the
delivered film invalid.

These tests pin three things: an in-range request keeps its own value rather
than being rounded onto a stock length, the range is the provider's, and a
duration the provider accepts is never turned into a plan failure -- a long beat
is a scripting decision, and rejecting it only buys LLM repair rounds against an
answer the provider never refused.

The mock plan's own beat grid is pinned here too, because it was the deepest
copy of the same fiction: ``_time_segments`` had one boundary set for 10s and one
for *everything else*, so every other duration produced a grid that still ended
at 5.0 and was then (correctly) rejected by the quality gate.
"""

from __future__ import annotations

import pydantic
import pytest

from app.schemas.v2_video_duration import (
    V2_VIDEO_PROVIDER_MAX_DURATION_SECONDS,
    V2_VIDEO_RELIABLE_MAX_DURATION_SECONDS,
    clamp_provider_duration_seconds,
    provider_duration_is_reliable,
)
from app.schemas.workflow_v2_storyboard_detail import (
    V2StoryboardDetailInput,
    V2StoryboardDetailPlan,
    V2StoryboardVideoDetailPlan,
)
from app.services.v2_storyboard_detail_materializer import (
    V2StoryboardDetailMaterializer,
    _time_segments,
)
from app.services.v2_storyboard_director import normalize_provider_duration
from app.services.v2_storyboard_detail_quality import (
    V2StoryboardDetailQualityService,
)


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        (1, 1),
        (5, 5),
        (7, 7),
        (8, 8),
        (10, 10),
        (12, 12),
        (15, 15),
        # past the provider's range: pulled in, not silently sent and rejected
        (20, V2_VIDEO_PROVIDER_MAX_DURATION_SECONDS),
        (25, V2_VIDEO_PROVIDER_MAX_DURATION_SECONDS),
        # below it: at least one second
        (0, 1),
        (-4, 1),
    ],
)
def test_provider_duration_is_clamped_not_snapped(requested: int, expected: int) -> None:
    assert clamp_provider_duration_seconds(requested) == expected


def test_an_in_range_duration_keeps_its_own_value() -> None:
    """The bug this module exists for: 7 used to come back as 10."""

    for requested in (6, 7, 8, 9):
        assert normalize_provider_duration(requested) == requested


def test_reliability_is_measured_not_a_preference() -> None:
    assert provider_duration_is_reliable(V2_VIDEO_RELIABLE_MAX_DURATION_SECONDS)
    assert provider_duration_is_reliable(8)
    assert not provider_duration_is_reliable(V2_VIDEO_RELIABLE_MAX_DURATION_SECONDS + 1)
    assert not provider_duration_is_reliable(0)


def _cell(index: int, role: str) -> dict:
    return {
        "slot_type": f"shot_cell_{index}",
        "cell_index": index,
        "cell_role": role,
        "provider_prompt": f"Cell {index}.",
        "continuity_notes": f"Continues from cell {index - 1}." if index > 1 else "Opening framing.",
    }


_ROLES = ("establishing", "action", "detail", "payoff")


def _detail_plan(duration: int) -> V2StoryboardDetailPlan:
    return V2StoryboardDetailPlan(
        shot_id="shot-1",
        shot_index=1,
        shot_summary_prompt="A product beat.",
        provider_duration_seconds=duration,
        desired_duration_seconds=duration,
        cell_prompts=[_cell(index, role) for index, role in enumerate(_ROLES, start=1)],
        video_detail=V2StoryboardVideoDetailPlan(
            provider_prompt="Render this beat.",
            storyboard_content="Four ordered cells.",
            dialogue="No dialogue.",
            audio_description="Room tone.",
            voice_style="None.",
            video_negative_constraints="No text overlays.",
            time_segments=[{
                "start_seconds": 0.0,
                "end_seconds": float(duration),
                "content": "Close hero camera as the action establishes the beat.",
            }],
            desired_duration_seconds=duration,
            provider_duration_seconds=duration,
        ),
        reference_item_ids=[],
        reference_asset_ids=[],
        materializer_mode="mock",
        model_id=None,
        materializer_version="test",
    )


def _input(duration: int) -> V2StoryboardDetailInput:
    return V2StoryboardDetailInput(
        workflow_id="workflow-1",
        shot_id="shot-1",
        shot_index=1,
        shot_summary_prompt="A product beat.",
        script_shot={"narration": "No dialogue."},
        workflow_aspect_ratio="16:9",
        desired_duration_seconds=duration,
        provider_duration_seconds=duration,
    )


@pytest.mark.parametrize("duration", [1, 5, 6, 7, 8, 10, 12, 15])
def test_every_duration_in_the_provider_range_passes_the_gate(duration: int) -> None:
    result = V2StoryboardDetailQualityService().evaluate_plan(
        _detail_plan(duration), input_data=_input(duration)
    )

    assert "video_uses_supported_duration" not in result.failure_codes


@pytest.mark.parametrize("duration", [0, 16, 20, 25])
def test_a_duration_outside_the_provider_range_fails_the_gate(duration: int) -> None:
    with pytest.raises(pydantic.ValidationError):
        _detail_plan(duration)


def test_a_long_but_accepted_beat_warns_without_failing() -> None:
    """Past the reliable ceiling is worth saying out loud, not worth rejecting.

    13s is still inside what the provider accepts, so it is a plan the gate has
    to let through -- it just has to say the clip will not render well, which is
    the difference between a 13s beat and the 25s single-shot previs this repo
    produced before the beat grids were cut.
    """

    result = V2StoryboardDetailQualityService().evaluate_plan(
        _detail_plan(13), input_data=_input(13)
    )

    assert "video_uses_supported_duration" not in result.failure_codes
    assert [warning["code"] for warning in result.warnings] == [
        "video_duration_beyond_reliable_range"
    ]
    assert "13" in result.warnings[0]["message"]


def test_a_reliable_duration_adds_no_warning() -> None:
    result = V2StoryboardDetailQualityService().evaluate_plan(
        _detail_plan(8), input_data=_input(8)
    )

    assert result.warnings == []


@pytest.mark.parametrize("duration", [1, 2, 5, 6, 7, 8, 10, 12, 13, 15])
def test_the_beat_grid_ends_at_the_clips_own_length(duration: int) -> None:
    """A grid that ends at 5.0 fails its own quality gate for any other length."""

    segments = _time_segments(duration, "the product is revealed")

    assert len(segments) == 4
    assert segments[0].start_seconds == 0.0
    assert abs(segments[-1].end_seconds - float(duration)) <= 0.01
    # beats are contiguous and ordered, which the gate also checks
    for previous, segment in zip(segments, segments[1:], strict=False):
        assert abs(segment.start_seconds - previous.end_seconds) <= 0.01
        assert segment.end_seconds > segment.start_seconds


def test_the_mock_plan_passes_its_own_quality_gate_at_every_legal_length() -> None:
    """End-to-end on the shape that actually broke: 15s came back as a 5s grid."""

    for duration in (1, 5, 7, 8, 10, 12, 15):
        plan = V2StoryboardDetailMaterializer().deterministic_fallback(
            _input(duration), error_code="probe", error_message="probe"
        )
        result = V2StoryboardDetailQualityService().evaluate_plan(
            plan, input_data=_input(duration)
        )
        assert result.failure_codes == [], (duration, result.failure_codes)
