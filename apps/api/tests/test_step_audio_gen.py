"""Unit tests for the StepAudio 3 Gen unified audio client.

Covers payload validation (pure), settings validation, and the adapter over a
mocked transport (raw audio, URL download, base64 JSON, HTTP error mapping,
probe failures). No network: httpx.MockTransport + injected audio probe.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.tools.media_provider_protocol import MediaConfigurationError
from app.tools.step_audio_gen import (
    STEP_AUDIO_GEN_MAX_INSTRUCTION_CHARS,
    STEP_AUDIO_GEN_MAX_ROLES_CHARS,
    STEP_AUDIO_GEN_MAX_SCRIPTS_CHARS,
    StepAudioGenAdapter,
    StepAudioGenError,
    build_step_audio_gen_payload,
    validate_step_audio_gen_settings,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _settings(tmp_path: Path, **overrides) -> Settings:
    payload = {
        "agent_runtime_mode": "real",
        "stepfun_api_key": "test-key",
        "media_data_dir": tmp_path / "data",
        "step_audio_gen_timeout_seconds": 5,
    }
    payload.update(overrides)
    return Settings(**payload)


def _probe_ok(path: Path) -> dict:
    return {
        "has_audio": True,
        "duration_seconds": 12.5,
        "audio_codec": "mp3",
        "sample_rate": 48000,
        "channels": 2,
    }


def _adapter(tmp_path: Path, transport: httpx.MockTransport, **overrides) -> StepAudioGenAdapter:
    client = httpx.Client(transport=transport)
    return StepAudioGenAdapter(
        _settings(tmp_path, **overrides),
        tmp_path / "data",
        client=client,
        audio_probe=_probe_ok,
    )


_DIALOGUE_SCRIPTS = [
    {"text": "[地下研究所 B2 层走廊，低频电机嗡鸣，远处传来金属门的撞击回响]"},
    {"speaker": "林澈", "text": "（压低声音，警惕）就是这里，信号源在墙后面。"},
    {"speaker": "苏晴", "text": "（轻声，犹豫）你确定要进去吗？整个研究所都停电了。"},
]
_DIALOGUE_ROLES = [
    {"name": "林澈", "description": "二十多岁的男性，嗓音低沉冷静，带着警惕"},
    {"name": "苏晴", "description": "年轻女性，声音轻而紧绷"},
]


# ---------------------------------------------------------------------------
# Payload validation (pure)
# ---------------------------------------------------------------------------


def test_payload_builds_dialogue_and_ambience() -> None:
    payload = build_step_audio_gen_payload(
        model="stepaudio-3-gen-preview",
        scripts=_DIALOGUE_SCRIPTS,
        roles=_DIALOGUE_ROLES,
        instruction="废弃地下研究所，悬疑氛围",
        speed=1.0,
        volume=1.2,
        sample_rate=48000,
    )
    assert payload["task"] == "text_to_audio"
    assert payload["response_format"] == "mp3"
    assert payload["stream_format"] == "audio"
    assert payload["instruction"] == "废弃地下研究所，悬疑氛围"
    assert [role["name"] for role in payload["roles"]] == ["林澈", "苏晴"]
    assert payload["scripts"][0] == {"text": _DIALOGUE_SCRIPTS[0]["text"]}
    assert payload["scripts"][1]["speaker"] == "林澈"
    assert payload["speed"] == 1.0
    assert payload["volume"] == 1.2
    assert payload["sample_rate"] == 48000
    assert "return_url" not in payload


def test_payload_requires_scripts_or_instruction() -> None:
    with pytest.raises(StepAudioGenError) as exc:
        build_step_audio_gen_payload(model="m", scripts=[])
    assert exc.value.code == "step_audio_gen_scripts_or_instruction_required"


def test_payload_accepts_instruction_only() -> None:
    payload = build_step_audio_gen_payload(model="m", scripts=[], instruction="BGM only")
    assert payload["instruction"] == "BGM only"
    assert "scripts" not in payload


def test_payload_rejects_empty_script_text() -> None:
    with pytest.raises(StepAudioGenError) as exc:
        build_step_audio_gen_payload(model="m", scripts=[{"text": "   "}])
    assert exc.value.code == "step_audio_gen_script_text_required"


def test_payload_rejects_speaker_without_roles() -> None:
    with pytest.raises(StepAudioGenError) as exc:
        build_step_audio_gen_payload(model="m", scripts=[{"speaker": "A", "text": "hi"}])
    assert exc.value.code == "step_audio_gen_speaker_without_roles"


def test_payload_rejects_unknown_speaker() -> None:
    with pytest.raises(StepAudioGenError) as exc:
        build_step_audio_gen_payload(
            model="m",
            scripts=[{"speaker": "Ghost", "text": "hi"}],
            roles=[{"name": "A", "description": "x"}],
        )
    assert exc.value.code == "step_audio_gen_unknown_speaker"


def test_payload_rejects_incomplete_role() -> None:
    with pytest.raises(StepAudioGenError) as exc:
        build_step_audio_gen_payload(
            model="m", scripts=[{"text": "hi"}], roles=[{"name": "A", "description": ""}]
        )
    assert exc.value.code == "step_audio_gen_role_incomplete"


def test_payload_rejects_oversized_scripts() -> None:
    scripts = [{"text": "x" * (STEP_AUDIO_GEN_MAX_SCRIPTS_CHARS + 1)}]
    with pytest.raises(StepAudioGenError) as exc:
        build_step_audio_gen_payload(model="m", scripts=scripts)
    assert exc.value.code == "step_audio_gen_scripts_too_long"


def test_payload_rejects_oversized_instruction() -> None:
    with pytest.raises(StepAudioGenError) as exc:
        build_step_audio_gen_payload(
            model="m", scripts=[], instruction="x" * (STEP_AUDIO_GEN_MAX_INSTRUCTION_CHARS + 1)
        )
    assert exc.value.code == "step_audio_gen_instruction_too_long"


def test_payload_rejects_oversized_roles() -> None:
    with pytest.raises(StepAudioGenError) as exc:
        build_step_audio_gen_payload(
            model="m",
            scripts=[{"text": "hi"}],
            roles=[
                {
                    "name": "A" * (STEP_AUDIO_GEN_MAX_ROLES_CHARS // 2 + 1),
                    "description": "B" * (STEP_AUDIO_GEN_MAX_ROLES_CHARS // 2 + 1),
                }
            ],
        )
    assert exc.value.code == "step_audio_gen_roles_too_long"


@pytest.mark.parametrize(
    "kwargs, code",
    [
        ({"speed": 0.4}, "step_audio_gen_speed_out_of_range"),
        ({"speed": 2.5}, "step_audio_gen_speed_out_of_range"),
        ({"volume": 0.05}, "step_audio_gen_volume_out_of_range"),
        ({"volume": 2.1}, "step_audio_gen_volume_out_of_range"),
        ({"sample_rate": 44100}, "step_audio_gen_sample_rate_unsupported"),
        ({"response_format": "aiff"}, "step_audio_gen_response_format_unsupported"),
        ({"text_normalization": "aggressive"}, "step_audio_gen_text_normalization_unsupported"),
    ],
)
def test_payload_rejects_out_of_contract_parameters(kwargs, code) -> None:
    with pytest.raises(StepAudioGenError) as exc:
        build_step_audio_gen_payload(model="m", scripts=[{"text": "hi"}], **kwargs)
    assert exc.value.code == code


def test_payload_pronunciation_map_and_return_url() -> None:
    payload = build_step_audio_gen_payload(
        model="m",
        scripts=[{"text": "hi"}],
        pronunciation_map={"B2": "B-two"},
        text_normalization="enhanced",
        return_url=True,
    )
    assert payload["pronunciation_map"] == {"B2": "B-two"}
    assert payload["text_normalization"] == "enhanced"
    assert payload["return_url"] is True


# ---------------------------------------------------------------------------
# Settings validation
# ---------------------------------------------------------------------------


def test_settings_require_api_key(tmp_path: Path) -> None:
    with pytest.raises(MediaConfigurationError):
        validate_step_audio_gen_settings(_settings(tmp_path, stepfun_api_key=None))


def test_settings_require_official_host(tmp_path: Path) -> None:
    with pytest.raises(MediaConfigurationError):
        validate_step_audio_gen_settings(
            _settings(tmp_path, step_audio_gen_endpoint="https://evil.example.com")
        )


# ---------------------------------------------------------------------------
# Adapter (mocked transport)
# ---------------------------------------------------------------------------


def test_generate_stores_raw_audio(tmp_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content=b"ID3fake-mp3-bytes",
            headers={"content-type": "audio/mpeg"},
        )
    )
    adapter = _adapter(tmp_path, transport)

    result = adapter.generate_unified_audio(
        workflow_id="wf-audio",
        scripts=_DIALOGUE_SCRIPTS,
        roles=_DIALOGUE_ROLES,
        instruction="地下研究所悬疑氛围",
    )

    assert result["status"] == "ready"
    assert result["duration_seconds"] == 12.5
    assert result["audio_codec"] == "mp3"
    assert result["per_element_timing_available"] is False
    stored = tmp_path / "data" / result["local_path"]
    assert stored.exists()
    assert stored.read_bytes() == b"ID3fake-mp3-bytes"


def test_generate_downloads_returned_url(tmp_path: Path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"url": "https://cdn.stepfun.example/audio/bed.mp3"},
                headers={"content-type": "application/json"},
            )
        calls["n"] += 1
        return httpx.Response(
            200, content=b"downloaded-mp3", headers={"content-type": "audio/mpeg"}
        )

    adapter = _adapter(tmp_path, httpx.MockTransport(handler))
    result = adapter.generate_unified_audio(
        workflow_id="wf-audio",
        scripts=[{"text": "[雨夜街道]"}],
        return_url=True,
    )

    assert result["status"] == "ready"
    assert calls["n"] == 1
    assert result["source_url"] == "https://cdn.stepfun.example/audio/bed.mp3"
    stored = tmp_path / "data" / result["local_path"]
    assert stored.read_bytes() == b"downloaded-mp3"


def test_generate_accepts_base64_json_audio(tmp_path: Path) -> None:
    import base64

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"audio": base64.b64encode(b"b64-audio").decode()},
            headers={"content-type": "application/json"},
        )
    )
    adapter = _adapter(tmp_path, transport)

    result = adapter.generate_unified_audio(
        workflow_id="wf-audio",
        instruction="ambient only",
        response_format="wav",
    )

    assert result["status"] == "ready"
    assert result["source_extension"] == ".wav"
    stored = tmp_path / "data" / result["local_path"]
    assert stored.read_bytes() == b"b64-audio"


def test_generate_maps_http_errors(tmp_path: Path) -> None:
    cases = [
        (400, "step_audio_gen_request_invalid", False),
        (402, "step_audio_gen_quota_exceeded", False),
        (429, "step_audio_gen_busy", True),
        (500, "step_audio_gen_provider_error", True),
    ]
    for status_code, expected_code, expected_retryable in cases:
        transport = httpx.MockTransport(
            lambda request, code=status_code: httpx.Response(
                code, json={"error": {"message": "provider said no"}}
            )
        )
        adapter = _adapter(tmp_path, transport)
        result = adapter.generate_unified_audio(
            workflow_id="wf-audio", scripts=[{"text": "hi"}]
        )
        assert result["status"] == "failed", status_code
        assert result["error_code"] == expected_code, status_code
        assert result["metadata"]["retryable"] is expected_retryable, status_code
        assert "provider said no" in result["error"]


def test_generate_rejects_empty_body(tmp_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"", headers={"content-type": "audio/mpeg"})
    )
    adapter = _adapter(tmp_path, transport)
    result = adapter.generate_unified_audio(workflow_id="wf-audio", scripts=[{"text": "hi"}])
    assert result["error_code"] == "step_audio_gen_output_invalid"


def test_generate_requires_workflow_id(tmp_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"x", headers={"content-type": "audio/mpeg"})
    )
    adapter = _adapter(tmp_path, transport)
    result = adapter.generate_unified_audio(workflow_id="  ", scripts=[{"text": "hi"}])
    assert result["error_code"] == "step_audio_gen_workflow_required"


def test_generate_surfaces_probe_failure(tmp_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=b"not-audio", headers={"content-type": "audio/mpeg"}
        )
    )
    client = httpx.Client(transport=transport)
    adapter = StepAudioGenAdapter(
        _settings(tmp_path),
        tmp_path / "data",
        client=client,
        audio_probe=lambda path: {"has_audio": False, "error": "no audio stream"},
    )
    result = adapter.generate_unified_audio(workflow_id="wf-audio", scripts=[{"text": "hi"}])

    assert result["status"] == "failed"
    assert result["error_code"] == "step_audio_gen_audio_invalid"


def test_generate_fails_closed_on_invalid_payload(tmp_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda request: pytest.fail("provider must not be called for an invalid payload")
    )
    adapter = _adapter(tmp_path, transport)
    result = adapter.generate_unified_audio(
        workflow_id="wf-audio",
        scripts=[{"speaker": " nobody", "text": "hi"}],
    )
    assert result["status"] == "failed"
    assert result["error_code"] == "step_audio_gen_speaker_without_roles"


class TestPerLineEmotionAnnotation:
    """V0.2 §14.7 表演层: every line can carry its emotion.

    The provider reads per-line direction as a ``(emotion)`` annotation
    inside the script text. Exposing it as a field is the difference between
    "每一句都能带情绪" and a bracket convention nobody types. Three rules are
    load-bearing, and each one exists because the annotation lands inside the
    provider's prompt text.
    """

    def _payload(self, scripts: list[dict[str, object]]):
        return build_step_audio_gen_payload(
            model="step-audio-3-gen",
            scripts=scripts,
            roles=[{"name": "girl", "description": "soft voice"}],
        )

    def test_an_emotion_becomes_the_providers_annotation_prefix(self) -> None:
        payload = self._payload([{"speaker": "girl", "text": "跟紧我", "emotion": "压低声音"}])
        assert payload["scripts"] == [{"speaker": "girl", "text": "(压低声音) 跟紧我"}]

    def test_a_line_without_emotion_keeps_its_text_verbatim(self) -> None:
        payload = self._payload([{"speaker": "girl", "text": "跟紧我"}])
        assert payload["scripts"] == [{"speaker": "girl", "text": "跟紧我"}]

    def test_an_empty_emotion_is_not_an_annotation(self) -> None:
        payload = self._payload([{"speaker": "girl", "text": "跟紧我", "emotion": "   "}])
        assert payload["scripts"] == [{"speaker": "girl", "text": "跟紧我"}]

    def test_a_text_that_already_annotates_itself_is_not_double_annotated(self) -> None:
        # Refusing beats guessing which annotation the provider will honour.
        with pytest.raises(StepAudioGenError) as raised:
            self._payload([{"speaker": "girl", "text": "(低声) 跟紧我", "emotion": "sad"}])
        assert raised.value.code == "step_audio_gen_script_emotion_ambiguous"

    def test_a_parenthesis_or_newline_inside_the_emotion_is_refused(self) -> None:
        for emotion in ["a)b", "line\nbreak", "carriage\rreturn"]:
            with pytest.raises(StepAudioGenError) as raised:
                self._payload([{"speaker": "girl", "text": "x", "emotion": emotion}])
            assert raised.value.code == "step_audio_gen_script_emotion_unbalanced"

    def test_an_emotion_is_bounded(self) -> None:
        with pytest.raises(StepAudioGenError) as raised:
            self._payload([{"speaker": "girl", "text": "x", "emotion": "x" * 65}])
        assert raised.value.code == "step_audio_gen_script_emotion_too_long"

    def test_a_non_string_emotion_is_refused(self) -> None:
        with pytest.raises(StepAudioGenError) as raised:
            self._payload([{"speaker": "girl", "text": "x", "emotion": 42}])
        assert raised.value.code == "step_audio_gen_script_emotion_not_string"

    def test_the_speaker_rules_survive_the_emotion_path(self) -> None:
        # A new field must not become a hole in the old validation.
        with pytest.raises(StepAudioGenError) as raised:
            build_step_audio_gen_payload(
                model="m",
                scripts=[{"text": "hi", "speaker": "ghost", "emotion": "sad"}],
            )
        assert raised.value.code == "step_audio_gen_speaker_without_roles"
