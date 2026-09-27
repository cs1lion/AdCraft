"""Agnes reads reference video through its own array, and only if ``mode`` says so.

09-23 (E2E, ``rose``): the storyboard_video node was bound to six 3D previs
clips and three whole shootable assets, and the provider refused the request
over the *image* aspect-ratio window.  While unwinding that, a second and much
quieter defect turned up in the adapter: the Agnes branch of
``payload_for_manifest`` only ever built an ``images`` list.

``videos`` and ``audios`` were never constructed anywhere in the repository, and
``mode`` was flipped by the image list alone.  So a shot bound only to a previs
clip -- which is exactly what the "use the 3D staging and camera-motion video"
route asks for -- shipped as ``"mode": "text"``, a mode in which the provider
reads none of the attached arrays.  The bytes left the building, the request was
billed, and the clip was never seen.  Nothing failed, because nothing was asked.

The endpoint's contract for that media is specific and it is what this file
pins:

* ``mode`` must be one of ``text``/``keyframe``/``reference``, and ``reference``
  needs at least one of ``images``/``audios``/``videos``.
* ``images`` and ``audios`` are arrays of URL strings.
* ``videos`` is an array of **objects** -- ``url``, plus ``start_seconds`` and
  ``require_audio`` -- and holds at most one clip.
* a video reference takes no image slot, which is the whole reason it exists.

The per-array *counts* are not this layer's job: ``apply_provider_reference_limits``
already freezes a subset per media type from the same catalog
``reference_limits`` and records what it withheld as an omission, so the adapter
serializes what it is handed and fails loudly on what it cannot express rather
than quietly dropping it -- the behaviour that hid this defect in the first
place.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.config import Settings
from app.schemas.agent_canvas import ResolvedMediaBindingInputV2, ResolvedNodeInputManifestV2
from app.schemas.agent_canvas_runtime import ResolvedModelExecutionV1
from app.schemas.seedance_inputs import (
    SeedanceInputManifestV1,
    SeedanceMediaInputV1,
)
from app.services.agent_canvas_resolved_inputs import apply_provider_reference_limits
from app.tools.seedance_adapter import VolcengineSeedanceAdapter

# The SKU that accepts ``videos``.  ``-flash`` refuses the parameter outright
# (HTTP 400 "当前模型不支持 videos"), so a channel test against that SKU would
# only ever prove the refusal.
AGNES_MODEL = "agnes-video-2.5"


def _adapter() -> VolcengineSeedanceAdapter:
    return VolcengineSeedanceAdapter(Settings(video_generation_model=AGNES_MODEL))


def _media(
    binding_id: str,
    *,
    media_type: str = "image",
    url: str = "https://cdn.example.com/ref.png",
    order: int = 0,
    label: str = "Image 1",
    instruction: str | None = None,
    input_type: str | None = None,
) -> SeedanceMediaInputV1:
    return SeedanceMediaInputV1(
        binding_id=binding_id,
        asset_id=f"asset_{binding_id}",
        version_id=f"version_{binding_id}",
        media_type=media_type,  # type: ignore[arg-type]
        input_role=f"{media_type}_reference",
        required=False,
        display_order=order,
        provider_input_type=input_type or f"{media_type}_url",  # type: ignore[arg-type]
        provider_input_value=url,
        checksum=f"sha_{binding_id}",
        label=label,
        reference_instruction=instruction,
    )


def _manifest(*media: SeedanceMediaInputV1, prompt: str = "A crane up over the birch."):
    return SeedanceInputManifestV1(
        node_id="node_rose",
        model_id=AGNES_MODEL,
        prompt=prompt,
        image_inputs=tuple(item for item in media if item.media_type == "image"),
        video_inputs=tuple(item for item in media if item.media_type == "video"),
        audio_inputs=tuple(item for item in media if item.media_type == "audio"),
        aspect_ratio="16:9",
        resolution="720p",
        requested_duration_seconds=5,
        effective_duration_seconds=5,
        generate_audio=False,
    )


class TestReferenceVideoReachesItsOwnArray:
    def test_a_video_reference_is_an_object_array_not_a_string(self) -> None:
        payload = _adapter().payload_for_manifest(
            _manifest(_media("previs", media_type="video", url="https://cdn.example.com/previs.mp4"))
        )
        assert payload["videos"] == [{"url": "https://cdn.example.com/previs.mp4"}]
        assert payload["mode"] == "reference"

    def test_an_audio_reference_is_a_plain_url(self) -> None:
        payload = _adapter().payload_for_manifest(
            _manifest(_media("theme", media_type="audio", url="https://cdn.example.com/theme.m4a"))
        )
        assert payload["audios"] == ["https://cdn.example.com/theme.m4a"]
        assert payload["mode"] == "reference"

    def test_a_video_reference_consumes_no_image_slot(self) -> None:
        """Why the array exists: adding the clip costs the shot no picture.

        With the old code the clip was dropped and the images were unchanged;
        with the fix both travel.  If this ever regresses into "the video
        arrives and an image is withheld", the two media types are competing
        for one budget again and the whole channel was pointless.
        """

        boards = [
            _media(f"board{index}", order=index, label=f"Image {index + 1}",
                   url=f"https://cdn.example.com/board{index}.png")
            for index in range(5)
        ]
        clip = _media("previs", media_type="video", order=9,
                      url="https://cdn.example.com/previs.mp4")
        payload = _adapter().payload_for_manifest(_manifest(*boards, clip))
        assert payload["images"] == [
            f"https://cdn.example.com/board{index}.png" for index in range(5)
        ]
        assert payload["videos"] == [{"url": "https://cdn.example.com/previs.mp4"}]
        assert payload["mode"] == "reference"


class TestModeCoversEveryReferenceArray:
    def test_a_video_only_request_no_longer_ships_as_text(self) -> None:
        """The regression that started this: media attached to a mode that ignores it.

        ``mode`` used to be decided by the image list alone, so a shot whose only
        reference was a previs clip went out as ``"mode": "text"``.  The provider
        accepted it, billed it, and read none of it.
        """

        payload = _adapter().payload_for_manifest(
            _manifest(
                _media("previs", media_type="video"),
                _media("theme", media_type="audio"),
            )
        )
        assert payload["mode"] == "reference"
        assert "images" not in payload

    def test_a_text_only_request_still_ships_as_text(self) -> None:
        payload = _adapter().payload_for_manifest(_manifest())
        assert payload["mode"] == "text"
        assert "videos" not in payload and "audios" not in payload
        assert payload["prompt"] == "A crane up over the birch."

    def test_every_empty_array_is_absent_from_the_payload(self) -> None:
        payload = _adapter().payload_for_manifest(
            _manifest(_media("board", label="Image 1"))
        )
        assert set(payload) == {
            "model",
            "prompt",
            "mode",
            "seconds",
            "size",
            "aspect_ratio",
            "images",
        }


class TestReferencePlaceholders:
    def test_each_array_numbers_from_one_in_submission_order(self) -> None:
        payload = _adapter().payload_for_manifest(
            _manifest(
                _media("hero", order=0, label="Image 1"),
                _media("board", order=1, label="Image 2"),
                _media("previs", media_type="video", order=2),
                _media("theme", media_type="audio", order=3),
            )
        )
        prompt = payload["prompt"]
        assert "<Picture 1>:" in prompt
        assert "<Picture 2>:" in prompt
        assert "<Video 1>:" in prompt
        assert "<Audio 1>:" in prompt
        # The numbering and the array order are the same claim stated twice, so
        # the text has to come out in the order the arrays were built.
        assert prompt.index("<Picture 1>") < prompt.index("<Picture 2>") < prompt.index("<Video 1>")
        assert prompt.index("<Video 1>") < prompt.index("<Audio 1>")
        assert prompt.startswith("A crane up over the birch.")

    def test_the_instruction_explains_what_the_reference_is_for(self) -> None:
        """Uploading material without saying what to do with it is hard to steer.

        The operator's own wording wins over the asset's name: the label says
        which clip, the instruction says which part of the shot it governs.
        """

        payload = _adapter().payload_for_manifest(
            _manifest(
                _media(
                    "previs",
                    media_type="video",
                    label="previs_shot2.mp4",
                    instruction=(
                        "Use this clip as the authoritative camera-motion reference."
                    ),
                )
            )
        )
        assert "<Video 1>: Use this clip as the authoritative camera-motion reference." in (
            payload["prompt"]
        )
        assert "previs_shot2.mp4" not in payload["prompt"]

    def test_a_label_stands_in_when_no_instruction_was_compiled(self) -> None:
        payload = _adapter().payload_for_manifest(
            _manifest(_media("theme", media_type="audio", label="theme_isle.m4a"))
        )
        assert "<Audio 1>: theme_isle.m4a" in payload["prompt"]


class TestNothingIsSilentlyDropped:
    def test_a_file_id_reference_raises_instead_of_vanishing(self) -> None:
        """The failure mode this whole change exists to end.

        A ``provider_file_id`` cannot be written into an array of URLs on this
        endpoint, and the old filter simply did not include it -- the reference
        left without a trace and the shot was generated without it.  Now the run
        names what it could not express, which is the same error the non-Agnes
        branch raises for a delivery it cannot carry.
        """

        with pytest.raises(ValueError, match="provider_reference_delivery_unavailable"):
            _adapter().payload_for_manifest(
                _manifest(
                    _media("board", label="Image 1", input_type="provider_file_id")
                )
            )

    def test_an_inline_clip_cannot_be_sent_as_a_url(self) -> None:
        with pytest.raises(ValueError, match="provider_reference_delivery_unavailable"):
            _adapter().payload_for_manifest(
                _manifest(
                    _media(
                        "previs",
                        media_type="video",
                        input_type="data_url",
                        url="data:video/mp4;base64,AAAA",
                    )
                )
            )


class TestTheVideoBudgetIsEnforcedBeforeTheAdapterRuns:
    """Where the "one clip per request" rule actually lives.

    Faithfully serializing a manifest is not the same as being allowed to send
    everything in it: ``agnes-video-2.5`` accepts at most one reference video per
    request, and the catalog says so.  The trim happens one layer up, in
    ``apply_provider_reference_limits``, which walks the references in
    composition order and records each one it withholds as an omission -- so the
    operator can see that a second clip was not sent and why.  The adapter must
    not keep a second, quietly divergent copy of that budget.
    """

    def _resolution(self) -> ResolvedModelExecutionV1:
        return ResolvedModelExecutionV1(
            model_ref=AGNES_MODEL,
            provider_id="volcengine_ark",
            provider_model_id=AGNES_MODEL,
            capability="video",
            provider_protocol="ark_video",
            credential_revision=1,
            catalog_revision=1,
            capability_metadata={
                "max_references": 15,
                "reference_limits": {"image": 5, "video": 1, "audio": 3},
            },
        )

    def _binding(self, binding_id: str, *, media_type: str = "image", order: int = 0):
        return ResolvedMediaBindingInputV2(
            binding_id=binding_id,
            source_kind="image_asset",
            source_node_id=None,
            source_node_revision=None,
            input_role=f"{media_type}_reference",
            binding_metadata={"semantic_reference_role": "scene_reference"},
            display_order=order,
            asset_id=f"asset_{binding_id}",
            asset_version_id=f"version_{binding_id}",
            media_type=media_type,  # type: ignore[arg-type]
            checksum=f"sha_{binding_id}",
        )

    def _manifest_v2(self, *items: ResolvedMediaBindingInputV2) -> ResolvedNodeInputManifestV2:
        return ResolvedNodeInputManifestV2(
            manifest_id="manifest_rose",
            workflow_id="wf_rose",
            execution_id="exec_rose",
            node_run_id="run_rose",
            target_node_id="node_rose",
            workflow_revision=1,
            media_inputs=tuple(items),
            created_at=datetime.now(timezone.utc),
        )

    def test_a_second_clip_is_omitted_with_a_reason_not_truncated_away(self) -> None:
        manifest = self._manifest_v2(
            self._binding("previs_wide", media_type="video", order=0),
            self._binding("previs_push", media_type="video", order=1),
            self._binding("previs_orbit", media_type="video", order=2),
        )
        frozen = apply_provider_reference_limits(manifest, self._resolution())
        reasons = {
            omission.binding_id: omission.reason_code
            for omission in frozen.omitted_optional_inputs
        }
        assert [item.binding_id for item in frozen.media_inputs] == ["previs_wide"]
        assert reasons == {
            "previs_push": "omitted_provider_reference_limit",
            "previs_orbit": "omitted_provider_reference_limit",
        }

    def test_the_adapter_serializes_the_frozen_subset_unchanged(self) -> None:
        """One clip in, one clip out -- the adapter is not where the cut happens."""

        manifest = self._manifest_v2(
            self._binding("previs_wide", media_type="video", order=0),
            self._binding("previs_push", media_type="video", order=1),
        )
        frozen = apply_provider_reference_limits(manifest, self._resolution())
        seedance = _manifest(
            *[
                _media(
                    item.binding_id,
                    media_type="video",
                    order=index,
                    url=f"https://cdn.example.com/{item.binding_id}.mp4",
                )
                for index, item in enumerate(frozen.media_inputs)
            ]
        )
        payload = _adapter().payload_for_manifest(seedance)
        assert len(payload["videos"]) == 1
        assert payload["videos"][0]["url"] == "https://cdn.example.com/previs_wide.mp4"


MOTION_URL = "https://origin.example.com/previs/previs-shot1.mp4"
MOTION_INSTRUCTION = (
    "3D previs camera motion for this beat: framing, path and pace."
)


def _segment(
    *assets: dict,
    prompt: str = "She stands outside the aquarium, one rose in hand.",
    duration: int = 6,
) -> dict:
    return {
        "prompt": prompt,
        "duration_seconds": duration,
        "ratio": "16:9",
        "input_assets": list(assets),
    }


def _picture(asset_id: str, role: str, semantic_type: str) -> dict:
    """A legacy segment's picture reference, which carries its bytes inline."""

    data_url = "data:image/png;base64,iVBORw0KGgo="
    return {
        "asset_id": asset_id,
        "role": role,
        "model_input_type": "data_url",
        "model_input_value": data_url,
        "url": data_url,
        "semantic_type": semantic_type,
    }


