"""The reference-image aspect-ratio window a provider declares must gate what we send.

09-23 (E2E, ``rose``): the storyboard_video node failed with ``400 invalid_request``
``输入图宽高比必须在 0.4–2.5 之间`` and nothing in our stack had ever looked at the
shape of a bound image.  ``asset_versions.width``/``height`` are ``NULL`` for these
assets and no metadata records a ratio, so the two 2896x540 character turnaround
sheets (5.36:1, a strip of five views) went to the provider unchecked and the request
was refused *as a whole* -- the six 1.76:1 scene boards attached to the same call were
thrown away with it, and the operator saw none of this in ``error_json``.

Two things are now fixed and locked in here:

* the window is read out of the frozen model manifest
  (``reference_image_aspect_ratio_range``) and refuses to treat an absent one as
  "unbounded"; and
* one out-of-range binding is refused on its own, naming the binding and the measured
  ratio, instead of costing the whole request.

The fixtures are hand-built JPEG *headers* rather than Pillow output: the reader only
parses segment markers, so a valid ``SOF0`` with invented dimensions is enough and the
test needs no image dependency.
"""

from __future__ import annotations

import struct

import pytest

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import ResolvedMediaInputSnapshotV2
from app.schemas.agent_canvas_runtime import ProviderReferenceDeliveryContextV1
from app.services.v2_provider_reference_input_delivery import (
    CANVAS_PROVIDER_REFERENCE_DELIVERY_UNAVAILABLE,
    V2DeliveredProviderReference,
    V2DeliveredReferenceSet,
    V2ProviderReferenceDeliveryError,
    _canvas_delivery_failure,
    _declared_image_aspect_ratio_range,
    _inline_image_aspect_ratio,
    _out_of_range_image_aspect_ratio,
)

#: What the Agnes video endpoint enforces on its ``images`` field.
WINDOW = (0.4, 2.5)


def _jpeg_header(width: int, height: int) -> bytes:
    """Just enough JPEG for the header reader: SOI, an APP0, one SOF0, EOI."""

    soi = b"\xff\xd8"
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sob0 = (
        b"\xff\xc0"
        + struct.pack(">H", 17)
        + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    )
    return soi + app0 + sob0 + b"\xff\xd9"


def _inline_reference(*, asset_id: str, width: int, height: int, source: str = "local_file") -> V2DeliveredProviderReference:
    payload = _jpeg_header(width, height)
    return V2DeliveredProviderReference(
        asset_id=asset_id,
        media_type="image",
        mime_type="image/jpeg",
        provider_input_type="data_url" if source == "local_file" else "provider_file_id",
        provider_input_value=(
            f"data:image/jpeg;base64,{__import__('base64').b64encode(payload).decode()}"
            if source == "local_file"
            else "ark-file-1"
        ),
        source=source,
        byte_count=len(payload),
    )


def _snapshot(*, binding_id: str = "bnd_1", media_type: str = "image") -> ResolvedMediaInputSnapshotV2:
    return ResolvedMediaInputSnapshotV2(
        source_kind="image_asset",
        binding_kind="image_reference",
        asset_id="asset_1",
        asset_version_id="version_1",
        media_type=media_type,
        asset_checksum="checksum_1",
        access_descriptor={
            "descriptor_type": "asset_content",
            "asset_id": "asset_1",
            "media_url": "/api/v2/assets/asset_1/content",
            "checksum": "checksum_1",
        },
        binding_id=binding_id,
        input_role="image_reference",
    )


class TestDeclaredWindow:
    def test_a_declared_pair_becomes_a_window(self) -> None:
        assert _declared_image_aspect_ratio_range({"reference_image_aspect_ratio_range": [0.4, 2.5]}) == (0.4, 2.5)

    def test_an_undeclared_window_is_none_not_unbounded(self) -> None:
        assert _declared_image_aspect_ratio_range({}) is None

    @pytest.mark.parametrize(
        "declared",
        [
            [2.5],
            [0.4, 1.0, 2.5],
            "0.4-2.5",
            [True, 2.5],
            [None, 2.5],
            {"min": 0.4, "max": 2.5},
        ],
    )
    def test_a_malformed_declaration_is_refused_not_ignored(self, declared: object) -> None:
        with pytest.raises(V2PersistenceError):
            _declared_image_aspect_ratio_range({"reference_image_aspect_ratio_range": declared})

    def test_the_window_must_be_positive_and_ordered(self) -> None:
        with pytest.raises(ValueError):
            ProviderReferenceDeliveryContextV1(
                provider_id="volcengine_ark",
                provider_model_id="agnes-video-2.5-flash",
                provider_protocol="ark_video",
                target_capability="video",
                accepted_input_types=("image",),
                reference_image_aspect_ratio_range=(2.5, 0.4),
            )


