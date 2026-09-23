"""The Agnes image contract, and the fork it forces in the shared serializer.

``agnes-image-2.5-flash`` is the fallback for the StepFun image outage
([[adcraft-stepfun-image-503-is-provider-outage]]).  It is reached through the
same ``IMAGE_GENERATION_ENDPOINT`` setting and the same serializer as
``step-image-edit-2``, so every difference between the two contracts is a place
where a request that is correct for one vendor is refused by the other.  Three
such differences are pinned here, each established by a live probe rather than
by the documentation:

1. **``watermark`` and ``sequential_image_generation`` are refused.**  Agnes
   answers HTTP 400 ``invalid_request`` and names ``watermark`` first, so a body
   carrying both reports only the watermark
   (``e2e_output/rose/probe_agnes_body_shape.py``,
   ``probe_agnes_shape2.py``).  StepFun, in the same body, *requires*
   ``sequential_image_generation="disabled"``.  The two requirements are
   mutually exclusive, which is why the serializer branches instead of
   reconciling.

2. **The credential is a different one.**  ``api.agnes-ai.cn`` answers 401 to
   the StepFun key and 200 to ``VIDEO_GENERATION_API_KEY``
   (``probe_agnes_image.py``), so ``Settings.image_generation_credential``
   resolves the key from the endpoint host rather than from the capability
   name.

3. **Sizes are ``width x height``**, the opposite orientation convention from
   StepFun's ``height x width``.  Copying one table into the other's place
   would silently rotate every frame, so the two tables live in separate
   modules with separate orientation helpers.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.agnes_image_contract import (
    AGNES_IMAGE_MODEL_IDS,
    AGNES_IMAGE_RATIOS,
    AGNES_IMAGE_SIZES_BY_ASPECT_RATIO,
    AGNES_IMAGE_SIZE_TIERS,
    AGNES_IMAGE_UNSUPPORTED_FIELDS,
    agnes_image_contract_violations,
    is_agnes_image_model,
    nearest_supported_agnes_image_size,
    normalize_agnes_image_size,
)
from app.services.stepfun_image_contract import (
    STEPFUN_IMAGE_SIZES_BY_ASPECT_RATIO,
    is_stepfun_image_model,
)
from app.tools.volcengine_image_generations import serialize_volcengine_image_generation_request

AGNES = "agnes-image-2.5-flash"
STEPFUN = "step-image-edit-2"


def _serialize(model: str, *, size: str = "1024x1024", prompt: str = "A quiet birch forest at dawn."):
    return serialize_volcengine_image_generation_request(
        model=model,
        canonical_prompt=prompt,
        size=size,
        references=[],
        required_reference_asset_ids=[],
    )


# ---------------------------------------------------------------------------
# Which model belongs to which contract
# ---------------------------------------------------------------------------


def test_the_two_model_families_are_disjoint() -> None:
    """A model in both tables would take whichever branch is checked first."""

    assert not (AGNES_IMAGE_MODEL_IDS & set(STEPFUN_IMAGE_SIZES_BY_ASPECT_RATIO))
    assert not any(is_stepfun_image_model(model) for model in AGNES_IMAGE_MODEL_IDS)
    assert not any(is_agnes_image_model(model) for model in STEPFUN_IMAGE_SIZES_BY_ASPECT_RATIO)


def test_a_stepfun_model_is_not_an_agnes_model() -> None:
    assert not is_agnes_image_model(STEPFUN)
    assert not is_agnes_image_model("doubao-seedream-5-0-lite-260128")
    assert not is_agnes_image_model("")


# ---------------------------------------------------------------------------
# Size tables
# ---------------------------------------------------------------------------


def test_every_documented_ratio_has_a_size() -> None:
    assert set(AGNES_IMAGE_RATIOS) == set(AGNES_IMAGE_SIZES_BY_ASPECT_RATIO)


@pytest.mark.parametrize(("ratio", "size"), sorted(AGNES_IMAGE_SIZES_BY_ASPECT_RATIO.items()))
def test_each_size_matches_its_ratio(ratio: str, size: str) -> None:
    """Agnes documents ``width x height``, so the ratio reads straight off.

    Approximately, though -- and that is the point.  The documented frames are
    quantized to 16-pixel multiples rather than being exact: 16:9's 1K frame is
    ``1312x736`` (1.7826) and not ``1296x729`` (1.7778), because 1312 and 736
    are the nearest 16-multiples that fit.  Asserting exactness here would
    "fix" the table into something the provider never publishes, so the
    tolerance is asserted instead and the quantization is documented.
    """

    width, height = (int(part) for part in size.split("x"))
    expected_width, expected_height = (int(part) for part in ratio.split(":"))
    actual = width / height
    expected = expected_width / expected_height
    assert abs(actual - expected) / expected < 0.01, f"{ratio} -> {size} is {actual:.4f}"
    # Quantization is a real property, not an accident of rounding.
    assert width % 16 == 0 and height % 16 == 0


def test_landscape_stays_landscape() -> None:
    """The StepFun table is ``height x width``; Agnes' is not.

    ``16:9`` is ``768x1360`` on StepFun (portrait-looking) and ``1312x736`` on
    Agnes (landscape).  A shared table would rotate every frame, so this pins
    the two apart.
    """

    assert STEPFUN_IMAGE_SIZES_BY_ASPECT_RATIO["16:9"] == "768x1360"
    assert AGNES_IMAGE_SIZES_BY_ASPECT_RATIO["16:9"] == "1312x736"
    width, height = (int(part) for part in AGNES_IMAGE_SIZES_BY_ASPECT_RATIO["16:9"].split("x"))
    assert width > height


def test_the_configured_size_is_the_documented_square() -> None:
    """``IMAGE_GENERATION_SIZE`` is 1024x1024, which is Agnes' 1K 1:1 frame.

    If these ever drift, every image node would be silently resized rather than
    sending the size the operator configured.
    """

    assert AGNES_IMAGE_SIZES_BY_ASPECT_RATIO["1:1"] == "1024x1024"
    assert Settings().image_generation_size == AGNES_IMAGE_SIZES_BY_ASPECT_RATIO["1:1"]


class TestNormalizeAgnesImageSize:
    def test_a_documented_size_passes_through_untouched(self) -> None:
        assert normalize_agnes_image_size(AGNES, "1024x1024") == ("1024x1024", None)

    @pytest.mark.parametrize("size", sorted(AGNES_IMAGE_SIZES_BY_ASPECT_RATIO.values()))
    def test_every_documented_size_passes_validation(self, size: str) -> None:
        assert normalize_agnes_image_size(AGNES, size) == (size, None)

    def test_the_old_configured_size_is_mapped_and_reported(self) -> None:
        """``1920x1920`` was this deployment's configured size for weeks.

        Agnes accepts it live and normalizes server-side, but the wire audit has
        to say the frame the caller asked for is not the frame it will get.
        """

        size, code = normalize_agnes_image_size(AGNES, "1920x1920")
        assert size in AGNES_IMAGE_SIZES_BY_ASPECT_RATIO.values()
        assert code == "image_size_normalized_to_provider_supported"

    def test_a_landscape_request_stays_landscape(self) -> None:
        size, _code = normalize_agnes_image_size(AGNES, "2560x1440")
        width, height = (int(part) for part in size.split("x"))
        assert width > height

    def test_a_portrait_request_stays_portrait(self) -> None:
        size, _code = normalize_agnes_image_size(AGNES, "1440x2560")
        width, height = (int(part) for part in size.split("x"))
        assert width < height

    def test_a_malformed_size_falls_back_to_the_square(self) -> None:
        size, code = normalize_agnes_image_size(AGNES, "not-a-size")
        assert size == "1024x1024"
        assert code == "image_size_normalized_to_provider_supported"

    def test_a_stepfun_model_is_left_alone(self) -> None:
        """The Agnes normalizer must not touch a StepFun request."""

        assert normalize_agnes_image_size(STEPFUN, "1920x1920") == ("1920x1920", None)


class TestNearestSupportedAgnesImageSize:
    def test_an_exact_documented_size_is_returned_as_is(self) -> None:
        assert nearest_supported_agnes_image_size(AGNES, "1312x736") == "1312x736"

    def test_a_stepfun_model_has_no_agnes_answer(self) -> None:
        assert nearest_supported_agnes_image_size(STEPFUN, "1024x1024") is None

    @pytest.mark.parametrize("tier", AGNES_IMAGE_SIZE_TIERS)
    def test_every_documented_tier_is_known(self, tier: str) -> None:
        """The tiers are a documented input form, so the contract must name them."""

        assert tier in {"1K", "2K", "3K", "4K"}
        assert agnes_image_contract_violations(AGNES, size=tier, prompt="a rose") == []


class TestContractViolations:
    def test_a_documented_request_has_no_violations(self) -> None:
        assert agnes_image_contract_violations(AGNES, size="1024x1024", prompt="a rose") == []

    def test_an_off_table_size_is_reported_as_a_substitution(self) -> None:
        violations = agnes_image_contract_violations(AGNES, size="1920x1080", prompt="a rose")
        assert len(violations) == 1
        assert "1920x1080" in violations[0]

    def test_a_stepfun_model_reports_nothing(self) -> None:
        """The StepFun contract has its own checker; this one must stay quiet."""

        assert (
            agnes_image_contract_violations(STEPFUN, size="9999x9999", prompt="x" * 5000) == []
        )

    def test_an_unsupported_field_is_named(self) -> None:
        violations = agnes_image_contract_violations(
            AGNES,
            size="1024x1024",
            prompt="a rose",
            unsupported_fields={"watermark": False},
        )
        assert len(violations) == 1
        assert "watermark" in violations[0]

    @pytest.mark.parametrize("field", sorted(AGNES_IMAGE_UNSUPPORTED_FIELDS))
    def test_every_unsupported_field_is_reported(self, field: str) -> None:
        violations = agnes_image_contract_violations(
            AGNES,
            size="1024x1024",
            prompt="a rose",
            unsupported_fields={field: False},
        )
        assert any(field in violation for violation in violations)


# ---------------------------------------------------------------------------
# The serializer fork
# ---------------------------------------------------------------------------


class TestSerializerFork:
    def test_an_agnes_request_drops_both_unsupported_fields(self) -> None:
        body, _audit = _serialize(AGNES)
        for field in AGNES_IMAGE_UNSUPPORTED_FIELDS:
            assert field not in body, f"{field} must not be sent to Agnes"

    def test_a_stepfun_request_still_sends_the_flag(self) -> None:
        body, _audit = _serialize(STEPFUN)
        assert body["sequential_image_generation"] == "disabled"
        assert body["watermark"] is False

    def test_both_requests_agree_on_the_shared_fields(self) -> None:
        """The fork is narrow on purpose -- everything but the model agrees.

        ``model`` is excluded on purpose: it is the one field that *must*
        differ, since it is what selects the contract.
        """

        agnes_body, _ = _serialize(AGNES)
        stepfun_body, _ = _serialize(STEPFUN)
        assert agnes_body["model"] != stepfun_body["model"]
        for field in ("prompt", "response_format", "size"):
            assert agnes_body[field] == stepfun_body[field]

    def test_the_size_is_normalized_against_the_agnes_table(self) -> None:
        body, audit = _serialize(AGNES, size="1920x1920")
        assert body["size"] in AGNES_IMAGE_SIZES_BY_ASPECT_RATIO.values()
        assert "image_size_normalized_to_provider_supported" in audit.warnings

    def test_the_stepfun_size_is_normalized_against_the_stepfun_table(self) -> None:
        body, audit = _serialize(STEPFUN, size="1920x1920")
        assert body["size"] in STEPFUN_IMAGE_SIZES_BY_ASPECT_RATIO.values()
        assert "image_size_normalized_to_provider_supported" in audit.warnings

    def test_the_same_requested_size_yields_different_frames(self) -> None:
        """16:9 must not come out portrait for one vendor and landscape for the other."""

        agnes_body, _ = _serialize(AGNES, size="2560x1440")
        stepfun_body, _ = _serialize(STEPFUN, size="2560x1440")
        agnes_width, agnes_height = (int(part) for part in agnes_body["size"].split("x"))
        stepfun_height, stepfun_width = (int(part) for part in stepfun_body["size"].split("x"))
        assert agnes_width > agnes_height
        assert stepfun_width > stepfun_height

    def test_references_still_reach_an_agnes_request(self) -> None:
        """img2img is documented for Agnes via ``extra_body.image``; the shared
        serializer puts them in the top-level ``image`` field, which Agnes also
        accepts live.  Dropping them here would silently turn every reference
        image into a text-only generation."""

        body, audit = serialize_volcengine_image_generation_request(
            model=AGNES,
            canonical_prompt="Restyle this reference.",
            size="1024x1024",
            references=[
                {
                    "asset_id": "ref-1",
                    "provider_input_value": "https://example.com/a.png",
                    "provider_input_type": "image_url",
                }
            ],
            required_reference_asset_ids=["ref-1"],
        )
        assert body["image"] == "https://example.com/a.png"
        assert audit.delivered_reference_asset_ids == ["ref-1"]
        for field in AGNES_IMAGE_UNSUPPORTED_FIELDS:
            assert field not in body


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------


class TestImageCredentialResolution:
    """A credential is per-vendor, and one setting now names two vendors."""

    STEPFUN_ENDPOINT = "https://api.stepfun.com/step_plan/v1/images/generations"
    AGNES_ENDPOINT = "https://api.agnes-ai.cn/v1/images/generations"

    def _settings(self, *, endpoint: str, image_key: str, video_key: str) -> Settings:
        return Settings(
            image_generation_api_key=image_key,
            image_generation_endpoint=endpoint,
            video_generation_api_key=video_key,
        )

    def test_a_stepfun_endpoint_uses_the_image_key(self) -> None:
        settings = self._settings(
            endpoint=self.STEPFUN_ENDPOINT, image_key="stepfun-key", video_key="agnes-key"
        )
        assert settings.image_generation_credential == "stepfun-key"

    def test_an_agnes_endpoint_uses_the_video_key(self) -> None:
        """The StepFun key gets 401 from api.agnes-ai.cn; the video key gets 200."""

        settings = self._settings(
            endpoint=self.AGNES_ENDPOINT, image_key="stepfun-key", video_key="agnes-key"
        )
        assert settings.image_generation_credential == "agnes-key"

    def test_an_agnes_endpoint_falls_back_to_the_image_key(self) -> None:
        """A partially configured deployment must still send something."""

        settings = self._settings(endpoint=self.AGNES_ENDPOINT, image_key="stepfun-key", video_key="")
        assert settings.image_generation_credential == "stepfun-key"

    def test_an_unrecognized_endpoint_keeps_the_image_key(self) -> None:
        """An unlisted vendor must not change behaviour."""

        settings = self._settings(
            endpoint="https://ark.cn-beijing.volces.com/api/v3/images/generations",
            image_key="ark-key",
            video_key="agnes-key",
        )
        assert settings.image_generation_credential == "ark-key"

    def test_no_endpoint_configured_keeps_the_image_key(self) -> None:
        settings = self._settings(endpoint="", image_key="ark-key", video_key="agnes-key")
        assert settings.image_generation_credential == "ark-key"

    @pytest.mark.parametrize(
        ("endpoint", "expected"),
        [
            (STEPFUN_ENDPOINT, "stepfun"),
            (AGNES_ENDPOINT, "agnes"),
            ("https://ark.cn-beijing.volces.com/api/v3/images/generations", "volcengine"),
            ("", "unknown"),
        ],
    )
    def test_the_provider_label_follows_the_endpoint(self, endpoint: str, expected: str) -> None:
        settings = self._settings(endpoint=endpoint, image_key="k", video_key="v")
        assert settings.image_generation_provider_label == expected
