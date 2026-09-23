"""Generate SceneScriptRoot from a natural-language scene description.

Two generators back the scene-3d canvas node:

* :class:`LLMSceneScriptGenerator` — the real path. Calls an
  OpenAI-compatible ``/chat/completions`` endpoint (``LLM_BASE_URL`` /
  ``LLM_API_KEY``) through ``httpx``, then validates the reply with the
  scene3d :mod:`parser`.
* :class:`TemplateSceneScriptGenerator` — the deterministic path used in
  fake/mock runtime. Builds a known-good SceneScript from a shot template.

Both generators fail with :class:`SceneScriptGenerationError` (carrying a
machine-readable ``code``) instead of returning a partial script, so the
node executor can fail closed with an explicit error.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import httpx

from app.core.config import Settings
from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.parser import parse_llm_output
from app.services.scene3d.shot_templates import generate_establishing_shot

#: Seconds; mirrors the reference video analyzer default.
DEFAULT_LLM_TIMEOUT_SECONDS = 120

#: Upper bound on the generated SceneScript reply.
DEFAULT_MAX_TOKENS = 2000


_SCENE_SCRIPT_SYSTEM_PROMPT = """\
You are a professional 3D previsualization artist. Convert the user's scene \
description into ONE SceneScript JSON object for a low-poly 3D previs \
renderer.

Output ONLY the JSON object inside a single ```json code block, no other text. \
The object must follow this shape:
{
  "scene": {"name": string, "environment": "indoor" | "outdoor" | "mixed", \
"lighting": "warm" | "cool" | "neutral" | "dramatic" | "soft" | "hard", \
"duration": number, "frame_rate": number},
  "characters": [
    {"id": string, "type": "lowpoly_human", \
"appearance": {"color": "#RRGGBB", "height": number, "scale": number}, \
"keyframes": [{"frame": int, "position": [x, y, z], "rotation_y": number, \
"action": "stand" | "walk" | "sit" | "talk" | "gesture"}]}
  ],
  "props": [{"id": string, "type": "box" | "chair" | "round_table" | \
"rect_table" | "book" | "cup", "position": [x, y, z], "scale": number, \
"rotation_y": number}],
  "environment": [{"id": string, "type": "wall" | "floor" | "pillar" | \
"door" | "window", "position": [x, y, z], "scale": number, \
"rotation_y": number}],
  "cameras": [
    {"id": string, "shot_type": "wide" | "medium" | "closeup" | \
"over_shoulder" | "pov", "keyframes": [{"frame": int, \
"position": [x, y, z], "look_at": [x, y, z]}]}
  ],
  "shots": [{"id": string, "camera": string, "start_frame": int, \
"end_frame": int, "description": string}],
  "speech_bindings": []
}

Hard rules:
- At least one camera and one shot. The shot's "camera" must equal a camera id.
- Every character and camera must have a keyframe at frame 0; add more \
keyframes for any described movement.
- Shot end_frame must equal round(scene.duration * scene.frame_rate) - 1.
- Positions are in meters. Characters stand on the ground (y = 0); typical \
camera height is y = 1.5, 2 to 15 meters from the subject.
- Use 24 or 30 fps and keep duration between 2 and 10 seconds.
"""


class SceneScriptGenerationError(RuntimeError):
    """Raised when a SceneScript cannot be generated."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class SceneScriptGenerator(Protocol):
    """Produces a validated SceneScript from a scene description."""

    def generate(self, *, description: str) -> SceneScriptRoot: ...


class LLMSceneScriptGenerator:
    """Generate a SceneScript through an OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
        timeout_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._timeout_seconds = timeout_seconds
        self._max_tokens = max_tokens

    def generate(self, *, description: str) -> SceneScriptRoot:
        text = description.strip()
        if not text:
            raise SceneScriptGenerationError(
                "scene3d_scene_script_missing",
                "A scene description is required before a SceneScript can be generated.",
            )
        if not self._settings.llm_api_key or not self._settings.llm_base_url:
            raise SceneScriptGenerationError(
                "scene3d_llm_unconfigured",
                "LLM is not configured: set LLM_API_KEY and LLM_BASE_URL.",
            )

        client = self._client_factory(timeout=self._timeout_seconds)
        try:
            content = self._request_completion(client, description=text)
        finally:
            client.close()

        result = parse_llm_output(content)
        if not result.success or result.scene_script is None:
            raise SceneScriptGenerationError(
                "scene3d_scene_script_generation_failed",
                result.retry_feedback,
            )
        return result.scene_script

    def _request_completion(self, client: httpx.Client, *, description: str) -> str:
        model = self._settings.llm_scene_model or self._settings.llm_front_desk_model
        response = client.post(
            f"{self._settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self._settings.llm_api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _SCENE_SCRIPT_SYSTEM_PROMPT},
                    {"role": "user", "content": description},
                ],
                "max_tokens": self._max_tokens,
                "temperature": 0.3,
            },
        )
        if response.status_code != 200:
            raise SceneScriptGenerationError(
                "scene3d_scene_script_generation_failed",
                f"LLM call failed ({response.status_code}): {response.text[:200]}",
            )
        data = response.json()
        choices = data.get("choices")
        if not choices:
            raise SceneScriptGenerationError(
                "scene3d_scene_script_generation_failed",
                "LLM returned no choices.",
            )
        content: Any = choices[0].get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise SceneScriptGenerationError(
                "scene3d_scene_script_generation_failed",
                "LLM returned an empty message.",
            )
        return content


class TemplateSceneScriptGenerator:
    """Deterministically build a SceneScript from a shot template."""

    def __init__(self, *, duration: float = 5.0, frame_rate: int = 30) -> None:
        self._duration = duration
        self._frame_rate = frame_rate

    def generate(self, *, description: str) -> SceneScriptRoot:
        text = description.strip()
        if not text:
            raise SceneScriptGenerationError(
                "scene3d_scene_script_missing",
                "A scene description is required before a SceneScript can be generated.",
            )
        scene_name = text[:40] if len(text) <= 40 else f"{text[:37]}..."
        return generate_establishing_shot(
            scene_name=scene_name,
            duration=self._duration,
            frame_rate=self._frame_rate,
        )
