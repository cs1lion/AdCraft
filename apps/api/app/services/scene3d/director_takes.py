"""Director takes — a labelled snapshot of the SceneScript plus the ops
that produced it, for A/B comparison and "go back to that version".

A take is the unit the director compares: "use the left one" is a take
id, not a re-derivation. The take stores:
- the full SceneScript at save time (whole-script, not a patch, for the
  same reason transition variants do — a partial snapshot would silently
  mix two states on restore),
- the ops diff that got the script to this state (replayable through
  the gate, queryable without re-running the LLM),
- a creator-facing label.

The module owns the pure data model + tolerant parse/serialize; the
workbench persists it on the node under a structured_content key,
mirroring the transition-variants pattern (``transitionVariants.ts``).

The cap is small and deliberate: takes are for *comparison*, not
version control. Four is the same number the transition variants use;
the panel states the cap rather than silently dropping the oldest.

The cap is enforced in exactly one place — ``serialize_director_takes``
— and it never drops a take silently: the same call is available as
``serialize_director_takes_with_report``, which returns the capped list
plus the ids that fell off the end and why (engineering standard §4).
Parity module: ``apps/web/.../directorTakes.ts`` mirrors the parse and
the cap; keep them in lockstep.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: How many takes a node keeps. Takes are for comparison, not version
#: control — the same cap the transition variants use, and the reason the
#: panel states it instead of quietly evicting the oldest take.
MAX_DIRECTOR_TAKES = 4


@dataclass(frozen=True, slots=True)
class DirectorTake:
    """One saved take: a labelled snapshot + the ops that produced it."""

    id: str
    #: Creator-facing label (defaults to "Take 1", "Take 2", …).
    label: str
    #: The full SceneScript JSON at save time.
    scene_script: dict[str, Any]
    #: The ops diff that produced this take (the replayable record).
    operations: list[dict[str, Any]] = field(default_factory=list)
    #: The frame the take was captured at, when meaningful.
    frame: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable entry for the node's structured_content block."""
        entry: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "scene_script": self.scene_script,
            "operations": self.operations,
        }
        if self.frame is not None:
            entry["frame"] = self.frame
        return entry


@dataclass(frozen=True, slots=True)
class DirectorTakeSerialization:
    """A capped serialization plus the record of what the cap evicted.

    ``dropped_take_ids`` names every take that fell off the end (oldest
    first) so the caller can say "Take 1 was replaced" instead of watching
    a saved take disappear.
    """

    takes: list[dict[str, Any]]
    dropped_take_ids: tuple[str, ...] = ()

    @property
    def capped(self) -> bool:
        """True when at least one take was dropped to honour the cap."""
        return bool(self.dropped_take_ids)


def parse_director_takes(raw: Any) -> list[DirectorTake]:
    """Tolerant parse of the structured_content block.

    Returns [] when the key is absent or unusable — the workbench treats
    that as "no takes saved yet". A take without a scene_script is
    skipped: restoring a blank scene over the director's work is worse
    than losing one take.
    """
    if not isinstance(raw, list):
        return []
    takes: list[DirectorTake] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        scene_script = entry.get("scene_script")
        if not isinstance(scene_script, dict):
            continue
        take_id = str(entry.get("id") or "").strip() or f"take_{len(takes) + 1}"
        label = str(entry.get("label") or "").strip()
        operations_raw = entry.get("operations")
        operations = (
            [op for op in operations_raw if isinstance(op, dict)]
            if isinstance(operations_raw, list)
            else []
        )
        frame_raw = entry.get("frame")
        frame = int(frame_raw) if isinstance(frame_raw, (int, float)) and not isinstance(frame_raw, bool) else None
        takes.append(
            DirectorTake(
                id=take_id,
                label=label or f"Take {len(takes) + 1}",
                scene_script=scene_script,
                operations=operations,
                frame=frame,
            )
        )
    return takes


def serialize_director_takes(takes: list[DirectorTake]) -> list[dict[str, Any]]:
    """Serialize for structured_content; keeps at most the cap, newest last.

    Thin wrapper over :func:`serialize_director_takes_with_report` for
    callers that do not surface the eviction; prefer the reporting variant
    whenever a creator can see the result.
    """
    return serialize_director_takes_with_report(takes).takes


def serialize_director_takes_with_report(
    takes: list[DirectorTake],
) -> DirectorTakeSerialization:
    """Serialize for structured_content, reporting what the cap evicted.

    Keeps at most :data:`MAX_DIRECTOR_TAKES` takes (newest last) and names
    every take that fell off the end, so the eviction is queryable instead
    of a take silently vanishing from the panel.
    """
    kept = takes[-MAX_DIRECTOR_TAKES:] if MAX_DIRECTOR_TAKES > 0 else []
    dropped = takes[: max(0, len(takes) - len(kept))]
    return DirectorTakeSerialization(
        takes=[take.to_dict() for take in kept],
        dropped_take_ids=tuple(take.id for take in dropped),
    )


def next_take_label(takes: list[DirectorTake]) -> str:
    """The next label in the Take 1/2/3… series, skipping used ones."""
    used = {take.label for take in takes}
    index = 1
    while f"Take {index}" in used:
        index += 1
    return f"Take {index}"
