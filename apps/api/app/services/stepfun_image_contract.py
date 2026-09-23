"""The StepFun image-generation contract, transcribed from the provider docs.

Source of truth (checked 2026-09-21 against the local StepFun documentation
snapshots):

* ``stepfun_docs_llm.txt:15762-15796`` -- the 文生图 request-parameter table
  (``model``, ``prompt``, ``size``, ``n``, ``response_format``, ``seed``,
  ``steps``, ``cfg_scale``, ``negative_prompt``, ``text_mode``)
* ``stepfun_docs_llm.txt:8096-8103`` -- the ``step-image-edit-2`` key-parameter
  summary (prompt ceiling, ``steps`` range, ``cfg_scale`` range, size table)
* ``工具模型.txt:59-98`` -- the same model page, which states the sizes again
  and notes the ``height x width`` ordering

Three limits in those tables were enforced nowhere in this codebase, and each
one alone was enough to make every image request fail:

1. **``size``**.  ``step-image-edit-2`` accepts exactly five values and
   ``step-2x-large`` accepts six, and neither list contains a 1920 or 2048
   square.  But ``Settings.image_generation_size`` defaulted to ``2048x2048``,
   this deployment's ``.env`` sets ``1920x1920``, and
   ``GUIDED_IMAGE_SIZES_BY_ASPECT_RATIO`` advertised ``2048x2048`` /
   ``2560x1440`` / ``1440x2560`` / ``2304x1728`` / ``1728x2304`` -- a
   Volcengine Ark table -- as the StepFun models'
   ``supported_sizes_by_aspect_ratio``.  So the catalog told callers StepFun
   accepts sizes it has never accepted.

2. **``prompt`` length**.  The ceiling is 512 characters.  The compiled prompt
   for a nine-panel storyboard node is well over a thousand (role boundary +
   creative prompt + one line per panel + style clause), so the request was
   certain to be refused on length regardless of size.

3. **``negative_prompt`` length**, also 512.

Keeping the tables here gives them one home and lets the tests assert against
the same numbers the serializer enforces, so the two cannot drift.

Note on ``sequential_image_generation``: it is a Volcengine Ark field and is
absent from the StepFun parameter table, but this module deliberately does
**not** strip it.  ``tests/test_stepfun_only_image_catalog.py:380`` records an
observation that the gateway answers 400 without the field, and while the image
engine is overloaded that claim cannot be re-verified.  Removing a field that
may be required, on evidence that cannot currently be checked, would trade a
known-good request for a guess.
"""

from __future__ import annotations

from collections.abc import Mapping

#: Documented ceiling for ``prompt`` on both StepFun image models.
STEPFUN_IMAGE_PROMPT_MAX_CHARS = 512

#: Documented ceiling for ``negative_prompt`` (``step-image-edit-2`` only).
STEPFUN_IMAGE_NEGATIVE_PROMPT_MAX_CHARS = 512

#: Documented ``steps`` range and default.
STEPFUN_IMAGE_STEPS_RANGE: tuple[int, int] = (1, 50)
STEPFUN_IMAGE_STEPS_DEFAULT = 8

#: Documented ``cfg_scale`` range and default.
STEPFUN_IMAGE_CFG_SCALE_RANGE: tuple[float, float] = (1.0, 10.0)
STEPFUN_IMAGE_CFG_SCALE_DEFAULT = 1.0

#: The five documented ``step-image-edit-2`` sizes, keyed by aspect ratio.
#: The docs state the format is ``height x width``, NOT ``width x height`` --
#: which is why ``16:9`` maps to the portrait-looking ``768x1360``: 768 is the
#: height and 1360 the width of a landscape frame.
STEPFUN_IMAGE_SIZES_BY_ASPECT_RATIO: Mapping[str, str] = {
    "1:1": "1024x1024",
    "16:9": "768x1360",
    "9:16": "1360x768",
    "4:3": "896x1184",
    "3:4": "1184x896",
}

#: The six documented ``step-2x-large`` sizes (stepfun_docs_llm.txt:15774-15776).
_STEP_2X_LARGE_SIZES: frozenset[str] = frozenset(
    {"256x256", "512x512", "768x768", "1024x1024", "1280x800", "800x1280"}
)

