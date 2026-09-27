"""Typed StepAudio 3 Gen provider primitives for unified audio generation.

Implements the StepAudio 3 Gen endpoint documented at
https://platform.stepfun.com/docs/llms.txt (音频生成):

* Generate: POST {base}/v1/audio/generate
            body: {model, task, roles?, scripts?, instruction?, ...}
            -> finished audio (raw bytes by default, or a URL when
               ``return_url`` is set)

Unlike the StepAudio 3 Music adapter (async submit/query), this endpoint is
synchronous: one request returns the complete, orchestrated audio bed. It
mixes, per the documented contract:

* multi-role dialogue -- ``roles`` (name + timbre/emotion description) plus
  speaker-tagged ``scripts`` entries with ``(emotion/style)`` annotations;
* SFX / ambience / BGM -- ``scripts`` entries wrapped in ``[...]`` without a
  speaker;
* a global ``instruction`` for environment / mood / BGM direction.

Known limitation (by design, surfaced as metadata): this model does not
support ``timestamp``, so per-element timing is NOT returned. Callers that
need shot-level alignment (dialogue-driven video, lip-sync) either generate
per-line speech separately (``stepaudio-2.5-tts``) or recover timings with a
forced-alignment pass; see docs/plans/blender-mcp-white-model-mode-and-audio-
collaboration.md §3.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Mapping, Sequence
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


STEP_AUDIO_GEN_HOST = "api.stepfun.com"
STEP_AUDIO_GEN_TASK = "text_to_audio"
STEP_AUDIO_GEN_DEFAULT_MODEL = "stepaudio-3-gen-preview"
STEP_AUDIO_GEN_MAX_ROLES_CHARS = 500
STEP_AUDIO_GEN_MAX_SCRIPTS_CHARS = 1000

#: Longest per-line emotion/style annotation. The provider reads these as an
#: ``(emotion)`` prefix; a paragraph there is a prompt-injection surface and a
#: billing surprise, not a performance note.
STEP_AUDIO_GEN_MAX_EMOTION_CHARS = 64
STEP_AUDIO_GEN_MAX_INSTRUCTION_CHARS = 500
STEP_AUDIO_GEN_SPEED_RANGE = (0.5, 2.0)
STEP_AUDIO_GEN_VOLUME_RANGE = (0.1, 2.0)
STEP_AUDIO_GEN_SAMPLE_RATES = (8000, 16000, 22050, 24000, 48000)
STEP_AUDIO_GEN_RESPONSE_FORMATS = ("wav", "mp3", "flac", "opus", "pcm")
STEP_AUDIO_GEN_TEXT_NORMALIZATIONS = ("standard", "enhanced")
_RESPONSE_FORMAT_EXTENSIONS = {
    "wav": ".wav",
    "mp3": ".mp3",
    "flac": ".flac",
    "opus": ".opus",
    "pcm": ".pcm",
}
_URL_PATTERN = re.compile(r"(?i)\bhttps?://[^\s\"'<>]+")


class StepAudioGenError(ValueError):
    def __init__(self, code: str, message: str, *, metadata: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.metadata = metadata or {}


def select_step_audio_gen_model(settings: Settings) -> str:
    model = str(settings.step_audio_gen_model or "").strip()
    return model or STEP_AUDIO_GEN_DEFAULT_MODEL


def validate_step_audio_gen_settings(settings: Settings) -> None:
    endpoint = str(settings.step_audio_gen_endpoint or "").strip()
    parsed = urlparse(endpoint)
    if not (str(settings.stepfun_api_key or "").strip() or str(settings.bgm_api_key or "").strip()):
        raise MediaConfigurationError(
            "StepAudio 3 Gen provider requires STEPFUN_API_KEY "
            "(the StepFun open-platform key, same key as BGM_API_KEY)."
        )
    if parsed.scheme != "https" or parsed.hostname != STEP_AUDIO_GEN_HOST:
        raise MediaConfigurationError(
            "STEP_AUDIO_GEN_ENDPOINT must use the official https://api.stepfun.com host."
        )
    if not str(settings.step_audio_gen_path or "").startswith("/"):
        raise MediaConfigurationError("STEP_AUDIO_GEN_PATH must start with '/'.")


def _normalized_script_emotion(script: Mapping[str, Any], index: int) -> str | None:
    """Validate a per-line emotion annotation (V0.2 §14.7 表演层).

    Every rule exists because the annotation lands INSIDE the provider's
    prompt text: a newline would split the line, a parenthesis would close
    the annotation early, and a paragraph is an injection surface. An absent
    emotion is normal (most lines need no direction) and returns None.
    """

    raw = script.get("emotion")
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise StepAudioGenError(
            "step_audio_gen_script_emotion_not_string",
            f"scripts[{index}]: emotion must be a string.",
        )
    cleaned = raw.strip()
    if not cleaned:
        return None
    if len(cleaned) > STEP_AUDIO_GEN_MAX_EMOTION_CHARS:
        raise StepAudioGenError(
            "step_audio_gen_script_emotion_too_long",
            f"scripts[{index}]: emotion exceeds {STEP_AUDIO_GEN_MAX_EMOTION_CHARS} chars.",
        )
    if any(char in cleaned for char in "()\n\r\t"):
        raise StepAudioGenError(
            "step_audio_gen_script_emotion_unbalanced",
            f"scripts[{index}]: emotion must not contain parentheses or line breaks "
            "(the provider reads it as a (emotion) annotation).",
        )
    text = str(script.get("text") or "")
    if text.lstrip().startswith("("):
        raise StepAudioGenError(
            "step_audio_gen_script_emotion_ambiguous",
            f"scripts[{index}] already starts its text with '(' — the text is its own "
            "annotation, so an emotion field would be read twice. Remove one of the two.",
        )
    return cleaned


def _script_entry(*, speaker: str | None, text: str) -> dict[str, str]:
    return {"speaker": speaker, "text": text} if speaker else {"text": text}


def emotion_annotation(emotion: str | None, text: str) -> str:
    """Prefix the provider's ``(emotion/style)`` annotation onto a script line.

    StepAudio 3 Gen takes per-line performance direction as an annotation
    inside the script text (``(excited) 我做到了``). Exposing it as a field
    rather than asking the author to type parentheses is the difference
    between "每一句都能带情绪" (§14.7 表演层) and a convention nobody uses.

    An emotion the author already annotated by hand wins: when the text
    already starts with ``(`` the text IS the annotation, and adding ours
    would produce ``((...) ...)`` which the provider misreads. Callers
    validate that case instead of silently choosing one reading.
    """

    cleaned = (emotion or "").strip()
    if not cleaned:
        return text
    if text.lstrip().startswith("("):
        # The caller decides: refusing beats guessing which annotation the
        # provider will honour.
        return text
    return f"({cleaned}) {text}"


def build_step_audio_gen_payload(
    *,
    model: str,
    scripts: Sequence[Mapping[str, Any]],
    roles: Sequence[Mapping[str, Any]] | None = None,
    instruction: str | None = None,
    response_format: str = "mp3",
    speed: float | None = None,
    volume: float | None = None,
    sample_rate: int | None = None,
    pronunciation_map: Mapping[str, str] | None = None,
    text_normalization: str | None = None,
    return_url: bool = False,
) -> dict[str, Any]:
    """Build and validate the request payload for one unified audio generation.

    Pure function: all documented limits are enforced client-side so a bad
    request never reaches the provider (a wasted synchronous generation).

    Raises:
        StepAudioGenError: With a stable ``code`` for every violated rule.
    """
    payload: dict[str, Any] = {
        "model": model or STEP_AUDIO_GEN_DEFAULT_MODEL,
        "task": STEP_AUDIO_GEN_TASK,
    }

    normalized_roles: list[dict[str, str]] = []
    role_names: set[str] = set()
    if roles:
        roles_chars = 0
        for index, role in enumerate(roles):
            name = str(role.get("name") or "").strip()
            description = str(role.get("description") or "").strip()
            if bool(name) != bool(description):
                raise StepAudioGenError(
                    "step_audio_gen_role_incomplete",
                    f"roles[{index}]: name and description must be both set or both empty.",
                )
            if not name:
                continue
            roles_chars += len(name) + len(description)
            if roles_chars > STEP_AUDIO_GEN_MAX_ROLES_CHARS:
                raise StepAudioGenError(
                    "step_audio_gen_roles_too_long",
                    f"roles name+description total exceeds {STEP_AUDIO_GEN_MAX_ROLES_CHARS} chars.",
                )
            normalized_roles.append({"name": name, "description": description})
            role_names.add(name)

    normalized_scripts: list[dict[str, str]] = []
    scripts_chars = 0
    for index, script in enumerate(scripts):
        text = str(script.get("text") or "").strip()
        if not text:
            raise StepAudioGenError(
                "step_audio_gen_script_text_required",
                f"scripts[{index}]: text is required.",
            )
        scripts_chars += len(text)
        if scripts_chars > STEP_AUDIO_GEN_MAX_SCRIPTS_CHARS:
            raise StepAudioGenError(
                "step_audio_gen_scripts_too_long",
                f"scripts total exceeds {STEP_AUDIO_GEN_MAX_SCRIPTS_CHARS} chars.",
            )
        emotion = _normalized_script_emotion(script, index)
        speaker = str(script.get("speaker") or "").strip() or None
        if speaker is not None:
            if not role_names:
                raise StepAudioGenError(
                    "step_audio_gen_speaker_without_roles",
                    f"scripts[{index}] names speaker '{speaker}' but no roles were provided.",
                )
            if speaker not in role_names:
                raise StepAudioGenError(
                    "step_audio_gen_unknown_speaker",
                    f"scripts[{index}] speaker '{speaker}' is not one of the role names.",
                )
            normalized_scripts.append(
                _script_entry(speaker=speaker, text=emotion_annotation(emotion, text))
            )
        else:
            normalized_scripts.append(_script_entry(speaker=None, text=emotion_annotation(emotion, text)))

    instruction_text = str(instruction or "").strip() or None
    if not normalized_scripts and not instruction_text:
        raise StepAudioGenError(
            "step_audio_gen_scripts_or_instruction_required",
            "At least one of scripts or instruction is required.",
        )
    if instruction_text is not None and len(instruction_text) > STEP_AUDIO_GEN_MAX_INSTRUCTION_CHARS:
        raise StepAudioGenError(
            "step_audio_gen_instruction_too_long",
            f"instruction exceeds {STEP_AUDIO_GEN_MAX_INSTRUCTION_CHARS} chars.",
        )

    if normalized_roles:
        payload["roles"] = normalized_roles
    if normalized_scripts:
        payload["scripts"] = normalized_scripts
    if instruction_text is not None:
        payload["instruction"] = instruction_text

    fmt = (response_format or "mp3").strip().lower()
    if fmt not in STEP_AUDIO_GEN_RESPONSE_FORMATS:
        raise StepAudioGenError(
            "step_audio_gen_response_format_unsupported",
            f"response_format must be one of {', '.join(STEP_AUDIO_GEN_RESPONSE_FORMATS)}.",
        )
    payload["response_format"] = fmt

    if speed is not None:
        low, high = STEP_AUDIO_GEN_SPEED_RANGE
        if not (low <= float(speed) <= high):
            raise StepAudioGenError(
                "step_audio_gen_speed_out_of_range",
                f"speed must be within [{low}, {high}].",
            )
        payload["speed"] = float(speed)
    if volume is not None:
        low, high = STEP_AUDIO_GEN_VOLUME_RANGE
        if not (low <= float(volume) <= high):
            raise StepAudioGenError(
                "step_audio_gen_volume_out_of_range",
                f"volume must be within [{low}, {high}].",
            )
        payload["volume"] = float(volume)
    if sample_rate is not None:
        if int(sample_rate) not in STEP_AUDIO_GEN_SAMPLE_RATES:
            raise StepAudioGenError(
                "step_audio_gen_sample_rate_unsupported",
                "sample_rate must be one of "
                + ", ".join(str(rate) for rate in STEP_AUDIO_GEN_SAMPLE_RATES)
                + ".",
            )
        payload["sample_rate"] = int(sample_rate)
    if pronunciation_map:
        payload["pronunciation_map"] = {
            str(key): str(value) for key, value in pronunciation_map.items()
        }
    if text_normalization:
        mode = text_normalization.strip().lower()
        if mode not in STEP_AUDIO_GEN_TEXT_NORMALIZATIONS:
            raise StepAudioGenError(
                "step_audio_gen_text_normalization_unsupported",
                "text_normalization must be standard or enhanced.",
            )
        payload["text_normalization"] = mode
    # stream_format stays at the documented default "audio": the SSE mode is
    # deliberately unsupported by this adapter (no streaming consumer yet).
    payload["stream_format"] = "audio"
    if return_url:
        payload["return_url"] = True
    return payload


class StepAudioGenAdapter:
    """StepAudio 3 Gen adapter for one-call unified audio generation."""

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
        self._client = client or httpx.Client(timeout=settings.step_audio_gen_timeout_seconds)
        self._owns_client = client is None
        self._audio_probe = audio_probe or self._probe_audio

    def __del__(self) -> None:
        if getattr(self, "_owns_client", False):
            self._client.close()

    def generate_unified_audio(
        self,
        *,
        workflow_id: str,
        scripts: Sequence[Mapping[str, Any]] | None = None,
        roles: Sequence[Mapping[str, Any]] | None = None,
        instruction: str | None = None,
        response_format: str | None = None,
        speed: float | None = None,
        volume: float | None = None,
        sample_rate: int | None = None,
        pronunciation_map: Mapping[str, str] | None = None,
        text_normalization: str | None = None,
        return_url: bool = False,
    ) -> dict[str, Any]:
        workflow_id = str(workflow_id or "").strip()
        if not workflow_id:
            return self._failure(
                "step_audio_gen_workflow_required",
                "A workflow_id is required to own the generated audio asset.",
            )
        try:
            payload = build_step_audio_gen_payload(
                model=select_step_audio_gen_model(self._settings),
                scripts=scripts or [],
                roles=roles,
                instruction=instruction,
                response_format=response_format or self._settings.step_audio_gen_response_format,
                speed=speed,
                volume=volume,
                sample_rate=sample_rate,
                pronunciation_map=pronunciation_map,
                text_normalization=text_normalization,
                return_url=return_url,
            )
        except StepAudioGenError as exc:
            return self._failure(exc.code, str(exc), metadata=exc.metadata)

        response, failure = self._post_json(payload)
        if failure is not None:
            return failure

        assert response is not None
        return self._consume_response(response, payload=payload, workflow_id=workflow_id)

    # -- internals ------------------------------------------------------------

    def _validate_settings(self) -> None:
        validate_step_audio_gen_settings(self._settings)

    def _endpoint(self) -> str:
        base = str(self._settings.step_audio_gen_endpoint or "").strip().rstrip("/")
        path = str(self._settings.step_audio_gen_path or "").strip()
        return f"{base}{path}"

    def _post_json(
        self, payload: dict[str, Any]
    ) -> tuple[httpx.Response | None, dict[str, Any] | None]:
        try:
            response = self._client.post(
                self._endpoint(),
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key()}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                timeout=self._settings.step_audio_gen_timeout_seconds,
            )
        except httpx.ConnectError:
            return None, self._failure(
                "step_audio_gen_unreachable",
                "StepAudio 3 Gen connection could not be established.",
                retryable=True,
            )
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.ReadError, httpx.WriteError):
            return None, self._failure(
                "step_audio_gen_timeout",
                "StepAudio 3 Gen request did not complete reliably "
                "(the generation may still have been accepted).",
                retryable=False,
            )
        except httpx.HTTPError:
            return None, self._failure(
                "step_audio_gen_transport_error",
                "StepAudio 3 Gen request could not be completed.",
                retryable=True,
            )
        if response.status_code >= 400:
            code, retryable = _http_error_mapping(response.status_code)
            return None, self._failure(
                code,
                f"StepAudio 3 Gen request returned HTTP {response.status_code}: "
                f"{_error_message(response)}",
                retryable=retryable,
                http_status=response.status_code,
            )
        return response, None

    def _consume_response(
        self,
        response: httpx.Response,
        *,
        payload: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        content_type = str(response.headers.get("content-type") or "").lower()
        if "json" in content_type:
            return self._consume_json_response(response, payload=payload, workflow_id=workflow_id)
        raw = response.content or b""
        if not raw:
            return self._failure(
                "step_audio_gen_output_invalid",
                "StepAudio 3 Gen returned an empty audio body.",
            )
        return self._store_audio(raw, payload=payload, workflow_id=workflow_id)

    def _consume_json_response(
        self,
        response: httpx.Response,
        *,
        payload: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError):
            return self._failure(
                "step_audio_gen_output_invalid",
                "StepAudio 3 Gen returned unreadable JSON.",
            )
        if not isinstance(data, dict):
            return self._failure(
                "step_audio_gen_output_invalid",
                "StepAudio 3 Gen JSON response is not an object.",
            )
        url = None
        for key in ("url", "audio_url", "data"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                url = value.strip()
                break
        encoded = data.get("audio")
        if url is None and isinstance(encoded, str) and encoded.strip():
            candidate = encoded.strip()
            # Base64-encoded audio under a generic "audio" key; if it does not
            # decode but looks like a URL, fall through to the download path.
            raw: bytes | None = None
            try:
                decoded = base64.b64decode(candidate, validate=True)
                raw = decoded or None
            except (ValueError, binascii.Error):
                raw = None
            if raw is not None:
                return self._store_audio(raw, payload=payload, workflow_id=workflow_id)
            if _URL_PATTERN.fullmatch(candidate):
                url = candidate
        if url is None:
            return self._failure(
                "step_audio_gen_output_invalid",
                "StepAudio 3 Gen JSON response carried neither a URL nor audio data.",
            )
        if not _URL_PATTERN.fullmatch(url):
            return self._failure(
                "step_audio_gen_output_invalid",
                "StepAudio 3 Gen JSON response carried a non-URL audio reference.",
            )
        try:
            downloaded = self._client.get(url, timeout=self._settings.step_audio_gen_timeout_seconds)
        except httpx.HTTPError:
            return self._failure(
                "step_audio_gen_download_failed",
                "StepAudio 3 Gen audio URL could not be downloaded.",
                retryable=True,
            )
        if downloaded.status_code >= 400 or not downloaded.content:
            return self._failure(
                "step_audio_gen_download_failed",
                f"StepAudio 3 Gen audio URL download returned HTTP {downloaded.status_code}.",
                retryable=downloaded.status_code >= 500,
                http_status=downloaded.status_code,
            )
        return self._store_audio(
            downloaded.content, payload=payload, workflow_id=workflow_id, source_url=url
        )

    def _store_audio(
        self,
        raw: bytes,
        *,
        payload: dict[str, Any],
        workflow_id: str,
        source_url: str | None = None,
    ) -> dict[str, Any]:
        max_bytes = self._settings.step_audio_gen_download_max_bytes
        if len(raw) > max_bytes:
            return self._failure(
                "step_audio_gen_output_too_large",
                "StepAudio 3 Gen audio exceeded the configured size limit.",
                retryable=False,
                download_expected_bytes=max_bytes,
            )
        response_format = str(payload.get("response_format") or "mp3").lower()
        extension = _RESPONSE_FORMAT_EXTENSIONS.get(response_format, ".mp3")
        generation_id = f"step_audio_gen_{uuid4().hex[:12]}"
        relative_path = (
            Path("assets") / "provider-output" / workflow_id / f"{generation_id}{extension}"
        )
        output_path = self._data_dir / relative_path
        try:
            validate_v2_data_path(
                self._data_dir,
                output_path,
                operation="v2-step-audio-gen-store",
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
            with temporary_path.open("xb") as output:
                output.write(raw)
        except OSError:
            temporary_path.unlink(missing_ok=True)
            return self._failure(
                "step_audio_gen_output_unwritable",
                "StepAudio 3 Gen audio could not be written to disk.",
                retryable=True,
            )
        try:
            probe = self._audio_probe(temporary_path)
        except Exception as exc:  # noqa: BLE001 - a probe failure is invalid provider media.
            temporary_path.unlink(missing_ok=True)
            return self._failure(
                "step_audio_gen_audio_invalid",
                f"StepAudio 3 Gen output could not be probed: {exc}",
            )
        if probe.get("error") or not probe.get("has_audio"):
            temporary_path.unlink(missing_ok=True)
            return self._failure(
                "step_audio_gen_audio_invalid",
                "StepAudio 3 Gen output is not a decodable audio stream.",
            )
        temporary_path.replace(output_path)
        metadata = {
            "provider_model": select_step_audio_gen_model(self._settings),
            "provider_wire_model": select_step_audio_gen_model(self._settings),
            "response_format": response_format,
            "workflow_id": workflow_id,
            # Per-element timing is not returned by this model (no timestamp
            # support): record the fact so downstream alignment decisions are
            # explicit instead of silent (engineering standard §4).
            "per_element_timing_available": False,
        }
        if source_url is not None:
            metadata["source_url"] = source_url
        return self._asset(
            status="ready",
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
                timeout=self._settings.step_audio_gen_timeout_seconds,
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

    def _api_key(self) -> str:
        return str(self._settings.stepfun_api_key or self._settings.bgm_api_key or "")

    def _asset(self, *, status: str, **fields: Any) -> dict[str, Any]:
        return {"status": status, **fields}

    def _failure(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        **metadata: Any,
    ) -> dict[str, Any]:
        return {
            "status": "failed",
            "error": message,
            "error_code": code,
            "metadata": {"retryable": retryable, **metadata},
        }


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested directly)
# ---------------------------------------------------------------------------


def _http_error_mapping(status_code: int) -> tuple[str, bool]:
    if status_code in {401, 403}:
        return "step_audio_gen_unauthorized", False
    if status_code == 402:
        return "step_audio_gen_quota_exceeded", False
    if status_code == 429:
        return "step_audio_gen_busy", True
    if status_code == 400 or status_code == 422:
        return "step_audio_gen_request_invalid", False
    if status_code == 404:
        return "step_audio_gen_endpoint_not_found", False
    if status_code >= 500:
        return "step_audio_gen_provider_error", True
    return "step_audio_gen_unexpected_status", status_code >= 500


def _error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except (json.JSONDecodeError, ValueError):
        text = (response.text or "").strip()
        return text[:200] if text else "no error body"
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:200]
        if isinstance(error, str) and error:
            return error[:200]
        if data.get("message"):
            return str(data["message"])[:200]
    return "provider error body"


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
