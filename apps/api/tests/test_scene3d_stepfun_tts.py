"""Unit tests for StepFun TTS engine."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from app.services.scene3d.stepfun_tts import StepFunTTSEngine, create_stepfun_tts_from_settings


@pytest.fixture(autouse=True)
def _isolate_stepfun_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear StepFun env vars for every test in this module.

    ``app.core.config`` calls ``load_dotenv()`` at import time, so once any
    test in the session imports it, the developer's real ``.env`` values sit in
    ``os.environ`` for the rest of the run. The engine reads its config from
    that environment, so without this isolation the "unconfigured" cases pass
    alone and fail in a full-suite run.
    """
    for name in ("STEPFUN_API_KEY", "STEPFUN_TTS_ENDPOINT", "STEPFUN_TTS_MODEL", "STEPFUN_TTS_VOICE"):
        monkeypatch.delenv(name, raising=False)


class TestStepFunTTSEngineInit:
    def test_default_values(self) -> None:
        engine = StepFunTTSEngine()
        assert engine.endpoint == StepFunTTSEngine.DEFAULT_ENDPOINT
        assert engine.model == StepFunTTSEngine.DEFAULT_MODEL
        assert engine.voice == StepFunTTSEngine.DEFAULT_VOICE
        assert engine.timeout_seconds == StepFunTTSEngine.DEFAULT_TIMEOUT

    def test_custom_values(self) -> None:
        engine = StepFunTTSEngine(
            api_key="test-key",
            endpoint="https://custom.endpoint",
            model="step-tts-2",
            voice="custom-voice",
            timeout_seconds=30,
        )
        assert engine.api_key == "test-key"
        assert engine.endpoint == "https://custom.endpoint"
        assert engine.model == "step-tts-2"
        assert engine.voice == "custom-voice"
        assert engine.timeout_seconds == 30

    def test_is_configured_false_without_key(self) -> None:
        engine = StepFunTTSEngine()
        assert engine.is_configured is False

    def test_is_configured_true_with_key(self) -> None:
        engine = StepFunTTSEngine(api_key="sk-test")
        assert engine.is_configured is True

    def test_env_var_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STEPFUN_API_KEY", "sk-from-env")
        engine = StepFunTTSEngine()
        assert engine.api_key == "sk-from-env"
        assert engine.is_configured is True

    def test_env_var_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STEPFUN_TTS_MODEL", "stepaudio-2.5-tts")
        engine = StepFunTTSEngine()
        assert engine.model == "stepaudio-2.5-tts"

    def test_env_var_voice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STEPFUN_TTS_VOICE", "nv-zh-female-1")
        engine = StepFunTTSEngine()
        assert engine.voice == "nv-zh-female-1"

    def test_inherits_duration_estimation(self) -> None:
        engine = StepFunTTSEngine()
        duration = engine.estimate_duration("你好世界")
        assert duration > 0.5
        assert duration < 5.0


class TestStepFunTTSEngineSynthesize:
    def test_fallback_without_api_key(self, tmp_path: str) -> None:
        engine = StepFunTTSEngine()  # No API key
        output = os.path.join(tmp_path, "test.mp3")
        result = engine.synthesize("hello", "char1", output)
        assert result == output
        # File should NOT be created (fallback mode)
        assert not os.path.exists(output)

    @patch("app.services.scene3d.stepfun_tts.httpx.Client")
    def test_synthesize_success(self, mock_client_cls: MagicMock, tmp_path: str) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"fake-mp3-data"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        engine = StepFunTTSEngine(api_key="sk-test")
        output = os.path.join(tmp_path, "test.mp3")
        result = engine.synthesize("你好", "char1", output)

        assert result == output
        assert os.path.exists(output)
        with open(output, "rb") as f:
            assert f.read() == b"fake-mp3-data"

        # Verify API call
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == StepFunTTSEngine.DEFAULT_ENDPOINT
        assert call_args[1]["json"]["input"] == "你好"
        assert call_args[1]["json"]["model"] == StepFunTTSEngine.DEFAULT_MODEL
        assert call_args[1]["json"]["voice"] == "cixingnansheng"
        assert "Authorization" in call_args[1]["headers"]

    @patch("app.services.scene3d.stepfun_tts.httpx.Client")
    def test_synthesize_with_voice_override(
        self, mock_client_cls: MagicMock, tmp_path: str
    ) -> None:
        mock_response = MagicMock()
        mock_response.content = b"data"
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        engine = StepFunTTSEngine(api_key="sk-test")
        output = os.path.join(tmp_path, "test.mp3")
        engine.synthesize("hello", "char1", output, voice_id="custom-voice")

        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["voice"] == "custom-voice"

    @patch("app.services.scene3d.stepfun_tts.httpx.Client")
    def test_synthesize_api_error(self, mock_client_cls: MagicMock) -> None:
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=mock_response
        )
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        engine = StepFunTTSEngine(api_key="sk-test")
        with pytest.raises(RuntimeError, match="StepFun TTS API error"):
            engine.synthesize("hello", "char1", "/tmp/test.mp3")


class TestStepFunTTSEngineBatch:
    def test_synthesize_batch_fallback(self, tmp_path: str) -> None:
        engine = StepFunTTSEngine()  # No API key
        items = [
            {"text": "hello", "character_id": "c1", "segment_id": "s1"},
            {"text": "world", "character_id": "c2", "segment_id": "s2"},
        ]
        paths = engine.synthesize_batch(items, tmp_path)
        assert len(paths) == 2
        assert paths[0].endswith("s1.mp3")
        assert paths[1].endswith("s2.mp3")

    def test_synthesize_batch_auto_ids(self, tmp_path: str) -> None:
        engine = StepFunTTSEngine()
        items = [{"text": "a", "character_id": "c1"}, {"text": "b", "character_id": "c2"}]
        paths = engine.synthesize_batch(items, tmp_path)
        assert paths[0].endswith("segment_000.mp3")
        assert paths[1].endswith("segment_001.mp3")


class TestCreateFromSettings:
    def test_create_from_settings(self) -> None:
        settings = MagicMock()
        settings.stepfun_api_key = "sk-settings"
        settings.stepfun_tts_endpoint = "https://settings.endpoint"
        settings.stepfun_tts_model = "step-tts-2"
        settings.stepfun_tts_voice = "settings-voice"

        engine = create_stepfun_tts_from_settings(settings)
        assert engine.api_key == "sk-settings"
        assert engine.endpoint == "https://settings.endpoint"
        assert engine.model == "step-tts-2"
        assert engine.voice == "settings-voice"

    def test_create_from_settings_missing_fields(self) -> None:
        settings = MagicMock(spec=[])  # No attributes
        engine = create_stepfun_tts_from_settings(settings)
        assert engine.api_key is None
        assert engine.endpoint == StepFunTTSEngine.DEFAULT_ENDPOINT
        assert engine.model == StepFunTTSEngine.DEFAULT_MODEL
