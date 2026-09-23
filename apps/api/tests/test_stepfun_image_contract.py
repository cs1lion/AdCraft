"""The StepFun image contract, and the serializer that enforces it.

Every number asserted here comes from the provider documentation snapshots in
the repository root (``stepfun_docs_llm.txt:15762-15796`` and ``:8096-8103``,
``工具模型.txt:59-98``), not from what the code happens to send.

The three failures these tests pin were all live on 2026-09-21:

* ``IMAGE_GENERATION_SIZE`` was ``1920x1920`` and the code default was
  ``2048x2048``; ``step-image-edit-2`` accepts five sizes and neither of those
  is one of them.
* ``GUIDED_IMAGE_SIZES_BY_ASPECT_RATIO`` -- a Volcengine Ark table -- was
  advertised as the StepFun models' ``supported_sizes_by_aspect_ratio``, and the
  guided-parameter compiler reads that field to choose a size, so the catalog
  produced requests the gateway would refuse.
* The compiled prompt for a nine-panel storyboard is several times the
  documented 512-character ceiling.

None of that was visible at the time, because StepFun's image engine was
answering 503 ``engine_overloaded`` to *every* request -- including the minimal
curl from its own docs, which ``e2e_output/rose/probe_image_contract.py``
demonstrates.  A provider outage hid three latent contract bugs behind it, which
is exactly why they need tests rather than a note.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.provider_model_catalog import (
    GUIDED_IMAGE_SIZES_BY_ASPECT_RATIO,
    _TRUSTED_MANIFESTS,
    _stepfun_image_metadata,
)
from app.services.stepfun_image_contract import (
    STEPFUN_IMAGE_CFG_SCALE_RANGE,
    STEPFUN_IMAGE_PROMPT_MAX_CHARS,
    STEPFUN_IMAGE_SIZES_BY_ASPECT_RATIO,
    STEPFUN_IMAGE_SIZES_BY_MODEL,
    clamp_stepfun_image_prompt,
    clamp_stepfun_negative_prompt,
    is_stepfun_image_model,
    nearest_supported_stepfun_image_size,
    normalize_stepfun_image_size,
    stepfun_image_contract_violations,
    supported_stepfun_image_sizes,
)
from app.services.agnes_image_contract import is_agnes_image_model
from app.tools.media_provider_protocol import MediaConfigurationError
from app.tools.seedance_adapter import _normalize_image_generation_size
from app.tools.volcengine_image_generations import (
    serialize_volcengine_image_generation_request,
)

#: stepfun_docs_llm.txt:15772-15773 -- the five documented step-image-edit-2 sizes.
DOCUMENTED_EDIT_2_SIZES = {
    "1024x1024",
    "768x1360",
    "896x1184",
    "1360x768",
    "1184x896",
}

#: stepfun_docs_llm.txt:15774-15776 -- the six documented step-2x-large sizes.
DOCUMENTED_2X_LARGE_SIZES = {
    "256x256",
    "512x512",
    "768x768",
    "1024x1024",
    "1280x800",
    "800x1280",
}


# ---------------------------------------------------------------------------
# The transcribed tables match the documentation
# ---------------------------------------------------------------------------


def test_edit_2_size_table_matches_the_documented_five() -> None:
    assert set(STEPFUN_IMAGE_SIZES_BY_ASPECT_RATIO.values()) == DOCUMENTED_EDIT_2_SIZES


def test_edit_2_and_2x_large_tables_match_their_documented_sets() -> None:
    assert supported_stepfun_image_sizes("step-image-edit-2") == DOCUMENTED_EDIT_2_SIZES
    assert supported_stepfun_image_sizes("step-2x-large") == DOCUMENTED_2X_LARGE_SIZES


def test_every_aspect_ratio_maps_to_a_size_its_own_model_accepts() -> None:
    """The table must not name a size the model would refuse.

    This is the invariant the old Ark table broke: every one of its five values
    was outside StepFun's list, so the mapping was usable but wrong.
    """

    for ratio, size in STEPFUN_IMAGE_SIZES_BY_ASPECT_RATIO.items():
        assert size in DOCUMENTED_EDIT_2_SIZES, f"{ratio} -> {size}"
        # The ratio label is ``width:height`` by convention, and StepFun's size
        # string is ``height x width`` -- so width/height must equal the label.
        # That is what puts "16:9" on the portrait-looking ``768x1360``.
        height, width = (int(part) for part in size.split("x"))
        assert _is_closest_to(width / height, _ratio_value(ratio), DOCUMENTED_EDIT_2_SIZES), (
            f"{ratio} -> {size} is not the closest documented size to that ratio"
        )


def _is_closest_to(value: float, target: float, candidates: set[str]) -> bool:
    """True when ``value`` is the documented size nearest ``target``.

    StepFun's sizes round the ratio to convenient pixel counts (1360/768 is
    1.771, not 1.778), so an exact comparison is wrong -- what matters is that
    each ratio label got the size that is actually nearest to it.
    """

    def ratio_of(size: str) -> float:
        height, width = (int(part) for part in size.split("x"))
        return width / height

    return abs(value - target) == min(abs(ratio_of(c) - target) for c in candidates)


def _ratio_value(ratio: str) -> float:
    left, right = ratio.split(":")
    return int(left) / int(right)


def test_ark_size_table_is_kept_but_not_served_to_stepfun() -> None:
    """The Ark table still exists for Ark models; it just must not leak.

    ``GUIDED_IMAGE_SIZES_BY_ASPECT_RATIO`` is still referenced by the Ark and
    fake manifests.  What must never happen again is a StepFun manifest reading
    it, which is what made the catalog lie.
    """

    assert set(GUIDED_IMAGE_SIZES_BY_ASPECT_RATIO.values()).isdisjoint(
        DOCUMENTED_EDIT_2_SIZES
    ), "the Ark table now overlaps StepFun's -- check which one changed"
    for manifest in _TRUSTED_MANIFESTS:
        if manifest.provider_id != "stepfun" or manifest.capability != "image":
            continue
        advertised = manifest.capability_metadata["supported_sizes_by_aspect_ratio"]
        assert set(advertised.values()) == DOCUMENTED_EDIT_2_SIZES


def test_stepfun_manifest_advertises_no_undocumented_parameters() -> None:
    metadata = _stepfun_image_metadata()
    assert metadata["supported_aspect_ratios"] == list(STEPFUN_IMAGE_SIZES_BY_ASPECT_RATIO)


def test_cfg_scale_and_prompt_ceilings_match_the_docs() -> None:
    assert STEPFUN_IMAGE_PROMPT_MAX_CHARS == 512
    assert STEPFUN_IMAGE_CFG_SCALE_RANGE == (1.0, 10.0)


def test_settings_defaults_are_sizes_stepfun_accepts() -> None:
    """A fresh checkout must not need the normalizer to be correct.

    This reads the *class* defaults, not ``from_env()``: ``apps/api/.env`` is
    gitignored, so a fresh checkout has none, and the deployment's local ``.env``
    legitimately points at whichever vendor the operator chose.  Asserting
    ``from_env()`` here made this test silently describe one machine's
    configuration instead of the shipped default -- it passed for months only
    because the two happened to agree.
    """

    settings = Settings()
    assert settings.image_generation_size in DOCUMENTED_EDIT_2_SIZES
    assert settings.image_generation_model in STEPFUN_IMAGE_SIZES_BY_MODEL


def test_the_configured_model_is_served_by_some_known_image_contract() -> None:
    """Whatever ``.env`` configures must belong to a contract the code knows.

    A model that is neither StepFun's nor Agnes' would serialize with no
    provider-specific reconciliation at all -- no size mapping, no field
    pruning -- and would fail at the gateway with nothing in the audit to say
    why.  This catches that at configuration time rather than at request time.
    """

    model = Settings.from_env().image_generation_model
    assert is_stepfun_image_model(model) or is_agnes_image_model(model), model


# ---------------------------------------------------------------------------
# Size normalization
# ---------------------------------------------------------------------------


class TestNormalizeStepfunImageSize:
    def test_supported_size_passes_through_untouched(self) -> None:
        assert normalize_stepfun_image_size("step-image-edit-2", "1024x1024") == (
            "1024x1024",
            None,
        )

    @pytest.mark.parametrize(
        ("requested", "expected"),
        [
            # Both values that were actually configured on 2026-09-21.
            ("1920x1920", "1024x1024"),
            ("2048x2048", "1024x1024"),
            # The Ark guided table, keyed by aspect ratio.
            ("2560x1440", "768x1360"),
            ("1440x2560", "1360x768"),
            ("2304x1728", "896x1184"),
            ("1728x2304", "1184x896"),
        ],
    )
    def test_unlisted_size_maps_to_the_nearest_supported_one(
        self, requested: str, expected: str
    ) -> None:
        size, code = normalize_stepfun_image_size("step-image-edit-2", requested)
        assert size == expected
        assert code == "image_size_normalized_to_provider_supported"

    def test_orientation_is_preserved(self) -> None:
        # A portrait request must not land on a landscape size even though both
        # have a similar pixel count.  ``1440x2560`` is width x height, so it is
        # portrait, and StepFun's portrait 9:16 size is ``1360x768`` (H x W).
        assert normalize_stepfun_image_size("step-image-edit-2", "1440x2560")[0] == "1360x768"
        assert normalize_stepfun_image_size("step-image-edit-2", "2560x1440")[0] == "768x1360"

    def test_a_non_stepfun_model_is_left_alone(self) -> None:
        """The normalizer must not touch a provider it does not know."""

        assert normalize_stepfun_image_size("doubao-seedream-5-0-lite-260128", "2048x2048") == (
            "2048x2048",
            None,
        )

    def test_nonsense_size_falls_back_to_the_square(self) -> None:
        assert normalize_stepfun_image_size("step-image-edit-2", "not-a-size")[0] == "1024x1024"

    def test_2x_large_uses_its_own_table(self) -> None:
        # 1280x800 is a 2x-large size and not an edit-2 size.
        assert normalize_stepfun_image_size("step-2x-large", "1280x800") == ("1280x800", None)
        assert normalize_stepfun_image_size("step-image-edit-2", "1280x800")[0] != "1280x800"

    def test_nearest_size_helper_agrees_with_the_normalizer(self) -> None:
        assert nearest_supported_stepfun_image_size("step-image-edit-2", "1920x1920") == (
            "1024x1024"
        )


# ---------------------------------------------------------------------------
# Prompt clamping
# ---------------------------------------------------------------------------


class TestClampStepfunImagePrompt:
    def test_short_prompt_passes_through(self) -> None:
        prompt = "a quiet teahouse courtyard at dawn"
        assert clamp_stepfun_image_prompt("step-image-edit-2", prompt) == (prompt, None)

    def test_prompt_at_the_ceiling_is_untouched(self) -> None:
        prompt = "x" * STEPFUN_IMAGE_PROMPT_MAX_CHARS
        assert clamp_stepfun_image_prompt("step-image-edit-2", prompt) == (prompt, None)

    def test_over_long_prompt_is_cut_to_the_ceiling(self) -> None:
        prompt = "x" * 1200
        clamped, code = clamp_stepfun_image_prompt("step-image-edit-2", prompt)
        assert len(clamped) <= STEPFUN_IMAGE_PROMPT_MAX_CHARS
        assert code == "image_prompt_truncated_to_provider_limit"

    def test_truncation_keeps_whole_sections(self) -> None:
        """The compiled prompt is blank-line-joined sections.

        Cutting mid-sentence would drop the tail of one panel's description and
        leave the rest intact, which is harder to reason about than dropping
        whole trailing sections.
        """

        sections = [f"section {index} " + "y" * 80 for index in range(12)]
        prompt = "\n\n".join(sections)
        clamped, code = clamp_stepfun_image_prompt("step-image-edit-2", prompt)
        assert code is not None
        assert len(clamped) <= STEPFUN_IMAGE_PROMPT_MAX_CHARS
        kept = clamped.split("\n\n")
        assert kept == sections[: len(kept)], "truncation must not cut inside a section"

    def test_a_single_oversized_section_falls_back_to_a_hard_cut(self) -> None:
        # If the first section alone exceeds the ceiling there is no boundary to
        # keep, and an over-long prompt is refused outright -- so a cut one runs.
        prompt = "z" * 900
        clamped, code = clamp_stepfun_image_prompt("step-image-edit-2", prompt)
        assert len(clamped) == STEPFUN_IMAGE_PROMPT_MAX_CHARS
        assert code == "image_prompt_truncated_to_provider_limit"

    def test_a_real_storyboard_prompt_fits_after_clamping(self) -> None:
        """The shape that actually failed: a nine-panel storyboard node."""

        panels = "\n".join(
            f"Top-left frame content: Lin pushes the gate open and stops; "
            f"continuity=opening beat {index}."
            for index in range(9)
        )
        prompt = (
            "Render one complete 3x3 storyboard image for one coherent sequence. "
            "Keep all nine distinct frames in strict reading order with consistent "
            "identities, world details, visual style, and narrative continuity.\n\n"
            f"Structured role content:\n{panels}\n\n"
            "Visual style (structured_content):\ncinematic, soft dawn light, muted palette."
        )
        assert len(prompt) > STEPFUN_IMAGE_PROMPT_MAX_CHARS
        clamped, code = clamp_stepfun_image_prompt("step-image-edit-2", prompt)
        assert len(clamped) <= STEPFUN_IMAGE_PROMPT_MAX_CHARS
        assert code == "image_prompt_truncated_to_provider_limit"

    def test_negative_prompt_has_its_own_ceiling(self) -> None:
        clamped, code = clamp_stepfun_negative_prompt("step-image-edit-2", "n" * 600)
        assert len(clamped) == STEPFUN_IMAGE_PROMPT_MAX_CHARS
        assert code == "image_negative_prompt_truncated_to_provider_limit"

    def test_non_stepfun_prompt_is_untouched(self) -> None:
        prompt = "q" * 900
        assert clamp_stepfun_image_prompt("doubao-seedream-5-0-lite-260128", prompt) == (
            prompt,
            None,
        )


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


class TestContractViolations:
    def test_a_valid_request_reports_nothing(self) -> None:
        assert (
            stepfun_image_contract_violations(
                "step-image-edit-2",
                size="1024x1024",
                prompt="a teahouse at dawn",
            )
            == []
        )

    def test_an_unlisted_size_is_named_with_its_alternatives(self) -> None:
        violations = stepfun_image_contract_violations(
            "step-image-edit-2", size="1920x1920", prompt="a teahouse at dawn"
        )
        assert len(violations) == 1
        assert "1920x1920" in violations[0]
        assert "1024x1024" in violations[0], "the message must name what to use instead"

    def test_an_over_long_prompt_is_named_with_both_lengths(self) -> None:
        violations = stepfun_image_contract_violations(
            "step-image-edit-2", size="1024x1024", prompt="p" * 900
        )
        assert len(violations) == 1
        assert "900" in violations[0]
        assert "512" in violations[0]

    def test_a_non_stepfun_model_is_never_checked(self) -> None:
        assert (
            stepfun_image_contract_violations(
                "doubao-seedream-5-0-lite-260128", size="1920x1920", prompt="p" * 900
            )
            == []
        )


# ---------------------------------------------------------------------------
# The serializer applies all of it before the request leaves the process
# ---------------------------------------------------------------------------


class TestSerializerEnforcesTheContract:
    def _serialize(self, **overrides: object):
        kwargs: dict[str, object] = {
            "model": "step-image-edit-2",
            "canonical_prompt": "A quiet seaside boardwalk at dusk.",
            "size": "1024x1024",
            "references": [],
            "required_reference_asset_ids": [],
        }
        kwargs.update(overrides)
        return serialize_volcengine_image_generation_request(**kwargs)  # type: ignore[arg-type]

    def test_a_valid_request_is_unchanged_and_reports_no_warnings(self) -> None:
        body, audit = self._serialize()
        assert body["size"] == "1024x1024"
        assert body["prompt"] == "A quiet seaside boardwalk at dusk."
        assert audit.warnings == []

    def test_the_configured_size_is_normalized_on_the_wire(self) -> None:
        body, audit = self._serialize(size="1920x1920")
        assert body["size"] == "1024x1024"
        assert "image_size_normalized_to_provider_supported" in audit.warnings

    def test_the_ark_default_size_is_normalized_on_the_wire(self) -> None:
        body, audit = self._serialize(size="2048x2048")
        assert body["size"] == "1024x1024"
        assert "image_size_normalized_to_provider_supported" in audit.warnings

    def test_an_over_long_prompt_is_clamped_on_the_wire(self) -> None:
        body, audit = self._serialize(canonical_prompt="p" * 1200)
        assert len(body["prompt"]) <= STEPFUN_IMAGE_PROMPT_MAX_CHARS
        assert "image_prompt_truncated_to_provider_limit" in audit.warnings

    def test_the_anti_tamper_check_still_holds_after_normalization(self) -> None:
        """``_validate_base_body`` compares the body prompt to the canonical one.

        Normalizing the prompt before the body is built is what keeps that check
        meaningful -- clamping afterwards would make every request fail its own
        validation.
        """

        body, audit = self._serialize(canonical_prompt="p" * 1200, size="1920x1920")
        assert body["prompt"] == body["prompt"].strip()
        assert audit.warnings  # the substitution is visible, not silent

    def test_both_normalizations_are_reported_together(self) -> None:
        _, audit = self._serialize(canonical_prompt="p" * 1200, size="1920x1920")
        assert set(audit.warnings) == {
            "image_size_normalized_to_provider_supported",
            "image_prompt_truncated_to_provider_limit",
        }

    @pytest.mark.parametrize("model_id", sorted(STEPFUN_IMAGE_SIZES_BY_MODEL))
    def test_every_stepfun_model_gets_a_size_it_accepts(self, model_id: str) -> None:
        """Neither model may be handed a size outside its own table."""

        body, _audit = self._serialize(model=model_id, size="1920x1920")
        assert body["size"] in supported_stepfun_image_sizes(model_id)

    def test_a_retired_ark_model_is_not_normalized(self) -> None:
        # Retired models keep their manifest so a stale row can be rewritten;
        # they are not StepFun models and must pass through untouched.
        body, audit = self._serialize(
            model="doubao-seedream-5-0-pro-260628", size="2048x2048"
        )
        assert body["size"] == "2048x2048"
        assert audit.warnings == []

    def test_is_stepfun_image_model_recognizes_both(self) -> None:
        assert is_stepfun_image_model("step-image-edit-2")
        assert is_stepfun_image_model("step-2x-large")
        assert not is_stepfun_image_model("doubao-seedream-5-0-pro-260628")


# ---------------------------------------------------------------------------
# The configured size is validated against the right provider's rules
# ---------------------------------------------------------------------------


class TestConfiguredSizeValidation:
    """The Ark pixel floor must not be applied to a StepFun request.

    ``SEEDREAM_MIN_IMAGE_PIXELS`` is 3,686,400 -- exactly 1920x1920, a
    Volcengine Ark seedream requirement.  It was applied unconditionally, which
    made every StepFun size below 1920x1920 a local configuration error and is
    why ``IMAGE_GENERATION_SIZE`` carried a resolution the gateway does not
    accept.  Setting it to a documented StepFun size then failed validation
    before the request was ever built.
    """

    def test_a_documented_stepfun_size_passes_validation(self) -> None:
        assert (
            _normalize_image_generation_size("1024x1024", model="step-image-edit-2")
            == "1024x1024"
        )

    @pytest.mark.parametrize("size", sorted(DOCUMENTED_EDIT_2_SIZES))
    def test_every_documented_stepfun_size_passes_validation(self, size: str) -> None:
        assert _normalize_image_generation_size(size, model="step-image-edit-2") == size

    def test_an_unlisted_stepfun_size_still_passes_so_the_serializer_can_map_it(self) -> None:
        """The floor must not become a second, stricter size check.

        ``serialize_volcengine_image_generation_request`` maps an unlisted size
        onto the nearest supported one.  Rejecting here instead would trade the
        Ark floor for a StepFun allow-list and break the self-healing path.
        """

        assert (
            _normalize_image_generation_size("1920x1920", model="step-image-edit-2")
            == "1920x1920"
        )

    def test_the_ark_floor_still_applies_to_an_ark_model(self) -> None:
        with pytest.raises(MediaConfigurationError) as error:
            _normalize_image_generation_size("1024x1024", model="doubao-seedream-5-0-lite-260128")
        assert "3686400" in str(error.value)

    def test_the_ark_floor_applies_when_no_model_is_named(self) -> None:
        """An unspecified model keeps the historical behaviour."""

        with pytest.raises(MediaConfigurationError):
            _normalize_image_generation_size("1024x1024")

    def test_a_malformed_size_is_rejected_for_stepfun_too(self) -> None:
        with pytest.raises(MediaConfigurationError):
            _normalize_image_generation_size("not-a-size", model="step-image-edit-2")
