"""Tests for the prop/environment type fallback table.

Locks the contract: an unknown type emitted by the LLM or the director bar
degrades to the nearest schema-known primitive instead of rejecting the batch.
The table is the single source of truth; a new entry here must be mirrored
in the frontend ``sceneScriptEditModel.ts`` (the nudge / add-prop flow).

The key folding is locked too: the table is keyed ``vending_machine`` while
the LLM writes "Vending Machine", so a table entry whose own documented
spelling cannot resolve is a silent failure the report would never show.
"""

from __future__ import annotations

from app.services.scene3d.prop_type_fallback import (
    PROP_FALLBACKS,
    ENVIRONMENT_FALLBACKS,
    build_fallback_report,
    resolve_environment_fallback,
    resolve_prop_fallback,
)


# ---------------------------------------------------------------------------
# resolve_prop_fallback
# ---------------------------------------------------------------------------


def test_locked_falls_back_to_box() -> None:
    assert resolve_prop_fallback("locker") == "box"


def test_vending_machine_falls_back_to_box() -> None:
    assert resolve_prop_fallback("vending_machine") == "box"


def test_coffee_table_falls_back_to_rect_table() -> None:
    assert resolve_prop_fallback("coffee_table") == "rect_table"


def test_torch_falls_back_to_lantern() -> None:
    assert resolve_prop_fallback("torch") == "lantern"


def test_neon_sign_falls_back_to_lantern() -> None:
    assert resolve_prop_fallback("neon_sign") == "lantern"


def test_sword_falls_back_to_weapon() -> None:
    assert resolve_prop_fallback("sword") == "weapon"


def test_notebook_falls_back_to_book() -> None:
    assert resolve_prop_fallback("notebook") == "book"


def test_bottle_falls_back_to_vase() -> None:
    assert resolve_prop_fallback("bottle") == "vase"


def test_known_type_returns_none() -> None:
    # A type that is already in the schema should NOT trigger a fallback.
    assert resolve_prop_fallback("box") is None
    assert resolve_prop_fallback("chair") is None


def test_unknown_type_returns_none() -> None:
    assert resolve_prop_fallback("quantum_flux_capacitor") is None
    assert resolve_prop_fallback("") is None


def test_case_insensitive() -> None:
    assert resolve_prop_fallback("Locker") == "box"
    assert resolve_prop_fallback("LOCKER") == "box"


def test_hyphen_to_underscore() -> None:
    assert resolve_prop_fallback("vending-machine") == "box"


# ---------------------------------------------------------------------------
# resolve_environment_fallback
# ---------------------------------------------------------------------------


def test_column_falls_back_to_pillar() -> None:
    assert resolve_environment_fallback("column") == "pillar"


def test_canopy_falls_back_to_flat_roof() -> None:
    assert resolve_environment_fallback("canopy") == "flat_roof"


def test_gate_falls_back_to_door() -> None:
    assert resolve_environment_fallback("gate") == "door"


def test_ramp_falls_back_to_stairs() -> None:
    assert resolve_environment_fallback("ramp") == "stairs"


def test_hedge_falls_back_to_fence() -> None:
    assert resolve_environment_fallback("hedge") == "fence"


def test_terrain_falls_back_to_ground() -> None:
    assert resolve_environment_fallback("terrain") == "ground"


def test_known_environment_type_returns_none() -> None:
    assert resolve_environment_fallback("wall") is None
    assert resolve_environment_fallback("tree") is None


def test_unknown_environment_type_returns_none() -> None:
    assert resolve_environment_fallback("hovercraft") is None


# ---------------------------------------------------------------------------
# Table completeness
# ---------------------------------------------------------------------------


def test_all_prop_fallbacks_resolve_to_known_primitives() -> None:
    """Every value in PROP_FALLBACKS must be a schema-known PropType."""
    from app.schemas.scene_script import PropType
    from typing import get_args

    known = set(get_args(PropType))
    for alias, primitive in PROP_FALLBACKS.items():
        assert primitive in known, f"PROP_FALLBACKS['{alias}'] -> '{primitive}' not in PropType"


def test_all_environment_fallbacks_resolve_to_known_primitives() -> None:
    """Every value in ENVIRONMENT_FALLBACKS must be a schema-known EnvironmentType."""
    from app.schemas.scene_script import EnvironmentType
    from typing import get_args

    known = set(get_args(EnvironmentType))
    for alias, primitive in ENVIRONMENT_FALLBACKS.items():
        assert primitive in known, f"ENVIRONMENT_FALLBACKS['{alias}'] -> '{primitive}' not in EnvironmentType"


# ---------------------------------------------------------------------------
# build_fallback_report
# ---------------------------------------------------------------------------