#: Every size either StepFun image model accepts, keyed by model id.
STEPFUN_IMAGE_SIZES_BY_MODEL: Mapping[str, frozenset[str]] = {
    "step-image-edit-2": frozenset(STEPFUN_IMAGE_SIZES_BY_ASPECT_RATIO.values()),
    "step-2x-large": _STEP_2X_LARGE_SIZES,
}

#: The square fallback for each model -- the size with no orientation bias, so
#: it is the safest target when the requested size cannot be matched.
STEPFUN_IMAGE_SQUARE_SIZE_BY_MODEL: Mapping[str, str] = {
    "step-image-edit-2": "1024x1024",
    "step-2x-large": "1024x1024",
}


def supported_stepfun_image_sizes(model: str) -> frozenset[str]:
    """Every ``size`` value the given StepFun image model accepts."""

    return STEPFUN_IMAGE_SIZES_BY_MODEL.get(model, frozenset())


def is_stepfun_image_model(model: str) -> bool:
    return model in STEPFUN_IMAGE_SIZES_BY_MODEL


def _split(size: str) -> tuple[int, int] | None:
    """Split an ``AxB`` string into its two integers, or None if malformed."""

    parts = size.lower().split("x")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    first, second = (int(part) for part in parts)
    if first <= 0 or second <= 0:
        return None
    return first, second


def _requested_orientation(size: str) -> str | None:
    """Orientation of a *requested* size.

    A requested size is ``width x height`` -- that is the convention
    ``_normalize_image_generation_size`` (``seedance_adapter.py:378``) parses the
    configured ``IMAGE_GENERATION_SIZE`` with, and the one the Volcengine table
    ``GUIDED_IMAGE_SIZES_BY_ASPECT_RATIO`` is written in.
    """

    dimensions = _split(size)
    if dimensions is None:
        return None
    width, height = dimensions
    if width == height:
        return "square"
    return "portrait" if height > width else "landscape"


def _requested_ratio(size: str) -> float | None:
    """``width / height`` of a requested size."""

    dimensions = _split(size)
    if dimensions is None:
        return None
    width, height = dimensions
    return width / height


def _supported_orientation(size: str) -> str | None:
    """Orientation of a *supported* StepFun size.

    The docs state StepFun's format is ``height x width``, "not ``width x
    height``" (``stepfun_docs_llm.txt:15771``).  Getting this backwards would
    turn every landscape request into a portrait image and vice versa, so the
    two conventions are parsed by separate helpers rather than by one function
    that callers have to remember to swap.
    """

    dimensions = _split(size)
    if dimensions is None:
        return None
    height, width = dimensions
    if height == width:
        return "square"
    return "portrait" if height > width else "landscape"


def _supported_ratio(size: str) -> float:
    """``width / height`` of a supported StepFun size, for like-for-like comparison."""

    height, width = _split(size)  # type: ignore[misc]
    return width / height


def nearest_supported_stepfun_image_size(
    model: str,
    requested: str,
) -> str | None:
    """The supported size closest to ``requested``, preserving orientation.

    ``requested`` is ``width x height``; the returned value is ``height x width``
    because that is the order StepFun documents.  The swap is the whole point of
    this function -- a caller that reads ``1920x1920`` as ``height x width`` and
    matches it against StepFun's ``height x width`` table gets the right answer
    by luck, while a caller reading ``2560x1440`` (Ark's 16:9) the same way
    concludes it is portrait and maps it to StepFun's portrait size, producing a
    rotated image.
    """

    supported = supported_stepfun_image_sizes(model)
    if not supported:
        return None
    if requested in supported:
        return requested
    orientation = _requested_orientation(requested)
    ratio = _requested_ratio(requested)
    if orientation is None or ratio is None:
        return STEPFUN_IMAGE_SQUARE_SIZE_BY_MODEL.get(model)

    same_orientation = [
        candidate
        for candidate in supported
        if _supported_orientation(candidate) == orientation
    ]
    pool = same_orientation or list(supported)
    return min(
        pool,
        key=lambda candidate: (abs(_supported_ratio(candidate) - ratio), candidate),
    )


