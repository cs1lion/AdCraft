"""Per-line dialogue events for the voice-cast node (V0.2 §14.7 内容层/表演层).

"如果 Audio Gen 只是一次生成一整条音轨，用户一旦修改一句台词，就被迫重新
生成整段，前面的时间组织也会失效" — the failure §14.7 names is a DATA MODEL
problem, not a synthesis problem: as long as the node owns one blob of text
there is nothing to address. So the node may instead own LINES, each one an
Audio Event with its own text, emotion, and take.

The interesting decision is which lines to RE-synthesize. The naive
implementation re-synthesizes everything (cheap to write, expensive to run,
and it throws away the takes the author already approved). This module makes
the reuse decision PURE and CONTENT-ADDRESSED:

* a line's cache file name carries a digest of its text+emotion, so "has this
  line changed?" is "does that file exist?" — no manifest to keep in sync and
  no stale-artifact class to reason about;
* ``regenerate_line_ids`` forces a line regardless (the author wants a
  different take of the SAME words — same text, new emotion, or simply not
  happy with the last one).

Everything the executor needs next — which lines to send to the engine, which
files to join, and the manifest of what the take contains — falls out of one
plan object, which is what makes the whole thing testable without a provider.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Callable

#: How many lines one node may own. A voice-cast take is a line of dialogue,
#: not a script: the cap keeps a typo (a pasted screenplay) from turning into
#: forty provider calls.
MAX_DIALOGUE_LINES = 40

#: Longest single line (chars). Same order as the unified bed's per-script
#: budget, so both authoring paths fail the same way.
MAX_LINE_CHARS = 400

#: Longest emotion annotation (chars) — mirrors the audio bed's rule.
MAX_LINE_EMOTION_CHARS = 64

#: Ids must survive a filename, so the characters are constrained rather than
#: sanitised away (a sanitised id could collide with another line's).
LINE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,48}$")

#: How a path is tested for existence. Injected so the reuse decision stays
#: pure; production passes ``os.path.isfile``.
FileExists = Callable[[str], bool]


@dataclass(frozen=True)
class DialogueLine:
    """One Audio Event: the words, the direction, and where its take lives."""

    line_id: str
    text: str
    emotion: str = ""

    @property
    def content_key(self) -> str:
        """Digest of what was SAID and how — the identity of its take."""

        digest = hashlib.sha1()
        digest.update(self.line_id.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(self.text.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(self.emotion.encode("utf-8"))
        return digest.hexdigest()[:12]

    @property
    def filename(self) -> str:
        """A safe, content-addressed cache filename for this line's take."""

        return f"{self.line_id}__{self.content_key}.mp3"


@dataclass(frozen=True)
class LinePlanEntry:
    """One line's verdict: reuse its take, or pay for a new one."""

    line: DialogueLine
    cached_path: str | None
    regenerate: bool

    @property
    def needs_synthesis(self) -> bool:
        return self.cached_path is None or self.regenerate


@dataclass(frozen=True)
class LineSynthesisPlan:
    """Which lines to synthesize, and what the joined take will contain."""

    entries: list[LinePlanEntry] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)

    @property
    def to_synthesize(self) -> list[DialogueLine]:
        return [entry.line for entry in self.entries if entry.needs_synthesis]

    @property
    def all_cached(self) -> bool:
        """True when nothing needs the provider (a pure cache replay)."""

        return bool(self.entries) and not self.to_synthesize

    def paths_after_synthesis(self) -> list[str]:
        """Every line's take in dialogue order, cached or newly built."""

        return [os.path.join("", entry.line.filename) for entry in self.entries]

    def manifest(self, durations: dict[str, float | None]) -> list[dict[str, object]]:
        """Per-line manifest with running offsets — the timing that follows.

        ``durations`` maps line id → measured seconds (or None when the probe
        failed). Offsets are the running sum, and a line whose duration is
        unknown poisons the offsets AFTER it: they are reported only while
        they are trustworthy, which is what lets a caller recompute the
        timeline without silently shifting everything after a gap.
        """

        manifest: list[dict[str, object]] = []
        offset = 0.0
        offsets_known = True
        for entry in self.entries:
            duration = durations.get(entry.line.line_id)
            record: dict[str, object] = {
                "line_id": entry.line.line_id,
                "text": entry.line.text,
                "emotion": entry.line.emotion,
                "duration_seconds": duration,
                "regenerated": entry.needs_synthesis,
            }
            if offsets_known and duration is not None:
                record["offset_seconds"] = round(offset, 3)
                offset += duration
            else:
                offsets_known = False
            manifest.append(record)
        return manifest


