"""Quality gate for provider media bytes before a canvas node accepts them.

The Agent Canvas media path used to label whatever bytes a provider returned
with a fixed table: every video became ``video/mp4``, every audio
``audio/mpeg``, no matter what the bytes were.  A truncated download, a
provider error page or a PNG standing in for a video was therefore stored as
the node's output asset, the node went ``ready``, and the segment was cut into
the film.  The v1 generation pipeline has gated this since
``v2_media_quality_gate`` landed; the canvas path had nothing.

What these checks are and are not:

* they are **deterministic byte checks**.  They answer "is this the kind of
  container the node promised", "is it whole", "does it carry decodable
  dimensions" -- never "is this picture good".
* they are **not** a style judge.  Two segments disagreeing about grade is not
  something a byte check can see, and pretending otherwise would be a gate that
  reports success while the film is still inconsistent.  What this gate does
  guarantee is that no truncated, empty or wrong-type payload can be silently
  concatenated into a film.
* a **warning** is never a reason to refuse: an undetected container (WebM
  reaches us without a recognised magic) keeps the historical behaviour and is
  recorded, so a provider that returns an exotic container is visible instead of
  mysteriously red.

Every passing verdict is projected onto the published asset version as
``metadata["media_output_gate"]``, so the outcome for any published segment is
queryable after the fact, per ``docs/agents/engineering-standards.md`` §4.  The
projection is a *summary* -- verdict, size, detected container, dimensions,
warning codes -- because the publication envelope is content-free and rejects
prose; the per-check messages are the node's error, and there is nothing to read
them off a passed asset for.  ``agent_canvas_publication_metadata`` owns the
projection, and drops nothing silently: a verdict whose shape is not what
``MediaOutputGateReport.to_dict`` writes fails the publication.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_errors import ActionableFailureV1
from app.services.v2_media_quality_gate import detect_media_format_from_bytes

#: Floors below which a payload from a media provider is a stub rather than a
#: rendered asset.  They exist to catch empty and near-empty bodies; the
#: container, atom and dimension checks do the real work.
_MINIMUM_OUTPUT_BYTES = {"image": 512, "audio": 512, "video": 1024}

#: Ceiling on top-level atoms walked in one file.  A well-formed file has a
#: handful; a corrupt size field can otherwise spin.
_MAX_MP4_ATOMS = 4096

#: JPEG start-of-frame markers (SOF0..SOF15 minus the ones that are not frames:
#: DHT, JPGext, DAC).
_JPEG_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)

_FALLBACK_IDENTITY = {
    "image": ("image/png", "image.png"),
    "video": ("video/mp4", "video.mp4"),
    "audio": ("audio/mpeg", "audio.mp3"),
}


@dataclass(frozen=True, slots=True)
class MediaOutputGateReport:
    """The verdict for one provider payload, plus every check behind it."""

    media_type: str
    size_bytes: int
    checks: tuple[dict[str, object], ...] = field(default_factory=tuple)
    warnings: tuple[dict[str, object], ...] = field(default_factory=tuple)
    detected_format: str | None = None
    detected_mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    failure_code: str | None = None
    failure_message: str | None = None

    @property
    def passed(self) -> bool:
        return self.failure_code is None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": "passed" if self.passed else "failed",
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "checks": list(self.checks),
        }
        if self.warnings:
            payload["warnings"] = list(self.warnings)
        if self.detected_format is not None:
            payload["detected_media_format"] = self.detected_format
        if self.detected_mime_type is not None:
            payload["mime_type"] = self.detected_mime_type
        if self.width is not None and self.height is not None:
            payload["width"] = self.width
            payload["height"] = self.height
        if self.failure_code is not None:
            payload["error_code"] = self.failure_code
            payload["error_message"] = self.failure_message
        return payload

    def _failed(self, code: str, message: str) -> "MediaOutputGateReport":
        return MediaOutputGateReport(
            media_type=self.media_type,
            size_bytes=self.size_bytes,
            checks=(*self.checks, {"code": code, "status": "failed", "message": message}),
            warnings=self.warnings,
            detected_format=self.detected_format,
            detected_mime_type=self.detected_mime_type,
            width=self.width,
            height=self.height,
            failure_code=code,
            failure_message=message,
        )


def inspect_media_output(
    *,
    media_type: str,
    content: bytes,
) -> MediaOutputGateReport:
    """Run the deterministic checks over one provider payload."""

    if media_type not in _FALLBACK_IDENTITY:
        raise ValueError(f"Unsupported canvas media type: {media_type!r}")
    size = len(content)
    report = MediaOutputGateReport(media_type=media_type, size_bytes=size)
    if size <= 0:
        return report._failed("media_output_empty", "Provider returned an empty payload.")
    minimum = _MINIMUM_OUTPUT_BYTES[media_type]
    if size < minimum:
        return report._failed(
            "media_output_too_small",
            f"Provider returned {size} bytes for a {media_type} asset, "
            f"below the {minimum}-byte floor.",
        )

    detected = detect_media_format_from_bytes(content[:64])
    checks: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    detected_format: str | None = None
    detected_mime_type: str | None = None
    if detected is None:
        # Not a reason to refuse -- but never silently either.  A provider that
        # returns an exotic container keeps the historical behaviour and leaves
        # a marker behind instead of becoming mysteriously red.
        warnings.append(
            {
                "code": "media_output_format_undetected",
                "message": "Provider payload carries no recognised media magic.",
            }
        )
        checks.append({"code": "media_output_format_undetected", "status": "warning"})
    else:
        detected_format = detected.detected_media_format
        detected_mime_type = detected.mime_type
        report = MediaOutputGateReport(
            media_type=media_type,
            size_bytes=size,
            detected_format=detected_format,
            detected_mime_type=detected_mime_type,
        )
        if detected.media_type != media_type:
            return report._failed(
                "media_output_format_mismatch",
                f"Provider returned {detected.mime_type} bytes for a {media_type} node.",
            )
        checks.append(
            {
                "code": "media_output_format_matches",
                "status": "passed",
                "detected_media_format": detected_format,
            }
        )

    width: int | None = None
    height: int | None = None
    if media_type == "image":
        dimensions = image_dimensions(content)
        if dimensions is None or min(dimensions) < 1:
            report = MediaOutputGateReport(
                media_type=media_type,
                size_bytes=size,
                checks=tuple(checks),
                warnings=tuple(warnings),
                detected_format=detected_format,
                detected_mime_type=detected_mime_type,
            )
            return report._failed(
                "media_output_image_dimensions_invalid",
                "Provider returned an image whose dimensions cannot be decoded.",
            )
        width, height = dimensions
        checks.append(
            {
                "code": "media_output_image_dimensions_decodable",
                "status": "passed",
                "width": width,
                "height": height,
            }
        )

    if media_type == "video" and content[4:8] == b"ftyp":
        atoms, complete = _top_level_mp4_atoms(content)
        if not complete or b"moov" not in atoms:
            report = MediaOutputGateReport(
                media_type=media_type,
                size_bytes=size,
                checks=tuple(checks),
                warnings=tuple(warnings),
                detected_format=detected_format,
                detected_mime_type=detected_mime_type,
            )
            return report._failed(
                "media_output_container_incomplete",
                "Provider returned an MP4 with no readable movie atom; "
                "the download is truncated.",
            )
        checks.append(
            {
                "code": "media_output_mp4_atoms_complete",
                "status": "passed",
                "atoms": sorted({atom.decode("latin-1") for atom in atoms}),
            }
        )

    checks.append(
        {
            "code": "media_output_minimum_size",
            "status": "passed",
            "size_bytes": size,
            "minimum_bytes": minimum,
        }
    )
    return MediaOutputGateReport(
        media_type=media_type,
        size_bytes=size,
        checks=tuple(checks),
        warnings=tuple(warnings),
        detected_format=detected_format,
        detected_mime_type=detected_mime_type,
        width=width,
        height=height,
    )


def media_output_identity(content: bytes, media_type: str) -> tuple[str, str]:
    """The mime type and filename the payload's own bytes say it is.

    This used to be a fixed table, which is how a PNG returned by a video
    provider came to be stored as ``video/mp4``.
    """

    detected = detect_media_format_from_bytes(content[:64])
    if detected is not None and detected.media_type == media_type:
        extension = detected.file_extension.lstrip(".") or media_type
        return detected.mime_type, f"{media_type}.{extension}"
    return _FALLBACK_IDENTITY[media_type]


def media_output_gate_failure(report: MediaOutputGateReport) -> V2PersistenceError:
    """The typed node failure for a payload that did not pass."""

    # Regenerating is the operator's move, and it is not a transient condition:
    # marking it retryable would have to be registered as an approved transient
    # code, and a payload that is the wrong container will simply be wrong
    # again.  The message carries the actionable part because
    # ``CanvasNodeErrorV2`` has no details field.
    return V2PersistenceError(
        report.failure_code or "media_output_gate_failed",
        (
            f"{report.failure_message or 'Provider media failed the output gate.'} "
            "The node was not marked ready and the asset was not published; "
            "regenerate the node to ask the provider again."
        ),
        stage="agent_canvas_node_execution",
        details={
            "actionable_failure": ActionableFailureV1(
                failure_class="deterministic",
                retry_scope="none",
                user_action="regenerate",
            ).model_dump(mode="json"),
            "media_output_gate": report.to_dict(),
        },
    )


def _top_level_mp4_atoms(data: bytes) -> tuple[tuple[bytes, ...], bool]:
    """Walk the ISO-BMFF box structure, returning atoms and whether it is whole.

    ``moov`` may legitimately sit after a large ``mdat``, so the walk follows
    each declared size rather than searching for a marker; a size that does not
    land exactly on the next box means the file is truncated.
    """

    atoms: list[bytes] = []
    offset = 0
    total = len(data)
    while offset + 8 <= total and len(atoms) < _MAX_MP4_ATOMS:
        size = int.from_bytes(data[offset : offset + 4], "big")
        header = 8
        if size == 1:
            if offset + 16 > total:
                return tuple(atoms), False
            size = int.from_bytes(data[offset + 8 : offset + 16], "big")
            header = 16
        if size < header or offset + size > total:
            return tuple(atoms), False
        atoms.append(data[offset + 4 : offset + 8])
        offset += size
    return tuple(atoms), offset == total


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Width and height straight out of a PNG IHDR or a JPEG SOF marker."""

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) < 24 or data[12:16] != b"IHDR":
            return None
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return width, height
    if data.startswith(b"\xff\xd8\xff"):
        return _jpeg_dimensions(data)
    return None


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    offset = 2
    total = len(data)
    while offset + 9 < total:
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        if marker == 0xFF:
            offset += 1
            continue
        if marker == 0xD8 or marker == 0xD9 or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            offset += 2
            continue
        length = int.from_bytes(data[offset + 2 : offset + 4], "big")
        if length < 2:
            return None
        if marker in _JPEG_SOF_MARKERS:
            height = int.from_bytes(data[offset + 5 : offset + 7], "big")
            width = int.from_bytes(data[offset + 7 : offset + 9], "big")
            return width, height
        offset += 2 + length
    return None
