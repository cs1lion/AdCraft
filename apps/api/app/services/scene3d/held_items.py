"""Held items — the Continuity State prop dimension (V0.2 §5).

The research doc's exact failure example: "Scene 01 里女孩右手拿伞，Scene 02
变成左手；或者上一镜人物向右运动，下一镜突然向左，且没有叙事意图". The
facing/position half of that sentence is ``blocking_continuity.py``; the prop
half lives here.

A prop declared ``held_by`` a character **follows that character's hand** for
the whole scene, in the preview AND the Blender render (the parity module is
``apps/web/src/features/agent-canvas/canvas/heldItems.ts``). That makes the
classic failure structurally impossible instead of merely detectable: there is
one item, in one hand, for every shot — it cannot vanish at a cut and it
cannot switch hands, because those are not representable states anymore.

What remains checkable is the ways the DECLARATION can go wrong, and those are
advisory (the consistency gate's shape):

* ``held_item_hand_conflict`` — two props claim the same character+hand. Only
  one item fits a hand, so one of the claims is a lie the render will make
  visible (items overlapping in one hand).
* ``held_item_authored_position_far`` — the authored position is far from the
  holder's whole path. The follow will move the item, so the author should
  know the number they typed is a rest position, not where it renders.

The hand offset is deliberately simple and shared: right = facing rotated
-90 degrees (SceneScript yaw convention: 0 = facing +Y), lifted to chest
height. Preview and renderer both derive from it, so "in the hand" means the
same point in space on both surfaces.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.schemas.scene_script import (
    CharacterKeyframe,
    SceneCharacter,
    SceneProp,
    SceneScriptRoot,
)

# Horizontal distance from the character's centre to the carrying hand (m).
HAND_REACH_M = 0.32
# Hand height as a share of the character's authored height (chest level).
HAND_HEIGHT_RATIO = 0.72
# An authored position this far from the holder's entire path is a stale rest
# position, not a placement (m).
AUTHORED_POSITION_SLACK_M = 2.5


def hand_offset(rotation_y: float, side: str | None, height: float) -> list[float]:
    """The hand offset in SceneScript space for a character pose.

    ``rotation_y`` is degrees with 0 = facing +Y, so facing is
    ``(sin yaw, cos yaw)`` and the right hand is facing rotated by -90 degrees
    (``cos yaw, -sin yaw``). The left hand mirrors it.
    """

    yaw = math.radians(rotation_y)
    sign = -1.0 if side == "left" else 1.0
    return [
        sign * HAND_REACH_M * math.cos(yaw),
        -sign * HAND_REACH_M * math.sin(yaw),
        height * HAND_HEIGHT_RATIO,
    ]


def _pose_at(character: SceneCharacter, frame: int) -> tuple[list[float], float]:
    """Nearest-keyframe pose semantics, matching the frontend's
    ``characterStateAtFrame`` (step, not interpolate — SceneScript keyframes
    are poses, and the preview treats them as such)."""

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


def held_position_at_frame(
    prop: SceneProp,
    character: SceneCharacter,
    frame: int,
) -> list[float]:
    """Where a held prop sits at ``frame`` (the holder's hand)."""

    position, yaw = _pose_at(character, frame)
    offset = hand_offset(yaw, prop.held_side, character.appearance.height)
    return [
        position[0] + offset[0],
        position[1] + offset[1],
        position[2] + offset[2],
    ]


def held_keyframe_positions(
    prop: SceneProp,
    character: SceneCharacter,
) -> list[tuple[int, list[float]]]:
    """Hand positions at each of the holder's OWN keyframe frames.

    The converter writes these as the prop's keyframes: the item then rides
    the same pose track the character does (same frames, same interpolation
    basis), so preview and render agree at every authored pose.
    """

    ordered: list[CharacterKeyframe] = sorted(
        character.keyframes, key=lambda keyframe: keyframe.frame
    )
    return [
        (keyframe.frame, held_position_at_frame(prop, character, keyframe.frame))
        for keyframe in ordered
    ]


@dataclass(frozen=True)
class HeldItemFinding:
    """One finding about a held-item declaration.

    Self-contained on purpose: the consistency gate imports THIS module, so
    this module cannot import the gate's issue type back (a cycle). The gate
    maps findings onto its own issue dataclass.
    """

    code: str
    subject: str
    message: str
    remedy: str


def check_held_items(scene_script: SceneScriptRoot) -> list[HeldItemFinding]:
    """Notice where a held-item declaration cannot hold true."""

    issues: list[HeldItemFinding] = []
    held = [prop for prop in scene_script.props if prop.held_by]
    if not held:
        return issues

    by_character: dict[str, SceneCharacter] = {
        character.id: character for character in scene_script.characters
    }

    # 1. One item per hand: two claims on the same character+hand cannot both
    #    render (the items overlap in one hand).
    claims: dict[tuple[str, str], list[str]] = {}
    for prop in held:
        claims.setdefault((prop.held_by or "", prop.held_side or "right"), []).append(prop.id)
    for (character_id, side), prop_ids in sorted(claims.items()):
        if len(prop_ids) > 1:
            issues.append(
                HeldItemFinding(
                    code="held_item_hand_conflict",
                    subject=",".join(sorted(prop_ids)),
                    message=(
                        f"道具 {sorted(prop_ids)} 都声明由角色「{character_id}」的"
                        f"{'左' if side == 'left' else '右'}手持有：一只手放不下两件东西。"
                    ),
                    remedy="把其中一件改成另一只手，或取消它的持有者。",
                )
            )

    # 2. The authored position is only a rest position once the item follows:
    #    if it is far from the holder's whole path, the author should know the
    #    number they typed will not be where it renders.
    for prop in held:
        character = by_character.get(prop.held_by or "")
        if character is None:
            continue  # schema rejects this; defensive only
        distances = [
            math.dist(prop.position, position)
            for _, position in held_keyframe_positions(prop, character)
        ]
        if distances and min(distances) > AUTHORED_POSITION_SLACK_M:
            issues.append(
                HeldItemFinding(
                    code="held_item_authored_position_far",
                    subject=prop.id,
                    message=(
                        f"道具「{prop.id}」声明由角色「{character.id}」持有，但它的位置"
                        f"离该角色的全部关键帧至少 {round(min(distances), 2)}m："
                        "渲染将以角色手部为准，手写位置只是未持有时的地方。"
                    ),
                    remedy="如需固定摆放，取消它的持有者；确认持有则忽略此条。",
                )
            )

    return issues
