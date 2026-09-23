"""Typed StepFun Music provider primitives for V2 BGM.

Implements the StepAudio 3 Music async workflow documented at
https://platform.stepfun.com/docs/zh/api-reference/audio/music:

* Submit:  POST {base}/v1/audio/music/submit
           body: {task, model_id, caption, instrumental, response_format, ...}
           -> {"task_id": "..."}
* Query:   POST {base}/v1/audio/music/query
           body: {task_id}
           -> {status: PENDING|RUNNING|SUCCESS|FAILED, audio: <base64>, error: {...}}

Unlike the Tianpuyue/Volcengine adapters, StepFun returns the finished audio
inline as base64 in the query response (no downloadable URL), and the output
duration is model-determined (typically 1-3 minutes) rather than precisely
controllable. The adapter therefore keeps the requested duration as metadata
and relies on the composition stage to trim/fade the bed to target length.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from app.core.config import Settings
from app.services.v2_data_boundary import validate_v2_data_path
from app.tools.media_provider_protocol import MediaConfigurationError


STEPFUN_MUSIC_HOST = "api.stepfun.com"
STEPFUN_MUSIC_SUBMIT_PATH = "/v1/audio/music/submit"
STEPFUN_MUSIC_QUERY_PATH = "/v1/audio/music/query"
STEPFUN_MUSIC_DEFAULT_MODEL = "stepaudio-3-music-preview"
STEPFUN_MUSIC_MIN_DURATION_SECONDS = 1
STEPFUN_MUSIC_MAX_DURATION_SECONDS = 270
STEPFUN_STATUS_PENDING = "PENDING"
STEPFUN_STATUS_RUNNING = "RUNNING"
STEPFUN_STATUS_SUCCESS = "SUCCESS"
STEPFUN_STATUS_FAILED = "FAILED"
_MAX_DIAGNOSTIC_ITEM_IDS = 8
_MAX_DIAGNOSTIC_ITEM_ID_LENGTH = 128
_MAX_SAFE_ERROR_MESSAGE_LENGTH = 2_048
_URL_PATTERN = re.compile(r"(?i)\bhttps?://[^\s\"'<>]+")
_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)\b(?P<key>authorization|api[_-]?key|access[_-]?key|token|secret|signature)"
    r"\s*(?:=|:)\s*(?:bearer\s+)?[^\s,;\"'}\]]+"
)
_RESPONSE_FORMAT_EXTENSIONS = {
    "wav": ".wav",
    "flac": ".flac",
    "opus": ".opus",
    "mp3": ".mp3",
    "pcm": ".pcm",
}


class StepfunMusicError(ValueError):
    def __init__(self, code: str, message: str, *, metadata: dict[str, Any]) -> None:
        super().__init__(message)
        self.code = code
        self.metadata = metadata


def select_stepfun_music_model(settings: Settings) -> str:
    model = str(settings.bgm_model or "").strip() or STEPFUN_MUSIC_DEFAULT_MODEL
    return model


def validate_stepfun_music_settings(settings: Settings) -> None:
    endpoint = str(settings.bgm_endpoint or "").strip()
    parsed = urlparse(endpoint)
    if not str(settings.bgm_api_key or "").strip():
        raise MediaConfigurationError(
            "StepFun Music BGM provider requires BGM_API_KEY "
            "(the StepFun open-platform key, same key as STEPFUN_API_KEY)."
        )
    if parsed.scheme != "https" or parsed.hostname != STEPFUN_MUSIC_HOST:
        raise MediaConfigurationError(
            "StepFun Music BGM_ENDPOINT must use the official https://api.stepfun.com host."
        )
    if not str(settings.bgm_model or "").strip():
        raise MediaConfigurationError(
            "StepFun Music BGM_MODEL must not be empty "
            "(expected stepaudio-3-music-preview)."
        )


class StepfunMusicAdapter:
    """StepAudio 3 Music adapter configured for V2 BGM work."""

    def __init__(
        self,
        settings: Settings,
        data_dir: Path,
        *,
        client: httpx.Client | None = None,
        audio_probe: Callable[[Path], dict[str, Any]] | None = None,
    ) -> None:
        self._settings = settings
        self._data_dir = data_dir
        self._validate_settings()
        self._client = client or httpx.Client(timeout=settings.bgm_timeout_seconds)
        self._owns_client = client is None
        self._audio_probe = audio_probe or self._probe_audio

    def __del__(self) -> None:
        if getattr(self, "_owns_client", False):
            self._client.close()

    def generate_bgm_audio(
        self,
        bgm_plan: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        prompt = str(bgm_plan.get("provider_prompt") or bgm_plan.get("prompt") or "").strip()
        if not prompt:
            return self._failure(
                "bgm_provider_output_invalid",
                "StepFun Music BGM provider prompt is required.",
                stage="submit",
            )
        duration_seconds = _duration_seconds(bgm_plan.get("duration_seconds"))
        if (
            duration_seconds < STEPFUN_MUSIC_MIN_DURATION_SECONDS
            or duration_seconds > STEPFUN_MUSIC_MAX_DURATION_SECONDS
        ):
            return self._failure(
                "bgm_duration_unsupported",
                "StepFun Music BGM generation supports durations from 1 to 270 seconds.",
                stage="submit",
                requested_duration_seconds=duration_seconds,
            )
        frozen_provider_model_id = _frozen_provider_model_id(bgm_plan)
        model = frozen_provider_model_id or select_stepfun_music_model(self._settings)
        request_body = {
            "task": "text_to_music",
            "model_id": model,
            "caption": _music_caption(prompt, duration_seconds),
            "instrumental": True,
            "response_format": _response_format(self._settings),
        }
        response, failure = self._post_json(
            STEPFUN_MUSIC_SUBMIT_PATH,
            request_body,
            stage="submit",
        )
        if failure is not None:
            return failure
        assert response is not None
        payload = _json_object(response)
        if payload is None:
            return self._failure(
                "bgm_provider_submission_uncertain",
                "StepFun Music BGM submission returned an unreadable response.",
                stage="submit",
                retryable=False,
            )
        task_id = _task_id(payload)
        if not task_id:
            return self._failure(
                "bgm_provider_submission_uncertain",
                "StepFun Music BGM submission did not include a task id.",
                stage="submit",
                retryable=False,
            )
        return self._asset(
            status="submitted",
            task_id=task_id,
            model=model,
            frozen_provider_model_id=frozen_provider_model_id,
            provider_wire_model=model,
            requested_duration_seconds=duration_seconds,
            response_format=request_body["response_format"],
            workflow_id=workflow_id,
        )

    def retrieve_bgm_audio_task(
        self,
        remote_task_id: str,
        *,
        workflow_id: str,
        provider_payload: dict[str, Any],
        download_media: bool = True,
    ) -> dict[str, Any]:
        response, failure = self._post_json(
            STEPFUN_MUSIC_QUERY_PATH,
            {"task_id": remote_task_id},
            stage="query",
        )
        if failure is not None:
            return self._query_failure_or_waiting(remote_task_id, failure)
        assert response is not None
        payload = _json_object(response)
        if payload is None:
            return self._waiting(
                remote_task_id,
                "StepFun Music BGM query returned an unreadable response.",
                waiting_reason="retryable_provider_query_error",
                error_code="bgm_provider_output_invalid",
            )
        status = str(payload.get("status") or "").strip().upper()
        if status == STEPFUN_STATUS_FAILED:
            return self._failed_payload(remote_task_id, payload)
        if status not in {STEPFUN_STATUS_SUCCESS, STEPFUN_STATUS_PENDING, STEPFUN_STATUS_RUNNING}:
            return self._waiting(
                remote_task_id,
                "StepFun Music BGM query returned an unknown task status.",
                waiting_reason="retryable_provider_query_error",
                error_code="bgm_provider_output_invalid",
            )
        if status != STEPFUN_STATUS_SUCCESS:
            return self._waiting(
                remote_task_id,
                "StepFun Music BGM task is still running.",
                waiting_reason="provider_task_still_running",
                requested_duration_seconds=_requested_duration_seconds(provider_payload),
                provider_status=status,
            )
        metadata = {
            "requested_duration_seconds": _requested_duration_seconds(provider_payload),
            "provider_status": status,
            "provider_model": _string_or_none(payload.get("model_id"))
            or _string_or_none(payload.get("model")),
            "response_format": _string_or_none(payload.get("response_format")),
            "sample_rate": _int_or_none(payload.get("sample_rate")),
            "workflow_id": workflow_id,
        }
        rewritten_caption = _string_or_none(payload.get("rewritten_caption"))
        if rewritten_caption is not None:
            metadata["rewritten_caption"] = rewritten_caption
        if not download_media:
            return self._asset(
                status="succeeded",
                task_id=remote_task_id,
                model=_string_or_none(payload.get("model_id"))
                or _string_or_none(payload.get("model")),
                **metadata,
            )
        encoded = payload.get("audio")
        if not isinstance(encoded, str) or not encoded.strip():
            return self._waiting(
                remote_task_id,
                "StepFun Music BGM task completed without usable audio yet.",
                waiting_reason="provider_audio_not_ready",
                **metadata,
            )
        return self._decode_and_store_audio(
            encoded,
            remote_task_id=remote_task_id,
            model=_string_or_none(payload.get("model_id"))
            or _string_or_none(payload.get("model")),
            **metadata,
        )

    def _validate_settings(self) -> None:
        validate_stepfun_music_settings(self._settings)

    def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        stage: str,
    ) -> tuple[httpx.Response | None, dict[str, Any] | None]:
        try:
            response = self._client.post(
                _endpoint(self._settings.bgm_endpoint, path),
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._settings.bgm_api_key}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                timeout=self._settings.bgm_timeout_seconds,
            )
        except httpx.ConnectError:
            return None, self._failure(
                "bgm_provider_busy",
                "StepFun Music BGM connection could not be established.",
                stage=stage,
                retryable=True,
            )
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.ReadError, httpx.WriteError):
            return None, self._failure(
                "bgm_provider_submission_uncertain" if stage == "submit" else "bgm_provider_busy",
                "StepFun Music BGM request did not complete reliably.",
                stage=stage,
                retryable=False if stage == "submit" else True,
            )
        except httpx.HTTPError:
            return None, self._failure(
                "bgm_provider_submission_uncertain" if stage == "submit" else "bgm_provider_busy",
                "StepFun Music BGM request could not be completed.",
                stage=stage,
                retryable=False if stage == "submit" else True,
            )
        if response.status_code >= 400:
            error_type = _error_type(response)
            code, retryable = _http_error_mapping(response.status_code, error_type)
            return None, self._failure(
                code,
                f"StepFun Music BGM request returned HTTP {response.status_code}: "
                f"{_error_message(response)}",
                stage=stage,
                retryable=retryable,
                http_status=response.status_code,
                provider_error_type=error_type,
            )
        return response, None

    def _query_failure_or_waiting(
        self,
        remote_task_id: str,
        failure: dict[str, Any],
    ) -> dict[str, Any]:
        if failure.get("metadata", {}).get("retryable"):
            metadata = dict(failure.get("metadata") or {})
            metadata.pop("remote_task_id", None)
            return self._waiting(
                remote_task_id,
                str(failure.get("error") or "StepFun Music BGM query can be retried."),
                waiting_reason="retryable_provider_query_error",
                error_code=str(failure.get("error_code") or "bgm_provider_busy"),
                **metadata,
            )
        return failure

    def _failed_payload(
        self,
        remote_task_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        error = payload.get("error")
        error_stage = None
        error_message = None
        if isinstance(error, dict):
            error_stage = _string_or_none(error.get("stage"))
            error_message = _string_or_none(error.get("message"))
        metadata: dict[str, Any] = {}
        if error_stage is not None:
            metadata["provider_failure_stage"] = error_stage
        return self._failure(
            "bgm_provider_task_failed",
            error_message or "StepFun Music BGM task reached a terminal failure state.",
            remote_task_id=remote_task_id,
            stage="query",
            retryable=error_stage == "internal",
            **metadata,
        )

    def _waiting(
        self,
        remote_task_id: str,
        message: str,
        *,
        waiting_reason: str,
        error_code: str | None = None,
        **metadata: Any,
    ) -> dict[str, Any]:
        return self._asset(
            status="submitted",
            task_id=remote_task_id,
            waiting_reason=waiting_reason,
            error_code=error_code,
            waiting_message=message,
            **metadata,
        )

    def _decode_and_store_audio(
        self,
        encoded: str,
        *,
        remote_task_id: str,
        model: str | None,
        **metadata: Any,
    ) -> dict[str, Any]:
        metadata = dict(metadata)
        if "sample_rate" in metadata:
            metadata["declared_sample_rate"] = metadata.pop("sample_rate")
        max_bytes = self._settings.bgm_download_max_bytes
        if len(encoded) > max_bytes * 4 // 3 + 8:
            return self._download_failure(
                "StepFun Music BGM audio exceeded the configured size limit.",
                remote_task_id=remote_task_id,
                model=model,
                retryable=False,
                download_attempted=True,
                download_expected_bytes=max_bytes,
                **metadata,
            )
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            return self._download_failure(
                f"StepFun Music BGM audio payload is not valid base64: {exc}",
                remote_task_id=remote_task_id,
                model=model,
                retryable=False,
                download_attempted=True,
                **metadata,
            )
        if not raw:
            return self._download_failure(
                "StepFun Music BGM output was empty.",
                remote_task_id=remote_task_id,
                model=model,
                retryable=False,
                download_attempted=True,
                **metadata,
            )
        workflow_id = str(metadata.get("workflow_id") or "").strip()
        if not workflow_id:
            return self._download_failure(
                "StepFun Music BGM output does not have a workflow owner.",
                remote_task_id=remote_task_id,
                model=model,
                retryable=False,
                download_attempted=False,
                **metadata,
            )
        response_format = str(metadata.get("response_format") or "mp3").strip().lower()
        extension = _RESPONSE_FORMAT_EXTENSIONS.get(response_format, ".mp3")
        relative_path = (
            Path("assets")
            / "provider-output"
            / workflow_id
            / f"{_safe_file_stem(remote_task_id)}{extension}"
        )
        output_path = self._data_dir / relative_path
        validate_v2_data_path(
            self._data_dir,
            output_path,
            operation="v2-stepfun-music-download",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
        try:
            with temporary_path.open("xb") as output:
                output.write(raw)
        except OSError:
            temporary_path.unlink(missing_ok=True)
            return self._download_failure(
                "StepFun Music BGM audio could not be written to disk.",
                remote_task_id=remote_task_id,
                model=model,
                retryable=True,
                download_attempted=True,
                **metadata,
            )
        if temporary_path.stat().st_size == 0:
            temporary_path.unlink(missing_ok=True)
            return self._download_failure(
                "StepFun Music BGM output was empty or not usable audio media.",
                remote_task_id=remote_task_id,
                model=model,
                retryable=False,
                download_attempted=True,
                **metadata,
            )
        try:
            probe = self._audio_probe(temporary_path)
        except Exception as exc:  # noqa: BLE001 - a probe failure is invalid provider media.
            temporary_path.unlink(missing_ok=True)
            return self._failure(
                "bgm_audio_invalid",
                f"StepFun Music BGM output could not be probed: {exc}",
                remote_task_id=remote_task_id,
                model=model,
                **metadata,
            )
        if probe.get("error") or not probe.get("has_audio"):
            temporary_path.unlink(missing_ok=True)
            return self._failure(
                "bgm_audio_invalid",
                "StepFun Music BGM output is not a decodable audio stream.",
                remote_task_id=remote_task_id,
                model=model,
                **metadata,
            )
        temporary_path.replace(output_path)
        return self._asset(
            status="ready",
            task_id=remote_task_id,
            model=model,
            local_path=relative_path.as_posix(),
            download_status="downloaded",
            download_attempted=True,
            source_extension=extension,
            duration_seconds=probe.get("duration_seconds"),
            audio_codec=probe.get("audio_codec"),
            sample_rate=probe.get("sample_rate"),
            channels=probe.get("channels"),
            **metadata,
        )

    def _probe_audio(self, path: Path) -> dict[str, Any]:
        command = [
            self._settings.ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,sample_rate,channels",
            "-of",
            "json",
            path.as_posix(),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self._settings.bgm_timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"error": str(exc)[:500], "has_audio": False}
        if completed.returncode != 0:
            return {"error": completed.stderr[:500], "has_audio": False}
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return {"error": "ffprobe returned invalid JSON", "has_audio": False}
        streams = payload.get("streams") if isinstance(payload, dict) else None
        audio_stream = next(
            (
                stream
                for stream in streams or []
                if isinstance(stream, dict) and stream.get("codec_type") == "audio"
            ),
            None,
        )
        if not isinstance(audio_stream, dict):
            return {"error": "ffprobe did not find an audio stream", "has_audio": False}
        format_payload = payload.get("format") if isinstance(payload, dict) else {}
        return {
            "has_audio": True,
            "duration_seconds": _float_or_none(
                format_payload.get("duration") if isinstance(format_payload, dict) else None
            ),
            "audio_codec": _string_or_none(audio_stream.get("codec_name")),
            "sample_rate": _int_or_none(audio_stream.get("sample_rate")),
            "channels": _int_or_none(audio_stream.get("channels")),
        }

    def _asset(
        self,
        *,
        status: str,
        task_id: str | None,
        model: str | None = None,
        **metadata: Any,
    ) -> dict[str, Any]:
        safe_metadata = _safe_metadata(metadata)
        return {
            "provider": "stepfun_music",
            "model": model,
            "asset_id": "bgm-audio",
            "status": status,
            "task_id": task_id,
            "metadata": safe_metadata,
            **{
                key: value
                for key, value in safe_metadata.items()
                if value is not None and key not in {"workflow_id", "waiting_message"}
            },
        }

    def _failure(self, code: str, message: str, **metadata: Any) -> dict[str, Any]:
        return {
            "provider": "stepfun_music",
            "asset_id": "bgm-audio",
            "status": "failed",
            "error_code": code,
            "error": _safe_error_message(message),
            "metadata": _safe_metadata(metadata),
        }

    def _download_failure(
        self,
        message: str,
        *,
        remote_task_id: str,
        model: str | None,
        retryable: bool,
        download_attempted: bool,
        **metadata: Any,
    ) -> dict[str, Any]:
        return self._asset(
            status="failed",
            task_id=remote_task_id,
            model=model,
            error_code="bgm_audio_download_failed",
            error=message,
            download_status="failed",
            download_error_code="bgm_audio_download_failed",
            download_retryable=retryable,
            download_attempted=download_attempted,
            **metadata,
        )


def _duration_seconds(value: object) -> int:
    try:
        duration = int(value)
    except (TypeError, ValueError):
        return 0
    return duration


def _frozen_provider_model_id(bgm_plan: dict[str, Any]) -> str | None:
    value = bgm_plan.get("provider_model_id")
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


STEPFUN_PROMPT_MAX_CHARS = 1000


def _music_caption(prompt: str, duration_seconds: int) -> str:
    suffix = (
        f"Target duration: approximately {duration_seconds} seconds. "
        "Instrumental background music only: no vocals, no lyrics, no narration, "
        "no spoken dialogue, and no sound effects."
    )
    separator = "\n\n"
    creative_prompt = prompt.strip()
    creative_limit = STEPFUN_PROMPT_MAX_CHARS - len(separator) - len(suffix)
    if len(creative_prompt) > creative_limit:
        creative_prompt = _truncate_prompt(creative_prompt, creative_limit)
    return f"{creative_prompt}{separator}{suffix}"


def _truncate_prompt(prompt: str, limit: int) -> str:
    candidate = prompt[:limit].rstrip()
    sentence_end = max(candidate.rfind(". "), candidate.rfind("! "), candidate.rfind("? "))
    if sentence_end >= limit // 2:
        return candidate[: sentence_end + 1].rstrip()
    word_end = candidate.rfind(" ")
    if word_end >= limit // 2:
        return candidate[:word_end].rstrip()
    return candidate


def _response_format(settings: Settings) -> str:
    value = str(settings.bgm_response_format or "mp3").strip().lower()
    return value if value in _RESPONSE_FORMAT_EXTENSIONS else "mp3"


def _endpoint(base_url: str | None, path: str) -> str:
    return f"{str(base_url or '').rstrip('/')}{path}"


def _json_object(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _task_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("task_id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _error_type(response: httpx.Response) -> str | None:
    payload = _json_object(response)
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            value = error.get("type")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _error_message(response: httpx.Response) -> str:
    payload = _json_object(response)
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            value = error.get("message")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "no error detail"


def _http_error_mapping(status_code: int, error_type: str | None) -> tuple[str, bool]:
    if status_code == 401:
        return "bgm_provider_auth_failed", False
    if status_code == 402:
        return "bgm_provider_quota_exhausted", False
    if status_code == 404:
        return "bgm_provider_model_unsupported", False
    if status_code == 451:
        return "bgm_provider_content_rejected", False
    if status_code == 429:
        if error_type in {
            "project_credit_limit_exceeded",
            "member_project_credit_limit_exceeded",
        }:
            return "bgm_provider_quota_exhausted", False
        return "bgm_provider_busy", True
    if status_code >= 500:
        return "bgm_provider_busy", True
    return "bgm_provider_request_invalid", False


def _requested_duration_seconds(provider_payload: dict[str, Any]) -> int | None:
    value = provider_payload.get("duration_seconds")
    if value is None:
        return None
    duration = _duration_seconds(value)
    return duration if duration > 0 else None


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _safe_metadata_value(value)
        for key, value in metadata.items()
        if value is not None and not _is_forbidden_metadata_key(key)
    }


def _safe_metadata_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _safe_metadata(value)
    if isinstance(value, list):
        return [_safe_metadata_value(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_metadata_value(item) for item in value]
    if isinstance(value, str):
        return _safe_error_message(value)
    return value


def _is_forbidden_metadata_key(key: str) -> bool:
    normalized = key.lower()
    return (
        normalized
        in {
            "api_key",
            "authorization",
            "audio",
            "audio_base64",
            "encoded_audio",
            "callback_url",
            "remote_url",
            "url",
        }
        or normalized.endswith("_api_key")
        or normalized.endswith("_authorization")
        or normalized.endswith("_token")
        or normalized.endswith("_secret")
    )


def _safe_error_message(message: str) -> str:
    without_urls = _URL_PATTERN.sub("[redacted-url]", str(message))
    redacted = _SENSITIVE_TEXT_PATTERN.sub(
        lambda match: f"{match.group('key')}=[redacted]",
        without_urls,
    )
    return redacted[:_MAX_SAFE_ERROR_MESSAGE_LENGTH]


def _safe_file_stem(value: str) -> str:
    normalized = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in value
    )
    normalized = normalized.strip("-_")[:96]
    if normalized:
        return normalized
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
