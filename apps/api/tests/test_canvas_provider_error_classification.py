"""Classification at the ``execute_minimal`` boundary (ISSUE-12, canvas path).

The 2026-09-19 E2E run left the image node red on a Volcengine 503
``engine_overloaded``. The classifier was wired into
``V2ProviderExecutor._execute_native_minimal``, but the canvas media path never
goes there: with no native adapter for the payload it returns ``None`` and
``execute_minimal`` falls through to its own ``except Exception``, which
hardcoded ``provider_generation_failed`` and emitted **no metadata**.

That is the failure the canvas media executor actually reads, so the test below
drives ``execute_minimal`` itself rather than the subsystem behind it. Without
this test every earlier classification test passed while the production path
stayed broken — the exact shape of the original bug.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.tools.media_provider_protocol import MediaApiError
from app.services.v2_provider_executor import V2ProviderExecutor
from app.services.workflow_v2 import RETRYABLE_PROVIDER_ERROR_CODES

OVERLOAD_BODY = (
    '{"error": {"message": "The engine is currently overloaded, '
    'please try again later", "type": "engine_overloaded", '
    '"description": "服务繁忙，请稍后重试"}}'
)


class _OverloadingImageProvider:
    """Raises the exact Volcengine 503 the E2E run produced."""

    def __init__(self, *, status: int, body: str) -> None:
        self._status = status
        self._body = body

    def generate_v2_canonical_image(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise MediaApiError(
            message=f"media_api_failed:\nstatus={self._status}\nresponse_body={self._body}",
            metadata={"provider": "volcengine", "status": self._status, "response_body": self._body},
        )


class _StubBgmAdapter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_bgm_audio(self, bgm_plan: dict[str, Any], workflow_id: str) -> dict[str, Any]:
        self.calls.append({"bgm_plan": dict(bgm_plan), "workflow_id": workflow_id})
        return {"provider": "stepfun_music", "model": "stepaudio-3-music-preview", "status": "ok"}
    def retrieve_bgm_audio_task(self, *_: Any, **__: Any) -> dict[str, Any]:
        return {"status": "ok"}


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "media_mode": "real",
        # Only decides whether the missing-config short circuit is skipped; the
        # provider is injected either way.
        "v2_provider_allow_fallback": True,
        "bgm_provider": "stepfun_music",
        "bgm_api_key": "stub-bgm-key",
        "bgm_endpoint": "https://api.stepfun.com",
        "bgm_model": "stepaudio-3-music-preview",
    }
    base.update(overrides)
    return Settings(**base)


def _executor(
    tmp_path: Path,
    *,
    provider: Any = None,
    settings: Settings | None = None,
) -> V2ProviderExecutor:
    resolved = settings or _settings()
    factory = ((lambda _s: provider) if provider is not None else None)
    return V2ProviderExecutor(
        settings=resolved,
        data_dir=tmp_path,
        provider_factory=factory,  # type: ignore[arg-type]
    )


def _submit_image(executor: V2ProviderExecutor) -> Any:
    return executor.execute_minimal(
        workflow_id="wf_overload",
        slot_type="scene",
        media_type="image",
        provider_payload={"prompt": "a teahouse at dusk", "node_id": "node_1"},
    )


class TestImageOverloadIsRetryable:
    def test_503_engine_overloaded_is_classified_transient(self, tmp_path: Path) -> None:
        # The exact failure from the E2E run. Before the fix this returned
        # error_code=None, so the canvas executor defaulted the code to
        # provider_generation_failed and never retried.
        provider = _OverloadingImageProvider(status=503, body=OVERLOAD_BODY)
        result = _submit_image(_executor(tmp_path, provider=provider))

        assert result.status == "failed"
        assert result.error_code == "provider_temporary_unavailable"
        assert result.error_code in RETRYABLE_PROVIDER_ERROR_CODES
        assert result.metadata["retryable"] is True
        assert result.metadata["provider_error_type"] == "engine_overloaded"
        assert result.metadata["provider_http_status"] == 503

    def test_non_retryable_failure_keeps_the_generic_code(self, tmp_path: Path) -> None:
        # A 400 must not become retryable: retrying a bad prompt burns quota
        # and still fails.
        provider = _OverloadingImageProvider(status=400, body='{"error": {"message": "prompt is empty"}}')
        result = _submit_image(_executor(tmp_path, provider=provider))

        assert result.error_code == "provider_generation_failed"
        assert "retryable" not in result.metadata

    def test_overload_body_promotes_a_non_5xx_status(self, tmp_path: Path) -> None:
        # A provider that reports overload under 400 is still transient,
        # otherwise the operator sees a permanent failure for a temporary one.
        provider = _OverloadingImageProvider(status=400, body=OVERLOAD_BODY)
        result = _submit_image(_executor(tmp_path, provider=provider))

        assert result.error_code == "provider_temporary_unavailable"
        assert result.metadata["retryable"] is True

    def test_retryable_flag_reaches_the_canvas_media_executor(self, tmp_path: Path) -> None:
        # The canvas executor retries on result.metadata["retryable"] alone, so
        # this flag is the contract between the two layers. If it stops being
        # set the automatic backoff silently stops happening.
        provider = _OverloadingImageProvider(status=503, body=OVERLOAD_BODY)
        result = _submit_image(_executor(tmp_path, provider=provider))

        assert result.status == "failed"
        assert bool(result.metadata.get("retryable"))

    def test_provider_error_message_is_preserved(self, tmp_path: Path) -> None:
        # The message carries the user_action hint, so losing it would hide the
        # "safe to retry" explanation the operator relies on.
        provider = _OverloadingImageProvider(status=503, body=OVERLOAD_BODY)
        result = _submit_image(_executor(tmp_path, provider=provider))

        assert "media_api_failed" in result.error_message


class TestBgmUsesConfiguredMusicModel:
    def test_tts_default_model_is_not_sent_as_the_music_model(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        # The plan's provider_model_id is frozen from the `audio` capability
        # default, which is a *TTS* model (tianpuyue:TemPolor-i3). StepFun Music
        # answers that with HTTP 404 "model does not exist", which surfaced as a
        # permission-sounding failure. BGM_MODEL must win so the adapter's own
        # selection (settings.bgm_model) is what gets sent.
        import app.services.v2_provider_executor as executor_module

        adapter = _StubBgmAdapter()
        monkeypatch.setattr(
            executor_module,
            "build_bgm_provider_adapter",
            lambda settings, data_dir, *, resolved_provider_id=None: adapter,
        )

        result = _executor(tmp_path, settings=_settings()).execute_minimal(
            workflow_id="wf_bgm",
            slot_type="bgm",
            media_type="audio",
            provider_payload={
                "prompt": "warm acoustic, piano",
                "provider_model_id": "TemPolor-i3",  # the TTS default
                "model": "TemPolor-i3",
            },
        )

        assert "does not exist" not in (result.error_message or "")
        assert len(adapter.calls) == 1
        sent = adapter.calls[0]["bgm_plan"]
        assert "provider_model_id" not in sent, (
            "the TTS default model id leaked into the music request"
        )

    def test_unset_bgm_model_keeps_the_plan_id(self, tmp_path: Path, monkeypatch: Any) -> None:
        # With no BGM_MODEL configured the adapter's own default must still
        # apply, so the plan's id has to survive.
        import app.services.v2_provider_executor as executor_module

        adapter = _StubBgmAdapter()
        monkeypatch.setattr(
            executor_module,
            "build_bgm_provider_adapter",
            lambda settings, data_dir, *, resolved_provider_id=None: adapter,
        )

        _executor(tmp_path, settings=_settings(bgm_model="")).execute_minimal(
            workflow_id="wf_bgm",
            slot_type="bgm",
            media_type="audio",
            provider_payload={"prompt": "warm acoustic", "provider_model_id": "some-music-model"},
        )

        assert adapter.calls[0]["bgm_plan"]["provider_model_id"] == "some-music-model"


class TestBgmHonorsConfiguredProvider:
    def test_plan_provider_cannot_override_bgm_provider(self, tmp_path: Path, monkeypatch: Any) -> None:
        # The model catalog has no music entry, so the plan resolved to
        # "tianpuyue" purely because it is the one other audio (TTS) provider.
        # Passing that to build_bgm_provider_adapter raised a provider mismatch
        # against BGM_PROVIDER=stepfun_music, which is what failed the BGM node.
        import app.services.v2_provider_executor as executor_module

        adapter = _StubBgmAdapter()
        captured: dict[str, Any] = {}

        def _capture(
            settings: Settings,
            data_dir: Path,
            *,
            resolved_provider_id: str | None = None,
        ) -> _StubBgmAdapter:
            captured["resolved_provider_id"] = resolved_provider_id
            return adapter

        monkeypatch.setattr(executor_module, "build_bgm_provider_adapter", _capture)

        result = _executor(tmp_path, settings=_settings()).execute_minimal(
            workflow_id="wf_bgm",
            slot_type="bgm",
            media_type="audio",
            provider_payload={
                "prompt": "warm acoustic, piano",
                "provider_id": "tianpuyue",  # the catalog's bogus resolution
            },
        )

        # No provider-mismatch raise and no bogus tianpuyue: the operator's
        # setting is what the adapter is built with. The stub produces no media
        # file, so the result is still `failed` further downstream — what this
        # test owns is that the mismatch never happened.
        assert "does not match configured BGM_PROVIDER" not in (result.error_message or "")
        assert captured["resolved_provider_id"] == "stepfun_music"
        assert adapter.calls, "expected the adapter to actually be invoked"
        assert "retryable" not in result.metadata

    def test_unset_bgm_provider_reports_missing_config_not_mismatch(
        self, tmp_path: Path
    ) -> None:
        # An empty BGM_PROVIDER must produce "unsupported/empty", never a
        # mismatch between two values the operator did choose.
        import app.services.v2_provider_executor as executor_module

        seen: dict[str, Any] = {}

        def _capture(
            settings: Settings,
            data_dir: Path,
            *,
            resolved_provider_id: str | None = None,
        ) -> _StubBgmAdapter:
            seen["resolved_provider_id"] = resolved_provider_id
            raise AssertionError("must not build an adapter when the provider is unset")

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(executor_module, "build_bgm_provider_adapter", _capture)
        try:
            result = _executor(
                tmp_path, settings=_settings(bgm_provider="", bgm_api_key="")
            ).execute_minimal(
                workflow_id="wf_bgm",
                slot_type="bgm",
                media_type="audio",
                provider_payload={"prompt": "warm acoustic", "provider_id": "tianpuyue"},
            )
        finally:
            monkeypatch.undo()

        assert result.status == "failed"
        assert seen["resolved_provider_id"] is None
        # The config error must not be dressed up as a transient failure.
        assert "retryable" not in result.metadata
