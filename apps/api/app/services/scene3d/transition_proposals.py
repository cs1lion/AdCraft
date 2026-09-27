"""Transition Intent proposals — Scene A → Scene B 的衔接方案.

The V0.2 research (§4.2 / §13) names this the single most valuable thing to
dig into next: two individually good shots do not make a good CUT, so the
product should propose how to get from A to B and let the creator choose.

The division of labour mirrors the rest of the pipeline:

* THIS module decides — what transitions are possible here, why each reading
  works, and what each would concretely DO (an ordered operation list).
* The front-end EXECUTES — every operation maps onto an already-tested motion
  preset (cameraMotionPresets / characterMotionPresets), so applying a
  proposal is a mechanical replay, not a second implementation.

Proposals are advisory and never auto-applied: the creator keeps the chair
(V0.2 §6.3: LLM proposes, the creator chooses).

Six readings, in the order the picker shows them:

==================  ==========================================  ============
reading             what it says                                operations
==================  ==========================================  ============
continuous_motion   人物穿过空间，运动本身掩盖剪切                walk + orbit
gaze_closeup        切点前推到特写，下一镜同视线方向摇开          push_in + pan
sound_bridge        跨切是有意的：让声音先到，画面后到            none (L-cut)
cut_after_line      太快了——把切点推迟到这句说完                 boundary move
time_jump           切在台词停顿里，用沉默完成跳跃                boundary move
angle_switch        用一个明确的新机位告诉观众「换看法了」        two clicks
==================  ==========================================  ============

The speech-aware readings (sound_bridge / cut_after_line / time_jump) are
the executable landing of the shot advisor's ``line_crosses_cut`` remedy —
the crossing predicate and the pause finder are imported from
``speech_boundaries.py`` so the advisor can never name a remedy this
catalogue cannot execute (V0.2 §15: "把顾问接到 Transition Intent 提案").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.schemas.scene_script import SceneCamera, SceneCharacter, SceneShot
from app.services.scene3d.speech_boundaries import (
    first_line_crossing_boundary,
    nearest_pause,
)
from app.services.scene3d.speech_orchestration import SpeechSegment

OperationKind = Literal["camera_preset", "character_preset", "camera_place", "cut"]


@dataclass(frozen=True, slots=True)
class TransitionOperation:
    """One concrete step of a proposal: a preset the front-end can apply."""

    kind: OperationKind
    rationale: str
    preset_id: str | None = None
    camera_id: str | None = None
    character_id: str | None = None
    start_frame: int | None = None
    duration_frames: int | None = None
    at_seconds: float | None = None
    # The shot this operation moves (cut ops move their start boundary).
    shot_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "rationale": self.rationale,
            "preset_id": self.preset_id,
            "camera_id": self.camera_id,
            "character_id": self.character_id,
            "start_frame": self.start_frame,
            "duration_frames": self.duration_frames,
            "at_seconds": self.at_seconds,
            "shot_id": self.shot_id,
        }


@dataclass(frozen=True, slots=True)
class TransitionProposal:
    """One way to get from A to B, with its narrative reason and its cost."""

    id: str
    label: str
    narrative: str
    feasible: bool
    infeasible_reason: str | None = None
    operations: tuple[TransitionOperation, ...] = field(default_factory=tuple)
    # Where this reading came from: the rule catalogue ("rules") or a
    # validated LLM proposal ("llm"). The surface shows it so the author
    # always knows which readings the machine invented.
    origin: str = "rules"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "narrative": self.narrative,
            "feasible": self.feasible,
            "infeasible_reason": self.infeasible_reason,
            "operations": [operation.to_dict() for operation in self.operations],
            "origin": self.origin,
        }


def _anchor_character(
    characters: list[SceneCharacter],
) -> SceneCharacter | None:
    """The character the transition should move: the first with keyframes."""

    return next(
        (character for character in characters if character.keyframes),
        None,
    )


def audit_declared_intent(
    *,
    declared_id: str | None,
    proposals: list[TransitionProposal],
    shot_b_id: str,
) -> dict[str, object]:
    """Does the shot's DECLARED entry reading still hold (V0.2 §13 第 5 问)?

    Once the choice is recorded on the shot it becomes checkable — and it
    MUST be checked, because a declaration outlives the timeline it was made
    against: the author re-times the dialogue, moves the cut, or swaps which
    pair the panel is looking at, and the label keeps saying "声音桥" while
    the scene says otherwise. Nothing else in the product would notice.

    Three outcomes, all advisory:

    * nothing declared → ``holds`` is ``None`` (not a defect: a first shot
      has no entry, and some cuts are just cuts);
    * declared and still offered as feasible → ``holds`` is ``True`` with
      the reading's label;
    * declared but NOT currently feasible (or no longer in the catalogue for
      this pair) → ``holds`` is ``False`` with the reason and the remedy.

    Feasibility is read off the SAME proposals the picker shows, so the audit
    can never disagree with the picker about whether a reading is available.
    """

    trimmed = (declared_id or "").strip()
    if not trimmed:
        return {"declared": None, "holds": None, "label": None, "reason": None, "remedy": None}
    by_id = {proposal.id: proposal for proposal in proposals}
    proposal = by_id.get(trimmed)
    if proposal is None:
        return {
            "declared": trimmed,
            "holds": False,
            "label": trimmed,
            "reason": (
                f"镜头 {shot_b_id} 登记的入镜读法「{trimmed}」不在当前这一对的读法目录里"
                "（可能镜头顺序变了，或这条读法是 LLM 针对当时的上下文提的）。"
            ),
            "remedy": (
                "重新为这一对选一条读法并登记；或清空该镜头的入镜读法。"
            ),
        }
    if proposal.feasible:
        return {
            "declared": trimmed,
            "holds": True,
            "label": proposal.label,
            "reason": None,
            "remedy": None,
        }
    return {
        "declared": trimmed,
        "holds": False,
        "label": proposal.label,
        "reason": (
            f"登记的「{proposal.label}」在当前场景里不再成立："
            f"{proposal.infeasible_reason or '条件已变化'}。"
        ),
        "remedy": (
            "按当前场景改选一条可行的读法，或改动场景条件（例如给这条边界留出停顿）"
            "后再保留原登记。"
        ),
    }


def propose_transitions(
    *,
    shot_a: SceneShot,
    shot_b: SceneShot,
    characters: list[SceneCharacter],
    cameras: list[SceneCamera],
    segments: list[SpeechSegment],
    frame_rate: int,
    scene_duration: float,
    transition_frames: int = 45,
) -> list[TransitionProposal]:
    """Propose ways to get from shot A to shot B.

    Six readings (V0.2 §4.3 + §14.12/§14.13): A 连续运动 / B 视线特写切换 /
    声音桥（L-cut）/ 说完再切 / C 时间空间跳跃 / D 视角切换. Each is priced
    honestly: what it needs, and whether the scene can currently pay for it.
    """

    fps = frame_rate if frame_rate > 0 else 30
    boundary_seconds = shot_a.end_frame / fps
    anchor = _anchor_character(characters)
    outgoing_camera = next((camera for camera in cameras if camera.id == shot_a.camera), None)

    proposals: list[TransitionProposal] = []

    # --- A 连续运动：人物穿过空间，摄影机跟随 -------------------------------
    if anchor is None:
        proposals.append(
            TransitionProposal(
                id="continuous_motion",
                label="连续运动",
                narrative="人物从一个空间走到另一个空间，观众跟着身体穿过场景。",
                feasible=False,
                infeasible_reason="场景里还没有带关键帧的角色，无法编排走位。",
            )
        )
    else:
        proposals.append(
            TransitionProposal(
                id="continuous_motion",
                label="连续运动",
                narrative="人物从一个空间走到另一个空间，观众跟着身体穿过场景。",
                feasible=True,
                operations=(
                    TransitionOperation(
                        kind="character_preset",
                        preset_id="walk_to",
                        character_id=anchor.id,
                        start_frame=shot_a.start_frame,
                        duration_frames=transition_frames,
                        rationale="角色从 A 的构图走向 B 的主体，身体带过画面切换。",
                    ),
                    TransitionOperation(
                        kind="camera_preset",
                        preset_id="orbit_right",
                        camera_id=shot_a.camera,
                        start_frame=shot_a.start_frame,
                        duration_frames=transition_frames,
                        rationale="摄影机随人物环绕，运动本身掩盖剪切。",
                    ),
                ),
            )
        )

    # --- B 视线/特写切换：用注视把两个画面缝起来 ---------------------------
    if outgoing_camera is None:
        proposals.append(
            TransitionProposal(
                id="gaze_closeup",
                label="视线/特写切换",
                narrative="先看人的眼睛或手中物件，再切到相同视线方向的下一画面。",
                feasible=False,
                infeasible_reason=f"镜头 {shot_a.id} 的相机 {shot_a.camera} 不存在。",
            )
        )
    else:
        proposals.append(
            TransitionProposal(
                id="gaze_closeup",
                label="视线/特写切换",
                narrative="先看人的眼睛或手中物件，再切到相同视线方向的下一画面。",
                feasible=True,
                operations=(
                    TransitionOperation(
                        kind="camera_preset",
                        preset_id="push_in",
                        camera_id=shot_a.camera,
                        start_frame=shot_a.end_frame - transition_frames // 2,
                        duration_frames=max(1, transition_frames // 2),
                        rationale="切点前推近到特写，用注视点承接下一镜。",
                    ),
                    TransitionOperation(
                        kind="camera_preset",
                        preset_id="pan_right",
                        camera_id=shot_b.camera,
                        start_frame=shot_b.start_frame,
                        duration_frames=transition_frames // 2,
                        rationale="下一镜从相同视线方向摇开，揭示空间。",
                    ),
                ),
            )
        )

    # --- 声音桥（L-cut）：跨切是有意的，声音先到、画面后到 ---------------
    # The advisor's line_crosses_cut finding names this reading first: the
    # V0.2 research (§14.12/§14.13) makes "声音先到" first-class and warns
    # against mechanical cut-on-line-end, so "keep the cut" is a CHOICE the
    # picker must be able to express. Zero operations is the honest price:
    # nothing structural changes — the creator is confirming intent, and the
    # surface says so instead of pretending an edit happened.
    crossing = first_line_crossing_boundary(segments, boundary_seconds)
    if crossing is None:
        proposals.append(
            TransitionProposal(
                id="sound_bridge",
                label="声音桥（有意保留）",
                narrative="让声音跨过画面切换：话音未落就切镜，把反应留给新画面。",
                feasible=False,
                infeasible_reason=(
                    f"镜头 {shot_a.id}→{shot_b.id} 的剪切点上没有台词跨切，"
                    "没有需要声音桥承载的话音。"
                ),
            )
        )
    else:
        proposals.append(
            TransitionProposal(
                id="sound_bridge",
                label="声音桥（有意保留）",
                narrative="让声音跨过画面切换：话音未落就切镜，把反应留给新画面。",
                feasible=True,
                operations=(),
            )
        )

    # --- 说完再切：把切点推迟到这句结束（V0.2 §8.1「太快了」的正解）-----
    # "我想让这个动作完整一点" must not become a parameter the author tunes;
    # it becomes this reading: the cut moves to where the line ends.
    if crossing is None:
        proposals.append(
            TransitionProposal(
                id="cut_after_line",
                label="说完再切",
                narrative="把剪切点推迟到当前这句台词说完，让话音完整地落在一个画面里。",
                feasible=False,
                infeasible_reason=(
                    f"镜头 {shot_a.id}→{shot_b.id} 的剪切点上没有跨切的台词，无需推迟切点。"
                ),
            )
        )
    else:
        cut_after_seconds = crossing.end_time
        cut_after_frame = round(cut_after_seconds * fps)
        if cut_after_frame >= shot_b.end_frame:
            proposals.append(
                TransitionProposal(
                    id="cut_after_line",
                    label="说完再切",
                    narrative="把剪切点推迟到当前这句台词说完，让话音完整地落在一个画面里。",
                    feasible=False,
                    infeasible_reason=(
                        f"这句台词要到 {cut_after_seconds:.1f}s 才结束，"
                        f"而镜头 {shot_b.id} 在 {shot_b.end_frame / fps:.1f}s 就结束了："
                        "推迟切点会吃掉整个镜头。"
                    ),
                )
            )
        else:
            proposals.append(
                TransitionProposal(
                    id="cut_after_line",
                    label="说完再切",
                    narrative="把剪切点推迟到当前这句台词说完，让话音完整地落在一个画面里。",
                    feasible=True,
                    operations=(
                        TransitionOperation(
                            kind="cut",
                            at_seconds=round(cut_after_seconds, 3),
                            shot_id=shot_b.id,
                            rationale=(
                                f"把镜头 {shot_b.id} 的起点移到 {cut_after_seconds:.1f}s"
                                f"（台词「{crossing.text[:18]}」结束处），"
                                "让这句在上一个镜头里说完。"
                            ),
                        ),
                    ),
                )
            )

    # --- C 时间/空间跳跃：切在停顿里，靠静音完成转场 -----------------------
    pause = nearest_pause(
        segments, around_seconds=boundary_seconds, scene_duration=scene_duration
    )
    if pause is None:
        proposals.append(
            TransitionProposal(
                id="time_jump",
                label="时间/空间跳跃",
                narrative="话音停顿处硬切，用沉默完成时间或空间跳跃。",
                feasible=False,
                infeasible_reason="台词之间没有足够长的停顿，硬切会切断话音。",
            )
        )
    else:
        proposals.append(
            TransitionProposal(
                id="time_jump",
                label="时间/空间跳跃",
                narrative="话音停顿处硬切，用沉默完成时间或空间跳跃。",
                feasible=True,
                operations=(
                    TransitionOperation(
                        kind="cut",
                        at_seconds=round(pause, 3),
                        shot_id=shot_b.id,
                        rationale=f"把镜头 {shot_b.id} 的起点移到 {pause:.1f}s 的停顿里，留白承接跳跃。",
                    ),
                ),
            )
        )

    # --- D 视角切换：新机位直接换一个看法 ---------------------------------
    proposals.append(
        TransitionProposal(
            id="angle_switch",
            label="视角切换",
            narrative="不藏剪切：用一个明确的新机位告诉观众「换看法了」。",
            feasible=True,
            operations=(
                TransitionOperation(
                    kind="camera_place",
                    camera_id=shot_b.camera,
                    start_frame=shot_b.start_frame,
                    rationale=f"为镜头 {shot_b.id} 放置新机位（两次点击：机位 + 注视点）。",
                ),
            ),
        )
    )

    return proposals