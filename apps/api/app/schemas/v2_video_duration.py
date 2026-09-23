"""What a video clip may ask the provider for, and what it is good at.

This module exists because the other answers were all wrong at once.  The
provider catalog publishes ``duration_range_seconds`` of ``[1, 15]`` for the
video capabilities (``provider_model_catalog._video_capability_metadata``),
the storyboard planner allowed 3-10s, and the prompt-contract schemas declared
``provider_duration_seconds: Literal[5, 10]``.  Only the first of those is what
the provider actually accepts, so a 7s or 8s shot -- the length every real
generation came back at -- was rejected by our own contract as invalid while a
20s or 25s shot could be requested and then trimmed by the executor.

The bounds here are the ones the provider states.  ``RELIABLE`` is not a
provider limit; it is where output quality stops being worth the quota, and it
is a measured number rather than a preference: the rose end-to-end cut asked
for beat grids of 6-8s per segment and every one of the 22 accepted segments
came back between 6.592s and 8.000s, while the 20/18/15/12/15/25s single-shot
previs durations that preceded them were unusable.

Kept in ``app/schemas`` so both the contract schemas and the services that fill
them can import one answer; services importing schemas is already the existing
direction of dependency, and schemas never import services.
"""

from __future__ import annotations


# The provider's own advertised range, in seconds (inclusive).
V2_VIDEO_PROVIDER_MIN_DURATION_SECONDS = 1
V2_VIDEO_PROVIDER_MAX_DURATION_SECONDS = 15

# Past this the clip stops being worth generating, even though the endpoint
# will accept it.  Ask for less, or cut the shot into more beats.
V2_VIDEO_RELIABLE_MAX_DURATION_SECONDS = 12

# What a clip should be asked for when the script does not say.
V2_VIDEO_TARGET_DURATION_SECONDS = 8

V2_VIDEO_PROVIDER_DURATION_RANGE_SECONDS: tuple[int, int] = (
    V2_VIDEO_PROVIDER_MIN_DURATION_SECONDS,
    V2_VIDEO_PROVIDER_MAX_DURATION_SECONDS,
)


def clamp_provider_duration_seconds(desired_duration_seconds: int) -> int:
    """Pull a requested clip length into the range the provider accepts.

    A clamp rather than a snap to one of two allowed values: a 7s shot stays 7s.
    Rounding an in-range request up to the nearest stock length is exactly what
    made the old ``{5, 10}`` contract lie about what it would accept.

    Per-model narrowing happens later and against the model's own declared
    ``duration_range_seconds`` (``agent_canvas_execution_parameters``), so this
    function only has to keep the request *possible*.
    """

    desired = int(desired_duration_seconds)
    if desired < V2_VIDEO_PROVIDER_MIN_DURATION_SECONDS:
        return V2_VIDEO_PROVIDER_MIN_DURATION_SECONDS
    if desired > V2_VIDEO_PROVIDER_MAX_DURATION_SECONDS:
        return V2_VIDEO_PROVIDER_MAX_DURATION_SECONDS
    return desired


def provider_duration_is_reliable(duration_seconds: int) -> bool:
    """Whether a clip length is one the provider is judged to handle well."""

    return 0 < int(duration_seconds) <= V2_VIDEO_RELIABLE_MAX_DURATION_SECONDS
