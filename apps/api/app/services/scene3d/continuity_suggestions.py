"""Continuity chat suggestions — advisory reports as conversational hints.

V3 capability: the blocking/emotion continuity checks and the held-items
audit already run as advisory reports (``check_blocking_continuity``,
``check_emotion_continuity``, ``check_held_items``). They were surfaced
as a flat list in the pre-render gate. This module translates the same
findings into *conversational, actionable* suggestions the creator reads
in the chat/director side instead of scrolling a report.

The boundary mirrors the rest of the advisory family: **LLM never gains
executable authority; suggestions are advisory only.** Each suggestion
references the specific finding that motivated it so the creator can
decide, and every finding is reported with a named reason when the
translation cannot proceed (engineering standard §4 — no silent
fallbacks).

A suggestion is one of:
- ``question``: the creator confirms or corrects.
- ``note``: a heads-up the creator reads and acts on manually.
- ``remedy``: the check's own remedy, restated as a sentence.

All three ride the same ``ContinuitySuggestion`` shape; the caller
renders them in whatever channel (chat bubble, director status line,
pre-render report) the surface uses.

Degradation is queryable, not silent (engineering standard §4). Nothing
falls on the floor: a finding whose code the translator has not caught up
with, a rule that declares an unrenderable kind, and a check that raises
all land in ``untranslated`` tagged with the check that produced them, so
the surface can say *why* advice is missing instead of showing a
reassuring empty list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.services.scene3d.blocking_continuity import check_blocking_continuity
from app.services.scene3d.emotion_continuity import check_emotion_continuity
from app.services.scene3d.held_items import check_held_items

#: The suggestion kinds a rule may declare. A rule naming anything else
#: cannot be rendered by any surface, so it is reported as untranslated
#: instead of shipped as a suggestion nobody can display.
SUGGESTION_KINDS = frozenset({"question", "note", "remedy"})

#: Named reason recorded in ``untranslated`` when one of the underlying
#: checks itself raises. The advisory family never blocks, so a broken
#: check costs one check's advice — never the whole translation.
CONTINUITY_CHECK_FAILED = "continuity_check_failed"

#: Named reason recorded in ``untranslated`` when a rule exists for a code
#: but declares an unusable kind (or no message at all).
CONTINUITY_RULE_INVALID = "continuity_rule_invalid"


@dataclass(frozen=True, slots=True)
class ContinuitySuggestion:
    """One conversational suggestion derived from a continuity finding."""

    #: "question" | "note" | "remedy"
    kind: str
    #: The finding's stable code (e.g. "facing_flip", "emotion_whiplash").
    source_code: str
    #: The finding's original message (verbatim, for the detail view).
    detail: str
    #: The creator-facing conversational suggestion.
    message: str
    #: The subject ids this suggestion concerns.
    subjects: tuple[str, ...]
    #: Optional remedy text from the original finding.
    remedy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "kind": self.kind,
            "source_code": self.source_code,
            "detail": self.detail,
            "message": self.message,
            "subjects": list(self.subjects),
        }
        if self.remedy is not None:
            entry["remedy"] = self.remedy
        return entry


@dataclass(frozen=True, slots=True)
class _Finding:
    """One advisory finding, normalised across the three checks.

    The three checks hand back three different dataclasses; this is the
    shape the translator actually needs, so the recording loop is written
    once instead of three times.
    """

    code: str
    message: str
    remedy: str | None
    subjects: tuple[str, ...]


# ---------------------------------------------------------------------------
# Per-finding translation rules
# ---------------------------------------------------------------------------
# Each rule maps a finding code to a suggestion kind + a short hook. The
# original ``message`` (which carries the numbers) is preserved verbatim
# in ``detail``; the rule's ``message`` is the one-line conversational
# hook the chat surface leads with.

_BLOCKING_RULES: dict[str, dict[str, str]] = {
    "facing_flip": {
        "kind": "question",
        "message": "转身方向跨镜反了，是故意的吗？",
    },
    "position_jump": {
        "kind": "note",
        "message": "两镜之间位置跳变，检查一下走位关键帧。",
    },
}

_EMOTION_RULES: dict[str, dict[str, str]] = {
    "emotion_whiplash": {
        "kind": "question",
        "message": "两句台词之间情绪硬切，是反转还是漏了停顿？",
    },
}

_HELD_ITEM_RULES: dict[str, dict[str, str]] = {
    "held_item_hand_conflict": {
        "kind": "note",
        "message": "一只手放不下两件道具，调一下持有手。",
    },
    "held_item_authored_position_far": {
        "kind": "note",
        "message": "道具位置离角色太远，渲染以手部为准，确认持有则忽略。",
    },
}

#: Which check owns which rule table — stamped on every untranslated entry
#: so a surface can point at the party that fell behind.
_RULES_BY_CHECK: dict[str, dict[str, dict[str, str]]] = {
    "blocking": _BLOCKING_RULES,
    "emotion": _EMOTION_RULES,
    "held_items": _HELD_ITEM_RULES,
}


def _translate(
    rules: dict[str, dict[str, str]],
    finding: _Finding,
    check: str,
) -> tuple[ContinuitySuggestion | None, str | None]:
    """Build a suggestion for one finding, or explain why it cannot be built.

    Returns ``(suggestion, reason)``; at most one is not None. An unknown
    code is *not* silent: the caller surfaces it via the ``untranslated``
    list (it means the check grew a code this translator has not caught
    up with yet). A rule that declares an unrenderable kind is reported
    the same way, with a reason naming what is wrong with the rule.
    """
    rule = rules.get(finding.code)
    if rule is None:
        return None, None
    kind = str(rule.get("kind", ""))
    message = str(rule.get("message", "")).strip()
    if kind not in SUGGESTION_KINDS:
        return None, (
            f"{check} 的 code「{finding.code}」规则声明了无法渲染的 kind"
            f"「{kind}」（可用：{sorted(SUGGESTION_KINDS)}），已跳过该条建议。"
        )
    if not message:
        return None, f"{check} 的 code「{finding.code}」规则没有 message，已跳过该条建议。"
    return (
        ContinuitySuggestion(
            kind=kind,
            source_code=finding.code,
            detail=finding.message,
            message=message,
            subjects=finding.subjects,
            remedy=finding.remedy,
        ),
        None,
    )


def _record(
    suggestions: list[ContinuitySuggestion],
    untranslated: list[dict[str, str]],
    rules: dict[str, dict[str, str]],
    findings: list[_Finding],
    check: str,
) -> None:
    """Translate one check's findings into the two output lists."""
    for finding in findings:
        suggestion, reason = _translate(rules, finding, check)
        if suggestion is not None:
            suggestions.append(suggestion)
            continue
        entry: dict[str, str] = {
            "code": finding.code,
            "detail": finding.message,
            "check": check,
        }
        if reason is not None:
            entry["code"] = CONTINUITY_RULE_INVALID
            entry["reason"] = reason
        untranslated.append(entry)


