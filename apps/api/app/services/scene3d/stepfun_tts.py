"""StepFun (阶跃星辰) TTS engine implementation.

Implements the TTSEngine protocol using StepFun's OpenAI-compatible
TTS API (POST /v1/audio/speech).

API docs: https://platform.stepfun.com/docs/zh/api-reference/audio/create-audio

Models:
- step-tts-mini: lightweight
- step-tts-2: balanced, 2.8元/万字符
- stepaudio-2.5-tts: contextual, 5.8元/万字符 (default)

Voices (partial list):
- cixingnansheng: 磁性男声
- (see StepFun console for full voice list)

Usage:
    engine = StepFunTTSEngine(
        api_key="sk-...",
        model="stepaudio-2.5-tts",
        voice="cixingnansheng",
    )
    audio_path = engine.synthesize("你好世界", "char1", "/tmp/out.mp3")
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.services.scene3d.speech_orchestration import SimpleTTSEngine


class StepFunTTSEngine(SimpleTTSEngine):
    """StepFun TTS engine.

    Extends SimpleTTSEngine for duration estimation, and overrides
    synthesize() to call the StepFun TTS API.

    If api_key is not provided, falls back to SimpleTTSEngine behavior
    (returns output_path without generating audio).
    """

    #: ``工具模型.txt:254`` -- "非流式语音合成" -> ``POST /v1/audio/speech``.
    #: Served through the ``/step_plan/`` gateway: measured 2026-09-21, the
    #: direct ``/v1/`` base answers 402 ``quota_exceeded`` while ``/step_plan/v1/``
    #: answers 200 with a real MP3 (``e2e_output/stepplan_probe/tts.mp3``).
    #: A previous comment here claimed ``/step_plan/`` answers 401 for audio;
    #: that was measured while the key was revoked, so the credential was
    #: rejected before routing.  ``STEPFUN_TTS_ENDPOINT`` still overrides this.
    DEFAULT_ENDPOINT = "https://api.stepfun.com/step_plan/v1/audio/speech"
    DEFAULT_MODEL = "stepaudio-2.5-tts"
    DEFAULT_VOICE = "cixingnansheng"
    DEFAULT_TIMEOUT = 60

    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT,
        chars_per_second: float = 8.0,
    ):
        """Initialize StepFun TTS engine.

        Args:
            api_key: StepFun API key. If None, reads from STEPFUN_API_KEY env var.
            endpoint: API endpoint URL. Defaults to StepFun production endpoint.
            model: TTS model name.
            voice: Voice ID.
            timeout_seconds: HTTP request timeout.
            chars_per_second: Fallback chars/sec for duration estimation.
        """
        super().__init__(chars_per_second=chars_per_second)
        self.api_key = api_key or os.getenv("STEPFUN_API_KEY")
        self.endpoint = endpoint or os.getenv("STEPFUN_TTS_ENDPOINT") or self.DEFAULT_ENDPOINT
        self.model = model or os.getenv("STEPFUN_TTS_MODEL") or self.DEFAULT_MODEL
        self.voice = voice or os.getenv("STEPFUN_TTS_VOICE") or self.DEFAULT_VOICE
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
        """Synthesize speech via StepFun TTS API.

        Args:
            text: Text to synthesize.
            character_id: Character ID (used for voice selection mapping;
                          currently uses self.voice unless voice_id overrides).
            output_path: Where to save the audio file.
            emotion: Optional emotion/tone hint. StepAudio 2.5 accepts a
                     natural-language ``instruction``; it is attached to the
                     request when present.
            voice_id: Optional explicit voice ID override.

        Returns:
            Path to the generated audio file.

        Raises:
            RuntimeError: If API request fails.
        """
        if not self.is_configured:
            # Fallback: return output path without generating audio
            return output_path

        voice = voice_id or self.voice
        payload: dict[str, Any] = {
            "model": self.model,
            "input": text,
            "voice": voice,
            "response_format": "mp3",
        }
        if emotion:
            payload["instruction"] = emotion

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(self.endpoint, json=payload, headers=headers)
                response.raise_for_status()

                # Ensure output directory exists
                os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

                with open(output_path, "wb") as f:
                    f.write(response.content)

            return output_path

        except httpx.HTTPStatusError as exc:
            error_detail = exc.response.text[:500] if exc.response.text else str(exc)
            raise RuntimeError(
                f"StepFun TTS API error {exc.response.status_code}: {error_detail}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"StepFun TTS request failed: {exc}") from exc

    def synthesize_batch(
        self,
        items: list[dict[str, Any]],
        output_dir: str,
    ) -> list[str]:
        """Synthesize multiple speech segments sequentially.

        Args:
            items: List of dicts with keys: text, character_id, emotion (optional),
                   voice_id (optional), segment_id (optional, used for filename).
            output_dir: Directory to save audio files.

        Returns:
            List of output file paths.
        """
        os.makedirs(output_dir, exist_ok=True)
        paths = []
        for i, item in enumerate(items):
            segment_id = item.get("segment_id", f"segment_{i:03d}")
            output_path = os.path.join(output_dir, f"{segment_id}.mp3")
            path = self.synthesize(
                text=item["text"],
                character_id=item.get("character_id", "unknown"),
                output_path=output_path,
                emotion=item.get("emotion"),
                voice_id=item.get("voice_id"),
            )
            paths.append(path)
        return paths


def create_stepfun_tts_from_settings(settings: Any) -> StepFunTTSEngine:
    """Create a StepFunTTSEngine from app settings.

    Args:
        settings: AppSettings instance with stepfun_* fields.

    Returns:
        Configured StepFunTTSEngine instance.
    """
    return StepFunTTSEngine(
        api_key=getattr(settings, "stepfun_api_key", None),
        endpoint=getattr(settings, "stepfun_tts_endpoint", None),
        model=getattr(settings, "stepfun_tts_model", None),
        voice=getattr(settings, "stepfun_tts_voice", None),
    )
