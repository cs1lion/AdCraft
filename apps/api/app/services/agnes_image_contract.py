"""The Agnes image-generation contract, transcribed from the provider docs.

Source of truth (checked 2026-09-21 against the local documentation snapshot
``工具模型.txt:1581-1900``, the "Agnes Image 2.5 Flash" page):

* endpoint ``POST https://api.agnes-ai.cn/v1/images/generations``
* request parameters: ``model``, ``prompt``, ``size`` (required),
  ``ratio``, ``image``, ``return_base64``, ``extra_body``
* the output-size table, reproduced below as
  ``AGNES_IMAGE_SIZES_BY_ASPECT_RATIO``
* the warning "请勿在请求体顶层放置 ``response_format``"

This is the fallback for the StepFun image outage
([[adcraft-stepfun-image-503-is-provider-outage]]).  Two things about it are not
guessable from the StepFun contract it replaces, and each one alone breaks
generation:

1. **``watermark`` and ``sequential_image_generation`` are rejected outright.**
   Agnes answers HTTP 400 ``invalid_request`` with
   "``watermark`` 是文生图不支持的字段" and the same for
   ``sequential_image_generation`` -- and ``watermark`` is checked *first*, so a
   request carrying both reports only the watermark and hides the second
   (``e2e_output/rose/probe_agnes_body_shape.py``,
   ``probe_agnes_shape2.py``).  Both fields are in the body this codebase has
   always sent, so an unmodified request cannot succeed against Agnes at all.

2. **The credential is a different one.**  ``api.agnes-ai.cn`` answers **401** to
   ``IMAGE_GENERATION_API_KEY`` (the StepFun key) and **200** to
   ``VIDEO_GENERATION_API_KEY`` -- the key that already drives the Agnes *video*
   endpoint (``probe_agnes_image.py``).  A per-vendor credential cannot be
   selected by capability name; it has to be selected by the endpoint's host.

Two live observations contradict the documentation and are kept deliberately,
for the same reason ``sequential_image_generation`` is kept for StepFun:

* The docs forbid a top-level ``response_format`` and route it through
  ``extra_body``.  Live, both forms return 200 with the expected payload; the
  top-level form is what this codebase already sends, so it is left alone.
* ``return_base64: true`` works, and so does ``extra_body.image`` for img2img,
  even though the parameter table also lists ``image`` at the top level.

**Size convention.** Agnes documents ``width x height`` -- the same convention
as a *requested* size in this codebase, and the opposite of StepFun's
``height x width``.  So ``16:9`` maps to ``1312x736`` (a landscape frame), not
to StepFun's portrait-looking ``768x1360``.  Keeping the two providers' tables
in separate modules, each with its own orientation helpers, is what stops that
swap from being made by accident.
"""

from __future__ import annotations

from collections.abc import Mapping

#: Fields Agnes refuses for text-to-image.  ``watermark`` is reported first, so
#: a body carrying both only ever surfaces the watermark -- which is why the
#: set is dropped wholesale rather than trimmed field by field.
AGNES_IMAGE_UNSUPPORTED_FIELDS: frozenset[str] = frozenset(
    {"watermark", "sequential_image_generation"}
)

#: The documented tier sizes.  A tier is combined with ``ratio``; an exact size
#: is sent on its own and may be normalized server-side.
AGNES_IMAGE_SIZE_TIERS: tuple[str, ...] = ("1K", "2K", "3K", "4K")

#: Every documented ratio, in the order the docs list them.
AGNES_IMAGE_RATIOS: tuple[str, ...] = (
    "1:1",
    "3:4",
    "4:3",
    "16:9",
    "9:16",
    "2:3",
    "3:2",
    "21:9",
)

#: The documented output sizes, ``width x height``, at the 1K tier
#: (``工具模型.txt:1712-1721``).  This is the tier this deployment asks for:
#: ``IMAGE_GENERATION_SIZE`` defaults to ``1024x1024``, which is exactly 1K 1:1,
#: so the common case passes through with no substitution at all.
AGNES_IMAGE_SIZES_BY_ASPECT_RATIO: Mapping[str, str] = {
    "1:1": "1024x1024",
    "3:4": "864x1152",
    "4:3": "1152x864",
    "16:9": "1312x736",
    "9:16": "736x1312",
    "2:3": "832x1248",
    "3:2": "1248x832",
    "21:9": "1568x672",
}

#: The two Agnes image model ids this deployment can reach.  Both are listed by
#: ``GET /v1/models`` on the configured host; 2.5 Flash is the current
#: generation and 2.1 Flash is the one its request shape is documented against.
AGNES_IMAGE_MODEL_IDS: frozenset[str] = frozenset(
    {"agnes-image-2.5-flash", "agnes-image-2.1-flash"}
)

