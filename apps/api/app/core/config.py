from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_DOTENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_LOCAL_SETTINGS_ALLOWED_ORIGINS = (
    "http://localhost:5189",
    "http://127.0.0.1:5189",
    "http://[::1]:5189",
)


def load_project_dotenv(dotenv_path: Path | None = None) -> bool:
    """Load the project dotenv without replacing explicit process values."""

    return load_dotenv(dotenv_path=dotenv_path or PROJECT_DOTENV_PATH, override=False)


load_project_dotenv()


def _read_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def _read_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


def _read_path(name: str, default: Path) -> Path:
    path = Path(os.getenv(name, str(default))).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_optional_path(name: str) -> Path | None:
    value = os.getenv(name)
    if not value:
        return None
    return _read_path(name, Path(value))


def _read_recommended_catalog_root() -> Path:
    """Read only the portable local Recommended Assets package root."""

    value = Path(os.getenv("V2_RECOMMENDED_CATALOG_ROOT", "assets/catalogs/recommended"))
    if value.is_absolute() or tuple(value.parts[:3]) != ("assets", "catalogs", "recommended"):
        raise ValueError("V2_RECOMMENDED_CATALOG_ROOT must stay below assets/catalogs/recommended")
    return value


def _read_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    app_name: str = "AdCraft"
    app_version: str = "1.0.0"
    v2_production_acceptance_enabled: bool = False
    v2_prompt_materializer_strict: bool = False
    v2_provider_allow_fallback: bool = False
    agent_runtime_mode: str = "real"
    agent_runtime_base_url: str = "http://127.0.0.1:8765"
    agent_runtime_internal_token: str | None = None
    agent_runtime_protocol_version: str = "1"
    agent_runtime_connect_timeout_seconds: float = 5.0
    agent_runtime_read_timeout_seconds: float = 30.0
    agent_runtime_run_timeout_seconds: float = 120.0
    agent_runtime_max_event_bytes: int = 65_536
    agent_runtime_max_stream_bytes: int = 1_048_576
    llm_provider: str = "OpenAI Compatible"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    siliconflow_api_key: str | None = None
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openrouter_api_key: str | None = None
    openrouter_text_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_image_base_url: str = "https://openrouter.ai/api/v1"
    minimax_api_key: str | None = None
    minimax_base_url: str | None = None
    llm_transient_retry_delay_seconds: float = 2.0
    llm_front_desk_model: str = "doubao-seed-2-0-mini-260428"
    llm_team_model: str = "doubao-seed-2-0-mini-260428"
    llm_requirements_model: str = "doubao-seed-2-0-mini-260428"
    llm_product_design_model: str = "doubao-seed-2-0-mini-260428"
    llm_creative_model: str = "doubao-seed-2-0-mini-260428"
    llm_script_model: str = "doubao-seed-2-0-mini-260428"
    llm_character_model: str = "doubao-seed-2-0-mini-260428"
    llm_scene_model: str = "doubao-seed-2-0-mini-260428"
    llm_storyboard_model: str = "doubao-seed-2-0-mini-260428"
    llm_sound_effects_model: str = "doubao-seed-2-0-mini-260428"
    llm_voiceover_model: str = "doubao-seed-2-0-mini-260428"
    llm_bgm_model: str = "doubao-seed-2-0-mini-260428"
    llm_final_video_model: str = "doubao-seed-2-0-mini-260428"
    media_mode: str = "mock"
    skip_audio_agents: bool = False
    local_settings_allowed_origins: tuple[str, ...] = DEFAULT_LOCAL_SETTINGS_ALLOWED_ORIGINS
    # CORS origins for the API (defaults to localhost frontend; set to "*" for development only)
    cors_allowed_origins: tuple[str, ...] = DEFAULT_LOCAL_SETTINGS_ALLOWED_ORIGINS
    # Optional API access token: when set, all /api/v1 and /api/v2 endpoints require Authorization: Bearer <token>
    api_access_token: str | None = None
    image_generation_api_key: str | None = None
    image_generation_endpoint: str | None = None
    #: The image endpoint this deployment is configured against is StepFun's
    #: step_plan gateway, so the executable model is a StepFun one.  The old
    #: ``doubao-seedream-5-0-lite-260128`` default is retired: it is an Ark model
    #: and the gateway answers 404 for it.
    image_generation_model: str = "step-image-edit-2"
    #: Must be a size ``step-image-edit-2`` accepts -- see
    #: ``stepfun_image_contract``.  ``2048x2048`` was the default while this
    #: pointed at Volcengine Ark, and it is not one of the five sizes StepFun
    #: documents.  The serializer normalizes an unlisted size onto the nearest
    #: supported one, so a stale value degrades instead of failing, but the
    #: default should not need that.
    image_generation_size: str = "1024x1024"
    video_generation_api_key: str | None = None
    video_generation_endpoint: str | None = None
    video_generation_model: str = "doubao-seedance-2-0-fast-260128"
    video_generation_resolution: str = "720p"
    video_generation_generate_audio: bool = True
    sound_effects_api_key: str | None = None
    sound_effects_endpoint: str | None = None
    sound_effects_model: str = "volcengine-sound-effects"
    tts_api_key: str | None = None
    tts_endpoint: str | None = None
    tts_model: str = "volcengine-tts"
    stepfun_api_key: str | None = None
    #: Documented at ``工具模型.txt:254`` ("非流式语音合成" -> ``POST
    #: /v1/audio/speech``), served through the ``/step_plan/`` gateway.
    #:
    #: Measured 2026-09-21 with the live key (``e2e_output/capability_matrix.log``,
    #: ``e2e_output/stepplan_artifacts.log``): the direct ``/v1/`` base answers
    #: 402 ``quota_exceeded`` on *every* capability, while the same request to
    #: ``/step_plan/v1/`` answers 200 with a real 78 KB MP3.  An earlier note
    #: here claimed the opposite -- that ``/step_plan/`` answers 401 for audio
    #: -- but that was measured while the key was revoked, so the gateway
    #: rejected the credential before it ever routed.  Re-measure before
    #: trusting either prefix; do not carry this comment forward as fact.
    #:
    #: ``STEPFUN_TTS_ENDPOINT`` in ``.env`` overrides this default
    #: (``os.getenv(..., cls.stepfun_tts_endpoint)``), so a deployment that
    #: still needs the direct base can set it there without a code change.
    stepfun_tts_endpoint: str = (
        "https://api.stepfun.com/step_plan/v1/audio/speech"
    )
    stepfun_tts_model: str = "stepaudio-2.5-tts"
    stepfun_tts_voice: str = "cixingnansheng"
    fish_audio_api_key: str | None = None
    fish_audio_tts_endpoint: str = "https://api.fish.audio/v1/audio/speech"
    fish_audio_tts_model: str = "default"
    fish_audio_tts_voice: str = "default"
    bgm_provider: str = "stepfun_music"
    bgm_access_key_id: str | None = None
    bgm_secret_access_key: str | None = None
    bgm_api_key: str | None = None
    bgm_endpoint: str | None = "https://api.stepfun.com"
    bgm_submit_action: str = "GenBGMForTime"
    bgm_api_version: str = "2024-08-12"
    bgm_generation_version: str = "v5.0"
    bgm_model: str | None = "stepaudio-3-music-preview"
    bgm_long_model: str | None = None
    bgm_callback_mode: str = "auto"
    bgm_callback_base_url: str | None = None
    bgm_query_endpoint: str | None = None
    bgm_timeout_seconds: int = 60
    bgm_download_max_bytes: int = 100 * 1024 * 1024
    bgm_response_format: str = "mp3"
    #: StepAudio 3 Gen unified audio generation
    #: (``POST https://api.stepfun.com/v1/audio/generate``, model
    #: ``stepaudio-3-gen-preview``): one call composes multi-role dialogue
    #: (``roles`` + speaker-tagged ``scripts``), SFX / ambience / BGM
    #: (``[...]``-wrapped script entries) and a global ``instruction`` into a
    #: single finished audio bed. Same StepFun open-platform key as
    #: ``stepfun_api_key`` / ``bgm_api_key``. Synchronous endpoint: the timeout
    #: covers the whole generation, so it is far larger than the music
    #: submit/query timeout.
    step_audio_gen_endpoint: str = "https://api.stepfun.com"
    step_audio_gen_path: str = "/v1/audio/generate"
    step_audio_gen_model: str = "stepaudio-3-gen-preview"
    step_audio_gen_timeout_seconds: int = 300
    step_audio_gen_download_max_bytes: int = 100 * 1024 * 1024
    step_audio_gen_response_format: str = "mp3"
    composition_api_key: str | None = None
    composition_endpoint: str | None = None
    composition_provider: str = "ffmpeg"
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    final_composition_subtitle_font_path: str | None = None
    final_composition_render_mode: str = "simple_sequence"
    final_composition_bgm_gain_db_with_source: float = -18.0
    final_composition_bgm_gain_db_without_source: float = -10.0
    final_composition_bgm_fade_out_seconds: float = 0.5
    ffmpeg_capability_timeout_seconds: int = 10
    ffmpeg_video_codec: str | None = None
    ffmpeg_allowed_video_encoders: str = "libx264,libopenh264"
    keep_intermediate_files: bool = False
    keep_failed_intermediate_files: bool = True
    workflow_max_parallel_nodes: int = 3
    workflow_parallel_scheduler_enabled: bool = True
    provider_max_attempts_image: int = 2
    provider_max_attempts_video: int = 2
    provider_max_attempts_audio: int = 2
    provider_transient_retry_attempts: int = 3
    provider_transient_retry_base_delay_seconds: float = 1.0
    provider_transient_retry_max_delay_seconds: float = 12.0
    # The video provider (volcengine ARK / Seedance) enforces a hard
    # requests-per-minute cap.  When set, a rate-limited retry waits one full
    # window instead of the generic 0.5s->2s curve, which against a 10 RPM cap
    # was guaranteed to 429 again and burn the retry budget for nothing.
    provider_requests_per_minute: int = 10
    scene3d_render_timeout_seconds: int = 1800
    scene3d_max_concurrent_renders: int = 1
    scene3d_render_keyframes_only: bool = True
    # Timeout budget derived from the frame count instead of a flat guess:
    #   timeout = startup + per_frame * frames_rendered
    # The flat ``scene3d_render_timeout_seconds`` above stays as the ceiling, so
    # an operator who wants more headroom raises that rather than the slope.
    scene3d_render_startup_seconds: int = 90
    scene3d_render_seconds_per_frame: float = 6.0
    # The MP4 is the optional half of a previs.  The camera trajectory and the
    # keyframe schedule are always published as structured content, because
    # that is what a downstream video node binds; the encoded video is for
    # reviewers who want to press play.  Set false to skip the encoder.
    scene3d_emit_video: bool = True
    # Speech forced alignment (C mode: bed audio -> per-line timings).
    # "estimated" is the deterministic fallback; "whisperx" opts into the
    # real engine when whisperX is installed (the report says which ran).
    speech_alignment_engine: str = "estimated"
    whisperx_model: str = "large-v3"
    # Blender MCP (white-model design mode): the server command (overridable
    # via BLENDER_MCP_COMMAND) and the per-call timeout. The client enforces a
    # tool whitelist, so the blast radius of a compromised server is the
    # whitelisted geometry vocabulary, not arbitrary Python.
    blender_mcp_command: str = "blender-mcp"
    blender_mcp_timeout_seconds: int = 30
    provider_failure_cooldown_threshold: int = 3
    provider_cooldown_seconds: int = 300
    v2_stale_running_timeout_seconds: int = 900
    v2_require_authoring_if_match: bool = False
    v2_max_parallel_image_jobs: int = 4
    v2_max_parallel_video_jobs: int = 1
    v2_max_parallel_audio_jobs: int = 1
    v2_max_parallel_generation_jobs: int = 5
    v2_provider_task_poll_interval_seconds: int = 8
    v2_provider_task_max_concurrent_polls: int = 2
    v2_provider_task_timeout_seconds: int = 3600
    v2_provider_download_max_attempts: int = 3
    v2_provider_rate_limit_cooldown_seconds: int = 120
    v2_provider_rate_limit_reduced_image_jobs: int = 2
    v2_provider_rate_limit_reduced_video_jobs: int = 1
    v2_provider_reference_max_data_url_bytes: int = 4 * 1024 * 1024
    v2_provider_reference_total_data_url_bytes: int = 8 * 1024 * 1024
    #: Where the app's own ``/media/...`` paths are reachable from the internet.
    #: See ``v2_provider_reference_input_delivery.py`` -- the library records
    #: public URLs as *paths*, so every one of them is refused by the public-URL
    #: gate until this names the host that serves them.
    provider_reference_public_base_url: str | None = None
    v2_recommended_catalog_root: Path = Path("assets/catalogs/recommended")
    upload_image_max_bytes: int = 20 * 1024 * 1024
    upload_audio_max_bytes: int = 100 * 1024 * 1024
    upload_video_max_bytes: int = 500 * 1024 * 1024
    media_data_dir: Path = Path("data")

    @property
    def image_generation_credential(self) -> str | None:
        """The API key that authenticates the *configured* image endpoint.

        A credential is per-vendor, not per-capability, and this deployment
        reaches two different image vendors through the one
        ``IMAGE_GENERATION_ENDPOINT`` setting:

        * ``api.stepfun.com`` -- the step_plan gateway, authenticated by
          ``IMAGE_GENERATION_API_KEY``.
        * ``api.agnes-ai.cn`` -- authenticated by ``VIDEO_GENERATION_API_KEY``,
          which is already the Agnes credential for the video endpoint.  Probing
          this is what makes the Agnes fallback possible at all: the StepFun key
          gets **401** from ``api.agnes-ai.cn`` while the video key gets **200**
          and generates (``e2e_output/rose/probe_agnes_image.py``).

        Resolving it here rather than at the call site means the preflight
        checks in ``v2_provider_executor`` and the connection status written by
        ``provider_model_bootstrap`` read the same key the request actually
        sends -- otherwise "credentials missing" is reported for a request that
        authenticates fine, or a request is sent with a key that 401s.

        Returns the configured image key whenever the endpoint is not
        recognized, so an unlisted vendor keeps working exactly as before.
        """

        endpoint = (self.image_generation_endpoint or "").casefold()
        if "agnes-ai.cn" in endpoint:
            # Agnes shares one key across image and video, and it is not the
            # StepFun one.  Fall back to the image key if the video key is
            # absent, so a partially-configured deployment still has something
            # to send rather than an empty header.
            return (self.video_generation_api_key or "").strip() or self.image_generation_api_key
        return self.image_generation_api_key

    @property
    def image_generation_provider_label(self) -> str:
        """``"agnes"`` / ``"stepfun"`` / ``"volcengine"`` for the configured endpoint.

        Used for operator-facing messages and for the provider label on a
        failure, so the name shown is the gateway the request actually reached.
        """

        endpoint = (self.image_generation_endpoint or "").casefold()
        for needle, label in (
            ("agnes-ai.cn", "agnes"),
            ("stepfun", "stepfun"),
            ("volces.com", "volcengine"),
            ("volcengine", "volcengine"),
        ):
            if needle in endpoint:
                return label
        return "unknown"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_name=os.getenv("APP_NAME", cls.app_name),
            app_version=os.getenv("APP_VERSION", cls.app_version),
            v2_production_acceptance_enabled=_read_bool(
                "V2_PRODUCTION_ACCEPTANCE_ENABLED",
                cls.v2_production_acceptance_enabled,
            ),
            v2_prompt_materializer_strict=_read_bool(
                "V2_PROMPT_MATERIALIZER_STRICT",
                cls.v2_prompt_materializer_strict,
            ),
            v2_provider_allow_fallback=_read_bool(
                "V2_PROVIDER_ALLOW_FALLBACK",
                cls.v2_provider_allow_fallback,
            ),
            agent_runtime_mode=os.getenv("AGENT_RUNTIME_MODE", cls.agent_runtime_mode),
            agent_runtime_base_url=os.getenv("AGENT_RUNTIME_BASE_URL", cls.agent_runtime_base_url),
            agent_runtime_internal_token=os.getenv("AGENT_RUNTIME_INTERNAL_TOKEN") or None,
            agent_runtime_protocol_version=os.getenv(
                "AGENT_RUNTIME_PROTOCOL_VERSION",
                cls.agent_runtime_protocol_version,
            ),
            agent_runtime_connect_timeout_seconds=_read_float(
                "AGENT_RUNTIME_CONNECT_TIMEOUT_SECONDS",
                cls.agent_runtime_connect_timeout_seconds,
            ),
            agent_runtime_read_timeout_seconds=_read_float(
                "AGENT_RUNTIME_READ_TIMEOUT_SECONDS",
                cls.agent_runtime_read_timeout_seconds,
            ),
            agent_runtime_run_timeout_seconds=_read_float(
                "AGENT_RUNTIME_RUN_TIMEOUT_SECONDS",
                cls.agent_runtime_run_timeout_seconds,
            ),
            agent_runtime_max_event_bytes=_read_int(
                "AGENT_RUNTIME_MAX_EVENT_BYTES",
                cls.agent_runtime_max_event_bytes,
            ),
            agent_runtime_max_stream_bytes=_read_int(
                "AGENT_RUNTIME_MAX_STREAM_BYTES",
                cls.agent_runtime_max_stream_bytes,
            ),
            llm_provider=os.getenv("LLM_PROVIDER", cls.llm_provider),
            llm_api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or None,
            llm_base_url=os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None,
            siliconflow_api_key=os.getenv("SILICONFLOW_API_KEY") or None,
            siliconflow_base_url=os.getenv(
                "SILICONFLOW_BASE_URL",
                cls.siliconflow_base_url,
            ),
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY") or None,
            openrouter_text_base_url=os.getenv(
                "OPENROUTER_TEXT_BASE_URL",
                cls.openrouter_text_base_url,
            ),
            openrouter_image_base_url=os.getenv(
                "OPENROUTER_IMAGE_BASE_URL",
                cls.openrouter_image_base_url,
            ),
            minimax_api_key=os.getenv("MINIMAX_API_KEY") or None,
            minimax_base_url=os.getenv("MINIMAX_BASE_URL") or None,
            llm_transient_retry_delay_seconds=_read_float(
                "LLM_TRANSIENT_RETRY_DELAY_SECONDS",
                cls.llm_transient_retry_delay_seconds,
            ),
            llm_front_desk_model=os.getenv(
                "LLM_FRONT_DESK_MODEL",
                cls.llm_front_desk_model,
            ),
            llm_team_model=os.getenv("LLM_TEAM_MODEL", cls.llm_team_model),
            llm_requirements_model=os.getenv(
                "LLM_REQUIREMENTS_MODEL",
                cls.llm_requirements_model,
            ),
            llm_product_design_model=os.getenv(
                "LLM_PRODUCT_DESIGN_MODEL",
                cls.llm_product_design_model,
            ),
            llm_creative_model=os.getenv("LLM_CREATIVE_MODEL", cls.llm_creative_model),
            llm_script_model=os.getenv("LLM_SCRIPT_MODEL", cls.llm_script_model),
            llm_character_model=os.getenv("LLM_CHARACTER_MODEL", cls.llm_character_model),
            llm_scene_model=os.getenv("LLM_SCENE_MODEL", cls.llm_scene_model),
            llm_storyboard_model=os.getenv("LLM_STORYBOARD_MODEL", cls.llm_storyboard_model),
            llm_sound_effects_model=(
                os.getenv("LLM_SOUND_EFFECTS_MODEL")
                or os.getenv("LLM_SOUND_MODEL")
                or cls.llm_sound_effects_model
            ),
            llm_voiceover_model=os.getenv("LLM_VOICEOVER_MODEL", cls.llm_voiceover_model),
            llm_bgm_model=os.getenv("LLM_BGM_MODEL", cls.llm_bgm_model),
            llm_final_video_model=os.getenv(
                "LLM_FINAL_VIDEO_MODEL",
                cls.llm_final_video_model,
            ),
            media_mode=os.getenv("MEDIA_MODE", cls.media_mode),
            skip_audio_agents=_read_bool("SKIP_AUDIO_AGENTS", cls.skip_audio_agents),
            local_settings_allowed_origins=_read_csv(
                "LOCAL_SETTINGS_ALLOWED_ORIGINS",
                cls.local_settings_allowed_origins,
            ),
            image_generation_api_key=os.getenv("IMAGE_GENERATION_API_KEY") or None,
            image_generation_endpoint=os.getenv("IMAGE_GENERATION_ENDPOINT") or None,
            image_generation_model=os.getenv(
                "IMAGE_GENERATION_MODEL",
                cls.image_generation_model,
            ),
            image_generation_size=os.getenv(
                "IMAGE_GENERATION_SIZE",
                cls.image_generation_size,
            ),
            video_generation_api_key=os.getenv("VIDEO_GENERATION_API_KEY") or None,
            video_generation_endpoint=os.getenv("VIDEO_GENERATION_ENDPOINT") or None,
            video_generation_model=os.getenv(
                "VIDEO_GENERATION_MODEL",
                cls.video_generation_model,
            ),
            video_generation_resolution=os.getenv(
                "VIDEO_GENERATION_RESOLUTION",
                cls.video_generation_resolution,
            ),
            video_generation_generate_audio=_read_bool(
                "VIDEO_GENERATION_GENERATE_AUDIO",
                cls.video_generation_generate_audio,
            ),
            sound_effects_api_key=os.getenv("SOUND_EFFECTS_API_KEY") or None,
            sound_effects_endpoint=os.getenv("SOUND_EFFECTS_ENDPOINT") or None,
            sound_effects_model=os.getenv("SOUND_EFFECTS_MODEL", cls.sound_effects_model),
            tts_api_key=os.getenv("TTS_API_KEY") or None,
            tts_endpoint=os.getenv("TTS_ENDPOINT") or None,
            tts_model=os.getenv("TTS_MODEL", cls.tts_model),
            stepfun_api_key=os.getenv("STEPFUN_API_KEY") or None,
            stepfun_tts_endpoint=os.getenv("STEPFUN_TTS_ENDPOINT", cls.stepfun_tts_endpoint),
            stepfun_tts_model=os.getenv("STEPFUN_TTS_MODEL", cls.stepfun_tts_model),
            stepfun_tts_voice=os.getenv("STEPFUN_TTS_VOICE", cls.stepfun_tts_voice),
            fish_audio_api_key=os.getenv("FISH_AUDIO_API_KEY") or None,
            fish_audio_tts_endpoint=os.getenv(
                "FISH_AUDIO_TTS_ENDPOINT", cls.fish_audio_tts_endpoint
            ),
            fish_audio_tts_model=os.getenv("FISH_AUDIO_TTS_MODEL", cls.fish_audio_tts_model),
            fish_audio_tts_voice=os.getenv("FISH_AUDIO_TTS_VOICE", cls.fish_audio_tts_voice),
            bgm_provider=os.getenv("BGM_PROVIDER", cls.bgm_provider),
            bgm_access_key_id=os.getenv("BGM_ACCESS_KEY_ID") or None,
            bgm_secret_access_key=os.getenv("BGM_SECRET_ACCESS_KEY") or None,
            bgm_api_key=os.getenv("BGM_API_KEY") or None,
            bgm_endpoint=os.getenv("BGM_ENDPOINT") or cls.bgm_endpoint,
            bgm_submit_action=os.getenv("BGM_SUBMIT_ACTION", cls.bgm_submit_action),
            bgm_api_version=os.getenv("BGM_API_VERSION", cls.bgm_api_version),
            bgm_generation_version=os.getenv("BGM_GENERATION_VERSION", cls.bgm_generation_version),
            bgm_model=os.getenv("BGM_MODEL") or cls.bgm_model,
            bgm_long_model=os.getenv("BGM_LONG_MODEL") or cls.bgm_long_model,
            bgm_callback_mode=os.getenv("BGM_CALLBACK_MODE", cls.bgm_callback_mode),
            bgm_callback_base_url=os.getenv("BGM_CALLBACK_BASE_URL") or None,
            bgm_query_endpoint=os.getenv("BGM_QUERY_ENDPOINT") or None,
            bgm_timeout_seconds=_read_int("BGM_TIMEOUT_SECONDS", cls.bgm_timeout_seconds),
            bgm_download_max_bytes=_read_int("BGM_DOWNLOAD_MAX_BYTES", cls.bgm_download_max_bytes),
            bgm_response_format=os.getenv("BGM_RESPONSE_FORMAT", cls.bgm_response_format),
            step_audio_gen_endpoint=os.getenv(
                "STEP_AUDIO_GEN_ENDPOINT", cls.step_audio_gen_endpoint
            ),
            step_audio_gen_path=os.getenv(
                "STEP_AUDIO_GEN_PATH", cls.step_audio_gen_path
            ),
            step_audio_gen_model=os.getenv(
                "STEP_AUDIO_GEN_MODEL", cls.step_audio_gen_model
            ),
            step_audio_gen_timeout_seconds=_read_int(
                "STEP_AUDIO_GEN_TIMEOUT_SECONDS", cls.step_audio_gen_timeout_seconds
            ),
            step_audio_gen_download_max_bytes=_read_int(
                "STEP_AUDIO_GEN_DOWNLOAD_MAX_BYTES", cls.step_audio_gen_download_max_bytes
            ),
            step_audio_gen_response_format=os.getenv(
                "STEP_AUDIO_GEN_RESPONSE_FORMAT", cls.step_audio_gen_response_format
            ),
            composition_api_key=os.getenv("COMPOSITION_API_KEY") or None,
            composition_endpoint=os.getenv("COMPOSITION_ENDPOINT") or None,
            composition_provider=os.getenv("COMPOSITION_PROVIDER", cls.composition_provider),
            ffmpeg_path=os.getenv("FFMPEG_PATH", cls.ffmpeg_path),
            ffprobe_path=os.getenv("FFPROBE_PATH", cls.ffprobe_path),
            final_composition_subtitle_font_path=(
                os.getenv("FINAL_COMPOSITION_SUBTITLE_FONT_PATH") or None
            ),
            final_composition_render_mode=os.getenv(
                "FINAL_COMPOSITION_RENDER_MODE",
                cls.final_composition_render_mode,
            ),
            final_composition_bgm_gain_db_with_source=_read_float(
                "FINAL_COMPOSITION_BGM_GAIN_DB_WITH_SOURCE",
                cls.final_composition_bgm_gain_db_with_source,
            ),
            final_composition_bgm_gain_db_without_source=_read_float(
                "FINAL_COMPOSITION_BGM_GAIN_DB_WITHOUT_SOURCE",
                cls.final_composition_bgm_gain_db_without_source,
            ),
            final_composition_bgm_fade_out_seconds=_read_float(
                "FINAL_COMPOSITION_BGM_FADE_OUT_SECONDS",
                cls.final_composition_bgm_fade_out_seconds,
            ),
            ffmpeg_capability_timeout_seconds=_read_int(
                "FFMPEG_CAPABILITY_TIMEOUT_SECONDS",
                cls.ffmpeg_capability_timeout_seconds,
            ),
            ffmpeg_video_codec=os.getenv("FFMPEG_VIDEO_CODEC") or None,
            ffmpeg_allowed_video_encoders=os.getenv(
                "FFMPEG_ALLOWED_VIDEO_ENCODERS",
                cls.ffmpeg_allowed_video_encoders,
            ),
            keep_intermediate_files=_read_bool(
                "KEEP_INTERMEDIATE_FILES", cls.keep_intermediate_files
            ),
            keep_failed_intermediate_files=_read_bool(
                "KEEP_FAILED_INTERMEDIATE_FILES", cls.keep_failed_intermediate_files
            ),
            workflow_max_parallel_nodes=_read_int(
                "WORKFLOW_MAX_PARALLEL_NODES", cls.workflow_max_parallel_nodes
            ),
            workflow_parallel_scheduler_enabled=_read_bool(
                "WORKFLOW_PARALLEL_SCHEDULER_ENABLED",
                cls.workflow_parallel_scheduler_enabled,
            ),
            provider_max_attempts_image=int(
                os.getenv(
                    "PROVIDER_MAX_ATTEMPTS_IMAGE",
                    str(cls.provider_max_attempts_image),
                )
            ),
            provider_max_attempts_video=int(
                os.getenv(
                    "PROVIDER_MAX_ATTEMPTS_VIDEO",
                    str(cls.provider_max_attempts_video),
                )
            ),
            provider_max_attempts_audio=int(
                os.getenv(
                    "PROVIDER_MAX_ATTEMPTS_AUDIO",
                    str(cls.provider_max_attempts_audio),
                )
            ),
            provider_transient_retry_attempts=max(
                1,
                _read_int(
                    "PROVIDER_TRANSIENT_RETRY_ATTEMPTS",
                    cls.provider_transient_retry_attempts,
                ),
            ),
            provider_transient_retry_base_delay_seconds=max(
                0.0,
                _read_float(
                    "PROVIDER_TRANSIENT_RETRY_BASE_DELAY_SECONDS",
                    cls.provider_transient_retry_base_delay_seconds,
                ),
            ),
            provider_transient_retry_max_delay_seconds=max(
                0.0,
                _read_float(
                    "PROVIDER_TRANSIENT_RETRY_MAX_DELAY_SECONDS",
                    cls.provider_transient_retry_max_delay_seconds,
                ),
            ),
            provider_requests_per_minute=max(
                0,
                _read_int(
                    "PROVIDER_REQUESTS_PER_MINUTE",
                    cls.provider_requests_per_minute,
                ),
            ),
            scene3d_render_timeout_seconds=min(
                3600,
                max(
                    30,
                    _read_int(
                        "SCENE3D_RENDER_TIMEOUT_SECONDS",
                        cls.scene3d_render_timeout_seconds,
                    ),
                ),
            ),
            scene3d_max_concurrent_renders=max(
                1,
                _read_int(
                    "SCENE3D_MAX_CONCURRENT_RENDERS",
                    cls.scene3d_max_concurrent_renders,
                ),
            ),
            scene3d_render_keyframes_only=_read_bool(
                "SCENE3D_RENDER_KEYFRAMES_ONLY",
                cls.scene3d_render_keyframes_only,
            ),
            scene3d_render_startup_seconds=max(
                0,
                _read_int(
                    "SCENE3D_RENDER_STARTUP_SECONDS",
                    cls.scene3d_render_startup_seconds,
                ),
            ),
            scene3d_render_seconds_per_frame=max(
                0.0,
                _read_float(
                    "SCENE3D_RENDER_SECONDS_PER_FRAME",
                    cls.scene3d_render_seconds_per_frame,
                ),
            ),
            scene3d_emit_video=_read_bool(
                "SCENE3D_EMIT_VIDEO",
                cls.scene3d_emit_video,
            ),
            speech_alignment_engine=os.getenv(
                "SPEECH_ALIGNMENT_ENGINE",
                cls.speech_alignment_engine,
            ),
            whisperx_model=os.getenv("WHISPERX_MODEL", cls.whisperx_model),
            blender_mcp_command=os.getenv(
                "BLENDER_MCP_COMMAND",
                cls.blender_mcp_command,
            ),
            blender_mcp_timeout_seconds=_read_int(
                "BLENDER_MCP_TIMEOUT_SECONDS",
                cls.blender_mcp_timeout_seconds,
            ),
            provider_failure_cooldown_threshold=int(
                os.getenv(
                    "PROVIDER_FAILURE_COOLDOWN_THRESHOLD",
                    str(cls.provider_failure_cooldown_threshold),
                )
            ),
            provider_cooldown_seconds=int(
                os.getenv("PROVIDER_COOLDOWN_SECONDS", str(cls.provider_cooldown_seconds))
            ),
            v2_stale_running_timeout_seconds=_read_int(
                "V2_STALE_RUNNING_TIMEOUT_SECONDS",
                cls.v2_stale_running_timeout_seconds,
            ),
            v2_max_parallel_image_jobs=_read_int(
                "V2_MAX_PARALLEL_IMAGE_JOBS",
                cls.v2_max_parallel_image_jobs,
            ),
            v2_max_parallel_video_jobs=_read_int(
                "V2_MAX_PARALLEL_VIDEO_JOBS",
                cls.v2_max_parallel_video_jobs,
            ),
            v2_max_parallel_audio_jobs=_read_int(
                "V2_MAX_PARALLEL_AUDIO_JOBS",
                cls.v2_max_parallel_audio_jobs,
            ),
            v2_max_parallel_generation_jobs=_read_int(
                "V2_MAX_PARALLEL_GENERATION_JOBS",
                cls.v2_max_parallel_generation_jobs,
            ),
            v2_provider_task_poll_interval_seconds=_read_int(
                "V2_PROVIDER_TASK_POLL_INTERVAL_SECONDS",
                cls.v2_provider_task_poll_interval_seconds,
            ),
            v2_require_authoring_if_match=_read_bool(
                "V2_REQUIRE_AUTHORING_IF_MATCH",
                cls.v2_require_authoring_if_match,
            ),
            v2_provider_task_max_concurrent_polls=_read_int(
                "V2_PROVIDER_TASK_MAX_CONCURRENT_POLLS",
                cls.v2_provider_task_max_concurrent_polls,
            ),
            v2_provider_task_timeout_seconds=_read_int(
                "V2_PROVIDER_TASK_TIMEOUT_SECONDS",
                cls.v2_provider_task_timeout_seconds,
            ),
            v2_provider_download_max_attempts=max(
                1,
                _read_int(
                    "V2_PROVIDER_DOWNLOAD_MAX_ATTEMPTS",
                    cls.v2_provider_download_max_attempts,
                ),
            ),
            v2_provider_rate_limit_cooldown_seconds=_read_int(
                "V2_PROVIDER_RATE_LIMIT_COOLDOWN_SECONDS",
                cls.v2_provider_rate_limit_cooldown_seconds,
            ),
            v2_provider_rate_limit_reduced_image_jobs=_read_int(
                "V2_PROVIDER_RATE_LIMIT_REDUCED_IMAGE_JOBS",
                cls.v2_provider_rate_limit_reduced_image_jobs,
            ),
            v2_provider_rate_limit_reduced_video_jobs=_read_int(
                "V2_PROVIDER_RATE_LIMIT_REDUCED_VIDEO_JOBS",
                cls.v2_provider_rate_limit_reduced_video_jobs,
            ),
            v2_provider_reference_max_data_url_bytes=_read_int(
                "V2_PROVIDER_REFERENCE_MAX_DATA_URL_BYTES",
                cls.v2_provider_reference_max_data_url_bytes,
            ),
            v2_provider_reference_total_data_url_bytes=_read_int(
                "V2_PROVIDER_REFERENCE_TOTAL_DATA_URL_BYTES",
                cls.v2_provider_reference_total_data_url_bytes,
            ),
            provider_reference_public_base_url=(
                os.getenv("PROVIDER_REFERENCE_PUBLIC_BASE_URL") or None
            ),
            v2_recommended_catalog_root=_read_recommended_catalog_root(),
            upload_image_max_bytes=int(
                os.getenv("UPLOAD_IMAGE_MAX_BYTES", str(cls.upload_image_max_bytes))
            ),
            upload_audio_max_bytes=int(
                os.getenv("UPLOAD_AUDIO_MAX_BYTES", str(cls.upload_audio_max_bytes))
            ),
            upload_video_max_bytes=int(
                os.getenv("UPLOAD_VIDEO_MAX_BYTES", str(cls.upload_video_max_bytes))
            ),
            media_data_dir=_read_path("MEDIA_DATA_DIR", cls.media_data_dir),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
