"""Dialogue takes — 听法分叉 (V0.2 §14.13 "不仅能分叉镜头，也能分叉同一句
对白的语气、速度、停顿").

The research names the idea in one line: fork the SAME line's tone, speed
and pause into different emotional versions, then compare which one suits
the picture that follows. That is a different concept from
``director_takes`` (a labelled whole-SceneScript snapshot for "go back to
that version") and from ``transitionVariants`` (readings of one boundary):
here the unit is ONE dialogue line, and the fork is a *delivery delta*
rather than a snapshot. Hence its own module rather than a flag on either.

The design keeps the existing per-line direction (``DialogueLine.emotion``,
V0.2 §14.7 表演层) as the baseline and describes a fork as a DELTA against
it: ``tempo_delta`` (relative rate), ``pause_delta`` (seconds added to the
pause around the line) and an emotion override. A fourth fork — 就按稿 —
is the line exactly as authored, so the comparison always contains the
original instead of only the rewrites.

Everything here is PURE: one line in, N takes out, no provider, no clock.
The workbench mirrors it in ``dialogueTakes.ts`` (same catalogue, same
cap, same fail-closed reasons) so the panel can offer the fork without a
round trip; keep the two in lockstep.

Two rules inherited from the house style:

* **fail closed, queryable** — an unusable line (no text, or an emotion
  annotation that cannot survive being pasted into a TTS prompt) yields no
  takes and a named reason. ``plan_dialogue_takes`` raises
  :class:`DialogueTakeError` so a caller cannot mistake a refused line for
  "no forks yet"; surfaces that must degrade rather than crash call
  :func:`plan_dialogue_takes_with_report`, which returns the same reason
  alongside an empty list (ADR 0005: degradation must be named).
* **the cap is stated** — forks are for comparison, not version control,
  so at most :data:`MAX_DIALOGUE_TAKES` (the same magnitude as
  ``MAX_TRANSITION_VARIANTS`` / ``MAX_DIRECTOR_TAKES``; the number is
  restated here because a fork is a different object and must be able to
  change on its own evidence — the parity is locked by test). A caller
  asking for more gets the first N and a report naming what was trimmed.

STILL OPEN (honest record, not a claim): the fork's tempo/pause are the
authoring record and the panel's parameter summary; the lipsync service
still estimates every line from the single global
``syllables_per_second``. The emotion override IS load-bearing today (it
rides ``SpeechSegment.emotion`` into the emotion-continuity check), the
deltas are not yet read by the timeline — so the summary shows them as
deltas instead of pretending they already re-time the shot. Reason for
leaving it: re-timing is a service-level change with its own tests, and
this item is the per-line fork surface.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.services.dialogue.voice_cast_lines import (
    LINE_ID_PATTERN,
    MAX_LINE_CHARS,
    MAX_LINE_EMOTION_CHARS,
    DialogueLine,
)

#: How many forks one line offers. Same magnitude as the transition
#: variants' cap (``MAX_TRANSITION_VARIANTS``) and the director takes'
#: cap: a comparison wider than four stops being a comparison and becomes
#: a version history nobody watches. Restated locally (not imported) so a
#: dialogue fork can be capped on its own evidence.
MAX_DIALOGUE_TAKES = 4

#: The tempo a fork may resolve to. A line read at half speed is already a
#: different performance; past it the delta stops describing a reading of
#: the same words.
MIN_TAKE_TEMPO_RATE = 0.5
MAX_TAKE_TEMPO_RATE = 2.0

#: Characters that must not appear in an emotion annotation: the
#: annotation is pasted into the provider's prompt as "(emotion)", so a
#: parenthesis closes it early and a line break splits the line (the rule
#: ``step_audio_gen`` already enforces, mirrored here because a fork that
#: cannot be synthesised is worse than no fork).
_ANNOTATION_BREAKERS = re.compile(r"[()\n\r\t]")


class DialogueTakeError(ValueError):
    """A line that cannot be forked. Carries a machine-readable code.

    The reason is a sentence a creator can read; the code is what a
    surface can switch on. Both are always present: the failure names
    itself instead of relying on a caller to describe it.
    """

    def __init__(self, reason: str, *, code: str = "dialogue_take_invalid_line") -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


@dataclass(frozen=True, slots=True)
class DialogueTakeFork:
    """One reading of a line: the deltas to apply to the authored take."""

    id: str
    #: Creator-facing label (the deliverable the panel lists).
    label: str
    #: Relative tempo delta (e.g. -0.15 = 15% slower than authored).
    tempo_delta: float
    #: Seconds added to the pause around the line (may be negative).
    pause_delta: float
    #: Emotion override; empty = keep the line's own annotation.
    emotion: str
    #: One line on what the reading is FOR (shown under the label).
    note: str


#: The catalogue, in the order the panel lists it. The last entry is the
#: line as authored: a comparison that omits the original cannot be won.
DIALOGUE_TAKE_FORKS: tuple[DialogueTakeFork, ...] = (
    DialogueTakeFork(
        id="take_emotion_pressed",
        label="压下去",
        tempo_delta=-0.15,
        pause_delta=0.12,
        emotion="压低",
        note="更慢、停顿更长：把话按回心里，适合接特写或沉默。",
    ),
    DialogueTakeFork(
        id="take_emotion_lifted",
        label="提起来",
        tempo_delta=0.12,
        pause_delta=-0.08,
        emotion="轻快",
        note="更快、停顿更短：话赶着画面走，适合接动作或反打。",
    ),
    DialogueTakeFork(
        id="take_emotion_broken",
        label="顿一顿",
        tempo_delta=-0.05,
        pause_delta=0.22,
        emotion="紧绷",
        note="几乎同速，但句间停顿被拉长：说到一半咽回去。",
    ),
    DialogueTakeFork(
        id="take_emotion_authored",
        label="就按稿",
        tempo_delta=0.0,
        pause_delta=0.0,
        emotion="",
        note="照你写的来：用来对照，别让它从比较里消失。",
    ),
)

#: Every fork id — for validating a picked take and for the error message.
DIALOGUE_TAKE_FORK_IDS: tuple[str, ...] = tuple(fork.id for fork in DIALOGUE_TAKE_FORKS)

_FORKS_BY_ID: dict[str, DialogueTakeFork] = {fork.id: fork for fork in DIALOGUE_TAKE_FORKS}


@dataclass(frozen=True, slots=True)
class DialogueTake:
    """One planned fork of one line: a stable id, a label, and the deltas.

    ``emotion`` is the RESOLVED value — what the line will say about its
    own delivery once this fork is picked (the line's own annotation for
    the 就按稿 fork). ``line_id`` rides along so a take is always
    answerable to the line it came from.
    """

    id: str
    label: str
    tempo_delta: float
    pause_delta: float
    emotion: str
    line_id: str = ""
    #: True when the emotion is the line's own, not an override.
    inherits_emotion: bool = False

    @property
    def tempo_rate(self) -> float:
        """The absolute tempo this fork resolves to (1.0 = as authored)."""

        return _clamp(1.0 + self.tempo_delta, MIN_TAKE_TEMPO_RATE, MAX_TAKE_TEMPO_RATE)

    @property
    def summary(self) -> str:
        """The panel's parameter summary: label + what actually changes."""

        tempo = f"{round(self.tempo_delta * 100):+d}%"
        pause = f"{self.pause_delta:+.2f}s"
        emotion = self.emotion or "留空"
        if self.inherits_emotion and self.emotion:
            emotion = f"{emotion}（稿件原有）"
        return f"{self.label} · 语速 {tempo} · 停顿 {pause} · 语气：{emotion}"

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable entry (id/label/deltas plus the same summary)."""

        return {
            "id": self.id,
            "label": self.label,
            "tempo_delta": self.tempo_delta,
            "pause_delta": self.pause_delta,
            "emotion": self.emotion,
            "line_id": self.line_id,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class DialogueTakeParameters:
    """The absolute values a picked fork puts on a line."""

    tempo_rate: float
    pause_seconds: float
    emotion: str


@dataclass(frozen=True, slots=True)
class DialogueTakePlan:
    """The forks offered, plus the record of the cap and of a refusal.

    ``reason`` is None on success. When it is set, ``takes`` is empty: a
    line that cannot be forked offers nothing rather than a default the
    author never asked for.
    """

    takes: tuple[DialogueTake, ...] = ()
    reason: str | None = None
    #: The machine-readable code for ``reason`` (what a surface switches on).
    code: str | None = None
    #: What the caller asked for (the cap clamps it, visibly).
    requested_variants: int = MAX_DIALOGUE_TAKES
    #: Fork ids trimmed off the end by the cap, oldest first (empty while
    #: the catalogue is exactly :data:`MAX_DIALOGUE_TAKES` long).
    dropped_take_ids: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.reason is None

    @property
    def capped(self) -> bool:
        """True when the cap gave fewer forks than were asked for.

        The panel states the cap rather than letting a request for nine
        readings silently render four (engineering standard §4).
        """

        return self.requested_variants > len(self.takes)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _validated_line(line: Any) -> DialogueLine:
    """A usable ``DialogueLine``, or a raised :class:`DialogueTakeError`.

    Accepts a ``DialogueLine`` or a raw mapping (the panel's line is plain
    JSON on the way in), so the fork does not depend on which side built
    the object.
    """

    if isinstance(line, DialogueLine):
        candidate = line
    elif isinstance(line, Mapping):
        text = line.get("text")
        emotion = line.get("emotion")
        candidate = DialogueLine(
            line_id=str(line.get("line_id") or line.get("id") or "").strip(),
            text="" if text is None else text if isinstance(text, str) else str(text),
            emotion="" if emotion is None else emotion
            if isinstance(emotion, str)
            else str(emotion),
        )
    else:
        raise DialogueTakeError(
            f"这一行不是可分叉的台词行（收到了 {type(line).__name__}），已拒绝听法分叉。",
            code="dialogue_line_not_a_line",
        )
    return _checked(candidate)


def _checked(line: DialogueLine) -> DialogueLine:
    """Every rule that makes a line forkable. See the module docstring.

    The emotion rules are the ones the provider already enforces for an
    annotation (it lands inside its prompt); the text rule is the one
    thing a fork cannot live without — words to fork.
    """

    if not line.line_id:
        raise DialogueTakeError(
            "台词行没有 id：听法分叉要能指回是哪一句（逐行模式的 id 规则同样适用）。",
            code="dialogue_line_id_missing",
        )
    if not LINE_ID_PATTERN.match(line.line_id):
        raise DialogueTakeError(
            f"台词行 id「{line.line_id}」只能用字母数字与 -_ 且不超过 48 字符，已拒绝分叉。",
            code="dialogue_line_id_invalid",
        )
    if not line.text.strip():
        raise DialogueTakeError(
            f"「{line.line_id}」没有台词文本：分叉的是同一句话的语气，空句无可分叉。",
            code="dialogue_line_text_empty",
        )
    if len(line.text.strip()) > MAX_LINE_CHARS:
        raise DialogueTakeError(
            f"「{line.line_id}」的台词超过 {MAX_LINE_CHARS} 字符，已拒绝分叉"
            "（与逐行台词同一上限）。",
            code="dialogue_line_text_too_long",
        )
    if not isinstance(line.emotion, str):
        raise DialogueTakeError(
            f"「{line.line_id}」的情绪标注不是字符串，已拒绝分叉。",
            code="dialogue_line_emotion_not_string",
        )
    emotion = line.emotion.strip()
    if len(emotion) > MAX_LINE_EMOTION_CHARS:
        raise DialogueTakeError(
            f"「{line.line_id}」的情绪标注「{emotion}」超过 {MAX_LINE_EMOTION_CHARS} 字符，"
            "已拒绝分叉。",
            code="dialogue_line_emotion_too_long",
        )
    if _ANNOTATION_BREAKERS.search(emotion):
        raise DialogueTakeError(
            f"「{line.line_id}」的情绪标注「{emotion}」含括号或换行：它会拼进 TTS 的 "
            "(emotion) 标注里，provider 会把整句切开，已拒绝分叉。",
            code="dialogue_line_emotion_unbalanced",
        )
    return DialogueLine(line_id=line.line_id, text=line.text, emotion=emotion)


def plan_dialogue_takes_with_report(
    line: Any,
    variants: int = MAX_DIALOGUE_TAKES,
) -> DialogueTakePlan:
    """Plan the forks for one line without ever raising.

    The surface for a UI or an endpoint: an unusable line comes back as an
    empty plan plus a reason, so the degradation is named instead of the
    fork list quietly rendering as "nothing to compare".
    """

    try:
        validated = _validated_line(line)
    except DialogueTakeError as error:
        return DialogueTakePlan(
            reason=error.reason, code=error.code, requested_variants=variants
        )
    if variants < 1:
        return DialogueTakePlan(
            reason=f"听法分叉数量至少为 1（收到了 {variants}），已拒绝分叉。",
            code="dialogue_take_variants_below_one",
            requested_variants=variants,
        )
    forks = DIALOGUE_TAKE_FORKS[: min(variants, MAX_DIALOGUE_TAKES)]
    # Only the CAP drops forks. Asking for two of four is a choice, not an
    # eviction, so nothing is reported as dropped until the catalogue is
    # longer than the cap itself.
    dropped = tuple(fork.id for fork in DIALOGUE_TAKE_FORKS[MAX_DIALOGUE_TAKES:])
    return DialogueTakePlan(
        takes=tuple(_take_from_fork(fork, validated) for fork in forks),
        reason=None,
        requested_variants=variants,
        dropped_take_ids=dropped,
    )


def plan_dialogue_takes(line: Any, variants: int = MAX_DIALOGUE_TAKES) -> list[DialogueTake]:
    """The forks of one line, as a list. Raises on an unusable line.

    Fail closed: a caller cannot mistake a refused line for "no forks
    yet". Prefer :func:`plan_dialogue_takes_with_report` wherever a
    creator is on the other side of the result.
    """

    plan = plan_dialogue_takes_with_report(line, variants)
    if plan.reason is not None:
        raise DialogueTakeError(plan.reason, code=plan.code or "dialogue_take_invalid_line")
    return list(plan.takes)


def _take_from_fork(fork: DialogueTakeFork, line: DialogueLine) -> DialogueTake:
    inherits = not fork.emotion
    return DialogueTake(
        id=fork.id,
        label=fork.label,
        tempo_delta=fork.tempo_delta,
        pause_delta=fork.pause_delta,
        emotion=line.emotion if inherits else fork.emotion,
        line_id=line.line_id,
        inherits_emotion=inherits,
    )


def dialogue_take_fork(take: DialogueTake | str | DialogueTakeFork) -> DialogueTakeFork:
    """The catalogue fork behind a take, an id, or itself (fail closed)."""

    if isinstance(take, DialogueTakeFork):
        return take
    fork_id = take.id if isinstance(take, DialogueTake) else str(take)
    fork = _FORKS_BY_ID.get(fork_id.strip())
    if fork is None:
        raise DialogueTakeError(
            f"未知的听法分叉「{fork_id}」（可用：{'、'.join(DIALOGUE_TAKE_FORK_IDS)}）。",
            code="dialogue_take_unknown",
        )
    return fork


def resolve_dialogue_take(
    line: Any,
    take: DialogueTake | str | DialogueTakeFork,
    *,
    base_tempo_rate: float = 1.0,
    base_pause_seconds: float = 0.0,
) -> DialogueTakeParameters:
    """The absolute values a picked fork puts on a line.

    ``base_*`` are the line's current (or the timeline's measured) values;
    the fork's deltas are applied to them and then clamped, so a stack of
    forks cannot talk the tempo out of the readable range. An unknown fork
    id fails closed: applying a take nobody planned would keep the old
    parameters while claiming otherwise.
    """

    fork = dialogue_take_fork(take)
    validated = _validated_line(line)
    return DialogueTakeParameters(
        tempo_rate=_clamp(
            base_tempo_rate + fork.tempo_delta, MIN_TAKE_TEMPO_RATE, MAX_TAKE_TEMPO_RATE
        ),
        pause_seconds=max(0.0, round(base_pause_seconds + fork.pause_delta, 3)),
        emotion=validated.emotion if not fork.emotion else fork.emotion,
    )


def apply_dialogue_take(
    line: Any,
    take: DialogueTake | str | DialogueTakeFork,
    *,
    base_pause_seconds: float = 0.0,
) -> dict[str, Any]:
    """The patch a picked fork puts on the line, as the panel stores it.

    Shapes the patch for the existing per-line edit path (the same one the
    语气 input drives) instead of inventing a second line model.
    """

    fork = dialogue_take_fork(take)
    parameters = resolve_dialogue_take(
        line, fork, base_tempo_rate=1.0, base_pause_seconds=base_pause_seconds
    )
    return {
        "emotion": parameters.emotion,
        "tempo_delta": fork.tempo_delta,
        "pause_delta": fork.pause_delta,
    }
