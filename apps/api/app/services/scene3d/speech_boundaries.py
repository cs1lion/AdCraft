"""Speech ↔ cut geometry shared by the shot advisor and the proposals.

Two modules answer "what does the speech timeline say about this cut?":

* ``shot_advisor.py`` — where do the shot list and the speech timeline
  DISAGREE (advisories, never applied);
* ``transition_proposals.py`` — what could we DO about it (readings the
  creator picks, each mapped to executable operations).

Both need the same two primitives: "does this line cross that cut?" and
"where is the nearest pause that could hide a cut?". When those primitives
lived in each module separately, the two could drift — a proposal offered
for a cut the advisor never flags, or an advisory whose remedy no proposal
executes. This module is the single definition both import, so the wire
between "提醒" and "补救" is structural rather than a promise.
"""

from __future__ import annotations

from app.services.scene3d.speech_orchestration import SpeechSegment

# A gap this long (seconds) is a breath: enough to hide a cut in.
SPEECH_CUT_TARGET_SECONDS = 0.35

# Numerical slack so a line starting exactly on a frame boundary is not a
# "crossing" (frame-quantised timings land on the cut by rounding alone).
_EPSILON = 1e-6


def line_crosses_boundary(segment: SpeechSegment, boundary_seconds: float) -> bool:
    """True when the line starts before the boundary and ends after it.

    The line is being CUT MID-WORD: it begins on one side of the cut and
    finishes on the other. Per V0.2 §14.12/§14.13 that is often the RIGHT
    cut (an L-cut carries the voice over the new picture), so this predicate
    deliberately detects a FACT, not a defect — callers frame it.
    """

    return (
        segment.start_time < boundary_seconds - _EPSILON
        and segment.end_time > boundary_seconds + _EPSILON
    )


def first_line_crossing_boundary(
    segments: list[SpeechSegment],
    boundary_seconds: float,
) -> SpeechSegment | None:
    """The earliest line that crosses the boundary, or None."""

    ordered = sorted(segments, key=lambda segment: segment.start_time)
    return next(
        (segment for segment in ordered if line_crosses_boundary(segment, boundary_seconds)),
        None,
    )


def nearest_pause(
    segments: list[SpeechSegment],
    *,
    around_seconds: float,
    scene_duration: float,
) -> float | None:
    """The start of the closest silence long enough to hide a cut.

    Both the gap's opening and its (target-shifted) closing edge are
    candidates: cutting at the opening leaves the breath intact, cutting
    near the closing edge keeps the following line attached to its picture.
    Silence shorter than the target cannot carry a cut and is skipped —
    pause quality is a design element (V0.2 §14.12 留白), so a tiny gap is
    not a hiding place.
    """

    if not segments:
        return None
    ordered = sorted(segments, key=lambda segment: segment.start_time)
    best: float | None = None
    best_distance = float("inf")
    for index in range(len(ordered)):
        gap_start = ordered[index].end_time
        gap_end = (
            ordered[index + 1].start_time
            if index + 1 < len(ordered)
            else scene_duration
        )
        if gap_end - gap_start < SPEECH_CUT_TARGET_SECONDS:
            continue
        for candidate in (gap_start, gap_end - SPEECH_CUT_TARGET_SECONDS):
            if candidate < 0 or candidate > scene_duration:
                continue
            distance = abs(candidate - around_seconds)
            if distance < best_distance:
                best_distance = distance
                best = candidate
    return best
