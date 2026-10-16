# Locks validated_ducking_config.
#
# The contract pinned here: a ducking config is either off (None), or a complete
# set of four in-range floats. It must never return a partial dict, and an
# out-of-range or non-finite value must fail loudly rather than be clamped into
# something the operator did not ask for.

from __future__ import annotations

import math

import pytest

from app.services.v2_final_composition_filters import validated_ducking_config


class TestValidatedDuckingConfig:
    def test_absent_config_is_off(self) -> None:
        assert validated_ducking_config(None) is None

    def test_empty_config_is_off(self) -> None:
        assert validated_ducking_config({}) is None

    def test_explicitly_disabled_config_is_off(self) -> None:
        assert validated_ducking_config({"enabled": False}) is None

    def test_enabled_config_fills_documented_defaults(self) -> None:
        result = validated_ducking_config({"enabled": True})
        assert result == {
            "threshold_db": -30.0,
            "ratio": 12.0,
            "attack_ms": 50.0,
            "release_ms": 250.0,
        }

    def test_supplied_values_are_floated(self) -> None:
        result = validated_ducking_config({"enabled": True, "ratio": 4})
        assert result is not None
        assert result["ratio"] == 4.0
        assert isinstance(result["ratio"], float)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("threshold_db", -61),
            ("threshold_db", 1),
            ("ratio", 0),
            ("ratio", 21),
            ("attack_ms", 0),
            ("attack_ms", 2001),
            ("release_ms", 0),
            ("release_ms", 9001),
        ],
    )
    def test_out_of_range_value_fails_loudly(self, field: str, value: float) -> None:
        with pytest.raises(ValueError, match=f"Invalid ducking {field}"):
            validated_ducking_config({"enabled": True, field: value})

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_value_fails_loudly(self, bad: float) -> None:
        with pytest.raises(ValueError, match="Invalid ducking threshold_db"):
            validated_ducking_config({"enabled": True, "threshold_db": bad})

    def test_boolean_is_not_a_number(self) -> None:
        # True is an int in Python; accepting it would let ratio=true through.
        with pytest.raises(ValueError, match="Invalid ducking ratio"):
            validated_ducking_config({"enabled": True, "ratio": True})

    def test_enabled_flag_must_be_exactly_true(self) -> None:
        assert validated_ducking_config({"enabled": "yes"}) is None

    def test_mutation_check_dropping_the_range_guard_goes_red(self) -> None:
        # Mutation check: the guard under test is the
        # limits[key][0] <= raw <= limits[key][1] comparison. Removing it makes
        # threshold_db=-61 pass through, which the range test above catches.
        assert math.isfinite(-61.0)
        with pytest.raises(ValueError, match="Invalid ducking threshold_db"):
            validated_ducking_config({"enabled": True, "threshold_db": -61})
