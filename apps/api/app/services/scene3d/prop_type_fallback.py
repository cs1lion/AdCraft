"""Nearest-primitive fallback table for unknown prop and environment types.

When the LLM (white-model generator) or the director command bar references a
prop type that the SceneScript schema does not know ("vending machine",
"locker", "neon sign", "arch"), the gate used to reject the whole batch with
``object_type_unsupported``. The fallback table degrades instead: it maps the
unknown word to the closest primitive already in the schema and records the
degradation in the ops result so the caller can surface it.

This is a code-level table, not a prompt-level rule. The white-model
generator's system prompt says "prefer the nearest primitive" but that is a
soft instruction; this table is a hard fallback that runs *after* the gate's
enum check has already passed, so the LLM never needs to know it exists.
The table is intentionally small and conservative — a new entry means the
primitive geometry is a reasonable stand-in at white-model fidelity.

The table is also the single source of truth for the frontend mirror in
``sceneScriptEditModel.ts`` / ``propTypeFallback.ts`` (the nudge / add-prop
flow uses the same keys), so a new entry here must be mirrored there — the
lookup key folding below included.
"""

from __future__ import annotations

from typing import Any, Callable

# ---------------------------------------------------------------------------
# Fallback tables
# ---------------------------------------------------------------------------
# Keys are lowercase free-form words the LLM or director might emit.
# Values are the schema-known primitive to substitute.
# The first key in a group is the "canonical" alias for that primitive.

PROP_FALLBACKS: dict[str, str] = {
    # --- table / seating family ---
    "desk": "rect_table",
    "desk_table": "rect_table",
    "coffee_table": "rect_table",
    "side_table": "rect_table",
    "dining_table": "round_table",
    "bench": "stool",
    "seat": "chair",
    "throne": "chair",
    "sofa": "rect_table",  # low, wide, rectangular — boxy stand-in
    "couch": "rect_table",
    "footstool": "stool",

    # --- box / storage family ---
    "locker": "box",
    "cabinet": "box",
    "chest": "box",
    "crate_stack": "crate",
    "pallet": "crate",
    "storage_bin": "box",
    "vending_machine": "box",
    "fridge": "box",
    "refrigerator": "box",
    "atm": "box",

    # --- lantern / light family ---
    "street_lamp": "lantern",
    "torch": "lantern",
    "candle": "lantern",
    "fireplace": "lantern",
    "neon_sign": "lantern",
    "light_fixture": "lantern",
    "spotlight": "lantern",

    # --- cup / vessel family ---
    "mug": "cup",
    "glass": "cup",
    "bowl": "cup",
    "pot": "cup",
    "kettle": "cup",
    "bottle": "vase",
    "jug": "vase",
    "flask": "vase",

    # --- weapon / tool family ---
    "sword": "weapon",
    "dagger": "weapon",
    "axe": "weapon",
    "hammer": "weapon",
    "tool": "weapon",
    "club": "weapon",

    # --- book / scroll family ---
    "notebook": "book",
    "tablet": "book",
    "codex": "book",
    "pamphlet": "book",
    "leaflet": "scroll",
    "flag": "scroll",
    "banner": "scroll",

    # --- misc ---
    "pottery": "vase",
    "urn": "vase",
    "planter": "vase",
    "pedestal": "box",
    "plinth": "box",
    "block": "box",
}

# ---------------------------------------------------------------------------
# Environment fallbacks
# ---------------------------------------------------------------------------

ENVIRONMENT_FALLBACKS: dict[str, str] = {
    # --- wall / structure family ---
    "column": "pillar",
    "post": "pillar",
    "support": "pillar",
    "pole": "pillar",

    # --- roof family ---
    "canopy": "flat_roof",
    "awning": "flat_roof",
    "carport": "flat_roof",

    # --- door / window family ---
    "gate": "door",
    "entry": "door",
    "opening": "door",
    "glass_window": "window",
    "panel": "window",

    # --- stairs / platform family ---
    "ramp": "stairs",
    "escalator": "stairs",
    "steps": "stairs",
    "podium": "platform",
    "stage": "platform",
    "podium_block": "platform",

    # --- tree / rock / fence family ---
    "bush": "tree",
    "shrub": "tree",
    "sapling": "tree",
    "palm": "tree",
    "boulder": "rock",
    "stone": "rock",
    "boulder_field": "rock",
    "hedge": "fence",
    "railing": "fence",
    "barrier": "fence",
    "guard_rail": "fence",

    # --- ground / floor family ---
    "flooring": "floor",
    "carpet": "floor",
    "mat": "floor",
    "terrain": "ground",
    "path": "ground",
    "road": "ground",
}