class TestInlineAspectRatio:
    def test_measures_the_bytes_we_would_send(self) -> None:
        ratio = _inline_image_aspect_ratio(_inline_reference(asset_id="a", width=1294, height=736))
        assert ratio is not None
        assert ratio == pytest.approx(1.758, abs=0.01)

    def test_measures_the_shape_that_broke_the_run(self) -> None:
        ratio = _inline_image_aspect_ratio(_inline_reference(asset_id="a", width=2896, height=540))
        assert ratio is not None
        assert ratio == pytest.approx(5.363, abs=0.01)

    def test_a_reference_the_provider_already_holds_has_no_ratio(self) -> None:
        assert _inline_image_aspect_ratio(_inline_reference(asset_id="a", width=2896, height=540, source="provider_upload")) is None

    def test_unreadable_bytes_are_not_guessed_at(self) -> None:
        broken = V2DeliveredProviderReference(
            asset_id="a",
            media_type="image",
            mime_type="image/jpeg",
            provider_input_type="data_url",
            provider_input_value="data:image/jpeg;base64,notajpeg",
            source="local_file",
        )
        assert _inline_image_aspect_ratio(broken) is None


class TestOutOfRangeDisposition:
    def test_the_turnaround_sheet_is_refused_and_named(self) -> None:
        # The binding's own identity, because that is what the operator has to
        # find on the canvas -- the provider's refusal named nothing.
        explanation = _out_of_range_image_aspect_ratio(
            _snapshot().model_copy(
                update={"asset_id": "asset_her", "binding_id": "bnd_her_turnaround"}
            ),
            _inline_reference(asset_id="asset_her", width=2896, height=540),
            WINDOW,
        )
        assert explanation is not None
        assert "asset_her" in explanation
        assert "bnd_her_turnaround" in explanation
        assert "5.36" in explanation
        assert "0.4-2.5" in explanation

    def test_the_scene_board_still_passes(self) -> None:
        assert (
            _out_of_range_image_aspect_ratio(
                _snapshot(),
                _inline_reference(asset_id="a", width=1294, height=736),
                WINDOW,
            )
            is None
        )

    def test_no_window_declared_means_no_verdict(self) -> None:
        assert (
            _out_of_range_image_aspect_ratio(
                _snapshot(),
                _inline_reference(asset_id="a", width=2896, height=540),
                None,
            )
            is None
        )

    def test_only_images_are_measured(self) -> None:
        assert (
            _out_of_range_image_aspect_ratio(
                _snapshot(media_type="video"),
                _inline_reference(asset_id="a", width=2896, height=540),
                WINDOW,
            )
            is None
        )


class TestRaiseForCanvasFailures:
    def _failure(self, *, asset_id: str, reason: str, message: str):
        return _canvas_delivery_failure(
            _snapshot().model_copy(update={"asset_id": asset_id}),
            reason,
            detail=message,
        )

    def test_the_operator_is_told_which_binding_and_why(self) -> None:
        failure = self._failure(
            asset_id="asset_her",
            reason="media_reference_aspect_ratio_out_of_range",
            message="bound image asset_her binding bnd_1 is 5.36:1.",
        )
        result = V2DeliveredReferenceSet(
            requested_reference_asset_ids=["asset_her", "asset_shot1"],
            failures=[failure],
        )
        with pytest.raises(V2ProviderReferenceDeliveryError) as raised:
            result.raise_for_canvas_failures()
        assert raised.value.code == CANVAS_PROVIDER_REFERENCE_DELIVERY_UNAVAILABLE
        message = str(raised.value)
        # The provider's own refusal named neither the binding nor the reason.
        assert "media_reference_aspect_ratio_out_of_range" in message
        assert "asset_her" in message

    def test_a_clean_delivery_does_not_raise(self) -> None:
        V2DeliveredReferenceSet(requested_reference_asset_ids=["a"]).raise_for_canvas_failures()
