"""The media output gate on the Agent Canvas provider path.

Before this gate the canvas media path named a payload after a fixed table: any
video became ``video/mp4``, any audio ``audio/mpeg``, no matter what the bytes
were, and the node went ``ready``.  These tests lock the replacement -- the
payload's own container decides -- and the two failures it has to catch: a
truncated download (an MP4 whose movie atom never arrived) and a payload of the
wrong type entirely (an image standing in for a video).

Every fixture below is a real, hand-built container: the box sizes, the IHDR
chunk and the SOF marker are the ones a decoder reads, so a check that passes
here is reading structure rather than a substring.
"""

from __future__ import annotations

import struct
from datetime import datetime, timezone
from typing import Any

import pytest

from app.core.config import Settings
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.workflow_v2 import V2ProviderResult
from app.services.agent_canvas_media_output_gate import (
    inspect_media_output,
    media_output_gate_failure,
    media_output_identity,
)
from app.services.agent_canvas_node_execution import (
    MediaNodeExecutor,
    NodeExecutionContext,
    accepted_provider_media,
)
from app.services.agent_canvas_publication_metadata import (
    asset_publication_metadata,
    project_canvas_publication_metadata,
)

pytestmark = pytest.mark.media


# ---------------------------------------------------------------------------
# Real containers, byte for byte
# ---------------------------------------------------------------------------


def _png(*, width: int = 64, height: int = 48, pad: int = 1400) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = b"IHDR" + struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    body = signature + struct.pack(">I", len(ihdr)) + ihdr
    # A tEXt chunk keeps the file above the size floor and gives the CRC bytes
    # something real to follow; the gate reads only IHDR.
    text = b"tEXt" + b"Comment\x00" + b"gate fixture"
    body += struct.pack(">I", len(text)) + text
    body += b"\x00" * pad
    return body


def _jpeg(*, width: int = 64, height: int = 48, pad: int = 1400) -> bytes:
    out = bytearray(b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9)
    # SOF0: precision, height, width, component count, then the components.
    sof = b"\x08" + struct.pack(">HH", height, width) + b"\x03" + b"\x01\x22\x00" * 3
    out += b"\xff\xc0" + struct.pack(">H", len(sof) + 2) + sof
    out += b"\x00" * pad
    out += b"\xff\xd9"
    return bytes(out)


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + kind + payload


def _mp4(
    *,
    with_moov: bool = True,
    declared_mdat: int = 2048,
    written_mdat: int | None = None,
) -> bytes:
    """An ISO-BMFF file whose boxes declare exactly what they contain.

    ``written_mdat`` shorter than ``declared_mdat`` is a download cut off
    mid-``mdat``: the header still promises the whole payload, the bytes stop
    early, and nothing after it can be reached.
    """

    written = declared_mdat if written_mdat is None else written_mdat
    out = _box(b"ftyp", b"isom" + b"\x00" * 8)
    out += _box(b"moov", b"\x00" * 32) if with_moov else b""
    out += struct.pack(">I", declared_mdat) + b"mdat" + b"\x00" * max(written - 8, 0)
    return out


def _mp3(*, pad: int = 700) -> bytes:
    return b"ID3\x04\x00\x00" + b"\x00" * 10 + b"\xff\xfb\x90\x00" + b"\x00" * pad


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


class TestAcceptedContainers:
    def test_a_png_reports_its_own_dimensions(self) -> None:
        report = inspect_media_output(media_type="image", content=_png(width=320, height=200))
        assert report.passed
        assert (report.width, report.height) == (320, 200)
        assert report.detected_format == "png"
        assert report.to_dict()["status"] == "passed"

    def test_a_jpeg_reports_its_own_dimensions(self) -> None:
        report = inspect_media_output(media_type="image", content=_jpeg(width=128, height=96))
        assert report.passed
        assert (report.width, report.height) == (128, 96)

    def test_a_whole_mp4_passes(self) -> None:
        report = inspect_media_output(media_type="video", content=_mp4())
        assert report.passed
        atoms = next(
            check
            for check in report.checks
            if check["code"] == "media_output_mp4_atoms_complete"
        )
        assert atoms["atoms"] == ["ftyp", "mdat", "moov"]

    def test_an_mp3_passes(self) -> None:
        report = inspect_media_output(media_type="audio", content=_mp3())
        assert report.passed
        assert report.detected_format == "mp3"

    def test_a_zero_dimension_image_is_refused(self) -> None:
        report = inspect_media_output(media_type="image", content=_png(width=0, height=0))
        assert not report.passed
        assert report.failure_code == "media_output_image_dimensions_invalid"