#: Which resolver serves which op kind. A report entry naming anything else
#: is a caller bug and is reported as such, never re-labelled "no fallback".
_RESOLVER_BY_KIND: dict[str, Callable[[str], str | None]] = {
    "add_prop": lambda unknown: resolve_prop_fallback(unknown),
    "add_environment": lambda unknown: resolve_environment_fallback(unknown),
}

_FALLBACK_KINDS = ("add_prop", "add_environment")

#: Separators an LLM may use where the table key has an underscore.
_SEPARATORS = ("-", " ", "\t", "\n", "/", "\\")


def _normalize_type_key(unknown_type: object) -> str:
    """Fold a free-form type word onto a table key.

    The table is keyed by ``vending_machine`` but an LLM writes "Vending
    Machine", "vending-machine" and "vending  machine" for the same object;
    all of them must land on the same key or the table's own documented
    example silently fails to resolve. Case, surrounding whitespace, and
    any of :data:`_SEPARATORS` are folded; repeated separators collapse.
    """
    if not isinstance(unknown_type, str):
        return ""
    folded = unknown_type.strip().lower()
    for separator in _SEPARATORS:
        folded = folded.replace(separator, "_")
    while "__" in folded:
        folded = folded.replace("__", "_")
    return folded


def resolve_prop_fallback(unknown_type: str) -> str | None:
    """Return the schema-known primitive for an unknown prop type, or None."""
    return PROP_FALLBACKS.get(_normalize_type_key(unknown_type))


def resolve_environment_fallback(unknown_type: str) -> str | None:
    """Return the schema-known primitive for an unknown environment type, or None."""
    return ENVIRONMENT_FALLBACKS.get(_normalize_type_key(unknown_type))


def _op_index(entry: dict[str, Any]) -> int | None:
    """The op index as an int, or None when the entry carries no usable one."""
    index = entry.get("index")
    if isinstance(index, bool) or not isinstance(index, int):
        return None
    return index


def _resolved_override(entry: dict[str, Any]) -> str | None:
    """The caller's own resolution, honoured verbatim when it is a word."""
    resolved = entry.get("resolved")
    if isinstance(resolved, str) and resolved.strip():
        return resolved.strip()
    return None


def build_fallback_report(
    rejected_types: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Turn a list of rejected ops into a degradation report.

    Each entry in ``rejected_types`` is a dict with keys:
      - ``index``:  op index in the batch
      - ``kind``:   "add_prop" | "add_environment"
      - ``type``:   the unknown type string
      - ``resolved``: the schema-known primitive, or None

    The report is a list of human-readable warnings, one per degraded op,
    so the caller can surface them without re-parsing the ops. Nothing is
    dropped: an entry that is not an object, a kind that is neither prop nor
    environment, and a type with no table entry all produce a row that says
    the op was skipped and why (engineering standard §4).
    """
    report: list[dict[str, Any]] = []
    for entry in rejected_types:
        if not isinstance(entry, dict):
            report.append(
                {
                    "op_index": None,
                    "kind": "",
                    "requested": "",
                    "resolved_to": None,
                    "message": "fallback entry is not an object; the op was skipped.",
                }
            )
            continue

        kind = str(entry.get("kind") or "")
        unknown = str(entry.get("type", ""))
        resolver = _RESOLVER_BY_KIND.get(kind)
        resolved = _resolved_override(entry)
        if resolved is None and resolver is not None:
            resolved = resolver(unknown)

        if resolved is not None:
            report.append(
                {
                    "op_index": _op_index(entry),
                    "kind": kind,
                    "requested": unknown,
                    "resolved_to": resolved,
                    "message": f"'{unknown}' is not a known type; using '{resolved}' as the stand-in.",
                }
            )
        elif resolver is None:
            report.append(
                {
                    "op_index": _op_index(entry),
                    "kind": kind,
                    "requested": unknown,
                    "resolved_to": None,
                    "message": (
                        f"kind '{kind}' is not a fallback kind "
                        f"(expected {'/'.join(_FALLBACK_KINDS)}); the op was skipped."
                    ),
                }
            )
        else:
            report.append(
                {
                    "op_index": _op_index(entry),
                    "kind": kind,
                    "requested": unknown,
                    "resolved_to": None,
                    "message": f"'{unknown}' has no known fallback; the op was skipped.",
                }
            )
    return report
