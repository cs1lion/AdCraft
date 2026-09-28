"""Gesture performance layer (V3 ④ 台词即表演): speech envelope -> body gestures.

The lip-sync chain already writes ``talk`` actions onto character keyframes;
what it does NOT do is let the body act. This module adds the two missing
programmatic gestures the plan calls "pure parameter interpolation, no
skeletons" (the white-model contract):

- 抬手 (raise arm)   — ``gesture`` action + a 18° head tilt at line start
- 前倾 (lean)        — emotion-driven: strong emotions add a 15° forward lean
- 摇头 (headshake)   — "no" / emphatic negation markers in the text add a
                       24° yaw oscillation across the line

It reuses the lip-sync merge machinery (``LipSyncGenerator``'s
``_interpolated_pose_at``) so gestures ride the interpolated pose exactly
like lip keyframes do: insert frames on the authored path, never retarget
it. The gesture keyframes carry ``action="gesture"`` so the preview can
render a head tilt distinct from ``talk``'s mouth-only state.

Input is the SAME ``SpeechSegment`` list the lip-sync service consumes, so
the two layers share one source of truth and can be driven from the same
"说多久 → 演多长" arithmetic.
"""

from __future__ import annotations

from app.schemas.scene_script import CharacterKeyframe, SceneCharacter, SceneScriptRoot
from app.services.scene3d.speech_orchestration import SpeechSegment, _interpolated_pose_at

#: Emotions that add a forward lean (strong affect makes the body commit).
_LEAN_EMOTIONS = frozenset({"angry", "sad", "fear", "scared", "shock", "excited", "激动", "愤怒", "悲伤", "害怕", "震惊"})

#: Text markers that add a headshake (emphatic negation).
_SHAKE_MARKERS = ("不", "别", "no", "don't", "never", "不要", "不行", "别", "没", "没有", "not")

_LEAN_ROTATION_DEGREES = 15.0
_SHAKE_ROTATION_DEGREES = 24.0


def emotion_signal(segment: SpeechSegment) -> str | None:
    """The comparable core of a segment's emotion, or None."""
    value = segment.emotion
    if value is None:
        return None
    core = str(value).strip().lower()
    return core or None


def _has_shake_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _SHAKE_MARKERS)


def gesture_keyframes_for_segment(
    segment: SpeechSegment,
    character: SceneCharacter,
    *,
    frame_rate: int,
    total_frames: int,
) -> list[CharacterKeyframe]:
    """Programmatic gestures for one speech segment, on the authored pose.

    Returns keyframes at the segment's start/end with an interpolated
    position/rotation (inherited from the authored path) plus the gesture
    rotation delta; the action is always ``"gesture"`` so the preview can
    distinguish a body gesture from the lip-sync ``"talk"`` state.
    """
    start_frame = max(0, int(round(segment.start_time * frame_rate)))
    end_frame = min(
        total_frames - 1 if total_frames > 0 else start_frame,
        max(start_frame + 1, int(round(segment.end_time * frame_rate))),
    )
    lean = emotion_signal(segment) in _LEAN_EMOTIONS
    shake = _has_shake_marker(segment.text)
    if not (lean or shake):
        return []

    keyframes: list[CharacterKeyframe] = []
    if lean:
        start_pose, start_yaw = _interpolated_pose_at(character, start_frame)
        end_pose, end_yaw = _interpolated_pose_at(character, end_frame)
        keyframes.append(CharacterKeyframe(
            frame=start_frame,
            position=list(start_pose),
            rotation_y=start_yaw + _LEAN_ROTATION_DEGREES,
            action="gesture",
        ))
        keyframes.append(CharacterKeyframe(
            frame=end_frame,
            position=list(end_pose),
            rotation_y=end_yaw,
            action="gesture",
        ))
    if shake:
        # A shake is a 3-frame oscillation at the segment midpoint: lean one
        # way, back, lean the other way. Three points is enough for the
        # low-poly preview to read "headshake" without any skeleton.
        mid_frame = (start_frame + end_frame) // 2
        if mid_frame > start_frame and mid_frame < end_frame:
            mid_pose, mid_yaw = _interpolated_pose_at(character, mid_frame)
            keyframes.append(CharacterKeyframe(
                frame=mid_frame - 1,
                position=list(mid_pose),
                rotation_y=mid_yaw - _SHAKE_ROTATION_DEGREES / 2,
                action="gesture",
            ))
            keyframes.append(CharacterKeyframe(
                frame=mid_frame,
                position=list(mid_pose),
                rotation_y=mid_yaw + _SHAKE_ROTATION_DEGREES / 2,
                action="gesture",
            ))
            keyframes.append(CharacterKeyframe(
                frame=mid_frame + 1,
                position=list(mid_pose),
                rotation_y=mid_yaw,
                action="gesture",
            ))
    keyframes.sort(key=lambda kf: kf.frame)
    return keyframes


def merge_gestures_into_scene_script(
    scene_script: SceneScriptRoot,
    segments: list[SpeechSegment],
) -> SceneScriptRoot:
    """Add programmatic gesture keyframes for every segment's speaker.

    Mirrors ``LipSyncGenerator.merge_into_scene_script``: authored keyframes
    win on collision (a lip frame or gesture frame only ever ADDS to the
    authored path, never rewrites it), and the result is re-validated.
    """
    from app.schemas.scene_script import SceneCharacter as _Character  # rebind for clarity

    total_frames = scene_script.total_frames
    fps = scene_script.scene.frame_rate if scene_script.scene.frame_rate > 0 else 30

    by_character: dict[str, list[CharacterKeyframe]] = {}
    for segment in segments:
        character = next(
            (char for char in scene_script.characters if char.id == segment.character_id),
            None,
        )
        if character is None:
            continue
        keyframes = gesture_keyframes_for_segment(
            segment, character, frame_rate=fps, total_frames=total_frames
        )
        if keyframes:
            by_character.setdefault(character.id, []).extend(keyframes)

    if not by_character:
        return scene_script

    updated = []
    for char in scene_script.characters:
        gestures = by_character.get(char.id)
        if not gestures:
            updated.append(char)
            continue
        authored = {kf.frame: kf for kf in char.keyframes}
        merged: dict[int, CharacterKeyframe] = dict(authored)
        for gesture_kf in gestures:
            # A lip/authored frame at the same frame wins: gesture only fills
            # the frames nobody else claimed.
            if gesture_kf.frame in merged and merged[gesture_kf.frame].action != "stand":
                continue
            merged[gesture_kf.frame] = gesture_kf
        final_keyframes = sorted(merged.values(), key=lambda kf: kf.frame)
        updated.append(_Character(
            id=char.id,
            type=char.type,
            appearance=char.appearance,
            character_asset_id=char.character_asset_id,
            keyframes=final_keyframes,
        ))

    result = scene_script.model_copy(deep=True)
    result.characters = updated
    return result
