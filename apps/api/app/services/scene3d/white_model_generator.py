"""White-model generator: natural language -> ops batch -> SceneScript.

The white-model design mode's generation path. Where the classic path emits
one whole SceneScript (``scene_script_generator.py``), this generator emits
an **operations batch** per the ``video_agent_3d_white_model`` skill contract
and applies it through ``SceneScriptToolService`` — the SAME validation and
application gate the frontend workbench and the agent-tools path use. So the
agent's output is never trusted as a script; it is a batch of ops that must
pass the gate.

LLM failures surface as coded errors (unconfigured / non-JSON / rejected
batch with violations), and the rejections come back with per-op detail so a
caller (or the user) can repair instead of retry-blind.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from app.core.config import Settings
from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.llm_json_salvage import salvage_json_text
from app.services.scene3d.scene_script_tool_service import (
    SceneOperationError,
    SceneOperationResult,
    SceneScriptToolService,
)


class WhiteModelGenerationError(RuntimeError):
    """Raised when white-model generation fails (fail closed, coded)."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        violations: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.violations = violations or []


DEFAULT_LLM_TIMEOUT_SECONDS = 120
DEFAULT_MAX_TOKENS = 4000

# Condensed from the video_agent_3d_white_model skill contract (the skill is
# the long form; this is what the model actually needs in-context).
_WHITE_MODEL_SYSTEM_PROMPT = """You are a white-model (blockout) scene builder. Given a scene
description, output ONLY a JSON object {"operations": [...]} — a batch of 2-10 operations that
build the scene incrementally. No prose outside the JSON.

Operations (only these):
- {"op": "add_environment", "type", "position": [x,y,z], "scale"?, "rotation_y"?}   # wall|pillar|floor|gable_roof|flat_roof|door|window|stairs|platform|tree|rock|fence|ground
- {"op": "add_prop", "type", "position"}                                            # round_table|rect_table|chair|stool|lantern|box|crate|vase|weapon|scroll|book|cup
- {"op": "add_character", "position", "color"?, "action"?}                          # action: stand|talk|walk|sit|gesture
- {"op": "add_camera", "position", "look_at", "shot_type"?}                         # wide|medium|closeup|over_shoulder|pov
- {"op": "move_object", "kind", "id", "position"}                                   # kind: environment|prop|character|camera
- {"op": "rotate_object", "kind", "id", "rotation_y"}
- {"op": "scale_object", "kind", "id", "scale"}
- {"op": "set_camera", "kind": "camera", "id", "position"?, "look_at"?, "shot_type"?}
- {"op": "add_keyframe", "kind", "id", "frame", "position"?, "rotation_y"?}
- {"op": "remove_object", "kind", "id"}

Rules: X right, Y forward, Z up, 1 unit = 1 m; |x|,|y| <= 50, 0 <= z <= 30; frames = seconds * 30.
Build order: floor -> walls -> door -> props -> characters -> cameras. A batch may reference
objects its own earlier ops create. Keep each batch to one area (<=8 objects).
Prefer enum types: use the nearest primitive for furniture-like things (a locker is a `box`).
"""