#: Documented prompt ceiling.  Agnes documents none for the image models, so the
#: generous StepFun-style ceiling is not imposed -- an absent limit must not be
#: invented, because inventing one truncates prompts for no reason.
AGNES_IMAGE_PROMPT_MAX_CHARS: int | None = None


def is_agnes_image_model(model: str) -> bool:
    return model in AGNES_IMAGE_MODEL_IDS


def supported_agnes_image_sizes(model: str) -> frozenset[str]:
    """Every exact ``size`` this module maps an Agnes request onto."""

    if not is_agnes_image_model(model):
        return frozenset()
    return frozenset(AGNES_IMAGE_SIZES_BY_ASPECT_RATIO.values())


def _split(size: str) -> tuple[int, int] | None:
    """Split an ``AxB`` string into its two integers, or None if malformed."""

    parts = str(size).strip().lower().replace(" ", "").split("x")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    first, second = (int(part) for part in parts)
    if first <= 0 or second <= 0:
        return None
    return first, second


def _requested_ratio(size: str) -> float | None:
    """``width / height`` of a requested size."""

    dimensions = _split(size)
    if dimensions is None:
        return None
    width, height = dimensions
    return width / height


def _supported_ratio(size: str) -> float:
    """``width / height`` of a documented Agnes size.

    Agnes documents ``width x height``, exactly like a requested size, so the
    two are compared directly.  (StepFun needs the opposite reading, which is
    why ``stepfun_image_contract`` keeps its own pair of helpers rather than
    sharing these.)
    """

    width, height = _split(size)  # type: ignore[misc]
    return width / height


def nearest_supported_agnes_image_size(model: str, requested: str) -> str | None:
    """The documented Agnes size closest to ``requested``, by aspect ratio."""

    if not is_agnes_image_model(model):
        return None
    requested = str(requested or "").strip()
    if requested in AGNES_IMAGE_SIZES_BY_ASPECT_RATIO.values():
        return requested
    ratio = _requested_ratio(requested)
    if ratio is None:
        return AGNES_IMAGE_SIZES_BY_ASPECT_RATIO["1:1"]
    return min(
        AGNES_IMAGE_SIZES_BY_ASPECT_RATIO.values(),
        key=lambda candidate: (abs(_supported_ratio(candidate) - ratio), candidate),
    )


def normalize_agnes_image_size(model: str, requested: str) -> tuple[str, str | None]:
    """Return ``(size, normalization_code)`` for an Agnes image request.

    A size Agnes documents passes through untouched.  Anything else is mapped
    onto the nearest documented size and reported with
    ``image_size_normalized_to_provider_supported``, so the substitution is
    visible in the wire audit rather than silently changing what the caller
    asked for.

    This normalizes rather than raises, for the same reason the StepFun path
    does: the configured default has carried a resolution the gateway does not
    accept (``2048x2048``, then ``1920x1920``), and raising would turn every
    image node into a hard failure until an operator edited configuration.
    Live, Agnes *accepts* an off-table size and normalizes it server-side
    (``1920x1920`` and ``2560x1440`` both returned 200), so the substitution is
    a preference for a predictable frame rather than a requirement.
    """

    if not is_agnes_image_model(model):
        return requested, None
    normalized = nearest_supported_agnes_image_size(model, requested)
    if normalized is None or normalized == str(requested).strip():
        return requested, None
    return normalized, "image_size_normalized_to_provider_supported"


def agnes_image_contract_violations(
    model: str,
    *,
    size: str,
    prompt: str,
    unsupported_fields: Mapping[str, object] | None = None,
) -> list[str]:
    """Human-readable contract problems, for preflight and diagnostics.

    Returns an empty list when the request matches the documented contract.
    The size check is advisory only -- ``normalize_agnes_image_size`` maps an
    off-table size rather than refusing it -- so this reports sizes that will be
    substituted, which is the thing an operator needs to see before the fact.
    """

    if not is_agnes_image_model(model):
        return []
    violations: list[str] = []
    documented = AGNES_IMAGE_SIZES_BY_ASPECT_RATIO.values()
    if str(size).strip() not in documented and str(size).strip() not in AGNES_IMAGE_SIZE_TIERS:
        violations.append(
            f"size {size!r} is not a documented Agnes size; it will be mapped to "
            f"{nearest_supported_agnes_image_size(model, size)!r} "
            f"(documented: {', '.join(documented)})"
        )
    ceiling = AGNES_IMAGE_PROMPT_MAX_CHARS
    if ceiling is not None and len(prompt) > ceiling:
        violations.append(f"prompt is {len(prompt)} characters; the documented ceiling is {ceiling}")
    for field in AGNES_IMAGE_UNSUPPORTED_FIELDS:
        if unsupported_fields and field in unsupported_fields:
            violations.append(
                f"{field!r} is not a supported field for {model} text-to-image; "
                "Agnes answers HTTP 400 invalid_request when it is present"
            )
    return violations
