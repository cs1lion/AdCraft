"""Speech-driven shot advisories — "说多久 → 分镜多长" (dialogue-driven editing).

The pipeline already knows WHEN each line is spoken (the speech timeline the
lip-sync rides on) and WHERE the cuts are (the shot list). Nobody had put the
two together, so an author who writes four lines of dialogue still cuts by
hand and lands cuts mid-word.

This module is deliberately ADVISORY, like the scene consistency gate: it
never blocks, never rewrites the shot list, and every finding carries a
remedy. The author stays the editor; this is the dramagic-style "the machine
notices" layer. Four notices:

1. ``line_crosses_cut`` — a line starts in one shot and ends in the next:
   the cut lands mid-word (offered as a choice, not a defect). Its remedy
   is executable: the advisory carries ``proposal_ids`` naming the
   Transition Intent readings that do what the remedy says, so the front-end
   can jump straight from "提醒" to the picker for "补救" (V0.2 §15).
2. ``cross_talk_in_tight_shot`` — two characters overlap in a closeup or
   over-shoulder: a single-subject framing cannot hold two speakers.
3. ``line_crosses_cut`` — a shot boundary lands inside a line. Framed as a
   CHOICE (L-cut sound-bridge vs. cutting in the nearby pause), because a
   mid-line cut is often the right cut: the V0.2 research insists "声音先到"
   is first-class and warns against mechanical cut-on-line-end.
4. ``shot_without_speech`` — a shot carries almost no dialogue while others
   are speech-heavy (advisory only: B-roll and establishing shots are
   legitimate, which is exactly why this is a warning and not a rule).

The speech↔cut primitives (crossing predicate, nearest pause) live in
``speech_boundaries.py`` so this advisor and ``transition_proposals.py``
share one definition and can never disagree about what crosses a cut.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.scene_script import SceneShot
from app.services.scene3d.speech_boundaries import (
    line_crosses_boundary,
    nearest_pause,
)
from app.services.scene3d.speech_orchestration import SpeechSegment

# A shot whose speech coverage is below this share is flagged for review.
SPEECH_COVERAGE_FLOOR = 0.08
# Framings that assume a single subject.
TIGHT_SHOT_TYPES = {"closeup", "over_shoulder", "pov"}

# The transition-intent readings that resolve a line crossing the cut. The
# ids name real entries in transition_proposals.py, so the advisory's remedy
# has an executable landing: the front-end can jump straight to the picker
# for these readings (V0.2 §15: "把顾问接到 Transition Intent 提案").
SOUND_BRIDGE_PROPOSAL_IDS: tuple[str, ...] = ("sound_bridge", "cut_after_line", "time_jump")


@dataclass(frozen=True, slots=True)
class ShotAdvisory:
    """One advisory about the shot list, with the remedy attached."""

    code: str
    shot_id: str | None
    message: str
    remedy: str
    severity: str = "warning"
    time_start: float | None = None
    time_end: float | None = None
    # Transition Intent readings (ids) that execute this advisory's remedy.
    # Empty for advisories whose remedy is not a cut move.
    proposal_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "shot_id": self.shot_id,
            "message": self.message,
            "remedy": self.remedy,
            "severity": self.severity,
            "time_start": self.time_start,
            "time_end": self.time_end,
            "proposal_ids": list(self.proposal_ids),
        }


@dataclass(slots=True)
class _ShotWindow:
    shot: SceneShot
    start_seconds: float
    end_seconds: float
    speech_seconds: float = 0.0


def _shot_windows(
    shots: list[SceneShot],
    frame_rate: int,
) -> list[_ShotWindow]:
    fps = frame_rate if frame_rate > 0 else 30
    windows = [
        _ShotWindow(
            shot=shot,
            start_seconds=shot.start_frame / fps,
            end_seconds=shot.end_frame / fps,
        )
        for shot in shots
    ]
    return sorted(windows, key=lambda window: window.start_seconds)


def _overlap_seconds(
    segment: SpeechSegment,
    window: _ShotWindow,
) -> float:
    return max(0.0, min(segment.end_time, window.end_seconds) - max(segment.start_time, window.start_seconds))


def advise_shots_from_speech(
    *,
    shots: list[SceneShot],
    segments: list[SpeechSegment],
    frame_rate: int,
    scene_duration: float,
    shot_types: dict[str, str] | None = None,
) -> list[ShotAdvisory]:
    """Notice where the shot list and the speech timeline disagree.

    Advisories only: the caller decides what to do. Every finding says what
    is wrong and how to fix it.
    """

    if not shots or not segments or scene_duration <= 0:
        return []

    windows = _shot_windows(shots, frame_rate)
    advisories: list[ShotAdvisory] = []
    shot_types = shot_types or {}

    # 1. A line that spans a cut: the cut lands mid-word. Framed as a CHOICE,
    #    not a defect: per the V0.2 research (§14.12/§14.13) a mid-line cut is
    #    often RIGHT — an L-cut carries the voice over the new picture and
    #    "声音先到，画面后到" is a first-class transition. So the advisory
    #    states the fact, offers the deliberate sound-bridge reading, and
    #    gives the clean alternative (cut before the line, or extend the
    #    shot past it, or cut in the nearby pause).
    for segment in segments:
        for window in windows:
            if not (
                line_crosses_boundary(segment, window.end_seconds)
                and segment.start_time >= window.start_seconds - 1e-6
            ):
                continue
            gap = nearest_pause(
                segments, around_seconds=window.end_seconds, scene_duration=scene_duration
            )
            plays_over = (
                "有意保留就是 L-cut：声音跨过画面切换，常用于留住听者反应；"
                if segment.end_time > window.end_seconds
                else ""
            )
            advisories.append(
                ShotAdvisory(
                    code="line_crosses_cut",
                    shot_id=window.shot.id,
                    message=(
                        f"台词「{segment.text[:18]}」({segment.start_time:.1f}s–"
                        f"{segment.end_time:.1f}s) 跨过镜头 {window.shot.id} 的剪切点 "
                        f"{window.end_seconds:.1f}s：话音未落就切镜。"
                    ),
                    remedy=(
                        plays_over
                        + "不想这样就把剪切点移到 "
                        + (
                            f"{gap:.1f}s 附近的停顿里，"
                            if gap is not None
                            else f"{segment.start_time:.1f}s 之前，"
                        )
                        + f"或把镜头 {window.shot.id} 延伸到 {segment.end_time:.1f}s 之后。"
                    ),
                    time_start=segment.start_time,
                    time_end=segment.end_time,
                    proposal_ids=SOUND_BRIDGE_PROPOSAL_IDS,
                )
            )
            break

    # 2. Cross-talk inside a single-subject framing.
    for window in windows:
        camera_type = shot_types.get(window.shot.camera, "")
        if camera_type not in TIGHT_SHOT_TYPES:
            continue
        speaking = [
            segment
            for segment in segments
            if _overlap_seconds(segment, window) > 0.05
        ]
        overlapping = sorted(
            {segment.character_id for segment in speaking},
        )
        if len(overlapping) > 1:
            advisories.append(
                ShotAdvisory(
                    code="cross_talk_in_tight_shot",
                    shot_id=window.shot.id,
                    message=(
                        f"镜头 {window.shot.id}（{camera_type}）的时间窗里 "
                        f"{len(overlapping)} 个角色同时在说（{', '.join(overlapping)}）："
                        "单人构图装不下对话双方。"
                    ),
                    remedy="把这一段改成中景或全景，或拆成正反打。",
                    time_start=window.start_seconds,
                    time_end=window.end_seconds,
                )
            )

    # 3. A cut that lands inside a pause is GOOD — no advisory. Silence is a
    #    design element (V0.2 §14.12 留白), so the absence of a finding here
    #    is the compliment. The next check therefore looks at the inverse.

    # 4. A shot that carries almost no dialogue (advisory: B-roll is legal).
    speech_heavy = [
        window
        for window in windows
        if any(_overlap_seconds(segment, window) > 0.05 for segment in segments)
    ]
    if len(speech_heavy) >= 2:
        for window in windows:
            if window in speech_heavy:
                continue
            span = window.end_seconds - window.start_seconds
            if span <= 0:
                continue
            advisories.append(
                ShotAdvisory(
                    code="shot_without_speech",
                    shot_id=window.shot.id,
                    message=(
                        f"镜头 {window.shot.id}（{window.start_seconds:.1f}s–"
                        f"{window.end_seconds:.1f}s）没有任何台词。"
                    ),
                    remedy="空镜/过场可以保留；若它是叙事镜头，考虑缩短或并入相邻镜头。",
                    time_start=window.start_seconds,
                    time_end=window.end_seconds,
                )
            )

    return advisories