def parse_dialogue_lines(raw: object) -> tuple[list[DialogueLine], list[str]]:
    """Read the node's ``dialogue_lines`` block (tolerant, never silent).

    Returns the usable lines in authoring order plus a reason for every entry
    dropped. A malformed line is skipped rather than failing the node: one bad
    row must not take the take down, but it must be SAYABLE — the caller
    publishes these reasons (ADR 0005: queryable, never silent).
    """

    if not isinstance(raw, list):
        return [], ["dialogue_lines 不是列表，已忽略逐行模式。"]
    lines: list[DialogueLine] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            dropped.append(f"dialogue_lines[{index}] 不是对象，已忽略。")
            continue
        line_id = str(entry.get("id") or entry.get("line_id") or "").strip()
        text = str(entry.get("text") or "").strip()
        emotion = str(entry.get("emotion") or "").strip()
        if not line_id:
            dropped.append(f"dialogue_lines[{index}] 缺少 id，已忽略。")
            continue
        if not LINE_ID_PATTERN.match(line_id):
            dropped.append(
                f"dialogue_lines[{index}] 的 id「{line_id}」只能用字母数字与 -_ 且不超过 "
                f"48 字符，已忽略。"
            )
            continue
        if not text:
            dropped.append(f"dialogue_lines[{index}]（{line_id}）没有台词文本，已忽略。")
            continue
        if len(text) > MAX_LINE_CHARS:
            dropped.append(
                f"dialogue_lines[{index}]（{line_id}）超过 {MAX_LINE_CHARS} 字符，已忽略。"
            )
            continue
        if len(emotion) > MAX_LINE_EMOTION_CHARS:
            dropped.append(
                f"dialogue_lines[{index}]（{line_id}）的情绪标注超过 "
                f"{MAX_LINE_EMOTION_CHARS} 字符，已忽略该行。"
            )
            continue
        if line_id in seen:
            dropped.append(f"dialogue_lines[{index}] 的 id「{line_id}」重复，已忽略。")
            continue
        seen.add(line_id)
        lines.append(DialogueLine(line_id=line_id, text=text, emotion=emotion))
    if len(lines) > MAX_DIALOGUE_LINES:
        dropped.append(
            f"逐行台词最多 {MAX_DIALOGUE_LINES} 行，已保留前 {MAX_DIALOGUE_LINES} 行。"
        )
        lines = lines[:MAX_DIALOGUE_LINES]
    return lines, dropped


def plan_line_synthesis(
    lines: list[DialogueLine],
    *,
    cache_dir: str,
    regenerate_ids: list[str] | None = None,
    file_exists: FileExists | None = None,
) -> LineSynthesisPlan:
    """Decide, per line, whether its take can be reused.

    ``file_exists`` is injected so the decision is a pure function of the
    lines and the requested regeneration; production passes ``os.path.isfile``.
    """

    exists: FileExists = file_exists or os.path.isfile
    forced = {str(line_id).strip() for line_id in (regenerate_ids or [])}
    entries: list[LinePlanEntry] = []
    for line in lines:
        path = os.path.join(cache_dir, line.filename)
        cached = path if exists(path) else None
        entries.append(
            LinePlanEntry(line=line, cached_path=cached, regenerate=line.line_id in forced)
        )
    return LineSynthesisPlan(entries=entries)
