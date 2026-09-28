"""Cross-shot 空间 / 动作状态 continuity — the two Continuity State rows that
no gate ever audited (V0.2 §5).

The research doc's Continuity State table (§5) lists seven state dimensions and
what the next shot does with each. Six of them are executable today
(人物 identity / 服装 / 道具 / 动作方向 / 情绪 / 镜头方向). Two rows had no
checker at all:

* ``空间`` — 夜晚街道 → 建筑入口, "保持空间方向逻辑";
* ``动作状态`` — 站立 → 转身 → 行走, "根据上一镜头的动作阶段继续".

This module is those two rows. It shares the family's shape and its one rule:
**advisory only, never blocking**, every finding carries a remedy, and a
finding that could not be fully judged says so in ``degraded`` instead of
implying a precision it does not have (engineering standard §4).

Where the numbers live (tree-verified, ``app/schemas/scene_script.py``):

* ``SceneShot`` carries ``id`` / ``camera`` / ``start_frame`` / ``end_frame`` /
  ``description`` / ``transition_intent`` — **no** ``entity_name``,
  ``position``, ``facing`` or motion-preset field. So "the previous shot's
  spatial anchor" cannot be a shot field; the anchor is the character's
  authored pose *inside* that shot (``CharacterKeyframe``: ``frame``,
  ``position``, ``rotation_y``, ``action``), plus the named space entities
  (``SceneEnvironmentObject``: ``id`` + ``position``) the pose sits in.
* The action phase is judged from ``CharacterKeyframe.action`` — one of
  ``stand`` / ``talk`` / ``walk`` / ``sit`` / ``gesture``. There is no
  ``turning`` literal: a turn is a ``rotation_y`` sweep across the shot's
  keyframes (the front-end ``turn_to`` preset writes exactly that ramp and
  clobbers the action on purpose).

Two tolerances are inherited from ``blocking_continuity`` on purpose rather
than re-invented: ``POSITION_JUMP_TOLERANCE_M`` and ``WALK_SPEED_MPS`` price
the same physical fact ("how far could the character have got"), and two rows
of one state table disagreeing about that would be worse than either number
alone.

Severity is ``warning`` for a break and ``info`` for a degradation: both are
published, neither blocks a render.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.schemas.scene_script import (
    CharacterKeyframe,
    SceneCharacter,
    SceneScriptRoot,
    SceneShot,
)
from app.services.scene3d.blocking_continuity import (
    POSITION_JUMP_TOLERANCE_M,
    WALK_SPEED_MPS,
    yaw_delta_degrees,
)

SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

#: Re-exported for parity/tests: the space row prices a gap with the SAME
#: budget as the motion row (walking speed × gap + slack), imported so the two
#: rows of one state table cannot drift apart on one physical fact.
SPATIAL_JUMP_TOLERANCE_M = POSITION_JUMP_TOLERANCE_M

# How far a pose may sit from a named environment object and still be "at" it.
# A street corner and the door in it are one continuous space; a jump to a
# different named entity is a different place (m).
SPACE_ANCHOR_LABEL_RADIUS_M = 8.0

# Ground-plane travel that still counts as "going somewhere" (m). Half of the
# position-jump slack: two authored poses closer than that are one re-block,
# not a heading, so there is no direction to preserve.
DIRECTION_TRAVEL_MIN_M = 0.15

# A course change beyond this across a cut reads as going the other way. The
# facing-flip threshold (90°) is about the BODY; this is about the PATH — a
# character may turn to face a new way while still travelling the old one.
DIRECTION_REVERSAL_DEGREES = 120.0

# Rotation swept inside one shot that reads as a turn phase (degrees). Below it
# the sweep is facing polish (a ``turn_to`` that barely turned), not a phase.
TURN_SWEEP_DEGREES = 30.0

#: The named degradation, verbatim where the task requires it. SceneScript does
#: not persist a motion-preset id (the presets only write keyframes), so a
#: phase inferred from geometry is inference — and says so.
DEGRADED_PRESET_ONLY = (
    "degraded: can only infer from motion preset name — SceneScript 不持久化预设 id，"
    "动作阶段只能由 CharacterKeyframe.action 与 rotation_y 渐变反推"
)

_HEADING_NAMES = ("前", "右前", "右", "右后", "后", "左后", "左", "左前")


@dataclass(frozen=True)
class SpatialActionFinding:
    """One finding about the 空间 or 动作状态 row across a cut.

    Self-contained on purpose (same reason as ``HeldItemFinding``): the
    executor maps these onto its own published report, so this module cannot
    import a gate type back. ``degraded`` is None when the check could judge
    everything it claims — a non-None value means PART of the message is
    inference, and the string names which part.
    """

    code: str
    severity: str
    subject: str
    boundary: str
    message: str
    remedy: str
    degraded: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "severity": self.severity,
            "subject": self.subject,
            "boundary": self.boundary,
            "message": self.message,
            "remedy": self.remedy,
        }
        if self.degraded is not None:
            payload["degraded"] = self.degraded
        return payload


# ---------------------------------------------------------------------------
# Pose helpers — the family's shared arithmetic, duplicated like held_items.py
# duplicates blocking_continuity's. The thresholds are imported (above) so the
# numbers cannot diverge even though the 15 lines do.
# ---------------------------------------------------------------------------


def _pose_at(character: SceneCharacter, frame: int) -> tuple[list[float], float]:
    """The character's pose at ``frame`` (nearest-keyframe semantics, matching
    the front-end ``characterStateAtFrame`` — clamps outside the authored
    range, interpolates between two authored keys)."""

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


def _action_at(character: SceneCharacter, frame: int) -> str | None:
    """The action governing ``frame`` (a keyframe's action governs frames AT and
    AFTER it — the front-end's forward-hold, so an unauthored stretch holds the
    last declared action)."""

    current: str | None = None
    for keyframe in sorted(character.keyframes, key=lambda kf: kf.frame):
        if keyframe.frame > frame:
            break
        current = keyframe.action
    return current


def _keyframes_within(character: SceneCharacter, shot: SceneShot) -> list[CharacterKeyframe]:
    """The keyframes authored INSIDE this shot — the shot's own contribution to
    the character's track (what the author decided while cutting this shot)."""

    return sorted(
        (
            keyframe
            for keyframe in character.keyframes
            if shot.start_frame <= keyframe.frame <= shot.end_frame
        ),
        key=lambda keyframe: keyframe.frame,
    )


