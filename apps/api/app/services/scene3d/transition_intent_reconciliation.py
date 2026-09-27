"""Continuity State ↔ Transition Intent, reconciled (V0.2 §13 第 4 问).

The doc's next-round ask is to CONNECT the two halves that were built
separately:

* Continuity State answers "什么必须连续" — `blocking_continuity` notices a
  character's pose disagreeing across a cut (a facing flip, a position jump);
  `emotion_continuity` notices emotion whiplashing without a pause to excuse it;
* Transition Intent answers "什么发生改变" — the reading the author declared for
  how a shot enters (`SceneShot.transition_intent`).

Two findings on their own are ambiguous, and that ambiguity is the whole
problem: "这一镜人物突然转身" reads as a BUG when nobody said the turn was the
point, and reads as INTENT when the shot declares 时间跳跃. The reverse is
worse: a shot that declares 连续运动 while its keyframes flip the character
around is a declaration that lies, and nothing in either gate would notice —
they never look at each other.

So this module cross-references them. Two outcomes, and the difference between
them is the product:

* ``transition_intent_explains_continuity`` — a CHANGE reading
  (时间跳跃 / 视角切换) sits on a boundary where the continuity gate found
  something. The finding is not rescinded (the motion still happened) but it is
  no longer a question: the author already answered it.
* ``transition_intent_contradicts_continuity`` — a CONTINUITY reading
  (连续运动 / 视线特写) sits on the same boundary. The declaration promises one
  thing and the keyframes do another.

Advisory only, in the repo's usual voice: both name what to do, neither blocks
a render (engineering standard §4).
"""

from __future__ import annotations

from dataclasses import dataclass

# Readings that promise the character/staging stays recognisably the same.
CONTINUITY_READINGS = frozenset({"continuous_motion", "gaze_closeup"})

# Readings whose whole point is that something changes.
CHANGE_READINGS = frozenset({"time_jump", "angle_switch"})

_READING_LABELS = {
    "continuous_motion": "连续运动",
    "gaze_closeup": "视线特写",
    "sound_bridge": "声音桥",
    "cut_after_line": "说完再切",
    "time_jump": "时间跳跃",
    "angle_switch": "视角切换",
}


@dataclass(frozen=True)
class TransitionIntentNote:
    """One way a declared reading and the continuity findings agree/disagree."""

    code: str
    severity: str
    shot_id: str
    reading_id: str | None
    message: str
    remedy: str

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "shot_id": self.shot_id,
            "reading_id": self.reading_id,
            "message": self.message,
            "remedy": self.remedy,
        }


def _label(reading_id: str | None) -> str:
    if not reading_id:
        return "（未登记）"
    return _READING_LABELS.get(reading_id, reading_id)


def reconcile_transition_intents(
    *,
    shots: list[object],
    blocking_issues: list[object] | None = None,
    emotion_advisories: list[object] | None = None,
) -> list[TransitionIntentNote]:
    """Cross-reference each declared reading with the continuity findings.

    ``blocking_issues`` carry ``boundary`` as ``"{a}→{b}"`` and
    ``emotion_advisories`` carry ``shot_id``; both name the boundary they were
    found on, which is what makes the join possible without a second pass over
    the script.
    """

    ordered = sorted(shots, key=lambda shot: shot.start_frame)  # type: ignore[attr-defined]
    # boundary → (continuity code, human summary), so a note can quote what it
    # is explaining or contradicting.
    # (outgoing shot, incoming shot) → codes found there. The two gates name
    # the SAME boundary in two conventions: blocking writes ``"a→b"``, emotion
    # writes the shot the cut sits in (``a``, the outgoing one). Storing the
    # outgoing id in the first slot for both is what lets one join serve both.
    findings: dict[tuple[str, str], list[str]] = {}
    for issue in blocking_issues or []:
        code = str(getattr(issue, "code", "") or "continuity")
        findings.setdefault(
            _normalised_boundary(str(getattr(issue, "boundary", "") or "")), []
        ).append(code)
    for advisory in emotion_advisories or []:
        shot_id = str(getattr(advisory, "shot_id", "") or "")
        code = str(getattr(advisory, "code", "") or "continuity")
        findings.setdefault((shot_id, ""), []).append(code)

    notes: list[TransitionIntentNote] = []
    for index, shot in enumerate(ordered):
        reading = str(getattr(shot, "transition_intent", "") or "").strip()
        if not reading or index == 0:
            # Nothing declared, or the first shot (no entry boundary to
            # reconcile a reading against).
            continue
        previous = ordered[index - 1]
        on_boundary: list[str] = []
        for (from_id, to_id), codes in findings.items():
            if to_id == shot.id or from_id == previous.id:
                on_boundary.extend(codes)
        if not on_boundary:
            continue
        described = "、".join(sorted(set(on_boundary)))
        if reading in CHANGE_READINGS:
            notes.append(
                TransitionIntentNote(
                    code="transition_intent_explains_continuity",
                    severity="info",
                    shot_id=shot.id,
                    reading_id=reading,
                    message=(
                        f"{shot.id} 声明以「{_label(reading)}」接入，而这一镜边界上确有 "
                        f"{described}：变化是读法的一部分，不是连续性缺陷。"
                    ),
                    remedy="无需处理；若这不符合作者本意，改登记或改走位，两者应对得上。",
                )
            )
        elif reading in CONTINUITY_READINGS:
            notes.append(
                TransitionIntentNote(
                    code="transition_intent_contradicts_continuity",
                    severity="warning",
                    shot_id=shot.id,
                    reading_id=reading,
                    message=(
                        f"{shot.id} 声明以「{_label(reading)}」接入（承诺连续），"
                        f"但这一镜边界上有 {described}：登记与关键帧互相矛盾。"
                    ),
                    remedy=(
                        "要么把走位/情绪改回连续，要么把登记改成能解释这次变化的读法"
                        "（例如时间跳跃）。"
                    ),
                )
            )
    return notes


def _normalised_boundary(boundary: str) -> tuple[str, str]:
    """``"a→b"`` → ``("a", "b")``; anything else becomes ``("", "")``."""

    for separator in ("→", "->", "→"):
        if separator in boundary:
            left, right = boundary.split(separator, 1)
            return (left.strip(), right.strip())
    return ("", "")