def _run_check(
    check: str,
    run: Callable[[], list[_Finding]],
    suggestions: list[ContinuitySuggestion],
    untranslated: list[dict[str, str]],
) -> None:
    """Run one check, degrading honestly when it cannot run at all.

    A raising check costs that check's advice only: the failure is recorded
    as a named reason so the surface can show *which* continuity half is
    unavailable instead of reporting a clean scene.
    """
    try:
        findings = run()
    except Exception as error:  # advisory family: never block the surface
        untranslated.append(
            {
                "code": CONTINUITY_CHECK_FAILED,
                "detail": f"{check} 检查未能运行：{error}",
                "check": check,
                "reason": f"{check} check raised; its advice is unavailable.",
            }
        )
        return
    _record(suggestions, untranslated, _RULES_BY_CHECK[check], findings, check)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_continuity_suggestions(
    script: Any,
    segments: Any | None = None,
) -> tuple[list[ContinuitySuggestion], list[dict[str, str]]]:
    """Run every continuity check on ``script`` and translate the findings.

    ``segments`` is an optional list of SpeechSegment for the emotion check;
    when omitted (or empty) the emotion half of the check is skipped —
    never a guess.

    Returns ``(suggestions, untranslated)``:
    - ``suggestions``: the conversational hooks, ready to render.
    - ``untranslated``: findings whose code this translator does not know
      yet (a named reason, never dropped silently — §4). Each entry is
      ``{"code": ..., "detail": ..., "check": ...}``, plus a ``"reason"``
      when the rule (not the finding) is what went wrong.

    ``script`` is a validated SceneScriptRoot. The function is pure: it
    never mutates the script, and an empty script yields two empty lists.
    """
    suggestions: list[ContinuitySuggestion] = []
    untranslated: list[dict[str, str]] = []

    def _blocking() -> list[_Finding]:
        return [
            _Finding(
                code=issue.code,
                message=issue.message,
                remedy=issue.remedy,
                subjects=(issue.subject, issue.boundary),
            )
            for issue in check_blocking_continuity(script)
        ]

    _run_check("blocking", _blocking, suggestions, untranslated)

    # Emotion continuity (whiplash) — only when the caller supplied lines.
    if segments is not None and len(segments) > 0:

        def _emotion() -> list[_Finding]:
            advisories = check_emotion_continuity(
                shots=list(script.shots),
                segments=segments,
                frame_rate=int(getattr(script.scene, "frame_rate", 30)) or 30,
            )
            return [
                _Finding(
                    code=advisory.code,
                    message=advisory.message,
                    remedy=advisory.remedy,
                    subjects=(advisory.shot_id or "",),
                )
                for advisory in advisories
            ]

        _run_check("emotion", _emotion, suggestions, untranslated)

    # Held items (hand conflict, authored position far).
    def _held_items() -> list[_Finding]:
        return [
            _Finding(
                code=finding.code,
                message=finding.message,
                remedy=finding.remedy,
                subjects=(finding.subject,),
            )
            for finding in check_held_items(script)
        ]

    _run_check("held_items", _held_items, suggestions, untranslated)

    return suggestions, untranslated


def build_continuity_suggestions_dict(script: Any, segments: Any | None = None) -> dict[str, Any]:
    """The suggestions + untranslated list as a JSON-serialisable dict."""
    suggestions, untranslated = build_continuity_suggestions(script, segments)
    return {
        "suggestions": [s.to_dict() for s in suggestions],
        "untranslated": untranslated,
    }