def _motion(asset_id: str = "previs-shot1-motion", **overrides) -> dict:
    motion = {
        "asset_id": asset_id,
        "role": "motion_reference",
        "model_input_type": "video_url",
        "model_input_value": MOTION_URL,
        "url": MOTION_URL,
        "semantic_type": "previs_camera_motion",
        "description": MOTION_INSTRUCTION,
    }
    motion.update(overrides)
    return motion


class TestALegacySegmentCarriesItsMotionClip:
    """The film path -- 22 segments, each one beat still plus its shot's clip.

    The canvas fix above is not the only place the channel was missing.  The
    production film is driven by ``RealMediaProvider._submit_storyboard_video_segment``
    → ``payload_for_segment``, whose Agnes branch built ``images`` from the same
    list and had no notion of a clip at all.  So a run that bound the 3D previs
    camera-motion video to its segments would have shipped without it, in a
    request that was billed and never questioned -- the identical failure, one
    layer down, on the path that actually produces the 成片.
    """

    def test_the_clip_rides_videos_and_costs_no_picture_slot(self) -> None:
        payload = _adapter().payload_for_segment(
            _segment(
                _picture("still", "storyboard", "storyboard_image"),
                _picture("board", "scene_reference", "scene_design_board"),
                _motion(),
            ),
            ratio="16:9",
            resolution="720p",
        )
        assert payload["mode"] == "reference"
        assert payload["videos"] == [{"url": MOTION_URL}]
        # Two pictures in, two pictures out: the clip took a slot of its own.
        assert len(payload["images"]) == 2

    def test_the_clip_is_described_in_the_prompt(self) -> None:
        """"Follow this camera" has to be said out loud, or it is only a file."""

        payload = _adapter().payload_for_segment(
            _segment(_motion()), ratio="16:9", resolution="720p"
        )
        assert "<Video 1>: 3D previs camera motion for this beat" in payload["prompt"]
        assert payload["prompt"].startswith("She stands outside the aquarium")

    def test_a_clip_only_segment_is_reference_mode(self) -> None:
        payload = _adapter().payload_for_segment(
            _segment(_motion()), ratio="16:9", resolution="720p"
        )
        assert payload["mode"] == "reference"
        assert "images" not in payload

    def test_an_unreferenced_segment_still_ships_as_text(self) -> None:
        payload = _adapter().payload_for_segment(
            _segment(), ratio="16:9", resolution="720p"
        )
        assert payload["mode"] == "text"
        assert "videos" not in payload
        assert payload["prompt"] == "She stands outside the aquarium, one rose in hand."

    def test_the_semantic_type_stands_in_when_no_description_was_written(self) -> None:
        motion = _motion()
        del motion["description"]
        payload = _adapter().payload_for_segment(
            _segment(motion), ratio="16:9", resolution="720p"
        )
        assert "<Video 1>: previs_camera_motion" in payload["prompt"]

    def test_an_unknown_role_is_ignored_rather_than_guessed_at(self) -> None:
        payload = _adapter().payload_for_segment(
            _segment(
                _picture("still", "storyboard", "storyboard_image"),
                {"asset_id": "x", "role": "some_future_role", "url": MOTION_URL},
            ),
            ratio="16:9",
            resolution="720p",
        )
        assert "videos" not in payload
        assert payload["mode"] == "reference"
        assert len(payload["images"]) == 1


