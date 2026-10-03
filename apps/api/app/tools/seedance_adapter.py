from __future__ import annotations

import ipaddress
import logging
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote, urlparse

from app.core.config import Settings
from app.schemas.ad_workflow import SUPPORTED_VIDEO_ASPECT_RATIOS, SUPPORTED_VIDEO_RESOLUTIONS
from app.schemas.seedance_inputs import SeedanceInputManifestV1, SeedanceMediaInputV1
from app.services.agnes_image_contract import is_agnes_image_model
from app.services.stepfun_image_contract import is_stepfun_image_model

from app.tools.media_provider_protocol import (
    ARK_SEEDANCE_RESOLUTION,
    DEFAULT_VIDEO_RATIO,
    SEEDANCE_MAX_SINGLE_TASK_DURATION_SECONDS,
    SEEDANCE_MIN_SINGLE_TASK_DURATION_SECONDS,
    SEEDANCE_PREFERRED_SEGMENT_SECONDS,
    SEEDANCE_SINGLE_TASK_DURATIONS_SECONDS,
    SEEDREAM_MIN_IMAGE_PIXELS,
    MediaConfigurationError,
)

logger = logging.getLogger(__name__)


#: The reference roles a legacy segment's ``input_assets`` may carry as still
#: pictures.  One definition, because the Agnes branch and the legacy content
#: walk build different request shapes out of the same list and have to agree on
#: which roles are images -- a role that one treats as a picture and the other
#: as a clip would be sent twice, or dropped by both.
SEEDANCE_SEGMENT_IMAGE_ROLES = frozenset(
    {
        "character_turnaround",
        "product_reference",
        "scene_reference",
        "storyboard",
    }
)

#: The one role that carries a *clip* rather than a picture.  Agnes takes it in
#: ``videos`` -- an array of objects with its own budget -- so it consumes no
#: image slot.  That is what lets the 3D previs camera-motion reference ride
#: alongside the finished character and scene stills instead of being traded
#: against them, which is the whole point of the channel.  (The ``-flash`` SKU
#: is the exception: it refuses the parameter outright and its payloads are
#: images-only -- see ``_is_agnes_flash_model``.)
SEEDANCE_SEGMENT_MOTION_ROLE = "motion_reference"


def _is_agnes_flash_model(model_id: str | None) -> bool:
    """The Agnes SKU whose request body may only carry images.

    2026-09-29 作者裁定（测试期）：``agnes-video-2.5-flash`` 对 ``videos``
    参数整单拒绝（HTTP 400「当前模型不支持 videos」——见
    ``provider_model_catalog`` 该行的留痕），音频参数按"只传图片"的同一口径
    一并收口。此函数是两个 Agnes payload 分支的开关；flash 支持视频参数后
    删掉它的两个调用点即可恢复三数组契约。
    """

    return "flash" in (model_id or "").lower()


def _video_generation_task_url(
    endpoint: str, task_id: str, model_id: str | None = None
) -> str:
    """Derive the task query URL from the configured submit endpoint.

    Agnes hosts task lookup on a dedicated sibling path (``/agnesapi``)
    rather than appending the task id to the submit URL, so both endpoints
    are derived from the submit endpoint's origin.
    """

    safe_task_id = quote(task_id.strip(), safe="")
    parsed = urlparse(endpoint)
    if parsed.netloc and parsed.netloc.endswith("agnes-ai.cn"):
        model_query = f"&model_name={quote(model_id.strip(), safe='')}" if model_id else ""
        return (
            f"{parsed.scheme}://{parsed.netloc}/agnesapi"
            f"?video_id={safe_task_id}{model_query}"
        )
    return f"{endpoint.rstrip('/')}/{safe_task_id}"