class WhiteModelOpsGenerator:
    """Generate a SceneScript through an ops batch applied by the tool service."""

    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
        tool_service: SceneScriptToolService | None = None,
        timeout_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._tool_service = tool_service or SceneScriptToolService()
        self._timeout_seconds = timeout_seconds
        self._max_tokens = max_tokens

    def generate(
        self,
        *,
        description: str,
        base_script: SceneScriptRoot | None = None,
        mcp_client: Any | None = None,
    ) -> tuple[SceneScriptRoot, dict[str, Any]]:
        """Generate (and apply) an ops batch for the description.

        Args:
            description: Natural-language scene or edit request.
            base_script: The current SceneScript to edit (None = a fresh
                starter script with one camera and one shot).
            mcp_client: Optional Blender MCP client for extension ops.

        Returns:
            (new SceneScript, report dict with applied/violations/mcp info).

        Raises:
            WhiteModelGenerationError: Coded failure at any stage.
        """

        text = description.strip()
        if not text:
            raise WhiteModelGenerationError(
                "white_model_description_required",
                "A scene description is required before a white model can be generated.",
            )
        if not self._settings.llm_api_key or not self._settings.llm_base_url:
            raise WhiteModelGenerationError(
                "white_model_llm_unconfigured",
                "LLM is not configured: set LLM_API_KEY and LLM_BASE_URL.",
            )

        base = base_script if base_script is not None else _starter_script()
        client = self._client_factory(timeout=self._timeout_seconds)
        try:
            content = self._request_completion(client, description=text, base=base)
        finally:
            client.close()

        operations = _parse_operations(content)
        try:
            result: SceneOperationResult = self._tool_service.apply_operations(
                base, operations, mcp_client=mcp_client
            )
        except SceneOperationError as error:
            raise WhiteModelGenerationError(
                error.code,
                str(error),
                violations=error.violations,
            ) from error

        report = {
            "applied": result.applied,
            "warnings": result.warnings,
            "mcp_results": result.mcp_results,
            "operation_count": len(operations),
        }
        return result.scene_script, report

    def _request_completion(self, client: httpx.Client, *, description: str, base: SceneScriptRoot) -> str:
        model = self._settings.llm_scene_model or self._settings.llm_front_desk_model
        user_content = (
            f"Current scene (object ids you may reference): {_scene_summary(base)}\n\n"
            f"Request: {description}"
        )
        response = client.post(
            f"{self._settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self._settings.llm_api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _WHITE_MODEL_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                "max_tokens": self._max_tokens,
                "temperature": 0.3,
            },
        )
        if response.status_code != 200:
            raise WhiteModelGenerationError(
                "white_model_llm_failed",
                f"LLM call failed ({response.status_code}): {response.text[:200]}",
            )
        data = response.json()
        choices = data.get("choices")
        if not choices:
            raise WhiteModelGenerationError(
                "white_model_llm_failed", "LLM returned no choices."
            )
        content: Any = choices[0].get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise WhiteModelGenerationError(
                "white_model_llm_failed", "LLM returned an empty message."
            )
        return content


def _scene_summary(script: SceneScriptRoot) -> str:
    """Compact id inventory so the model references existing objects."""

    parts = [
        f"scene duration {script.scene.duration}s @ {script.scene.frame_rate}fps",
        "environment: " + (", ".join(obj.id for obj in script.environment) or "none"),
        "props: " + (", ".join(obj.id for obj in script.props) or "none"),
        "characters: " + (", ".join(obj.id for obj in script.characters) or "none"),
        "cameras: " + (", ".join(obj.id for obj in script.cameras) or "none"),
    ]
    return "; ".join(parts)


def _starter_script() -> SceneScriptRoot:
    """A minimal renderable scene an ops batch can build on."""

    return SceneScriptRoot.model_validate(
        {
            "scene": {"name": "white-model", "environment": "indoor", "lighting": "neutral", "duration": 6.0, "frame_rate": 30},
            "characters": [],
            "props": [],
            "environment": [],
            "cameras": [
                {
                    "id": "cam1",
                    "shot_type": "wide",
                    "keyframes": [{"frame": 0, "position": [8, -10, 5], "look_at": [0, 0, 1]}],
                }
            ],
            "shots": [{"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 179, "description": "wide"}],
            "speech_bindings": [],
        }
    )


def _parse_operations(content: str) -> list[dict[str, Any]]:
    """Extract the operations array from the LLM output (fenced or raw)."""

    text = content.strip()
    candidates = [text]
    for fence in ("```json", "```"):
        if fence in text:
            start = text.find(fence) + len(fence)
            end = text.find("```", start)
            if end > start:
                candidates.append(text[start:end].strip())
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        candidates.append(text[brace_start : brace_end + 1])

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            # A trailing comma is one character away from valid — repair
            # locally (llm_json_salvage) before failing the whole batch.
            repaired = salvage_json_text(candidate)
            if repaired is None:
                continue
            try:
                payload = json.loads(repaired)
            except json.JSONDecodeError:
                continue
        if isinstance(payload, dict) and isinstance(payload.get("operations"), list):
            operations = payload["operations"]
            if operations and all(isinstance(op, dict) for op in operations):
                return operations
    raise WhiteModelGenerationError(
        "white_model_operations_unparseable",
        "The LLM output carried no valid {\"operations\": [...]} payload.",
    )
