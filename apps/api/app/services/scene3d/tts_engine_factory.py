"""TTS engine factory.

Selects a concrete TTSEngine implementation based on the configured
TTS provider so that callers (e.g. the scene3d speech orchestration
pipeline) get a working engine out of the box instead of the
placeholder SimpleTTSEngine.

The factory is provider-agnostic: each provider ships its own engine
module (``stepfun_tts``, ``fish_audio_tts``) plus a
``create_*_tts_from_settings`` constructor.  Add a new TTS provider by
adding an entry to ``_PROVIDER_FACTORIES`` here.
"""

from __future__ import annotations

from typing import Any, Callable

from app.services.scene3d.fish_audio_tts import create_fish_audio_tts_from_settings
from app.services.scene3d.speech_orchestration import TTSEngine, SimpleTTSEngine
from app.services.scene3d.stepfun_tts import create_stepfun_tts_from_settings


def _create_simple_tts_from_settings(settings: Any) -> SimpleTTSEngine:
    return SimpleTTSEngine()


_PROVIDER_FACTORIES: dict[str, Callable[[Any], TTSEngine]] = {
    "stepfun": create_stepfun_tts_from_settings,
    "fish_audio": create_fish_audio_tts_from_settings,
}


def create_tts_engine_from_settings(
    settings: Any,
    provider: str | None = None,
) -> TTSEngine:
    """Build a TTSEngine for the requested (or configured) TTS provider.

    Args:
        settings: AppSettings instance (or duck-typed equivalent).
        provider: TTS provider id (``stepfun`` / ``fish_audio`` /
            ``simple`` / None).  When None, the first provider that has
            an API key configured is chosen; otherwise the simple
            placeholder engine is returned.

    Returns:
        A configured TTSEngine.
    """
    if provider:
        normalized = provider.strip().lower()
        if normalized in _PROVIDER_FACTORIES:
            return _PROVIDER_FACTORIES[normalized](settings)
        if normalized in ("simple", "placeholder", "none"):
            return _create_simple_tts_from_settings(settings)
        raise ValueError(
            f"Unsupported TTS provider: {provider}. "
            f"Supported: {', '.join(sorted(_PROVIDER_FACTORIES))}, simple."
        )

    # No explicit provider: pick the first configured real engine, else simple.
    for provider_id, factory in _PROVIDER_FACTORIES.items():
        engine = factory(settings)
        if _engine_is_configured(engine):
            return engine
    return _create_simple_tts_from_settings(settings)


def _engine_is_configured(engine: TTSEngine) -> bool:
    attribute = getattr(engine, "is_configured", None)
    if callable(attribute):
        return bool(attribute())
    return bool(getattr(engine, "api_key", None))


def tts_provider_ids() -> tuple[str, ...]:
    return tuple(_PROVIDER_FACTORIES)
