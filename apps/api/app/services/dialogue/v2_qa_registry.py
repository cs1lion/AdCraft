"""The QA registry — automated pre-commit checks, not ad-hoc ones (ADR 0003 §5).

"QA registry, not ad-hoc checks": the speech track's quality gates are named,
ordered entries that return a structured outcome, so a reviewer can ask "what
was checked, what did it find" instead of grepping for `if` statements. This
module is that registry; the entries themselves live beside it.

Contract:

* a check is a NAMED, VERSIONED entry with one ``run(subject) -> QaOutcome``;
* an outcome is ``pass`` / ``warn`` / ``fail`` with a human reason and a
  structured ``details`` payload (never a bare boolean — the reason is the
  product);
* registration is ordered and rejects duplicate names LOUDLY (two checks
  claiming one name is exactly how a gate silently stops running);
* a check that cannot run (missing ffmpeg, missing input) degrades to ``warn``
  WITH a reason — a skipped check that reports itself as ``pass`` is the
  failure mode this design exists to prevent (engineering standard §4).

The registry is modality-neutral by design: the speech checks read ``audio_path``
and the image/video checks read ``image_path`` / ``video_path``, all off one
subject, so "what was checked" is one question with one answer per run rather
than one per modality (see ``media_qa_checks.py``).

Boundary, recorded honestly: the registry runs wherever a caller asks it to,
and "where" differs by path — deliberately, because the two tracks have
different blast radii:

* the **speech** track (ADR 0003) publishes its report as queryable provenance
  and lets the pipeline that owns alignment decide; a warned bed still commits,
  a FAIL (a take measuring as silence) raises before the node goes ready;
* the **image/video** track (``media_qa_checks``) runs the same contract on
  ``image_path`` / ``video_path`` inside ``MediaNodeExecutor._media_qa_gate``,
  with the same two verdicts — a ``warn`` publishes the report, a ``fail``
  (a flat image, a truncated render) blocks the commit.

The registry itself never decides to block: it reports, and the caller that
owns the commit turns a verdict into a decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field

QA_PASS = "pass"
QA_WARN = "warn"
QA_FAIL = "fail"


@dataclass(frozen=True)
class QaOutcome:
    """One check's verdict: status, human reason, structured details."""

    check: str
    status: str
    reason: str
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "check": self.check,
            "status": self.status,
            "reason": self.reason,
            "details": dict(self.details),
        }


@dataclass
class QaSubject:
    """Everything the phase-1 checks may look at (all optional)."""

    # Per-line measured-vs-estimated durations: [{segment_id, measured,
    # estimated}]. Present when a real TTS engine measured the lines.
    measured_durations: list[dict[str, float]] = field(default_factory=list)
    # Speech segments (with start/end/character) from the speech timeline.
    segments: list[object] = field(default_factory=list)
    # Bound speech bindings: [{character, speech_asset, mode}].
    speech_bindings: list[dict[str, str]] = field(default_factory=list)
    # Shot windows: [{id, start_seconds, end_seconds}].
    shots: list[dict[str, float]] = field(default_factory=list)
    # The timeline's own consistency findings (overlap/gap/out-of-bounds).
    timeline_issues: list[dict[str, str]] = field(default_factory=list)
    # Audio file for the loudness probe (absolute path).
    audio_path: str | None = None
    # The other modalities of the v2 production chain (ADR 0003 §5's second
    # half): an image or video file to inspect, and for video the slot the
    # node ASKED for — a 5-second request answered with 1.5 seconds is a
    # truncated render, and nothing else in the chain would notice.
    image_path: str | None = None
    video_path: str | None = None
    requested_duration_seconds: float | None = None


class QaCheck:
    """Base class for a registry entry (a protocol would do; this documents)."""

    name: str = ""
    version: str = "1"

    def run(self, subject: QaSubject) -> QaOutcome:  # pragma: no cover - interface
        raise NotImplementedError


class QaRegistry:
    """An ordered set of named checks with one ``run_all``."""

    def __init__(self) -> None:
        self._checks: list[QaCheck] = []

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(check.name for check in self._checks)

    def register(self, check: QaCheck) -> "QaRegistry":
        """Add a check. A duplicate name fails loud: two checks claiming one
        name is how a gate silently stops running."""

        if not check.name:
            raise ValueError("QA check must declare a name")
        if check.name in self.names:
            raise ValueError(f"duplicate QA check name: {check.name}")
        self._checks.append(check)
        return self

    def run_all(self, subject: QaSubject) -> list[QaOutcome]:
        return [check.run(subject) for check in self._checks]

    def report(self, subject: QaSubject) -> dict[str, object]:
        """The whole run as one queryable payload."""

        outcomes = self.run_all(subject)
        failed = [outcome for outcome in outcomes if outcome.status == QA_FAIL]
        warned = [outcome for outcome in outcomes if outcome.status == QA_WARN]
        return {
            "checks": list(self.names),
            "outcomes": [outcome.to_dict() for outcome in outcomes],
            "failed": [outcome.check for outcome in failed],
            "warned": [outcome.check for outcome in warned],
            "passed": not failed,
        }
