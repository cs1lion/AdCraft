"""BGM provider selection and pre-flight diagnostics (ISSUE-13).

The 2026-09-19 E2E run left a BGM node failing with a bare
"Resolved BGM provider does not match configured BGM_PROVIDER" and no way to
work out which side to change. Two contracts are locked here:

* the mismatch and unsupported-provider errors name *both* values, so the
  operator sees which file to edit;
* ``bgm_provider_configuration_error`` reports the *real* blocking cause —
  an unsupported provider used to fall through to ``None``, i.e. "ready",
  which made the canvas let the operator start a node that could not run.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.tools.bgm_provider_factory import (
    SUPPORTED_BGM_PROVIDERS,
    build_bgm_provider_adapter,
    bgm_provider_configuration_error,
    is_supported_bgm_provider,
)
from app.tools.media_provider_protocol import MediaConfigurationError


def _settings(**overrides: object) -> SimpleNamespace:
    """A settings stub carrying only the fields the BGM factory reads."""
    values: dict[str, object] = {
        "bgm_provider": "stepfun_music",
        "bgm_api_key": "sk-test",
        "bgm_endpoint": "https://api.stepfun.com/step_plan/v1",
        "bgm_model": "stepaudio-3-music-preview",
        "bgm_access_key_id": "",
        "bgm_secret_access_key": "",
        "bgm_submit_action": "GenBGM",
        "bgm_api_version": "2025-01-01",
        "bgm_generation_version": "v1",
        "bgm_timeout_seconds": 300,
        "bgm_callback_mode": "auto",
        "bgm_callback_base_url": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)  # type: ignore[arg-type]


class TestBuildBgmProviderAdapter:
    def test_provider_mismatch_names_both_values(self, tmp_path: Path) -> None:
        with pytest.raises(MediaConfigurationError) as excinfo:
            build_bgm_provider_adapter(
                _settings(),  # type: ignore[arg-type]
                tmp_path,
                resolved_provider_id="tianpuyue",
            )
        message = str(excinfo.value)
        assert "tianpuyue" in message
        assert "stepfun_music" in message
        # The operator must be told both directions to fix it in.
        assert "BGM_PROVIDER=" in message

    def test_unsupported_provider_lists_supported_values(self, tmp_path: Path) -> None:
        with pytest.raises(MediaConfigurationError) as excinfo:
            build_bgm_provider_adapter(
                _settings(bgm_provider="nope"),  # type: ignore[arg-type]
                tmp_path,
            )
        message = str(excinfo.value)
        for provider in SUPPORTED_BGM_PROVIDERS:
            assert provider in message

    def test_matching_provider_ids_build_the_adapter(self, tmp_path: Path) -> None:
        adapter = build_bgm_provider_adapter(
            _settings(),  # type: ignore[arg-type]
            tmp_path,
            resolved_provider_id="stepfun_music",
        )
        assert adapter is not None


class TestBgmProviderConfigurationError:
    def test_missing_api_key_is_reported_directly(self) -> None:
        # The operator configured stepfun_music; the fix is the key, not the
        # provider. Reporting a provider mismatch here sends them to the wrong
        # setting entirely.
        error = bgm_provider_configuration_error(_settings(bgm_api_key=""))  # type: ignore[arg-type]
        assert error is not None
        assert "BGM_API_KEY" in error

    def test_unsupported_provider_is_not_reported_as_ready(self) -> None:
        # Regression: the unsupported value fell through both branches and
        # returned None, so the canvas advertised a runnable BGM node.
        error = bgm_provider_configuration_error(
            _settings(bgm_provider="typo")  # type: ignore[arg-type]
        )
        assert error is not None
        assert "Unsupported BGM_PROVIDER" in error
        assert "typo" in error

    def test_fully_configured_stepfun_music_is_ready(self) -> None:
        assert bgm_provider_configuration_error(_settings()) is None  # type: ignore[arg-type]

    def test_is_supported_bgm_provider_accepts_all_three(self) -> None:
        for provider in SUPPORTED_BGM_PROVIDERS:
            settings = _settings(bgm_provider=provider)  # type: ignore[arg-type]
            assert is_supported_bgm_provider(settings) is True  # type: ignore[arg-type]
        assert is_supported_bgm_provider(_settings(bgm_provider="")) is False  # type: ignore[arg-type]