class VolcengineSeedanceAdapter:
    """Translate generic video segment tasks into Ark Seedance task payloads."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _is_agnes_model(self, model_id: str | None = None) -> bool:
        """Check if the configured model is Agnes (uses prompt field, not content)."""
        model = (model_id or self._settings.video_generation_model or "").lower()
        return model.startswith("agnes-video") or "agnes" in model

    def payload_for_segment(
        self,
        segment: dict[str, Any],
        ratio: str | None = None,
        resolution: str | None = None,
    ) -> dict[str, Any]:
        prompt = str(segment.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("v2_video_prompt_empty")
        normalized_resolution = _normalize_video_resolution(
            resolution
            or segment.get("resolution")
            or segment.get("output_resolution")
            or self._settings.video_generation_resolution
        )
        normalized_ratio = _normalize_video_ratio(
            ratio or segment.get("ratio") or segment.get("aspect_ratio") or DEFAULT_VIDEO_RATIO
        )
        if self._is_agnes_model():
            # Agnes video API uses prompt field directly
            agnes_payload: dict[str, Any] = {
                "model": self._settings.video_generation_model,
                "prompt": prompt,
                "mode": "text",
                "seconds": str(int(segment["duration_seconds"])),
                "size": "720P",
                "aspect_ratio": normalized_ratio,
            }
            # Add reference images if present (Agnes reference mode), and the
            # motion clip if one is bound: they are separate arrays with
            # separate budgets, so the clip costs no image slot.  ``mode`` is
            # decided by the union, not by the image list alone -- a segment
            # bound only to a previs clip used to ship as ``"text"`` with a
            # ``videos`` array attached to a mode that ignores it.
            # The ``-flash`` SKU is the exception to all of that: its body is
            # images-only (2026-09-29 作者裁定), so the clip is withheld here
            # rather than sent into a guaranteed 400.
            images, videos, described = _seedance_segment_reference_plan(
                segment,
                images_only=_is_agnes_flash_model(self._settings.video_generation_model),
            )
            if images:
                agnes_payload["images"] = images
            if videos:
                agnes_payload["videos"] = videos
            if described:
                agnes_payload["mode"] = "reference"
                # The provider's own guidance is that unattributed material is
                # harder to steer than none, and a video reference especially:
                # "follow this camera" has to be said out loud.
                agnes_payload["prompt"] = _agnes_reference_directives(prompt, described)
            return agnes_payload

        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": prompt,
            }
        ]
        content.extend(_seedance_image_content_items(segment.get("input_assets", [])))
        return {
            "model": self._settings.video_generation_model,
            "content": content,
            "resolution": normalized_resolution,
            "ratio": normalized_ratio,
            "duration": segment["duration_seconds"],
            "generate_audio": bool(
                segment.get("generate_audio", self._settings.video_generation_generate_audio)
            ),
            "watermark": False,
            "camera_fixed": bool(segment.get("camera_fixed", False)),
        }

    def payload_for_manifest(self, manifest: SeedanceInputManifestV1) -> dict[str, Any]:
        """Serialize the canonical Agent Canvas manifest without rediscovery."""

        if self._is_agnes_model(manifest.model_id):
            return _agnes_manifest_payload(manifest)

        content: list[dict[str, Any]] = [{"type": "text", "text": manifest.prompt}]
        content.extend(_seedance_manifest_content_item(item) for item in manifest.media_inputs)
        payload = {
            "model": manifest.model_id,
            "content": content,
            "resolution": _normalize_video_resolution(manifest.resolution),
            "ratio": _normalize_video_ratio(manifest.aspect_ratio),
            "duration": manifest.effective_duration_seconds,
            "generate_audio": manifest.generate_audio,
            "watermark": False,
            "camera_fixed": False,
        }
        _validate_storyboard_grounding_payload(manifest, payload)
        return payload

    def task_url(self, task_id: str) -> str:
        return _video_generation_task_url(
            self._settings.video_generation_endpoint or "",
            task_id,
            self._settings.video_generation_model,
        )


def _agnes_manifest_payload(manifest: SeedanceInputManifestV1) -> dict[str, Any]:
    """Build the Agnes request body for a typed Agent Canvas manifest.

    Agnes reads reference media out of three separate arrays -- ``images`` and
    ``audios`` as plain URL strings, ``videos`` as one object per clip -- so a
    video reference rides its own channel and takes no image slot.  That is the
    point of the channel: the finished character and scene pictures a shot is
    bound to are no longer traded away for the clip that carries its camera.

    ``mode`` is a *separate* decision from which arrays are populated, and it
    used to be flipped by the image list alone.  A shot bound only to a previs
    clip therefore shipped as ``"mode": "text"`` with ``videos`` attached to a
    mode that ignores it -- the media left the building and the provider never
    saw any of it.  Any of the three arrays now selects reference mode.

    The ``-flash`` SKU breaks the three-array rule on purpose (2026-09-29
    作者裁定, test period): its body is images-only, so non-image inputs are
    withheld with a warning instead of serialized.  Upstream
    ``apply_provider_reference_limits`` should already have kept them out of
    the manifest (the catalog row declares ``video: 0``/``audio: 0`` for that
    SKU and records the omission); reaching the warning means it did not, and
    the warning says which binding fell out.

    Nothing else is trimmed here.  How many of each kind the provider accepts
    is already enforced per media type by ``apply_provider_reference_limits``
    over the same catalog ``reference_limits``, which also records what it
    withheld as an omission; a second copy of that budget in the adapter could
    only disagree with it, and the manifest is frozen and carries no omission
    field to record the disagreement in.  So this layer serializes what it is
    given and fails loudly on anything it cannot express.
    """

    payload: dict[str, Any] = {
        "model": manifest.model_id,
        "prompt": manifest.prompt,
        "mode": "text",
        "seconds": str(int(manifest.effective_duration_seconds)),
        "size": "720P",
        "aspect_ratio": _normalize_video_ratio(manifest.aspect_ratio),
    }
    images: list[str] = []
    videos: list[dict[str, Any]] = []
    audios: list[str] = []
    #: (array name, position in that array, replacement) per reference, in the
    #: order the arrays are built -- which is the manifest's own order.
    described: list[tuple[str, int, str]] = []
    images_only = _is_agnes_flash_model(manifest.model_id)
    for item in manifest.media_inputs:
        if item.media_type != "image" and images_only:
            logger.warning(
                "agnes flash payload withholds %s reference %s (%s): the -flash "
                "SKU accepts images only (2026-09-29 ruling); upstream "
                "apply_provider_reference_limits should already have omitted it",
                item.media_type,
                item.binding_id,
                item.label,
            )
            continue
        url = _agnes_reference_url(item)
        description = _agnes_reference_description(item)
        if item.media_type == "image":
            images.append(url)
            described.append(("Picture", len(images), description))
        elif item.media_type == "video":
            # ``start_seconds`` and ``require_audio`` describe one clip's own
            # trim and soundtrack; nothing in the manifest records either, and a
            # guessed default is a decision made on the provider's behalf.  They
            # belong here once a binding can carry them, not invented now.
            videos.append({"url": url})
            described.append(("Video", len(videos), description))
        else:
            audios.append(url)
            described.append(("Audio", len(audios), description))
    if images:
        payload["images"] = images
    if videos:
        payload["videos"] = videos
    if audios:
        payload["audios"] = audios
    if described:
        payload["mode"] = "reference"
        payload["prompt"] = _agnes_reference_directives(manifest.prompt, described)
    return payload


def _agnes_reference_url(item: SeedanceMediaInputV1) -> str:
    """The one thing Agnes accepts in a reference array: a URL it can fetch.

    ``images`` and ``audios`` are bare strings, ``videos`` is ``{"url": ...}``
    per clip.  ``data_url`` counts because the bytes are inline and already
    ours; ``provider_uploaded_url`` and ``{media_type}_url`` are URLs.  A
    ``provider_file_id`` has no URL form on this endpoint, and skipping it is
    exactly how this branch used to lose whole media types without a word -- so
    it raises instead, and the run says which reference it could not express.
    """

    if item.provider_input_type == f"{item.media_type}_url":
        return item.provider_input_value
    if item.provider_input_type == "provider_uploaded_url":
        return item.provider_input_value
    if item.provider_input_type == "data_url" and item.media_type == "image":
        return item.provider_input_value
    raise ValueError("provider_reference_delivery_unavailable")


def _agnes_reference_description(item: SeedanceMediaInputV1) -> str:
    """What this reference is for, in the operator's own validated wording.

    ``reference_instruction`` was compiled from the binding's
    reference kind and purpose by ``compile_provider_reference_instruction``,
    which is why it is preferred over the label: the label names the asset, the
    instruction says what to do with it.  Only single-line text can go into the
    prompt block.
    """

    text = item.reference_instruction or item.label
    return " ".join(str(text).split())


def _agnes_reference_directives(
    prompt: str,
    described: Sequence[tuple[str, int, str]],
) -> str:
    """Tell the model what each numbered reference is for.

    Agnes resolves ``<Picture N>`` / ``<Video N>`` / ``<Audio N>`` against the
    corresponding array *by position*, each numbered from 1 on its own, so the
    numbering in the text and the order of the array are the same claim stated
    twice -- which is why both are built from one walk.  The provider's own
    guidance is that unattributed material is harder to steer than none, and a
    video reference especially so: "follow this camera" has to be said.
    """

    lines = [f"<{name} {position}>: {description}" for name, position, description in described]
    if not lines:
        return prompt
    body = "\n".join(lines)
    if not prompt.strip():
        return body
    return f"{prompt.rstrip()}\n\nReference materials:\n{body}"


def _seedance_image_content_items(input_assets: Any) -> list[dict[str, Any]]:
    if not isinstance(input_assets, list):
        return []
    content_items = []
    for asset in input_assets:
        if not isinstance(asset, dict):
            continue
        if asset.get("role") not in SEEDANCE_SEGMENT_IMAGE_ROLES:
            continue
        model_input_type = asset.get("model_input_type")
        image_url = (
            asset.get("model_input_value")
            if model_input_type in {"image_url", "data_url", "provider_uploaded_url"}
            else asset.get("url")
        )
        if not isinstance(image_url, str) or not image_url.strip():
            continue
        if not _is_seedance_compatible_image_input(image_url):
            raise ValueError("v2_provider_reference_url_invalid")
        content_items.append(
            {
                "type": "image_url",
                "role": "reference_image",
                "image_url": {
                    "url": image_url,
                },
            }
        )
    return content_items


def _seedance_segment_image_url(asset: dict[str, Any]) -> str:
    """Where a segment's picture reference actually points.

    ``model_input_value`` when the recorded type says it carries the bytes, and
    ``url`` otherwise -- the same precedence ``_seedance_image_content_items``
    uses, because they walk the same list and must not disagree about which
    field holds the payload.
    """

    model_input_type = asset.get("model_input_type")
    value = (
        asset.get("model_input_value")
        if model_input_type in {"image_url", "data_url", "provider_uploaded_url"}
        else asset.get("url")
    )
    return value.strip() if isinstance(value, str) else ""


def _seedance_segment_reference_description(asset: dict[str, Any]) -> str:
    """What this reference is for, in the wording recorded on the binding.

    Legacy segment references carry a ``description`` or a ``semantic_type``;
    the manifest path compiles a ``reference_instruction`` from the binding's
    kind and purpose.  Both are preferred over naming the asset, and both are
    single-line text because they are pasted into the prompt.
    """

    for key in ("description", "reference_instruction", "semantic_type"):
        value = asset.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return "reference image"


def _seedance_segment_reference_plan(
    segment: dict[str, Any],
    *,
    images_only: bool = False,
) -> tuple[list[str], list[dict[str, Any]], list[tuple[str, int, str]]]:
    """Split a legacy segment's references into the three arrays Agnes accepts.

    Returns ``(images, videos, described)`` where ``described`` is
    ``(kind, position, description)`` per reference in the order each array is
    built -- which is the order ``<Picture N>`` / ``<Video N>`` in the prompt are
    numbered against, because Agnes resolves those placeholders against their own
    array by position.  So one walk builds both claims.

    A motion clip is *refused*, not skipped, when it is not a URL the provider
    can fetch: the local previs file has no public address until someone
    publishes one, and a silently dropped camera is indistinguishable from a
    model that simply ignored the reference.  That is the failure this whole
    channel used to have -- and unlike an image, a clip cannot be inlined as a
    data URL, because the payload is the file and the provider has to stream it.

    ``images_only`` is the ``-flash`` carve-out (2026-09-29 作者裁定): that SKU
    refuses the ``videos`` parameter outright, so the clip is withheld with a
    warning rather than refused or sent -- the segment degrades to its images
    and says so in the log, which is the only channel left once the provider
    stopped accepting the parameter.
    """

    images: list[str] = []
    videos: list[dict[str, Any]] = []
    described: list[tuple[str, int, str]] = []
    for asset in segment.get("input_assets") or []:
        if not isinstance(asset, dict):
            continue
        role = asset.get("role")
        if role not in SEEDANCE_SEGMENT_IMAGE_ROLES:
            if role != SEEDANCE_SEGMENT_MOTION_ROLE:
                continue
            if images_only:
                logger.warning(
                    "agnes flash payload withholds motion reference %s: the "
                    "-flash SKU accepts images only (2026-09-29 ruling)",
                    asset.get("asset_id") or asset.get("url") or "<unnamed>",
                )
                continue
            url = asset.get("model_input_value")
            if not isinstance(url, str):
                url = asset.get("url")
            url = url.strip() if isinstance(url, str) else ""
            if not url or not _is_seedance_compatible_image_input(url):
                raise ValueError("provider_reference_delivery_unavailable")
            # No ``start_seconds`` and no ``require_audio``: one is the clip's
            # own trim and the other describes its soundtrack, and a guessed
            # default for either is a decision made on the provider's behalf.
            # They belong here once a binding can carry them.
            videos.append({"url": url})
            described.append(
                ("Video", len(videos), _seedance_segment_reference_description(asset))
            )
            continue
        image_url = _seedance_segment_image_url(asset)
        if not image_url:
            continue
        if not _is_seedance_compatible_image_input(image_url):
            raise ValueError("v2_provider_reference_url_invalid")
        images.append(image_url)
        described.append(
            ("Picture", len(images), _seedance_segment_reference_description(asset))
        )
    return images, videos, described


def _seedance_manifest_content_item(item: SeedanceMediaInputV1) -> dict[str, Any]:
    if item.provider_input_type == "data_url" and item.media_type != "image":
        raise ValueError("provider_reference_delivery_unavailable")
    if item.provider_input_type == "provider_file_id":
        return {
            "type": "provider_file_id",
            "label": item.label,
            "role": _seedance_wire_role(item),
            "file_id": item.provider_input_value,
        }
    input_type = item.provider_input_type
    if input_type == "provider_uploaded_url":
        input_type = f"{item.media_type}_url"
    if input_type == "data_url":
        input_type = "image_url"
    expected_type = f"{item.media_type}_url"
    if input_type != expected_type:
        raise ValueError("provider_reference_delivery_unavailable")
    content_item = {
        "type": input_type,
        "label": item.label,
        "role": _seedance_wire_role(item),
        input_type: {"url": item.provider_input_value},
    }
    if item.reference_instruction is not None:
        content_item["reference_instruction"] = item.reference_instruction
    return content_item


def _seedance_wire_role(item: SeedanceMediaInputV1) -> str:
    return "reference_image" if item.media_type == "image" else item.input_role


def _validate_storyboard_grounding_payload(
    manifest: SeedanceInputManifestV1,
    payload: dict[str, Any],
) -> None:
    plan = manifest.grounding_plan
    if plan is None:
        return
    ordered_images = tuple(item for item in manifest.media_inputs if item.media_type == "image")
    expected = tuple(
        (item.asset_id, item.version_id, item.checksum) for item in plan.ordered_references
    )
    actual = tuple((item.asset_id, item.version_id, item.checksum) for item in ordered_images)
    if (
        not actual
        or actual[0] != (plan.grid_asset_id, plan.grid_version_id, plan.grid_checksum)
        or any(identity not in expected for identity in actual)
        or tuple(expected.index(identity) for identity in actual)
        != tuple(sorted(expected.index(identity) for identity in actual))
        or any(
            reference.required and identity not in actual
            for reference, identity in zip(
                plan.ordered_references,
                expected,
                strict=True,
            )
        )
        or len(ordered_images) > plan.provider_reference_limit
    ):
        raise ValueError("v2_storyboard_grid_provider_payload_invalid")

    expected_labels = tuple(f"Image {index}" for index in range(1, len(ordered_images) + 1))
    if tuple(item.label for item in ordered_images) != expected_labels:
        raise ValueError("v2_storyboard_grid_provider_payload_invalid")
    if any(label not in manifest.prompt for label in expected_labels):
        raise ValueError("v2_storyboard_grid_provider_payload_invalid")
    expected_roles = {
        (reference.asset_id, reference.version_id): reference.semantic_role
        for reference in plan.ordered_references
    }
    for item in ordered_images:
        identity = (item.asset_id, item.version_id)
        actual_role = _grounding_semantic_role(item)
        if actual_role != expected_roles[identity]:
            raise ValueError("v2_storyboard_grid_provider_payload_invalid")
    if any(
        private_value in manifest.prompt
        for item in ordered_images
        for private_value in (
            item.asset_id,
            item.version_id or "",
            item.binding_id,
            item.provider_input_value,
        )
        if private_value
    ):
        raise ValueError("v2_storyboard_grid_provider_payload_invalid")

    wire_images = tuple(
        item
        for item in payload.get("content", ())
        if isinstance(item, dict) and item.get("type") in {"image_url", "provider_file_id"}
    )
    if len(wire_images) != len(ordered_images):
        raise ValueError("v2_storyboard_grid_provider_payload_invalid")
    for expected_item, wire_item in zip(ordered_images, wire_images, strict=True):
        if (
            wire_item.get("label") != expected_item.label
            or wire_item.get("role") != "reference_image"
        ):
            raise ValueError("v2_storyboard_grid_provider_payload_invalid")
        if expected_item.provider_input_type == "provider_file_id":
            if wire_item.get("file_id") != expected_item.provider_input_value:
                raise ValueError("v2_storyboard_grid_provider_payload_invalid")
            continue
        input_value = _wire_media_url(wire_item)
        if input_value != expected_item.provider_input_value:
            raise ValueError("v2_storyboard_grid_provider_payload_invalid")
        if not _is_seedance_compatible_image_input(input_value):
            raise ValueError("v2_storyboard_grid_reference_delivery_failed")


def _wire_media_url(content_item: dict[str, Any]) -> str:
    image_url = content_item.get("image_url")
    if not isinstance(image_url, dict):
        return ""
    value = image_url.get("url")
    return value if isinstance(value, str) else ""


def _grounding_semantic_role(item: SeedanceMediaInputV1) -> str:
    if item.reference_purpose == "storyboard_grid":
        return "storyboard_grid"
    return {
        "character": "character_reference",
        "scene": "scene_reference",
        "scene_board": "scene_reference",
        "environment_reference": "scene_reference",
        "product": "product_reference",
        "prop": "prop_reference",
    }.get(item.source_semantic_role or "", item.source_semantic_role or "reference")


def _is_seedance_compatible_image_input(value: str) -> bool:
    stripped = value.strip()
    if stripped.startswith("data:image/") and ";base64," in stripped:
        return True
    parsed = urlparse(stripped)
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    if hostname.lower() in {"localhost", "0.0.0.0"}:
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    )


def _normalize_video_resolution(value: Any) -> str:
    normalized = str(value or ARK_SEEDANCE_RESOLUTION).strip().lower()
    if normalized not in SUPPORTED_VIDEO_RESOLUTIONS:
        raise ValueError(
            "Unsupported video resolution. Supported values are: "
            f"{', '.join(sorted(SUPPORTED_VIDEO_RESOLUTIONS))}."
        )
    return normalized


def _normalize_video_ratio(value: Any) -> str:
    normalized = str(value or DEFAULT_VIDEO_RATIO).strip().replace("：", ":")
    if normalized not in SUPPORTED_VIDEO_ASPECT_RATIOS:
        raise ValueError(
            "Unsupported video aspect ratio. Supported values are: "
            f"{', '.join(sorted(SUPPORTED_VIDEO_ASPECT_RATIOS))}."
        )
    return normalized


def _normalize_image_generation_size(value: Any, *, model: str = "") -> str:
    """Normalize a configured image size for the model that will receive it.

    The 3,686,400-pixel floor is a Volcengine Ark seedream requirement -- it is
    exactly 1920x1920, which is why ``IMAGE_GENERATION_SIZE`` was pinned there.
    StepFun's image models have no such floor: they accept a closed set of five
    or six specific sizes, the smallest documented one being 256x256.  Applying
    the Ark floor to a StepFun request is what made every StepFun size below
    1920x1920 a local configuration error, which in turn forced the config to
    carry a resolution the gateway does not accept at all.

    ``model`` is the model the request will actually name.  It defaults to empty,
    which keeps the Ark floor for every caller that does not say otherwise.
    """

    raw = str(value or "").strip()
    normalized = raw.replace("X", "x").replace(" ", "").lower()
    parts = normalized.split("x")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise MediaConfigurationError(
            "IMAGE_GENERATION_SIZE must be WxH with at least "
            f"{SEEDREAM_MIN_IMAGE_PIXELS} pixels; got {raw!r}."
        )

    width, height = (int(part) for part in parts)
    if width <= 0 or height <= 0:
        raise MediaConfigurationError(
            "IMAGE_GENERATION_SIZE must be WxH with at least "
            f"{SEEDREAM_MIN_IMAGE_PIXELS} pixels; got {raw!r}."
        )
    if is_stepfun_image_model(model) or is_agnes_image_model(model):
        # StepFun's constraint is a closed set of sizes, not a pixel floor, and
        # ``serialize_volcengine_image_generation_request`` maps anything outside
        # the set onto the nearest supported value.  Rejecting here would only
        # re-impose the Ark floor under a different name.  Agnes documents a
        # ``width x height`` table whose smallest entry is 864x1152 (995,328
        # pixels, well under the floor), so the same exemption applies to it.
        return normalized
    pixels = width * height
    if pixels < SEEDREAM_MIN_IMAGE_PIXELS:
        raise MediaConfigurationError(
            "IMAGE_GENERATION_SIZE must be WxH with at least "
            f"{SEEDREAM_MIN_IMAGE_PIXELS} pixels; got {raw!r} ({pixels} pixels)."
        )
    return normalized


def _ark_seedance_video_task_payload(
    settings: Settings,
    final_video_prompt: dict[str, Any],
) -> dict[str, Any]:
    prompt = str(final_video_prompt.get("final_video_prompt") or "").strip()
    if not prompt:
        raise ValueError("Seedance video generation requires final_video_prompt.")

    return {
        "model": settings.video_generation_model,
        "content": [
            {
                "type": "text",
                "text": prompt,
            }
        ],
        "resolution": _normalize_video_resolution(
            final_video_prompt.get("output_resolution")
            or final_video_prompt.get("resolution")
            or settings.video_generation_resolution
        ),
        "ratio": _normalize_video_ratio(final_video_prompt.get("aspect_ratio")),
        "duration": _seedance_task_duration(final_video_prompt.get("duration_seconds")),
        "generate_audio": bool(final_video_prompt.get("generate_audio", False)),
        "watermark": False,
        "camera_fixed": bool(final_video_prompt.get("camera_fixed", False)),
    }


def _final_video_segments(final_video_prompt: dict[str, Any]) -> list[dict[str, Any]]:
    input_assets = [
        asset
        for asset in final_video_prompt.get("input_assets", [])
        if isinstance(asset, dict) and isinstance(asset.get("asset_id"), str)
    ]
    v2_segments = [
        segment for segment in final_video_prompt.get("segments", []) if isinstance(segment, dict)
    ]
    if v2_segments:
        return [
            _segment_from_v2_segment(segment, index, input_assets)
            for index, segment in enumerate(
                sorted(v2_segments, key=lambda value: int(value.get("order") or 0)),
                start=1,
            )
        ]

    total_duration = _integer_duration(final_video_prompt.get("duration_seconds"))
    scene_prompts = [
        scene
        for scene in final_video_prompt.get("scene_prompts", [])
        if isinstance(scene, dict) and str(scene.get("prompt") or "").strip()
    ]
    if _scene_prompts_are_valid_segments(scene_prompts, total_duration):
        return [
            _segment_from_scene_prompt(scene, index, input_assets)
            for index, scene in enumerate(scene_prompts, start=1)
        ]

    durations = _normalized_segment_durations(total_duration)
    return [
        _normalized_segment(
            final_video_prompt,
            scene_prompts,
            input_assets,
            order,
            duration,
            len(durations),
        )
        for order, duration in enumerate(durations, start=1)
    ]


def _scene_prompts_are_valid_segments(
    scene_prompts: list[dict[str, Any]],
    total_duration: int,
) -> bool:
    if not scene_prompts:
        return False
    durations = [
        _integer_duration(scene.get("duration_seconds"), allow_float=True)
        for scene in scene_prompts
    ]
    return (
        all(duration in SEEDANCE_SINGLE_TASK_DURATIONS_SECONDS for duration in durations)
        and sum(durations) == total_duration
    )


def _segment_from_scene_prompt(
    scene: dict[str, Any],
    order: int,
    input_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    segment_assets = _segment_input_assets(input_assets, scene.get("input_asset_ids", []))
    shot_id = str(scene.get("shot_id") or scene.get("item_id") or f"shot_{order:03d}")
    return {
        "order": order,
        "scene_id": scene.get("scene_id") or f"scene-{scene.get('order', order)}",
        "asset_id": f"storyboard-video-segment-{order}",
        "entity_id": shot_id,
        "shot_id": shot_id,
        "item_id": shot_id,
        "primary_scene_id": scene.get("primary_scene_id") or scene.get("scene_id"),
        "scene_reference_ids": scene.get("scene_reference_ids", []),
        "character_ids": scene.get("character_ids", []),
        "product_reference_ids": scene.get("product_reference_ids", []),
        "style_reference_ids": scene.get("style_reference_ids", []),
        "no_scene_reason": scene.get("no_scene_reason"),
        "prompt": str(scene["prompt"]).strip(),
        "duration_seconds": _seedance_task_duration(scene.get("duration_seconds")),
        "input_asset_ids": [asset["asset_id"] for asset in segment_assets],
        "input_assets": segment_assets,
        "source_assets": [asset["asset_id"] for asset in segment_assets],
        "source_storyboard_image": scene.get("source_storyboard_image"),
        "storyboard_asset_id": scene.get("storyboard_asset_id"),
        "source_scene_orders": [scene.get("order", order)],
        "metadata": scene.get("metadata") if isinstance(scene.get("metadata"), dict) else {},
    }


def _segment_from_v2_segment(
    segment: dict[str, Any],
    order: int,
    input_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt = str(segment.get("prompt") or segment.get("provider_prompt") or "").strip()
    input_asset_ids = _ordered_segment_asset_ids(
        segment.get("input_asset_ids"),
        segment.get("source_assets"),
        segment.get("source_asset_ids"),
    )
    segment_assets = _segment_input_assets(input_assets, input_asset_ids)
    shot_id = str(
        segment.get("shot_id")
        or segment.get("item_id")
        or segment.get("scene_id")
        or f"shot_{order:03d}"
    )
    return {
        **segment,
        "order": int(segment.get("order") or order),
        "scene_id": segment.get("scene_id") or shot_id,
        "asset_id": segment.get("asset_id") or f"storyboard-video-segment-{order}",
        "entity_id": segment.get("entity_id") or shot_id,
        "shot_id": shot_id,
        "item_id": segment.get("item_id") or shot_id,
        "prompt": prompt,
        "duration_seconds": _seedance_task_duration(segment.get("duration_seconds")),
        "input_asset_ids": [asset["asset_id"] for asset in segment_assets],
        "input_assets": segment_assets,
        "source_assets": [asset["asset_id"] for asset in segment_assets],
        "metadata": segment.get("metadata") if isinstance(segment.get("metadata"), dict) else {},
    }


def _ordered_segment_asset_ids(*values: Any) -> list[str]:
    ordered: list[str] = []
    for value in values:
        if not isinstance(value, list):
            continue
        ordered.extend(str(asset_id) for asset_id in value if isinstance(asset_id, str))
    return list(dict.fromkeys(asset_id.strip() for asset_id in ordered if asset_id.strip()))


def _normalized_segment(
    final_video_prompt: dict[str, Any],
    scene_prompts: list[dict[str, Any]],
    input_assets: list[dict[str, Any]],
    order: int,
    duration: int,
    total_segments: int,
) -> dict[str, Any]:
    prompt = _normalized_segment_prompt(final_video_prompt, scene_prompts, order, total_segments)
    input_asset_ids = {
        asset_id
        for scene in scene_prompts
        for asset_id in scene.get("input_asset_ids", [])
        if isinstance(asset_id, str)
    }
    segment_assets = _segment_input_assets(input_assets, sorted(input_asset_ids))
    return {
        "order": order,
        "scene_id": f"scene-{order}",
        "asset_id": f"storyboard-video-segment-{order}",
        "prompt": prompt,
        "duration_seconds": duration,
        "input_asset_ids": [asset["asset_id"] for asset in segment_assets],
        "input_assets": segment_assets,
        "source_assets": [asset["asset_id"] for asset in segment_assets],
        "source_scene_orders": _source_scene_orders(scene_prompts, order, total_segments),
    }


def _segment_input_assets(
    input_assets: list[dict[str, Any]],
    input_asset_ids: Any,
) -> list[dict[str, Any]]:
    requested_ids = (
        {asset_id for asset_id in input_asset_ids if isinstance(asset_id, str)}
        if isinstance(input_asset_ids, list)
        else set()
    )
    if requested_ids:
        return [
            asset
            for asset in input_assets
            if str(asset.get("asset_id") or "").strip() in requested_ids
        ]
    selected_assets = []
    seen_asset_ids = set()
    reusable_reference_roles = {
        "product_reference",
        "character_turnaround",
        "scene_reference",
        "storyboard",
    }
    for asset in input_assets:
        asset_id = asset["asset_id"]
        should_include = asset_id in requested_ids or asset.get("role") in reusable_reference_roles
        if should_include and asset_id not in seen_asset_ids:
            selected_assets.append(asset)
            seen_asset_ids.add(asset_id)
    return selected_assets


def _normalized_segment_prompt(
    final_video_prompt: dict[str, Any],
    scene_prompts: list[dict[str, Any]],
    order: int,
    total_segments: int,
) -> str:
    final_prompt = str(final_video_prompt.get("final_video_prompt") or "").strip()
    if len(scene_prompts) <= 1:
        return final_prompt

    selected_scenes = _scene_prompt_group(scene_prompts, order, total_segments)
    scene_text = " ".join(str(scene.get("prompt", "")).strip() for scene in selected_scenes)
    if not scene_text:
        return final_prompt
    return f"Segment {order}/{total_segments}. {scene_text}"


def _source_scene_orders(
    scene_prompts: list[dict[str, Any]],
    order: int,
    total_segments: int,
) -> list[Any]:
    return [
        scene.get("order")
        for scene in _scene_prompt_group(scene_prompts, order, total_segments)
        if scene.get("order") is not None
    ]


def _scene_prompt_group(
    scene_prompts: list[dict[str, Any]],
    order: int,
    total_segments: int,
) -> list[dict[str, Any]]:
    if not scene_prompts:
        return []
    start = (order - 1) * len(scene_prompts) // total_segments
    end = order * len(scene_prompts) // total_segments
    if end <= start:
        end = min(start + 1, len(scene_prompts))
    return scene_prompts[start:end]


def _normalized_segment_durations(total_duration: int) -> list[int]:
    """Split a total duration into per-task segments the model actually accepts.

    The old implementation required ``total_duration % 5 == 0`` and emitted a
    list of 10s (plus one 5s), which made any shot whose length was not a
    multiple of five -- every 3D previs shot in the rose workflow -- impossible
    to segment at all.  Segments now target the model's 7-8s quality band and
    fall back to whole seconds that still sum exactly to ``total_duration``.
    """

    total = int(total_duration)
    if total < SEEDANCE_MIN_SINGLE_TASK_DURATION_SECONDS:
        raise ValueError(
            "Final video duration must be at least "
            f"{SEEDANCE_MIN_SINGLE_TASK_DURATION_SECONDS} second; got {total} seconds."
        )

    target = min(SEEDANCE_PREFERRED_SEGMENT_SECONDS, SEEDANCE_MAX_SINGLE_TASK_DURATION_SECONDS)
    count = max(1, -(-total // target))  # ceil(total / target)
    count = max(count, -(-total // SEEDANCE_MAX_SINGLE_TASK_DURATION_SECONDS))

    base, remainder = divmod(total, count)
    # Spread the remainder over the leading segments (never the trailing one) so
    # the shot's closing beat is not the shortest -- that reads as an edit.
    durations = [base + (1 if index < remainder else 0) for index in range(count)]

    for duration in durations:
        if duration not in SEEDANCE_SINGLE_TASK_DURATIONS_SECONDS:
            raise ValueError(
                "Cannot split the final video duration into Seedance segments "
                f"of {SEEDANCE_MIN_SINGLE_TASK_DURATION_SECONDS}-"
                f"{SEEDANCE_MAX_SINGLE_TASK_DURATION_SECONDS} seconds: got {total} seconds."
            )
    return durations


def _integer_duration(duration_seconds: Any, allow_float: bool = False) -> int:
    try:
        duration = float(duration_seconds) if allow_float else int(duration_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("Video generation requires duration_seconds.") from exc
    if allow_float and not duration.is_integer():
        return int(duration)
    return int(duration)


def _seedance_task_duration(duration_seconds: Any) -> int:
    try:
        duration = int(duration_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("Seedance video generation requires an integer duration_seconds.") from exc

    if duration in SEEDANCE_SINGLE_TASK_DURATIONS_SECONDS:
        return duration
    if duration > SEEDANCE_MAX_SINGLE_TASK_DURATION_SECONDS:
        raise ValueError(
            "Seedance single video generation supports "
            f"{SEEDANCE_MIN_SINGLE_TASK_DURATION_SECONDS} to "
            f"{SEEDANCE_MAX_SINGLE_TASK_DURATION_SECONDS} seconds per task; "
            f"got {duration} seconds. Split the workflow into multiple short video "
            "segments and compose them for longer ads."
        )
    raise ValueError(
        "Seedance video generation duration must be between "
        f"{SEEDANCE_MIN_SINGLE_TASK_DURATION_SECONDS} and "
        f"{SEEDANCE_MAX_SINGLE_TASK_DURATION_SECONDS} seconds; "
        f"got {duration} seconds."
    )