def test_fallback_report_degrades_known_alias() -> None:
    report = build_fallback_report(
        [{"index": 0, "kind": "add_prop", "type": "locker", "resolved": None}]
    )
    assert len(report) == 1
    entry = report[0]
    assert entry["resolved_to"] == "box"
    assert entry["requested"] == "locker"
    assert "box" in entry["message"]


def test_fallback_report_reports_unresolvable() -> None:
    report = build_fallback_report(
        [{"index": 1, "kind": "add_prop", "type": "quantum_flux_capacitor", "resolved": None}]
    )
    entry = report[0]
    assert entry["resolved_to"] is None
    assert "no known fallback" in entry["message"]


def test_fallback_report_respects_explicit_resolved() -> None:
    # When the caller already knows the resolution, it is used verbatim.
    report = build_fallback_report(
        [{"index": 0, "kind": "add_prop", "type": "locker", "resolved": "crate"}]
    )
    assert report[0]["resolved_to"] == "crate"


def test_fallback_report_environment_kind() -> None:
    report = build_fallback_report(
        [{"index": 2, "kind": "add_environment", "type": "column", "resolved": None}]
    )
    assert report[0]["resolved_to"] == "pillar"


# ---------------------------------------------------------------------------
# Key folding (the table's own documented spelling must resolve)
# ---------------------------------------------------------------------------


def test_spaced_type_resolves_to_the_underscored_key() -> None:
    """The module docstring's example is spelled 'vending machine'."""
    assert resolve_prop_fallback("vending machine") == "box"
    assert resolve_prop_fallback("Vending Machine") == "box"
    assert resolve_prop_fallback("  vending   machine  ") == "box"


def test_environment_type_folds_the_same_way() -> None:
    assert resolve_environment_fallback("guard rail") == "fence"
    assert resolve_environment_fallback("Guard-Rail") == "fence"
    assert resolve_environment_fallback("glass window") == "window"
    assert resolve_environment_fallback("podium block") == "platform"


def test_slash_separated_type_resolves() -> None:
    assert resolve_prop_fallback("vending/machine") == "box"


def test_folding_does_not_collapse_distinct_keys() -> None:
    """'post' and 'pillar' are different words; folding must not merge them."""
    assert resolve_prop_fallback("post") is None
    assert resolve_prop_fallback("pillar") is None
    assert resolve_environment_fallback("post") == "pillar"


def test_non_string_type_does_not_resolve_or_raise() -> None:
    assert resolve_prop_fallback(None) is None  # type: ignore[arg-type]
    assert resolve_prop_fallback(42) is None  # type: ignore[arg-type]
    assert resolve_environment_fallback(["column"]) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Report hardening (nothing is dropped without a named reason)
# ---------------------------------------------------------------------------


def test_report_names_an_unknown_kind_instead_of_blaming_the_type() -> None:
    """A typo'd kind must not be re-labelled 'no fallback' — that misleads."""
    report = build_fallback_report(
        [{"index": 0, "kind": "add_propp", "type": "locker", "resolved": None}]
    )
    entry = report[0]
    assert entry["resolved_to"] is None
    assert "add_propp" in entry["message"]
    assert "add_prop" in entry["message"]


def test_report_handles_a_non_object_entry() -> None:
    report = build_fallback_report(["garbage", 42])
    assert len(report) == 2
    for entry in report:
        assert entry["resolved_to"] is None
        assert "not an object" in entry["message"]
        assert entry["op_index"] is None


def test_report_drops_a_non_index_index() -> None:
    """A non-integer index becomes None rather than poisoning the row."""
    report = build_fallback_report(
        [{"index": "second", "kind": "add_prop", "type": "locker", "resolved": None}]
    )
    assert report[0]["op_index"] is None
    assert report[0]["resolved_to"] == "box"


def test_report_ignores_a_blank_explicit_resolution() -> None:
    """An empty 'resolved' is not a resolution — fall back to the table."""
    report = build_fallback_report(
        [{"index": 0, "kind": "add_prop", "type": "locker", "resolved": "   "}]
    )
    assert report[0]["resolved_to"] == "box"


def test_report_resolves_a_spaced_type() -> None:
    report = build_fallback_report(
        [{"index": 0, "kind": "add_prop", "type": "Vending Machine", "resolved": None}]
    )
    assert report[0]["resolved_to"] == "box"
    assert "Vending Machine" in report[0]["message"]


def test_report_is_json_safe() -> None:
    import json

    payload = json.loads(
        json.dumps(
            build_fallback_report(
                [
                    {"index": 0, "kind": "add_prop", "type": "locker", "resolved": None},
                    {"index": 1, "kind": "add_environment", "type": "hovercraft", "resolved": None},
                ]
            )
        )
    )
    assert payload[0]["resolved_to"] == "box"
    assert payload[1]["resolved_to"] is None
    assert payload[1]["op_index"] == 1


def test_empty_report_is_empty() -> None:
    assert build_fallback_report([]) == []