class TestALocalClipIsRefusedNotSilentlyDropped:
    """The failure this channel exists to end, in its segment-path form.

    A previs clip has no public address until someone publishes one: the library
    records ``/media/<path>`` and the app has never been told its own internet
    address.  Sending that string to the provider is a refusal, but *dropping*
    it is worse -- the segment generates, the request is billed, and the camera
    the operator asked for is simply absent with nothing in the log to say so.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "http://origin.example.com/previs/previs-shot1.mp4",  # not https
            "https://127.0.0.1:8000/media/previs-shot1.mp4",  # loopback
            "https://10.0.0.5:8000/media/previs-shot1.mp4",  # private
            "/media/assets/objects/sha256/06/67/06670eb9.mp4",  # a local path
            "assets/objects/sha256/06/67/06670eb9.mp4",  # a relative path
            "",
        ],
    )
    def test_a_clip_the_provider_cannot_fetch_raises(self, url: str) -> None:
        with pytest.raises(ValueError, match="provider_reference_delivery_unavailable"):
            _adapter().payload_for_segment(
                _segment(_motion(model_input_value=url)), ratio="16:9", resolution="720p"
            )

    def test_an_inline_clip_cannot_be_sent_as_a_url_either(self) -> None:
        """The bytes are the file, and the provider has to stream it.

        An image can be a ``data:`` URL because Agnes accepts it inline; a video
        reference is fetched, so an inline clip is not a smaller version of the
        same thing -- it is a different request that will be refused, after the
        quota is spent.
        """

        with pytest.raises(ValueError, match="provider_reference_delivery_unavailable"):
            _adapter().payload_for_segment(
                _segment(_motion(model_input_value="data:video/mp4;base64,AAAA")),
                ratio="16:9",
                resolution="720p",
            )


class TestTheMotionRoleDoesNotDisturbTheOtherBranch:
    def test_the_legacy_content_walk_ignores_a_clip_it_cannot_express(self) -> None:
        """The non-Agnes branch puts media in ``content`` and has no clip slot.

        It must skip the motion reference rather than raise, because this list is
        shared: a film that carries a clip for the Agnes endpoint still has to be
        renderable by a provider that has no such parameter.
        """

        adapter = VolcengineSeedanceAdapter(
            Settings(video_generation_model="doubao-seedance-1-0")
        )
        payload = adapter.payload_for_segment(
            _segment(
                _picture("still", "storyboard", "storyboard_image"),
                _motion(),
            ),
            ratio="16:9",
            resolution="720p",
        )
        types = [item["type"] for item in payload["content"]]
        assert types == ["text", "image_url"]
        assert "videos" not in payload