def _ground_delta(a: list[float], b: list[float]) -> tuple[float, float]:
    """Plan-view delta. SceneScript is Blender Z-up (x right, y forward), so the
    ground plane is x/y and a height difference is not a direction."""

    return b[0] - a[0], b[1] - a[1]


def _angle_between_degrees(ax: float, ay: float, bx: float, by: float) -> float | None:
    """Angle between two plan-view vectors; None when either is too short to
    have a direction at all."""

    magnitude_a = math.hypot(ax, ay)
    magnitude_b = math.hypot(bx, by)
    if magnitude_a < DIRECTION_TRAVEL_MIN_M or magnitude_b < DIRECTION_TRAVEL_MIN_M:
        return None
    cosine = (ax * bx + ay * by) / (magnitude_a * magnitude_b)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _heading_label(dx: float, dy: float) -> str:
    """8-wind label with 0° = +Y (SceneScript's facing convention)."""

    degrees = math.degrees(math.atan2(dx, dy)) % 360.0
    return _HEADING_NAMES[int((degrees + 22.5) // 45) % 8]


def _space_anchor_label(scene_script: SceneScriptRoot, position: list[float]) -> str | None:
    """The named space this pose sits in (nearest environment object), or None
    when the script declares no space entity within
    ``SPACE_ANCHOR_LABEL_RADIUS_M``."""

    best: tuple[float, str] | None = None
    for obj in scene_script.environment:
        distance = math.dist(obj.position[:2], position[:2])
        if distance > SPACE_ANCHOR_LABEL_RADIUS_M:
            continue
        candidate = (distance, obj.id)
        if best is None or candidate < best:
            best = candidate
    return None if best is None else best[1]


# ---------------------------------------------------------------------------
# Row 1 — 空间 (night street → building entrance: keep the direction logic)
# ---------------------------------------------------------------------------

_SPACE_REMEDY = (
    "在角色检查器里把「位置」/「朝向 (rotation_y °)」接回上一镜的落点，或用「动作预设」"
    "的 走到 (walk_to) / 转身面向 (turn_to) 把这段位移写成有意的走位；确实是有意的空间"
    "跳跃就把这一镜的 transition_intent 登记成 time_jump，让读法留下记录。"
)


def check_spatial_continuity(
    scene_script: SceneScriptRoot,
    prev_shot: SceneShot,
    next_shot: SceneShot,
) -> list[SpatialActionFinding]:
    """Notice a character's place or heading refusing to continue across a cut.

    Two reasons, one code (``spatial_direction_break``) because both are "the
    next shot did not continue this shot's space":

    1. a position jump past the walk budget the gap allows — the character is
       somewhere the previous shot's anchor does not reach (the place itself
       broke);
    2. a direction reversal — the character spent the whole previous shot
       heading one way and the cut puts them heading the opposite way, even
       when the distance is walkable (the heading broke).

    At most one finding per character per boundary: the break when there is
    one, otherwise the named degradation when the space could not be labelled.
    """

    fps = scene_script.scene.frame_rate if scene_script.scene.frame_rate > 0 else 30
    gap_seconds = max(0, next_shot.start_frame - prev_shot.end_frame) / fps
    budget = WALK_SPEED_MPS * gap_seconds + POSITION_JUMP_TOLERANCE_M
    boundary = f"{prev_shot.id}→{next_shot.id}"
    findings: list[SpatialActionFinding] = []

    for character in scene_script.characters:
        if not character.keyframes:
            # The schema requires at least one keyframe; without a pose there is
            # no place to compare, so this row simply has nothing to say.
            continue
        exit_position, _exit_yaw = _pose_at(character, prev_shot.end_frame)
        entry_position, _entry_yaw = _pose_at(character, next_shot.start_frame)
        distance = math.dist(entry_position, exit_position)
        label_exit = _space_anchor_label(scene_script, exit_position)
        label_entry = _space_anchor_label(scene_script, entry_position)

        if distance > budget:
            place_exit = f"「{label_exit}」" if label_exit else "（无名空间）"
            place_entry = f"「{label_entry}」" if label_entry else "（无名空间）"
            findings.append(
                SpatialActionFinding(
                    code="spatial_direction_break",
                    severity=SEVERITY_WARNING,
                    subject=character.id,
                    boundary=boundary,
                    message=(
                        f"角色「{character.id}」在 {prev_shot.id} 结尾的地点是 {place_exit}，"
                        f"到 {next_shot.id} 开头变成 {place_entry}：跨镜位移 "
                        f"{round(distance, 2)}m，而两镜只隔 {round(gap_seconds, 2)}s"
                        f"（步行预算 {round(budget, 2)}m）：空间断了。"
                    ),
                    remedy=_SPACE_REMEDY,
                    degraded=(
                        None
                        if (label_exit and label_entry)
                        else (
                            "degraded: 空间锚点无法命名 — 场景没有在角色首尾姿势 "
                            f"{SPACE_ANCHOR_LABEL_RADIUS_M}m 内声明环境物体，"
                            "只能给坐标，不能给地点名"
                        )
                    ),
                )
            )
            continue

        # A reversal needs the character to have actually gone somewhere inside
        # the previous shot (two authored poses, not one held keyframe).
        within = _keyframes_within(character, prev_shot)
        if len(within) >= 2:
            dx_in, dy_in = _ground_delta(within[0].position, within[-1].position)
            dx_out, dy_out = _ground_delta(exit_position, entry_position)
            reversal = _angle_between_degrees(dx_in, dy_in, dx_out, dy_out)
            if reversal is not None and reversal > DIRECTION_REVERSAL_DEGREES:
                findings.append(
                    SpatialActionFinding(
                        code="spatial_direction_break",
                        severity=SEVERITY_WARNING,
                        subject=character.id,
                        boundary=boundary,
                        message=(
                            f"角色「{character.id}」在 {prev_shot.id} 里整体朝"
                            f"{_heading_label(dx_in, dy_in)}移动（{within[0].frame}→"
                            f"{within[-1].frame} 帧走了 "
                            f"{round(math.hypot(dx_in, dy_in), 2)}m），到 {next_shot.id} 开头"
                            f"却落在反方向（夹角 {round(reversal, 2)}°）：方向没有接上。"
                        ),
                        remedy=_SPACE_REMEDY,
                        degraded=(
                            None
                            if (label_exit and label_entry)
                            else (
                                "degraded: 空间锚点无法命名 — 场景没有在角色首尾姿势 "
                                f"{SPACE_ANCHOR_LABEL_RADIUS_M}m 内声明环境物体，"
                                "只能给坐标，不能给地点名"
                            )
                        ),
                    )
                )
                continue

        # Nothing broke, but the space row still owes an answer when the script
        # declares spaces and this character lives in none of them.
        if scene_script.environment and (label_exit is None or label_entry is None):
            findings.append(
                SpatialActionFinding(
                    code="spatial_anchor_degraded",
                    severity=SEVERITY_INFO,
                    subject=character.id,
                    boundary=boundary,
                    message=(
                        f"场景声明了 {len(scene_script.environment)} 个环境物体，但角色"
                        f"「{character.id}」在 {prev_shot.id} 结尾/"
                        f"{next_shot.id} 开头的姿势不在其中任何一个 "
                        f"{SPACE_ANCHOR_LABEL_RADIUS_M}m 内：空间这一维没有被锚定。"
                    ),
                    remedy=(
                        "给这一镜的角色补一个落在环境物体附近的关键帧，或调整环境物体的"
                        "「位置」，让「夜晚街道 → 建筑入口」有可指认的地点。"
                    ),
                    degraded=(
                        "degraded: 空间锚点无法命名 — 只有坐标，没有地点名；"
                        "本维度的结论按坐标算，不按地点算"
                    ),
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Row 2 — 动作状态 (standing → turning → walking: continue the phase)
# ---------------------------------------------------------------------------

_STATIC_STAGES = frozenset({"stand"})


def _prev_action_phase(
    character: SceneCharacter,
    prev_shot: SceneShot,
) -> tuple[str, str | None]:
    """The phase the character carries OUT of ``prev_shot`` — whether a phase is
    still OPEN at the cut, not merely whether it happened during the shot.

    Returns one of ``walk`` / ``turn`` / ``other`` / ``absent`` plus the named
    degradation when the phase is inference:

    * ``walk`` — the EXIT keyframe's ``action == "walk"`` (the only field that
      says "walking"; the motion presets write it). A walk whose last authored
      keyframe is ``stand`` landed INSIDE the previous shot (``walk_to`` writes
      exactly that), so it is a finished phase, not an interrupted one.
    * ``turn`` — no such literal exists, so it is the ``rotation_y`` still
      sweeping on the shot's last segment: DEGRADED, and the finding says so.
    * ``other`` — the exit keyframe's own action (stand/talk/sit/gesture), or a
      walk/turn that already stopped: not a phase the next shot must continue.
    * ``absent`` — no keyframe inside the shot: the character is not in this
      shot, so there is nothing to continue (out of scope, not degraded).
    """

    within = _keyframes_within(character, prev_shot)
    if not within:
        return "absent", None
    if within[-1].action == "walk":
        return "walk", None
    if len(within) >= 2:
        final_sweep = yaw_delta_degrees(within[-2].rotation_y, within[-1].rotation_y)
        if final_sweep >= TURN_SWEEP_DEGREES:
            return "turn", DEGRADED_PRESET_ONLY
    return "other", None


def _next_stage(character: SceneCharacter, next_shot: SceneShot) -> tuple[str, str | None]:
    """How the next shot starts for this character: ``static`` / ``moving`` /
    ``other`` / ``unknown``, plus the degradation when the answer is held rather
    than authored."""

    within = _keyframes_within(character, next_shot)
    if within:
        if any(keyframe.action not in _STATIC_STAGES for keyframe in within):
            return "moving", None
        travel = math.dist(within[0].position[:2], within[-1].position[:2])
        if travel > DIRECTION_TRAVEL_MIN_M:
            return "moving", None
        return "static", None

    # No keyframe inside the next shot: the preview holds the last authored
    # pose forward. That is the preview's semantics, not proof the author
    # decided the character stands through the shot.
    held = _action_at(character, next_shot.start_frame)
    if held == "walk":
        return "unknown", (
            "degraded: can only infer from motion preset name — 下一镜没有该角色的关键帧，"
            "上一镜的 walk 是否被延续，SceneScript 里没有任何记录（预设 id 不持久化）"
        )
    if held in (None, "stand"):
        return "static", (
            "degraded: 下一镜没有该角色的关键帧，「静止」由 held 姿势推断"
            "（预览语义），不是作者写在下一镜里的东西"
        )
    return "other", None


_ACTION_REMEDY = (
    "用「动作预设」的 走到 (walk_to) / 转身面向 (turn_to) 把动作接到下一镜，或在下一镜开头"
    "「捕获关键帧」后把该关键帧的 action 写成 walk；如果确实是走到门口站住，就忽略本条。"
)


def check_action_stage_continuity(
    scene_script: SceneScriptRoot,
    prev_shot: SceneShot,
    next_shot: SceneShot,
) -> list[SpatialActionFinding]:
    """Notice a walk/turn that was in flight at the cut and is gone after it.

    Judged from ``CharacterKeyframe.action`` for walking (the only field that
    says it) and from the ``rotation_y`` sweep for turning (there is no turning
    literal — that half is degraded by construction and says so in the
    finding). The next shot counts as standing still when every keyframe the
    author wrote inside it is ``stand`` and the character does not move.
    """

    boundary = f"{prev_shot.id}→{next_shot.id}"
    findings: list[SpatialActionFinding] = []

    for character in scene_script.characters:
        phase, phase_degraded = _prev_action_phase(character, prev_shot)
        if phase not in ("walk", "turn"):
            continue
        stage, stage_degraded = _next_stage(character, next_shot)
        if stage == "static":
            if phase == "walk":
                detail = (
                    f"角色「{character.id}」在 {prev_shot.id} 结尾仍在走"
                    "（最后一个关键帧的 action = walk），"
                )
            else:
                within = _keyframes_within(character, prev_shot)
                sweep = round(
                    sum(
                        yaw_delta_degrees(a.rotation_y, b.rotation_y)
                        for a, b in zip(within, within[1:])
                    ),
                    2,
                )
                detail = (
                    f"角色「{character.id}」在 {prev_shot.id} 结尾还在转（整镜转过 {sweep}°，"
                    "由关键帧 rotation_y 渐变算出），"
                )
            findings.append(
                SpatialActionFinding(
                    code="action_phase_interrupted",
                    severity=SEVERITY_WARNING,
                    subject=character.id,
                    boundary=boundary,
                    message=(
                        f"{detail}到 {next_shot.id} 开头变成站立不动："
                        "上一镜的动作阶段在剪切处断了。"
                    ),
                    remedy=_ACTION_REMEDY,
                    degraded=phase_degraded or stage_degraded,
                )
            )
            continue
        if stage == "unknown":
            findings.append(
                SpatialActionFinding(
                    code="action_phase_degraded",
                    severity=SEVERITY_INFO,
                    subject=character.id,
                    boundary=boundary,
                    message=(
                        f"角色「{character.id}」在 {prev_shot.id} 里的动作阶段没有在 "
                        f"{next_shot.id} 里被续写，也无法判断它是否被续写。"
                    ),
                    remedy=_ACTION_REMEDY,
                    degraded=stage_degraded,
                )
            )

    return findings


def check_spatial_action_continuity(
    scene_script: SceneScriptRoot,
) -> list[SpatialActionFinding]:
    """Both rows, every adjacent shot pair (the shape the executor publishes)."""

    shots: list[SceneShot] = sorted(scene_script.shots, key=lambda shot: shot.start_frame)
    findings: list[SpatialActionFinding] = []
    for prev_shot, next_shot in zip(shots, shots[1:]):
        findings.extend(check_spatial_continuity(scene_script, prev_shot, next_shot))
        findings.extend(check_action_stage_continuity(scene_script, prev_shot, next_shot))
    return findings