def normalize_stepfun_image_size(
    model: str,
    requested: str,
) -> tuple[str, str | None]:
    """Return ``(size, normalization_code)`` for a StepFun image request.

    A size the model accepts passes through untouched with no code.  Anything
    else is mapped onto the nearest accepted size and reported with
    ``image_size_normalized_to_provider_supported``, so the substitution is
    visible in the wire audit instead of silently changing what the caller
    asked for.

    This normalizes rather than raises on purpose.  The configured default was
    ``2048x2048`` and this deployment's ``.env`` says ``1920x1920``; raising
    would turn every image node into a hard failure until an operator edited
    configuration, while normalizing keeps generation working at the closest
    supported resolution and records that it did.
    """

    if not is_stepfun_image_model(model):
        return requested, None
    normalized = nearest_supported_stepfun_image_size(model, requested)
    if normalized is None or normalized == requested:
        return requested, None
    return normalized, "image_size_normalized_to_provider_supported"


def clamp_stepfun_image_prompt(
    model: str,
    prompt: str,
    *,
    field: str = "prompt",
) -> tuple[str, str | None]:
    """Return ``(prompt, normalization_code)`` clamped to the documented ceiling.

    ``step-image-edit-2`` refuses a prompt over 512 characters, and the compiled
    prompt for a nine-panel storyboard is several times that.  Truncating keeps
    the request deliverable; the code records that the caller's text was cut so
    the loss is not invisible.

    The cut is made at a clause boundary where possible -- the compiled prompt
    is ``"\\n\\n"``-joined sections, so dropping whole trailing sections loses
    less than slicing mid-sentence.
    """

    ceiling = STEPFUN_IMAGE_PROMPT_MAX_CHARS
    if not is_stepfun_image_model(model) or len(prompt) <= ceiling:
        return prompt, None
    return _truncate_at_section_boundary(prompt, ceiling), (
        f"image_{field}_truncated_to_provider_limit"
    )


def clamp_stepfun_negative_prompt(model: str, prompt: str) -> tuple[str, str | None]:
    """Same clamp for ``negative_prompt``, whose ceiling is also 512."""

    if not is_stepfun_image_model(model) or len(prompt) <= STEPFUN_IMAGE_NEGATIVE_PROMPT_MAX_CHARS:
        return prompt, None
    return (
        prompt[:STEPFUN_IMAGE_NEGATIVE_PROMPT_MAX_CHARS],
        "image_negative_prompt_truncated_to_provider_limit",
    )


def _truncate_at_section_boundary(prompt: str, ceiling: int) -> str:
    """Keep the leading sections that fit inside ``ceiling`` characters.

    The compiled prompt joins its parts with blank lines, so the first section
    (the role boundary) and as many following sections as fit survive intact.
    If even the first section alone exceeds the ceiling, fall back to a hard cut
    -- an over-long prompt is refused outright, so a cut one at least runs.
    """

    kept: list[str] = []
    used = 0
    for section in prompt.split("\n\n"):
        cost = len(section) + (2 if kept else 0)
        if used + cost > ceiling:
            break
        kept.append(section)
        used += cost
    if not kept:
        return prompt[:ceiling]
    return "\n\n".join(kept)


def stepfun_image_contract_violations(
    model: str,
    *,
    size: str,
    prompt: str,
    negative_prompt: str | None = None,
) -> list[str]:
    """Human-readable contract problems, for preflight and diagnostics.

    Returns an empty list when the request matches the documented contract.
    This is the check that turns "the provider said 503 and we do not know why"
    into a named field, and it runs before the request leaves the process so a
    self-inflicted refusal never costs a call against an overloaded gateway.
    """

    if not is_stepfun_image_model(model):
        return []
    violations: list[str] = []
    supported = supported_stepfun_image_sizes(model)
    if size not in supported:
        violations.append(
            f"size {size!r} is not supported by {model}; "
            f"supported sizes are {', '.join(sorted(supported))}"
        )
    if len(prompt) > STEPFUN_IMAGE_PROMPT_MAX_CHARS:
        violations.append(
            f"prompt is {len(prompt)} characters; {model} accepts at most "
            f"{STEPFUN_IMAGE_PROMPT_MAX_CHARS}"
        )
    if negative_prompt and len(negative_prompt) > STEPFUN_IMAGE_NEGATIVE_PROMPT_MAX_CHARS:
        violations.append(
            f"negative_prompt is {len(negative_prompt)} characters; {model} accepts "
            f"at most {STEPFUN_IMAGE_NEGATIVE_PROMPT_MAX_CHARS}"
        )
    return violations
