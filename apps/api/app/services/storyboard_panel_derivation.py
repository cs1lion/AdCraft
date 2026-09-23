"""Storyboard panel derivation from script + world_setting context.

Implements P1a of the structured-derivation flow (ADR bulletin §3):
- script text + world_setting summary → StoryboardPanelV2[]
- LLM-driven, with structured output validation
- Derivation failure is retryable and local to the storyboard node
  (script node is never modified — per Party B Objection 1).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.agent_canvas_ad_media import StoryboardPanelV2


@dataclass(frozen=True)
class DerivationResult:
    """Result of a panel derivation attempt."""

    panels: tuple[StoryboardPanelV2, ...]
    raw_output: str
    warnings: tuple[str, ...] = ()


class StoryboardPanelDerivationError(RuntimeError):
    """Raised when panel derivation fails irrecoverably."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class StoryboardPanelDerivationService:
    """Derive StoryboardPanelV2[] from script text + world_setting context.

    This is a draft-layer intermediate for the storyboard node. It does NOT
    modify the script node's canonical output (per Party B Objection 1 in
    docs/plans/3d-creation-flow-collaboration.md §2).
    """

    SYSTEM_PROMPT = """You are a storyboard artist for advertising video production.
Given a script and optional world-setting context, derive a sequence of storyboard panels.

Each panel must describe:
- beat: the narrative beat or action in this panel (1-2 sentences)
- composition: visual composition (framing, layout, foreground/background)
- camera: camera description (angle, lens, distance)
- subject_action: what the subject(s) are doing
- continuity_from_previous: how this panel connects to the previous one
- shot_type: one of wide, medium, close-up, ecu, ots
- camera_move: one of static, pan, tilt, dolly, zoom, crane, handheld
- duration_seconds: estimated duration (0.5-60)

Output ONLY a JSON array of panel objects, no markdown, no explanation.
Panel index starts at 1. Aim for 4-9 panels for a typical short ad script."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()

    def derive(
        self,
        *,
        script_text: str,
        world_setting_summary: str | None = None,
        target_panel_count: int | None = None,
        model_id: str | None = None,
    ) -> DerivationResult:
        """Derive storyboard panels from script text.

        Args:
            script_text: The script content (plain text or structured).
            world_setting_summary: Optional summary of the world setting.
            target_panel_count: Optional hint for desired panel count.
            model_id: Override the LLM model ID.

        Returns:
            DerivationResult with validated panels.

        Raises:
            StoryboardPanelDerivationError: If derivation fails.
        """
        if not script_text or not script_text.strip():
            raise StoryboardPanelDerivationError(
                "empty_script",
                "Cannot derive panels from empty script text.",
            )

        if not self._settings.llm_api_key or not self._settings.llm_base_url:
            raise StoryboardPanelDerivationError(
                "llm_unavailable",
                "LLM API key and base URL are required for panel derivation.",
            )

        model = model_id or self._settings.llm_storyboard_model or "gpt-4o"
        user_prompt = self._build_user_prompt(
            script_text=script_text,
            world_setting_summary=world_setting_summary,
            target_panel_count=target_panel_count,
        )

        try:
            raw_output = self._call_llm(model=model, user_prompt=user_prompt)
        except httpx.HTTPError as exc:
            raise StoryboardPanelDerivationError(
                "llm_http_error",
                f"LLM HTTP request failed: {exc}",
                {"model": model},
            ) from exc

        panels, warnings = self._parse_and_validate(raw_output)
        return DerivationResult(panels=panels, raw_output=raw_output, warnings=tuple(warnings))

    def _build_user_prompt(
        self,
        *,
        script_text: str,
        world_setting_summary: str | None,
        target_panel_count: int | None,
    ) -> str:
        parts = [f"## Script\n\n{script_text.strip()}"]
        if world_setting_summary:
            parts.append(f"## World Setting\n\n{world_setting_summary.strip()}")
        if target_panel_count:
            parts.append(f"## Target Panel Count\n\nAim for approximately {target_panel_count} panels.")
        parts.append("\nOutput the JSON array of panels now.")
        return "\n\n".join(parts)

    def _call_llm(self, *, model: str, user_prompt: str) -> str:
        """Call the LLM API and return the raw text output."""
        url = f"{self._settings.llm_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 4096,
        }
        with httpx.Client(timeout=120.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"]

    def _parse_and_validate(self, raw_output: str) -> tuple[tuple[StoryboardPanelV2, ...], list[str]]:
        """Parse raw LLM output into validated StoryboardPanelV2 objects."""
        warnings: list[str] = []

        # Extract JSON array from output (handle markdown code blocks)
        json_str = self._extract_json_array(raw_output)
        if not json_str:
            raise StoryboardPanelDerivationError(
                "no_json_in_output",
                "LLM output did not contain a valid JSON array.",
                {"raw_output_preview": raw_output[:500]},
            )

        try:
            raw_panels = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise StoryboardPanelDerivationError(
                "invalid_json",
                f"Failed to parse LLM output as JSON: {exc}",
                {"raw_output_preview": raw_output[:500]},
            ) from exc

        if not isinstance(raw_panels, list):
            raise StoryboardPanelDerivationError(
                "output_not_array",
                f"Expected JSON array, got {type(raw_panels).__name__}.",
            )

        panels: list[StoryboardPanelV2] = []
        for idx, raw_panel in enumerate(raw_panels):
            if not isinstance(raw_panel, dict):
                warnings.append(f"Panel {idx + 1}: not an object, skipped.")
                continue
            try:
                # Ensure panel_index is set correctly
                raw_panel.setdefault("panel_index", idx + 1)
                panel = StoryboardPanelV2.model_validate(raw_panel)
                panels.append(panel)
            except ValidationError as exc:
                warnings.append(f"Panel {idx + 1}: validation failed — {exc.errors()[0]['msg']}")
                continue

        if not panels:
            raise StoryboardPanelDerivationError(
                "no_valid_panels",
                "No valid panels could be parsed from LLM output.",
                {"warnings": warnings},
            )

        return tuple(panels), warnings

    @staticmethod
    def _extract_json_array(text: str) -> str | None:
        """Extract a JSON array from text, handling markdown code blocks."""
        # Try markdown code block first
        code_block_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if code_block_match:
            return code_block_match.group(1)

        # Try to find the first [ and matching ]
        start = text.find("[")
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None
