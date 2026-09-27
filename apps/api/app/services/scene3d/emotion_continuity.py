"""Emotion continuity — the Continuity State 情绪 dimension (V0.2 §5).

The research doc's Continuity State table lists 情绪 with the note "为下一镜头
提供状态基础": the emotion a character carries OUT of a shot is the state the
next shot starts from. A line's emotion is already data (``SpeechSegment.emotion``,
authored per dialogue line), but nothing read it against the cut — so a script
can flip 恐惧 → 喜悦 across a hard cut with no beat and no one notices.

This module asks the question, it does not answer it: an emotion whiplash is
often exactly right (a reveal, a rebuttal, a joke landing). The advisory fires
only when the whiplash has no pause to read as intentional — a silence long
enough to hide a cut is how a script says "time passed / mood turned". With one,
silence is doing the work; without one, the author should at least LOOK.

Advisory only, like every check in this family: never blocks, always carries a
remedy, and an absent finding is the compliment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.scene_script import SceneShot
from app.services.scene3d.speech_boundaries import SPEECH_CUT_TARGET_SECONDS
from app.services.scene3d.speech_orchestration import SpeechSegment

# Punctuation and case carry no emotion signal for this comparison.
_NOISE = re.compile(r"[\s，。！？、,.!?~—…·\"'\"'()（）]+")


def normalize_emotion(value: str | None) -> str:
    """The comparable core of an emotion tag (empty when there is none)."""

    if not value:
        return ""
    return _NOISE.sub("", value).lower()


@dataclass(frozen=True)
class EmotionAdvisory:
    """One finding about how emotion moves across a cut."""

    code: str
    shot_id: str | None
    message: str
    remedy: str
    time_start: float | None = None
    time_end: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "shot_id": self.shot_id,
            "message": self.message,
            "remedy": self.remedy,
            "time_start": self.time_start,
            "time_end": self.time_end,
        }


def _active_at(
    ordered_segments: list[SpeechSegment],
    at_seconds: float,
) -> SpeechSegment | None:
    """The line the audience hears at ``at_seconds`` (None in a silence)."""

    for segment in ordered_segments:
        if segment.start_time - 1e-6 <= at_seconds < segment.end_time + 1e-6:
            return segment
    return None


def check_emotion_continuity(
    *,
    shots: list[SceneShot],
    segments: list[SpeechSegment],
    frame_rate: int,
) -> list[EmotionAdvisory]:
    """Notice emotion that whiplashes across a cut with no pause to excuse it."""

    if not shots or not segments:
        return []
    fps = frame_rate if frame_rate > 0 else 30
    ordered_segments = sorted(segments, key=lambda segment: segment.start_time)
    ordered_shots = sorted(shots, key=lambda shot: shot.start_frame)
    advisories: list[EmotionAdvisory] = []

    for shot in ordered_shots:
        boundary_seconds = shot.end_frame / fps
        # What the audience hears on either side of the cut. A line that
        # STRADDLES the cut is heard on both sides — that is an L-cut, the
        # same emotion throughout, so the hand-off question never arises.
        incoming = _active_at(ordered_segments, boundary_seconds - 1e-3)
        if incoming is None:
            starting_before = [
                segment
                for segment in ordered_segments
                if segment.start_time < boundary_seconds - 1e-6
            ]
            incoming = starting_before[-1] if starting_before else None
        outgoing = _active_at(ordered_segments, boundary_seconds + 1e-3)
        if outgoing is None:
            starting_after = [
                segment
                for segment in ordered_segments
                if segment.start_time >= boundary_seconds - 1e-6
            ]
            outgoing = starting_after[0] if starting_after else None
        if incoming is None or outgoing is None or incoming is outgoing:
            continue
        emotion_in = normalize_emotion(incoming.emotion)
        emotion_out = normalize_emotion(outgoing.emotion)
        if not emotion_in or not emotion_out or emotion_in == emotion_out:
            continue
        # A pause long enough to hide a cut is how the script says "time
        # passed" — the whiplash then reads as intentional and no one asks.
        gap = outgoing.start_time - incoming.end_time
        if gap >= SPEECH_CUT_TARGET_SECONDS:
            continue
        advisories.append(
            EmotionAdvisory(
                code="emotion_whiplash",
                shot_id=shot.id,
                message=(
                    f"镜头 {shot.id} 的剪切点 {boundary_seconds:.1f}s 处情绪从"
                    f"「{incoming.emotion}」直接切到「{outgoing.emotion}」，"
                    f"两句之间只有 {gap:.2f}s：没有停顿替这个转折说话。"
                ),
                remedy=(
                    "有意的情绪转折（反转、揭晓）请忽略本条；否则在两句之间留出停顿，"
                    "或先给一个反应镜头，让情绪的变化被看见。"
                ),
                time_start=incoming.start_time,
                time_end=outgoing.end_time,
            )
        )

    return advisories