class TestRefusedPayloads:
    def test_an_empty_payload_is_refused(self) -> None:
        report = inspect_media_output(media_type="video", content=b"")
        assert report.failure_code == "media_output_empty"

    def test_a_stub_payload_is_refused(self) -> None:
        # The 8-byte PNG magic and nothing else: a file that exists but is not
        # an image.
        report = inspect_media_output(media_type="image", content=b"\x89PNG\r\n\x1a\n")
        assert report.failure_code == "media_output_too_small"

    def test_an_image_returned_for_a_video_node_is_refused(self) -> None:
        report = inspect_media_output(media_type="video", content=_png())
        assert report.failure_code == "media_output_format_mismatch"

    def test_a_video_returned_for_an_image_node_is_refused(self) -> None:
        report = inspect_media_output(media_type="image", content=_mp4())
        assert report.failure_code == "media_output_format_mismatch"

    def test_a_truncated_mp4_is_refused(self) -> None:
        report = inspect_media_output(
            media_type="video", content=_mp4(declared_mdat=8192, written_mdat=2048)
        )
        assert report.failure_code == "media_output_container_incomplete"

    def test_an_mp4_with_no_movie_atom_is_refused(self) -> None:
        report = inspect_media_output(media_type="video", content=_mp4(with_moov=False))
        assert report.failure_code == "media_output_container_incomplete"

    def test_an_mp4_whose_mdat_size_runs_past_the_end_is_refused(self) -> None:
        # A size the walk cannot land on is the same signature as truncation,
        # but reached through a different door.
        content = bytearray(_mp4())
        mdat_at = content.index(b"mdat")
        content[mdat_at - 4 : mdat_at] = struct.pack(">I", 10**7)
        report = inspect_media_output(media_type="video", content=bytes(content))
        assert report.failure_code == "media_output_container_incomplete"

    def test_a_jpeg_whose_sof_never_arrives_is_refused(self) -> None:
        content = bytearray(b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9)
        content += b"\x00" * 1400 + b"\xff\xd9"
        report = inspect_media_output(media_type="image", content=bytes(content))
        assert report.failure_code == "media_output_image_dimensions_invalid"


class TestUnrecognisedContainerIsVisibleNotFatal:
    def test_an_unknown_container_warns_and_passes(self) -> None:
        # Matroska/WebM reaches us without a magic this module knows.  Refusing
        # would turn a working provider red; passing silently would hide it.
        content = b"\x1aE\xdf\xa3" + b"\x00" * 1500
        report = inspect_media_output(media_type="video", content=content)
        assert report.passed
        payload = report.to_dict()
        assert payload["status"] == "passed"
        assert payload["warnings"][0]["code"] == "media_output_format_undetected"
        assert any(
            check["code"] == "media_output_format_undetected" for check in report.checks
        )


class TestMutationCheck:
    """§3(B): state what the check locks, then break the input and watch it go red."""

    def test_breaking_the_movie_atom_size_flips_the_verdict(self) -> None:
        # The lock: ``media_output_mp4_atoms_complete`` asserts the box walk
        # lands exactly on the end of the file *and* found a ``moov``.  Corrupt
        # the ``moov`` box's declared size so the walk stops short.
        content = bytearray(_mp4())
        moov_at = content.index(b"moov")
        content[moov_at - 4 : moov_at] = struct.pack(">I", 4)
        report = inspect_media_output(media_type="video", content=bytes(content))
        assert report.failure_code == "media_output_container_incomplete"
        assert not report.passed


