"""Cross-shot blocking continuity — the computable core of Continuity State.

V0.2 §5 names scene consistency a core problem and gives the exact failure:
"上一镜人物向右运动，下一镜突然向左，且没有叙事意图". Two shots that are each
fine can still fail the CUT.

This service compares, for every adjacent shot pair, each character's EXIT
pose (end of A) with their ENTRY pose (start of B):

* a FACING flip beyond a threshold — the character apparently turned around
  between two shots that share no turn;
* a POSITION jump farther than the character could have walked in the gap.

Advisory only, like every other check in this family: it never blocks, and
every finding carries the remedy (usually "author the move" — the motion
presets write it).

Parity module: `apps/web/src/features/agent-canvas/canvas/blockingContinuity.ts`
computes the same codes for the live workbench banner; keep them in lockstep.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.schemas.scene_script import SceneCharacter, SceneScriptRoot, SceneShot

# A turn larger than this across a cut reads as an unexplained reversal.
FACING_FLIP_THRESHOLD_DEGREES = 90
# Comfortable walking speed used to price a gap crossing (m/s).
WALK_SPEED_MPS = 1.2
# Slack for keyframe rounding and authored offsets before we call it a jump.
POSITION_JUMP_TOLERANCE_M = 0.35


def yaw_delta_degrees(from_degrees: float, to_degrees: float) -> float:
    """Shortest absolute angle between two yaws (0..180)."""

    delta = abs((to_degrees - from_degrees + 540) % 360 - 180)
    return 360 - delta if delta > 180 else delta


@dataclass(frozen=True, slots=True)
class BlockingContinuityIssue:
    code: str
    severity: str
    subject: str
    boundary: str
    message: str
    remedy: str

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "subject": self.subject,
            "boundary": self.boundary,
            "message": self.message,
            "remedy": self.remedy,
        }


def _pose_at(character: SceneCharacter, frame: int) -> tuple[list[float], float]:
    """The character's pose at `frame` (nearest-keyframe semantics, matching
    the frontend's characterStateAtFrame)."""

    keyframes = sorted(character.keyframes, key=lambda keyframe: keyframe.frame)
    if not keyframes:
        return [0.0, 0.0, 0.0], 0.0
    if frame <= keyframes[0].frame:
        first = keyframes[0]
        return list(first.position), float(first.rotation_y)
    last = keyframes[-1]
    if frame >= last.frame:
        return list(last.position), float(last.rotation_y)
    for index in range(len(keyframes) - 1):
        a = keyframes[index]
        b = keyframes[index + 1]
        if a.frame <= frame <= b.frame:
            span = b.frame - a.frame or 1
            t = (frame - a.frame) / span
            position = [
                a.position[0] + (b.position[0] - a.position[0]) * t,
                a.position[1] + (b.position[1] - a.position[1]) * t,
                a.position[2] + (b.position[2] - a.position[2]) * t,
            ]
            yaw = a.rotation_y + (b.rotation_y - a.rotation_y) * t
            return position, float(yaw)
    return list(last.position), float(last.rotation_y)


def check_blocking_continuity(script: SceneScriptRoot) -> list[BlockingContinuityIssue]:
    """Notice where a character's pose disagrees across a shot boundary."""

    shots: list[SceneShot] = sorted(script.shots, key=lambda shot: shot.start_frame)
    if len(shots) < 2:
        return []
    fps = script.scene.frame_rate if script.scene.frame_rate > 0 else 30
    issues: list[BlockingContinuityIssue] = []

    for shot_a, shot_b in zip(shots, shots[1:]):
        gap_seconds = max(0, shot_b.start_frame - shot_a.end_frame) / fps
        for character in script.characters:
            if not character.keyframes:
                continue
            exit_position, exit_yaw = _pose_at(character, shot_a.end_frame)
            entry_position, entry_yaw = _pose_at(character, shot_b.start_frame)

            flip = yaw_delta_degrees(exit_yaw, entry_yaw)
            if flip > FACING_FLIP_THRESHOLD_DEGREES:
                issues.append(
                    BlockingContinuityIssue(
                        code="facing_flip",
                        severity="warning",
                        subject=character.id,
                        boundary=f"{shot_a.id}→{shot_b.id}",
                        message=(
                            f"角色「{character.id}」在 {shot_a.id} 结尾朝 "
                            f"{round(exit_yaw, 2)}°，到 {shot_b.id} 开头变成 "
                            f"{round(entry_yaw, 2)}°（差 {round(flip, 2)}°），"
                            "两个镜头之间没有转身。"
                        ),
                        remedy=(
                            f"用「转身面向」预设在两镜之间补一段转身，或在 {shot_b.id} "
                            "开头捕获一个关键帧——让朝向变化成为有意的表演。"
                        ),
                    )
                )

            distance = math.dist(entry_position, exit_position)
            walkable = WALK_SPEED_MPS * gap_seconds + POSITION_JUMP_TOLERANCE_M
            if distance > walkable:
                issues.append(
                    BlockingContinuityIssue(
                        code="position_jump",
                        severity="warning",
                        subject=character.id,
                        boundary=f"{shot_a.id}→{shot_b.id}",
                        message=(
                            f"角色「{character.id}」在 {shot_a.id}→{shot_b.id} 之间移动了 "
                            f"{round(distance, 2)}m，而两镜只隔 {round(gap_seconds, 2)}s"
                            f"（步行约 {round(walkable, 2)}m）：位置跳变了。"
                        ),
                        remedy=(
                            "用「走到」预设在两镜之间补一段走位；如果这是有意的时空跳跃，"
                            "就用「时间/空间跳跃」衔接方案把剪切点放进停顿里。"
                        ),
                    )
                )

    return issues
