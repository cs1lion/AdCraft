"""Fish Audio TTS engine implementation.

Implements the TTSEngine protocol using Fish Audio's TTS API.

API docs: https://docs.fish.audio
Base URL: https://api.fish.audio (override with FISH_AUDIO_TTS_ENDPOINT)

Endpoint (text-to-speech):
    POST /v1/audio/speech
        {"text": "...", "reference_id": "voice-slug", "format": "mp3"}
    Returns audio bytes (or a JSON wrapper with audio data, depending on
    the response shape the gateway returns).

Configuration comes from the following settings/env fields:
- FISH_AUDIO_API_KEY
- FISH_AUDIO_TTS_ENDPOINT (default https://api.fish.audio/v1/audio/speech)
- FISH_AUDIO_TTS_MODEL (default "default")
- FISH_AUDIO_TTS_VOICE (reference_id / voice slug, default "default")

Usage:
    engine = FishAudioTTSEngine(api_key="sk-fish-...")
    audio_path = engine.synthesize("你好世界", "char1", "/tmp/out.mp3")
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.services.scene3d.speech_orchestration import SimpleTTSEngine


class FishAudioTTSEngine(SimpleTTSEngine):
    """Fish Audio TTS engine.

    Extends SimpleTTSEngine for duration estimation, and overrides
    synthesize() to call the Fish Audio TTS API.

    If api_key is not provided, falls back to SimpleTTSEngine behavior
    (returns output_path without generating audio).
    """

    DEFAULT_ENDPOINT = "https://api.fish.audio/v1/audio/speech"
    DEFAULT_MODEL = "default"
    DEFAULT_VOICE = "default"
    DEFAULT_TIMEOUT = 60

    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        response_format: str = "mp3",
        timeout_seconds: int = DEFAULT_TIMEOUT,
        chars_per_second: float = 8.0,
    ):
        """Initialize Fish Audio TTS engine.

        Args:
            api_key: Fish Audio API key. If None, reads from FISH_AUDIO_API_KEY.
            endpoint: API endpoint URL. Defaults to Fish Audio production.
            model: TTS model name.
            voice: Voice reference_id / slug.
            response_format: Audio format (mp3, wav, pcm, ...).
            timeout_seconds: HTTP request timeout.
            chars_per_second: Fallback chars/sec for duration estimation.
        """
        super().__init__(chars_per_second=chars_per_second)
        self.api_key = api_key or os.getenv("FISH_AUDIO_API_KEY")
        self.endpoint = endpoint or os.getenv("FISH_AUDIO_TTS_ENDPOINT") or self.DEFAULT_ENDPOINT
        self.model = model or os.getenv("FISH_AUDIO_TTS_MODEL") or self.DEFAULT_MODEL
        self.voice = voice or os.getenv("FISH_AUDIO_TTS_VOICE") or self.DEFAULT_VOICE
        self.response_format = response_format
        self.timeout_seconds = timeout_seconds

    @property
    def is_configured(self) -> bool:
        """Whether the engine has an API key and can make real requests."""
        return bool(self.api_key)

    def synthesize(
        self,
        text: str,
        character_id: str,
        output_path: str,
        emotion: str | None = None,
        voice_id: str | None = None,
    ) -> str:
        """Synthesize speech via Fish Audio TTS API.

        Args:
            text: Text to synthesize.
            character_id: Character ID (used for voice selection mapping;
                          currently uses self.voice unless voice_id overrides).
            output_path: Where to save the audio file.
            emotion: Optional emotion/tone hint; appended to the text prompt
                    when Fish Audio does not expose a dedicated field.
            voice_id: Optional explicit voice reference_id override.

        Returns:
            Path to the generated audio file.

        Raises:
            RuntimeError: If API request fails.
        """
        if not self.is_configured:
            # Fallback: return output path without generating audio
            return output_path

        prompt_text = text
        if emotion:
            prompt_text = f"{text}（{emotion}）"

        payload: dict[str, Any] = {
            "text": prompt_text,
            "reference_id": voice_id or self.voice,
            "format": self.response_format,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(self.endpoint, json=payload, headers=headers)
                response.raise_for_status()

                # Fish Audio may return raw audio bytes or a JSON payload with
                # audio data (b64 or nested url). Handle both shapes.
                content_type = (response.headers.get("content-type") or "").lower()
                audio_bytes = response.content
                if "application/json" in content_type:
                    try:
                        parsed: Any = response.json()
                    except Exception:  # noqa: BLE001 - non-JSON body, use raw
                        parsed = None
                    if isinstance(parsed, dict):
                        audio_bytes = _extract_audio_bytes(parsed)

                import os as _os

                _os.makedirs(_os.path.dirname(_os.path.abspath(output_path)), exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(audio_bytes)

            return output_path

        except httpx.HTTPStatusError as exc:
            error_detail = exc.response.text[:500] if exc.response.text else str(exc)
            raise RuntimeError(
                f"Fish Audio TTS API error {exc.response.status_code}: {error_detail}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Fish Audio TTS request failed: {exc}") from exc


def _extract_audio_bytes(payload: dict[str, Any]) -> bytes:
    """Best-effort extraction of audio bytes from a JSON TTS response.

    Supports common shapes: {"audio_b64"}, {"data": "b64..."},
    {"audio": {"base64": ...}}, or {"url": "https://..."}.
    """
    import base64
    import json as _json

    for key in ("audio_b64", "b64", "audio", "data", "base64"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            stripped = value.strip()
            if stripped.startswith("data:"):
                stripped = stripped.split(",", 1)[1] if "," in stripped else ""
            if "http" not in stripped[:8]:
                try:
                    return base64.b64decode(stripped)
                except Exception:  # noqa: BLE001 - not base64, fall through
                    pass
    for nested in ("audio", "result"):
        inner = payload.get(nested)
        if isinstance(inner, dict):
            extracted = _extract_audio_bytes(inner)
            if extracted:
                return extracted
    url = payload.get("url")
    if isinstance(url, str) and url.startswith("http"):
        with httpx.Client(timeout=30) as client:
            audio_response = client.get(url)
            audio_response.raise_for_status()
            return audio_response.content
    return _json.dumps(payload).encode("utf-8")


def create_fish_audio_tts_from_settings(settings: Any) -> FishAudioTTSEngine:
    """Create a FishAudioTTSEngine from app settings.

    Args:
        settings: AppSettings instance with fish_audio_* fields.

    Returns:
        Configured FishAudioTTSEngine instance.
    """
    return FishAudioTTSEngine(
        api_key=getattr(settings, "fish_audio_api_key", None),
        endpoint=getattr(settings, "fish_audio_tts_endpoint", None),
        model=getattr(settings, "fish_audio_tts_model", None),
        voice=getattr(settings, "fish_audio_tts_voice", None),
    )