class TestIdentityFollowsTheBytes:
    def test_the_mime_type_comes_from_the_container(self) -> None:
        assert media_output_identity(_jpeg(), "image") == ("image/jpeg", "image.jpg")
        assert media_output_identity(_png(), "image") == ("image/png", "image.png")
        assert media_output_identity(_mp4(), "video") == ("video/mp4", "video.mp4")
        assert media_output_identity(_mp3(), "audio") == ("audio/mpeg", "audio.mp3")

    def test_an_unrecognised_payload_keeps_the_historical_label(self) -> None:
        assert media_output_identity(b"\x1aE\xdf\xa3" + b"\x00" * 900, "video") == (
            "video/mp4",
            "video.mp4",
        )


class TestFailureProjection:
    def test_the_failure_names_a_regenerable_node_not_a_retryable_one(self) -> None:
        report = inspect_media_output(media_type="video", content=b"")
        error = media_output_gate_failure(report)
        assert isinstance(error, V2PersistenceError)
        assert error.code == "media_output_empty"
        # The actionable disposition has to survive safe_execution_error(): a
        # disposition marked retryable under a code that is not an approved
        # transient one is silently dropped there, which would leave the
        # operator with a bare code.
        details = error.details or {}
        assert details["actionable_failure"]["user_action"] == "regenerate"
        assert details["actionable_failure"]["retryable"] is False
        assert details["media_output_gate"]["error_code"] == "media_output_empty"

    def test_the_message_says_the_node_was_not_published(self) -> None:
        report = inspect_media_output(media_type="video", content=b"")
        message = str(error) if (error := media_output_gate_failure(report)) else ""
        assert "not marked ready" in message
        assert "regenerate" in message


# ---------------------------------------------------------------------------
# The wiring: the gate runs where the payload is still bytes
# ---------------------------------------------------------------------------


