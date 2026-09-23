from __future__ import annotations

from typing import Any, Protocol


# Seedance's own parameter matrix (provider_model_catalog._ark_video_profile)
# declares duration_seconds as an integer with minimum 1 / maximum 15, and every
# doubao-seedance manifest repeats it as "duration_range_seconds": [1, 15].
# The {5, 10} set that used to live here was copied from an early Ark release
# note and never reconciled with the catalog, so a legal 7s / 8s / 12s request
# was rejected inside our own validator before it ever reached the provider.
# The range is now the single source of truth; the "sweet spot" band below is
# only a *preference* for the segment planner, never a hard rejection.
SEEDANCE_SINGLE_TASK_DURATIONS_SECONDS = frozenset(range(1, 16))
SEEDANCE_MIN_SINGLE_TASK_DURATION_SECONDS = 1
SEEDANCE_MAX_SINGLE_TASK_DURATION_SECONDS = 15
# Quality band observed on the Seedance family: the model is strongest around
# 7-8s and degrades past ~12s.  Segment planning targets this band so a shot is
# cut into more, better clips rather than fewer marginal ones.
SEEDANCE_PREFERRED_SEGMENT_SECONDS = 8
SEEDANCE_SUPPORTED_SEGMENT_SECONDS_CEILING = 12
ARK_SEEDANCE_RESOLUTION = "480p"
DEFAULT_VIDEO_RATIO = "16:9"
SEEDREAM_MIN_IMAGE_PIXELS = 3_686_400


class MediaConfigurationError(RuntimeError):
    """Raised when a media provider cannot be configured."""


class MediaApiError(ValueError):
    """Raised when a real media API returns an error response."""

    def __init__(self, message: str, metadata: dict[str, Any]) -> None:
        super().__init__(message)
        self.metadata = metadata


class MediaProvider(Protocol):
    mode: str

    def generate_storyboard_images(
        self,
        storyboard_scenes: list[dict[str, Any]],
        workflow_id: str,
        input_assets: list[dict[str, Any]] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def generate_scene_reference_images(
        self,
        scene_design: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def generate_product_images(
        self,
        product_design: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def generate_v2_canonical_image(
        self,
        request: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def generate_storyboard_video(
        self,
        storyboard_video_prompt: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def generate_character_turnaround_images(
        self,
        character_design: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def generate_subtitle_asset(
        self,
        script: dict[str, Any],
        duration_seconds: int,
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def generate_audio_assets(
        self,
        sound_effects_plan: dict[str, Any],
        voiceover_plan: dict[str, Any],
        bgm_plan: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def generate_bgm_audio(
        self,
        bgm_plan: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def generate_final_video_from_multimodal_prompt(
        self,
        final_video_prompt: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def synchronize_audio_video(
        self,
        video_asset: dict[str, Any],
        audio_asset: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]: ...

    def compose_final_video(
        self,
        synchronized_asset: dict[str, Any],
        duration_seconds: int,
        workflow_id: str,
    ) -> dict[str, Any]: ...
