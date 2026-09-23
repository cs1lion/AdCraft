"""The asset library's public URLs are *paths*, and a path cannot be fetched.

``media_paths.public_url_for_path`` writes ``/media/<relative path>`` and stops
there, because the app has never been told its own internet address.  So an asset
version carrying ``metadata["public_url"]`` records a URL that
``is_provider_compatible_public_url`` refuses for having no scheme -- and with
nothing absolute to fall back on, every non-image asset version in the library
comes out of delivery as ``media_requires_remote_transport``.

That is what stood between the rose previs clips and the provider's dedicated
``videos[]`` channel.  The clips are legal in every other respect: 24.00 FPS,
inside the 2-12s window once trimmed, and now serialized into ``videos`` by the
adapter with an image slot left untouched.  They are unreachable purely because
nothing says where ``/media/...`` is served from.

``PROVIDER_REFERENCE_PUBLIC_BASE_URL`` is that one fact, and this file pins what
it does and does not do: it turns a path-shaped public URL into an absolute one
so the existing gate can judge it.  It does not invent a host, does not rewrite a
URL someone recorded deliberately, and does not make the authenticated content
route look public.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.schemas.agent_canvas import ResolvedMediaInputSnapshotV2
from app.schemas.v2_asset_library import AssetVersionMetadataV2
from app.services.v2_provider_reference_input_delivery import (
    V2ProviderReferenceInputDeliveryService,
    _canvas_public_url,
    is_provider_compatible_public_url,
)

#: A previs clip the way the library stores it: a sha256-addressed object under
#: the media root, so its public URL is a path.
CLIP_PUBLIC_PATH = "/media/objects/sha256/9f2c7a1b.mp4"


def _snapshot(*, media_type: str = "video") -> ResolvedMediaInputSnapshotV2:
    return ResolvedMediaInputSnapshotV2(
        source_kind="image_asset",
        binding_kind="video_reference",
        asset_id="asset_previs",
        asset_version_id="version_previs",
        media_type=media_type,
        asset_checksum="checksum_previs",
        access_descriptor={
            "descriptor_type": "asset_content",
            "asset_id": "asset_previs",
            "media_url": "/api/v2/assets/asset_previs/content",
            "checksum": "checksum_previs",
        },
        binding_id="bnd_previs",
        input_role="video_reference",
    )


def _clip_version(**metadata: object) -> AssetVersionMetadataV2:
    return AssetVersionMetadataV2(
        version_id="version_previs",
        asset_id="asset_previs",
        version_no=1,
        storage_key="objects/sha256/9f2c7a1b.mp4",
        sha256="9f2c7a1b",
        size_bytes=524_288,
        mime_type="video/mp4",
        metadata=dict(metadata),
        status="ready",
        created_at="2026-09-23T00:00:00Z",
    )


def _service(tmp_path: Path, base_url: str | None) -> V2ProviderReferenceInputDeliveryService:
    return V2ProviderReferenceInputDeliveryService(
        tmp_path,
        settings=Settings(
            media_data_dir=tmp_path,
            provider_reference_public_base_url=base_url,
        ),
    )


class TestAPathIsNotAUrl:
    def test_the_library_records_a_path_and_the_gate_refuses_it(self) -> None:
        """The defect, stated at its source rather than at its symptom."""

        assert CLIP_PUBLIC_PATH.startswith("/")
        assert not is_provider_compatible_public_url(CLIP_PUBLIC_PATH)

    def test_with_no_base_url_the_path_is_returned_as_it_was_recorded(self) -> None:
        resolved = _canvas_public_url(
            {"public_url": CLIP_PUBLIC_PATH}, _snapshot(), base_url=None
        )
        assert resolved == CLIP_PUBLIC_PATH

    def test_the_api_content_route_is_not_made_public(self) -> None:
        """What the snapshot falls back to when no public_url was recorded.

        ``/api/v2/assets/.../content`` is authenticated.  Absolutizing it would
        turn a clear local refusal -- ``media_requires_remote_transport``, which
        the frontend already explains -- into an opaque 401 at the provider, so
        it is left alone even when a base URL is configured.  ``main.py:111``
        draws the same line from the other side: ``/media`` is in the access
        token middleware's exempt prefixes, this route is not.
        """

        resolved = _canvas_public_url(
            {}, _snapshot(), base_url="https://media.example.com"
        )
        assert resolved == "/api/v2/assets/asset_previs/content"


class TestTheBaseURLNamesTheHost:
    def test_a_recorded_path_becomes_absolute(self) -> None:
        resolved = _canvas_public_url(
            {"public_url": CLIP_PUBLIC_PATH}, _snapshot(),
            base_url="https://media.example.com",
        )
        assert resolved == f"https://media.example.com{CLIP_PUBLIC_PATH}"
        assert is_provider_compatible_public_url(resolved)

    def test_a_trailing_slash_does_not_double_the_separator(self) -> None:
        resolved = _canvas_public_url(
            {"public_url": CLIP_PUBLIC_PATH}, _snapshot(),
            base_url="https://media.example.com/",
        )
        assert resolved == f"https://media.example.com{CLIP_PUBLIC_PATH}"

    def test_an_already_absolute_url_is_someone_elsses_answer(self) -> None:
        """Pointing the setting at a CDN must not rewrite a deliberate URL."""

        recorded = "https://cdn.elsewhere.example/previs.mp4"
        resolved = _canvas_public_url(
            {"public_url": recorded}, _snapshot(), base_url="https://media.example.com"
        )
        assert resolved == recorded

    def test_a_base_url_cannot_lower_the_bar_the_gate_sets(self) -> None:
        """The gate's price is https on a public host, and the setting does not pay it.

        ``http://`` and any private/loopback host are refused whatever the base
        URL is -- which is the whole reason a quick "just point it at the box"
        deployment does not work.  Note what this does *not* rule out: a bare
        public IP over https **passes** the gate, because the gate only looks at
        scheme and address class.  Whether such a URL is fetchable is a different
        question the gate never asked -- the box at 49.233.207.18 accepts TCP on
        443 and then resets the handshake, i.e. it has no certificate at all.
        (Earlier on 2026-09-23 it also answered nothing on 80; by that evening
        port 80 was serving nginx and the web frontend, still with no TLS.  Both
        shapes fail the gate's ``https`` requirement in opposite directions.)
        """

        for base in ("http://media.example.com", "http://10.0.0.5", "https://127.0.0.1"):
            resolved = _canvas_public_url(
                {"public_url": CLIP_PUBLIC_PATH}, _snapshot(), base_url=base
            )
            assert not is_provider_compatible_public_url(resolved), base

    def test_a_public_ip_over_https_passes_the_gate_and_that_is_all(self) -> None:
        """The gate admits an address it cannot know is unservable.

        Asserted so nobody later reads a green delivery as proof the URL works:
        the gate's answer is about shape, and a host with no web server on it has
        the right shape.
        """

        resolved = _canvas_public_url(
            {"public_url": CLIP_PUBLIC_PATH}, _snapshot(),
            base_url="https://93.184.216.34",
        )
        assert is_provider_compatible_public_url(resolved)


class TestTheClipActuallyTravels:
    """The end-to-end claim the probe could only show with a placeholder."""

    def test_a_previs_clip_is_delivered_once_its_host_is_named(self, tmp_path: Path) -> None:
        service = _service(tmp_path, "https://media.example.com")
        delivered = service._deliver_canvas_version(  # noqa: SLF001
            _snapshot(),
            _clip_version(public_url=CLIP_PUBLIC_PATH),
            frozenset({"video_url", "data_url"}),
        )
        assert delivered.provider_input_type == "video_url"
        assert delivered.provider_input_value == (
            f"https://media.example.com{CLIP_PUBLIC_PATH}"
        )

    def test_the_same_clip_names_the_real_blocker(self, tmp_path: Path) -> None:
        """Without the host, the reason is the transport and nothing else."""

        service = _service(tmp_path, None)
        failure = service._deliver_canvas_version(  # noqa: SLF001
            _snapshot(),
            _clip_version(public_url=CLIP_PUBLIC_PATH),
            frozenset({"video_url", "data_url"}),
        )
        assert failure.code == "provider_reference_delivery_unavailable"
        assert failure.reason == "media_requires_remote_transport"

    def test_an_image_still_falls_back_to_inline_bytes(self, tmp_path: Path) -> None:
        """The change is about non-image assets; the image path is untouched."""

        service = _service(tmp_path, "https://media.example.com")
        failure = service._deliver_canvas_version(  # noqa: SLF001
            _snapshot(media_type="image"),
            AssetVersionMetadataV2(
                version_id="version_previs",
                asset_id="asset_previs",
                version_no=1,
                storage_key="objects/sha256/9f2c7a1b.png",
                sha256="9f2c7a1b",
                size_bytes=1,
                mime_type="image/png",
                metadata={},
                status="ready",
                created_at="2026-09-23T00:00:00Z",
            ),
            frozenset({"image_url", "data_url"}),
        )
        assert failure.reason == "local_file_missing"