def _node() -> CanvasNodeV2:
    return CanvasNodeV2(
        node_id="node-media",
        workflow_id="wf_gate",
        node_type="image",  # type: ignore[arg-type]
        creative_role="general_image",  # type: ignore[arg-type]
        title="Gate node",
        status="draft",
        generation_prompt="a dusk boardwalk",
        structured_content={},
        position={"x": 0.0, "y": 0.0},
        revision=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


class _ScriptedProvider:
    def __init__(self, result: V2ProviderResult) -> None:
        self._result = result
        self.calls = 0

    def execute_minimal(self, **_: Any) -> V2ProviderResult:
        self.calls += 1
        return self._result


def _executor(tmp_path: Any, provider: _ScriptedProvider) -> MediaNodeExecutor:
    return MediaNodeExecutor(
        provider,  # type: ignore[arg-type]
        data_dir=tmp_path,
        settings=Settings(),
        seedance_inputs=None,
    )


def _context() -> NodeExecutionContext:
    from app.schemas.agent_canvas_runtime import ResolvedModelExecutionV1

    resolution = ResolvedModelExecutionV1(
        model_ref="stepfun:step-image-edit-2",
        provider_id="stepfun",
        provider_model_id="step-image-edit-2",
        capability="image",
        provider_protocol="stepfun_image",
        credential_revision=1,
        catalog_revision=1,
    )
    return NodeExecutionContext(
        execution_id="exec-gate",
        node=_node(),
        inputs=(),
        model_resolution=resolution,
    )


def _completed(content: bytes) -> V2ProviderResult:
    return V2ProviderResult(
        status="completed",
        media_type="image",
        asset_bytes=content,
        provider="stepfun",
        provider_model="step-image-edit-2",
    )


class TestGateRunsBeforeTheNodeGoesReady:
    def test_a_whole_image_is_published_with_its_own_mime_type(self, tmp_path: Any) -> None:
        provider = _ScriptedProvider(_completed(_png()))
        outcome = _executor(tmp_path, provider)(_context())
        assert outcome.media is not None
        assert outcome.media.mime_type == "image/png"
        # The verdict travels with the payload; that it reaches the published
        # asset row is TestTheVerdictOutlivesTheRun's business, because that
        # crossing is where it used to be dropped (§4: a check whose result
        # nobody can query later is not a check).
        assert outcome.media.metadata["media_output_gate"]["status"] == "passed"

    def test_an_empty_payload_fails_the_node_and_publishes_nothing(
        self, tmp_path: Any
    ) -> None:
        provider = _ScriptedProvider(_completed(b""))
        with pytest.raises(V2PersistenceError) as excinfo:
            _executor(tmp_path, provider)(_context())
        assert excinfo.value.code == "media_output_empty"
        assert provider.calls == 1

    def test_a_video_returned_for_an_image_node_fails_the_node(self, tmp_path: Any) -> None:
        provider = _ScriptedProvider(_completed(_mp4()))
        with pytest.raises(V2PersistenceError) as excinfo:
            _executor(tmp_path, provider)(_context())
        assert excinfo.value.code == "media_output_format_mismatch"


# ---------------------------------------------------------------------------
# The crossing: the verdict has to survive onto the published asset
# ---------------------------------------------------------------------------


class TestTheVerdictOutlivesTheRun:
    """``project_canvas_publication_metadata`` projects declared facts only.

    The gate's verdict was not a declared fact, so every published asset row
    said nothing about whether the file is a whole media file.  These tests
    assert it crosses, and that what crosses is the verdict rather than the
    per-check prose (which the content-free publication envelope rejects).
    """

    def test_a_passed_png_reaches_the_asset_metadata(self, tmp_path: Any) -> None:
        content = _png()
        outcome = _executor(tmp_path, _ScriptedProvider(_completed(content)))(_context())
        assert outcome.media is not None
        published = project_canvas_publication_metadata(
            _context(), None, outcome.media.metadata
        )
        assert published["media_output_gate"] == {
            "status": "passed",
            "media_type": "image",
            "size_bytes": len(content),
            "detected_media_format": "png",
            "mime_type": "image/png",
            "width": 64,
            "height": 48,
        }

    def test_a_container_that_only_warned_says_which_check_warned(self) -> None:
        # A Matroska/WebM payload on a video node: no recognised magic for
        # ``detect_media_format_from_bytes``, so it is *not* refused -- but it is
        # not silently labelled either, and the warning code has to reach the
        # asset row for that provider to stay visible.
        _, _, gate = accepted_provider_media("video", b"\x1aE\xdf\xa3" + b"\x00" * 1500)
        published = project_canvas_publication_metadata(
            _context(),
            None,
            {"provider": "stepfun", "model_id": "step-image-edit-2", "media_output_gate": gate},
        )
        assert published["media_output_gate"] == {
            "status": "passed",
            "media_type": "video",
            "size_bytes": 1504,
            "warning_codes": ["media_output_format_undetected"],
        }

    def test_a_verdict_that_is_not_the_gate_s_shape_fails_the_publication(self) -> None:
        with pytest.raises(V2PersistenceError) as excinfo:
            project_canvas_publication_metadata(
                _context(),
                None,
                {
                    "provider": "stepfun",
                    "model_id": "step-image-edit-2",
                    # A verdict is never dropped silently: a payload the gate did
                    # not write must fail the publication, not publish unlabelled.
                    "media_output_gate": {"status": "passed"},
                },
            )
        assert excinfo.value.code == "node_result_publication_metadata_invalid"

    def test_the_scheduler_call_site_stores_the_same_summary(self) -> None:
        # The scheduler and provider-task recovery publish through
        # ``asset_publication_metadata``, which merges the payload verbatim.  It
        # had no projection step, so the raw report -- sentences and all -- would
        # have reached the asset row there while this route stored the verdict.
        _, _, gate = accepted_provider_media("image", _png())
        merged = asset_publication_metadata(
            _context(),
            {"provider": "stepfun", "model_id": "step-image-edit-2", "media_output_gate": gate},
        )
        assert merged["media_output_gate"] == {
            "status": "passed",
            "media_type": "image",
            "size_bytes": len(_png()),
            "detected_media_format": "png",
            "mime_type": "image/png",
            "width": 64,
            "height": 48,
        }
        assert "checks" not in merged["media_output_gate"]
